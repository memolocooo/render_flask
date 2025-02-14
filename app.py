import os
import requests
import uuid
from flask import Flask, jsonify, request, redirect, session
from dotenv import load_dotenv
from flask_cors import CORS
from flask_session import Session
import psycopg2
from datetime import datetime, timedelta
import csv
from flask import send_file


# Load environment variables
load_dotenv()

app = Flask(__name__)
app.secret_key = os.getenv("FLASK_SECRET_KEY")

# Enable CORS for Webflow
CORS(app, supports_credentials=True, origins=["https://guillermos-amazing-site-b0c75a.webflow.io"])

# Configure Flask Session
app.config["SESSION_TYPE"] = "filesystem"
app.config["SESSION_PERMANENT"] = False
Session(app)

# Amazon OAuth Variables
LWA_APP_ID = os.getenv("LWA_APP_ID")
LWA_CLIENT_SECRET = os.getenv("LWA_CLIENT_SECRET")
REDIRECT_URI = os.getenv("REDIRECT_URI")
AUTH_URL = os.getenv("AUTH_URL")
TOKEN_URL = os.getenv("TOKEN_URL")
SP_API_BASE_URL = os.getenv("SP_API_BASE_URL")
APP_ID = os.getenv("APP_ID")

# PostgreSQL Database Connection
DATABASE_URL = os.getenv("DB_URL")
DB_CONN = psycopg2.connect(DATABASE_URL, sslmode="require")


def save_oauth_tokens(selling_partner_id, access_token, refresh_token, expires_in):
    """Save Amazon OAuth credentials to PostgreSQL."""
    expires_at = datetime.utcnow() + timedelta(seconds=expires_in)

    with DB_CONN.cursor() as cur:
        cur.execute("""
            INSERT INTO amazon_oauth_tokens (selling_partner_id, access_token, refresh_token, expires_at)
            VALUES (%s, %s, %s, %s)
            ON CONFLICT (selling_partner_id) DO UPDATE 
            SET access_token = EXCLUDED.access_token,
                refresh_token = EXCLUDED.refresh_token,
                expires_at = EXCLUDED.expires_at;
        """, (selling_partner_id, access_token, refresh_token, expires_at))

        DB_CONN.commit()


def get_stored_tokens(selling_partner_id):
    """Retrieve stored tokens from database."""
    with DB_CONN.cursor() as cur:
        cur.execute("""
            SELECT access_token, refresh_token, expires_at 
            FROM amazon_oauth_tokens 
            WHERE selling_partner_id = %s
        """, (selling_partner_id,))
        return cur.fetchone()


def refresh_access_token(selling_partner_id, refresh_token):
    """Refresh Amazon SP-API access token using the refresh token."""
    print("🔄 Refreshing expired access token...")

    payload = {
        "grant_type": "refresh_token",
        "refresh_token": refresh_token,
        "client_id": LWA_APP_ID,
        "client_secret": LWA_CLIENT_SECRET
    }

    response = requests.post(TOKEN_URL, data=payload)
    token_data = response.json()

    if "access_token" in token_data:
        print("✅ Access token refreshed successfully!")
        save_oauth_tokens(selling_partner_id, token_data["access_token"], refresh_token, token_data["expires_in"])
        return token_data["access_token"]
    
    print("❌ Failed to refresh access token:", token_data)
    return None


@app.route('/start-oauth')
def start_oauth():
    """Redirects user to Amazon for OAuth authentication."""
    state = str(uuid.uuid4())
    session["oauth_state"] = state

    oauth_url = (
        f"{AUTH_URL}/apps/authorize/consent"
        f"?application_id={APP_ID}"
        f"&state={state}"
        f"&redirect_uri={REDIRECT_URI}"
        f"&version=beta"
    )

    print(f"🔗 OAuth Redirect URL: {oauth_url}")
    return redirect(oauth_url)


