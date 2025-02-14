from flask import Flask, request, jsonify, send_file
import requests
import psycopg2  # PostgreSQL
import pandas as pd
from datetime import datetime, timedelta
import os
import io
import json

app = Flask(__name__)

# 🔹 Database Connection
DB_CONFIG = {
    "dbname": "your_db_name",
    "user": "your_db_user",
    "password": "your_db_password",
    "host": "your_db_host",
    "port": "5432",
}

# 🔹 Amazon SP-API Base URL
SP_API_BASE_URL = "https://sellingpartnerapi-na.amazon.com"

# 🔹 Connect to PostgreSQL
def get_db_connection():
    return psycopg2.connect(**DB_CONFIG)

### 1️⃣ Fetch Real-Time Orders (API + Database) ###
@app.route('/get-orders', methods=['GET'])
def get_orders():
    """Fetch orders from Amazon SP-API & fallback to DB."""
    selling_partner_id = request.args.get("selling_partner_id")
    access_token = request.args.get("access_token")

    if not selling_partner_id or not access_token:
        return jsonify({"error": "Missing selling_partner_id or access_token"}), 400

    marketplace_id = "A1AM78C64UM0Y8"  # Amazon Mexico
    created_after = (datetime.utcnow() - timedelta(days=30)).isoformat() + "Z"

    amazon_orders_url = (
        f"{SP_API_BASE_URL}/orders/v0/orders"
        f"?MarketplaceIds={marketplace_id}"
        f"&CreatedAfter={created_after}"
    )

    headers = {
        "x-amz-access-token": access_token,
        "Content-Type": "application/json"
    }

    try:
        response = requests.get(amazon_orders_url, headers=headers)
        orders_data = response.json()

        if "payload" in orders_data and "Orders" in orders_data["payload"]:
            orders_list = orders_data["payload"]["Orders"]

            if len(orders_list) == 0:
                return fetch_orders_from_db()

            orders_summary = [
                {
                    "order_id": order.get("AmazonOrderId", "N/A"),
                    "status": order.get("OrderStatus", "N/A"),
                    "total": float(order.get("OrderTotal", {}).get("Amount", 0)),
                    "currency": order.get("OrderTotal", {}).get("CurrencyCode", "N/A"),
                    "purchase_date": order.get("PurchaseDate", "N/A")
                }
                for order in orders_list
            ]

            # 🔹 Save to DB for future use
            save_orders_to_db(orders_summary)

            return jsonify({"orders": orders_summary})

        else:
            return fetch_orders_from_db()

    except requests.exceptions.RequestException as e:
        return fetch_orders_from_db()


### 2️⃣ Fetch Orders from Database (Fallback) ###
def fetch_orders_from_db():
    """Fetch stored orders from PostgreSQL in case of API failure."""
    conn = get_db_connection()
    cur = conn.cursor()

    cur.execute("SELECT order_id, status, total, currency, purchase_date FROM orders ORDER BY purchase_date DESC LIMIT 100")
    orders = cur.fetchall()
    
    cur.close()
    conn.close()

    orders_list = [
        {"order_id": row[0], "status": row[1], "total": row[2], "currency": row[3], "purchase_date": row[4]}
        for row in orders
    ]

    return jsonify({"orders": orders_list})


### 3️⃣ Save Orders to Database ###
def save_orders_to_db(orders):
    """Save Amazon orders to PostgreSQL database."""
    conn = get_db_connection()
    cur = conn.cursor()

    for order in orders:
        cur.execute(
            "INSERT INTO orders (order_id, status, total, currency, purchase_date) VALUES (%s, %s, %s, %s, %s) ON CONFLICT (order_id) DO NOTHING;",
            (order["order_id"], order["status"], order["total"], order["currency"], order["purchase_date"]),
        )

    conn.commit()
    cur.close()
    conn.close()


### 4️⃣ Fetch Historical Reports from Amazon ###
@app.route('/fetch-reports', methods=['POST'])
def fetch_reports():
    """Request Amazon Reports API for historical order, refund, and financial data."""
    selling_partner_id = request.json.get("selling_partner_id")
    access_token = request.json.get("access_token")

    if not selling_partner_id or not access_token:
        return jsonify({"error": "Missing selling_partner_id or access_token"}), 400

    report_type = "_GET_FLAT_FILE_ALL_ORDERS_DATA_BY_ORDER_DATE_"

    amazon_reports_url = f"{SP_API_BASE_URL}/reports/2021-06-30/reports"

    headers = {
        "x-amz-access-token": access_token,
        "Content-Type": "application/json"
    }

    payload = {
        "reportType": report_type,
        "marketplaceIds": ["A1AM78C64UM0Y8"]
    }

    try:
        response = requests.post(amazon_reports_url, headers=headers, json=payload)
        report_data = response.json()

        return jsonify(report_data)

    except requests.exceptions.RequestException as e:
        return jsonify({"error": "Failed to request report", "details": str(e)}), 500


### 5️⃣ Download Orders as CSV ###
@app.route('/download-orders', methods=['GET'])
def download_orders():
    """Download orders as CSV file."""
    conn = get_db_connection()
    cur = conn.cursor()
    
    cur.execute("SELECT * FROM orders")
    orders = cur.fetchall()
    
    cur.close()
    conn.close()

    df = pd.DataFrame(orders, columns=["order_id", "status", "total", "currency", "purchase_date"])

    csv_buffer = io.StringIO()
    df.to_csv(csv_buffer, index=False)
    
    response = send_file(
        io.BytesIO(csv_buffer.getvalue().encode()),
        mimetype="text/csv",
        as_attachment=True,
        download_name="orders.csv"
    )

    return response
