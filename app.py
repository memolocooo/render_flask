import os
import requests
import uuid
from flask import Flask, jsonify, request, redirect, session
from dotenv import load_dotenv
from flask_cors import CORS
from flask_session import Session
import psycopg2
from datetime import datetime, timedelta

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


@app.route('/start-oauth')
def start_oauth():
    """Redirects user to Amazon OAuth login page."""
    state = str(uuid.uuid4())
    session['oauth_state'] = state  # Store state in session

    amazon_auth_url = (
        f"{AUTH_URL}?"
        f"application_id={APP_ID}&"
        f"state={state}&"
        f"redirect_uri={REDIRECT_URI}&"
        f"version=beta"
    )

    print(f"🔗 OAuth Redirect URL: {amazon_auth_url}")
    return redirect(amazon_auth_url)


@app.route('/callback')
def callback():
    """Handles OAuth callback and exchanges auth code for tokens."""
    auth_code = request.args.get("spapi_oauth_code")
    selling_partner_id = request.args.get("selling_partner_id")

    if not auth_code or not selling_partner_id:
        print("❌ ERROR: Missing auth_code or selling_partner_id")
        return jsonify({"error": "Missing parameters"}), 400

    print("🚀 Received auth_code:", auth_code)
    print("🔍 Received selling_partner_id:", selling_partner_id)

    if not LWA_APP_ID or not LWA_CLIENT_SECRET or not REDIRECT_URI:
        print("❌ ERROR: Missing OAuth credentials from .env")
        return jsonify({"error": "OAuth credentials missing"}), 500

    payload = {
        "grant_type": "authorization_code",
        "code": auth_code,
        "redirect_uri": REDIRECT_URI,
        "client_id": LWA_APP_ID,
        "client_secret": LWA_CLIENT_SECRET,
    }

    headers = {"Content-Type": "application/x-www-form-urlencoded"}

    print("🛠️ Sending OAuth Token Exchange Request...")
    response = requests.post(TOKEN_URL, data=payload, headers=headers)

    try:
        token_data = response.json()
    except Exception as e:
        print("❌ ERROR: Could not parse JSON response", e)
        return jsonify({"error": "Invalid response from Amazon", "details": str(e)}), 500

    print("🔍 OAuth Response:", token_data)

    if "access_token" not in token_data:
        return jsonify({"error": "Failed to exchange token", "details": token_data}), 400

    # Save tokens in DB
    save_oauth_tokens(
        selling_partner_id,
        token_data["access_token"],
        token_data["refresh_token"],
        token_data["expires_in"]
    )

    # Store tokens in session for Webflow dashboard
    session["access_token"] = token_data["access_token"]
    session["refresh_token"] = token_data["refresh_token"]
    session["selling_partner_id"] = selling_partner_id

    # Redirect to Webflow dashboard with tokens
    return redirect(f"https://guillermos-amazing-site-b0c75a.webflow.io/dashboard"
                    f"?selling_partner_id={selling_partner_id}"
                    f"&access_token={token_data['access_token']}"
                    f"&refresh_token={token_data['refresh_token']}"
                    f"&expires_in={token_data['expires_in']}")



@app.route('/get-amazon-tokens', methods=["GET"])
def get_amazon_tokens():
    """Fetch stored OAuth tokens for a selling partner."""
    selling_partner_id = request.args.get("selling_partner_id")

    if not selling_partner_id:
        return jsonify({"error": "Missing selling_partner_id"}), 400

    try:
        with DB_CONN.cursor() as cur:
            cur.execute("""
                SELECT access_token, refresh_token, expires_at 
                FROM amazon_oauth_tokens 
                WHERE selling_partner_id = %s
            """, (selling_partner_id,))
            result = cur.fetchone()

        if result:
            access_token, refresh_token, expires_at = result
            return jsonify({
                "message": "Amazon SP-API Tokens Retrieved Successfully!",
                "access_token": access_token,
                "refresh_token": refresh_token,
                "selling_partner_id": selling_partner_id,
                "expires_at": expires_at.isoformat(),
                "token_type": "bearer"
            })

        return jsonify({"error": "User not authenticated"}), 401

    except Exception as e:
        return jsonify({"error": "Database connection failed", "details": str(e)}), 500



@app.route('/get-orders', methods=['GET'])
def get_orders():
    """Fetch orders from Amazon SP-API for the last 30 days."""
    selling_partner_id = request.args.get("selling_partner_id")
    access_token = request.args.get("access_token")

    if not selling_partner_id or not access_token:
        print("❌ ERROR: Missing selling_partner_id or access_token")
        return jsonify({"error": "Missing selling_partner_id or access_token"}), 400

    # Define Amazon Marketplace ID (Mexico: A1AM78C64UM0Y8, Change if needed)
    marketplace_id = "A1AM78C64UM0Y8"

    # Calculate the date 30 days ago
    created_after = (datetime.utcnow() - timedelta(days=200)).isoformat() + "Z"

    # Construct the API request URL with CreatedAfter filter
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
    print(f"🔑 Access Token (masked): {access_token[:10]}...")
    print(f"📅 Created After: {created_after}")

    try:
        response = requests.get(amazon_orders_url, headers=headers)
        orders_data = response.json()

        print("📊 Amazon Orders Response:", orders_data)

        # 🛠 FIX: Ensure response contains 'Orders' before proceeding
        if "payload" in orders_data and "Orders" in orders_data["payload"]:
            orders_list = orders_data["payload"]["Orders"]

            # ✅ Check if there are no orders and return a clean response
            if len(orders_list) == 0:
                print("⚠️ No orders found in the requested date range.")
                return jsonify({"message": "No orders found", "orders": []}), 200

            # ✅ Extract order details
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

            return jsonify({"orders": orders_summary})

        else:
            print("❌ ERROR: Unexpected API response format")
            return jsonify({"error": "Failed to fetch orders", "details": orders_data}), 400

    except requests.exceptions.RequestException as e:
        print("❌ API Request Error:", e)
        return jsonify({"error": "Failed to connect to Amazon", "details": str(e)}), 500



if __name__ == "__main__":
    from os import environ
    app.run(host="0.0.0.0", port=int(environ.get("PORT", 5000)))