@app.route('/callback')
def callback():
    """Handles Amazon OAuth callback and stores access tokens."""
    auth_code = request.args.get("spapi_oauth_code")
    selling_partner_id = request.args.get("selling_partner_id")

    if not auth_code or not selling_partner_id:
        return jsonify({"error": "Missing auth_code or selling_partner_id"}), 400

    print(f"🚀 Received auth_code: {auth_code}")
    print(f"🔍 Received selling_partner_id: {selling_partner_id}")

    # Exchange auth code for access & refresh tokens
    token_payload = {
        "grant_type": "authorization_code",
        "code": auth_code,
        "client_id": LWA_APP_ID,
        "client_secret": LWA_CLIENT_SECRET
    }

    token_response = requests.post(TOKEN_URL, data=token_payload)
    token_data = token_response.json()

    if "access_token" in token_data and "refresh_token" in token_data:
        save_oauth_tokens(
            selling_partner_id,
            token_data["access_token"],
            token_data["refresh_token"],
            token_data["expires_in"]
        )

        return redirect(f"https://guillermos-amazing-site-b0c75a.webflow.io/dashboard")

    return jsonify({"error": "Failed to obtain tokens", "details": token_data}), 400


@app.route('/get-orders', methods=['GET'])
def get_orders():
    """Fetch orders from database first, if not found then fetch from Amazon SP-API."""
    selling_partner_id = request.args.get("selling_partner_id")

    if not selling_partner_id:
        return jsonify({"error": "Missing selling_partner_id"}), 400

    # 1️⃣ Check if orders exist in the database
    stored_orders = get_stored_orders(selling_partner_id)

    if stored_orders:
        print("📊 Returning orders from database cache.")
        return jsonify({"orders": stored_orders})

    print("🔍 No orders found in database, fetching from SP-API...")

    # 2️⃣ Fetch from API if not found in DB
    orders_data = fetch_orders_from_amazon(selling_partner_id)

    if "orders" in orders_data:
        # 3️⃣ Store in the database for future requests
        store_orders_in_database(selling_partner_id, orders_data["orders"])
        return jsonify(orders_data)

    return jsonify({"error": "Failed to fetch orders", "details": orders_data}), 400

def get_stored_orders(selling_partner_id):
    """Retrieve stored orders from PostgreSQL database."""
    with DB_CONN.cursor() as cur:
        cur.execute("""
            SELECT order_id, status, total, currency, purchase_date 
            FROM amazon_orders 
            WHERE selling_partner_id = %s
            ORDER BY purchase_date DESC
        """, (selling_partner_id,))

        orders = cur.fetchall()
        return [
            {
                "order_id": row[0],
                "status": row[1],
                "total": row[2],
                "currency": row[3],
                "purchase_date": row[4]
            }
            for row in orders
        ]

def store_orders_in_database(selling_partner_id, orders):
    """Store fetched orders into PostgreSQL for future use."""
    with DB_CONN.cursor() as cur:
        for order in orders:
            cur.execute("""
                INSERT INTO amazon_orders (selling_partner_id, order_id, status, total, currency, purchase_date)
                VALUES (%s, %s, %s, %s, %s, %s)
                ON CONFLICT (order_id) DO NOTHING;
            """, (
                selling_partner_id,
                order.get("order_id"),
                order.get("status"),
                order.get("total"),
                order.get("currency"),
                order.get("purchase_date")
            ))
        
        DB_CONN.commit()




@app.route('/fetch-reports', methods=['GET'])
def fetch_reports():
    """Fetch financial reports from Amazon Reports API and store in PostgreSQL."""
    selling_partner_id = request.args.get("selling_partner_id")

    if not selling_partner_id:
        return jsonify({"error": "Missing selling_partner_id"}), 400

    print(f"📊 Fetching reports for {selling_partner_id}")

    # 1️⃣ Call Amazon Reports API
    reports_data = fetch_reports_from_amazon(selling_partner_id)

    if "reports" in reports_data:
        # 2️⃣ Store in the database
        store_reports_in_database(selling_partner_id, reports_data["reports"])
        return jsonify({"message": "Reports saved successfully!", "reports": reports_data["reports"]})

    return jsonify({"error": "Failed to fetch reports", "details": reports_data}), 400


def fetch_reports_from_amazon(selling_partner_id):
    """Request financial reports from Amazon Reports API."""
    amazon_reports_url = f"{SP_API_BASE_URL}/reports/v0/reports"

    headers = {
        "x-amz-access-token": get_valid_access_token(selling_partner_id),
        "Content-Type": "application/json"
    }

    try:
        response = requests.get(amazon_reports_url, headers=headers)
        reports_data = response.json()

        return reports_data
    except requests.exceptions.RequestException as e:
        print("❌ API Request Error:", e)
        return {"error": "Failed to connect to Amazon", "details": str(e)}

def store_reports_in_database(selling_partner_id, reports):
    """Save Amazon financial reports into PostgreSQL for future analysis."""
    with DB_CONN.cursor() as cur:
        for report in reports:
            cur.execute("""
                INSERT INTO amazon_reports (selling_partner_id, report_id, report_type, created_date, data)
                VALUES (%s, %s, %s, %s, %s)
                ON CONFLICT (report_id) DO NOTHING;
            """, (
                selling_partner_id,
                report.get("reportId"),
                report.get("reportType"),
                report.get("createdDate"),
                str(report.get("data"))  # Store JSON as a string
            ))
        
        DB_CONN.commit()



@app.route('/download-orders', methods=['GET'])
def download_orders():
    """Fetch orders from Amazon SP-API and generate a downloadable CSV file."""
    selling_partner_id = request.args.get("selling_partner_id")
    access_token = request.args.get("access_token")
    refresh_token = request.args.get("refresh_token")

    if not selling_partner_id:
        return jsonify({"error": "Missing selling_partner_id"}), 400

    stored_tokens = get_stored_tokens(selling_partner_id)
    if stored_tokens:
        stored_access_token, stored_refresh_token, expires_at = stored_tokens
        if not access_token:
            access_token = stored_access_token
        if not refresh_token:
            refresh_token = stored_refresh_token

        # Check if the access token is expired
        if expires_at and datetime.utcnow() >= expires_at:
            print("🔄 Token expired, refreshing...")
            access_token = refresh_access_token(selling_partner_id, refresh_token)

    if not access_token or not refresh_token:
        return jsonify({"error": "Missing authentication credentials"}), 400

    # Define Amazon Marketplace ID (Mexico: A1AM78C64UM0Y8)
    marketplace_id = "A1AM78C64UM0Y8"
    created_after = (datetime.utcnow() - timedelta(days=200)).isoformat() + "Z"

    # Construct the API request URL
    amazon_orders_url = (
        f"{SP_API_BASE_URL}/orders/v0/orders"
        f"?MarketplaceIds={marketplace_id}"
        f"&CreatedAfter={created_after}"
    )

    headers = {
        "x-amz-access-token": access_token,
        "Content-Type": "application/json"
    }

    print(f"📡 Fetching orders for Selling Partner ID: {selling_partner_id}")
    print(f"🔗 Amazon API URL: {amazon_orders_url}")

    try:
        response = requests.get(amazon_orders_url, headers=headers)
        orders_data = response.json()

        if "errors" in orders_data and orders_data["errors"][0]["code"] == "Unauthorized":
            print("🔄 Access token expired, attempting refresh...")
            new_access_token = refresh_access_token(selling_partner_id, refresh_token)

            if new_access_token:
                headers["x-amz-access-token"] = new_access_token
                response = requests.get(amazon_orders_url, headers=headers)
                orders_data = response.json()
            else:
                return jsonify({"error": "Failed to refresh access token"}), 401

        if "payload" in orders_data and "Orders" in orders_data["payload"]:
            orders_list = orders_data["payload"]["Orders"]
        else:
            print("❌ ERROR: Unexpected API response format")
            return jsonify({"error": "Failed to fetch orders", "details": orders_data}), 400

        # Define CSV file path
        csv_filename = "orders.csv"
        csv_filepath = os.path.join(os.getcwd(), csv_filename)

        # Write fetched orders to CSV
        with open(csv_filepath, "w", newline="", encoding="utf-8") as csv_file:
            writer = csv.DictWriter(csv_file, fieldnames=["order_id", "status", "total", "currency", "purchase_date"])
            writer.writeheader()

            for order in orders_list:
                writer.writerow({
                    "order_id": order.get("AmazonOrderId", "N/A"),
                    "status": order.get("OrderStatus", "N/A"),
                    "total": float(order.get("OrderTotal", {}).get("Amount", 0)),
                    "currency": order.get("OrderTotal", {}).get("CurrencyCode", "N/A"),
                    "purchase_date": order.get("PurchaseDate", "N/A")
                })

        # Send file as an attachment for download
        return send_file(csv_filepath, as_attachment=True)

    except requests.exceptions.RequestException as e:
        print("❌ API Request Error:", e)
        return jsonify({"error": "Failed to connect to Amazon", "details": str(e)}), 500



if __name__ == "__main__":
    from os import environ
    app.run(host="0.0.0.0", port=int(environ.get("PORT", 5000)))