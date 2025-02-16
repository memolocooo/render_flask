import os
import uuid 
import requests
import redis
import json 
from flask import Flask, session, redirect, request
from flask_sqlalchemy import SQLAlchemy
from flask_migrate import Migrate
from dotenv import load_dotenv  # ✅ Load .env variables
from models import AmazonOAuthTokens
from datetime import datetime, timedelta


load_dotenv()  # ✅ Load environment variables

app = Flask(__name__)

# ✅ Get database URL from environment variables
app.config["SQLALCHEMY_DATABASE_URI"] = os.getenv("DATABASE_URL")
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

# Load OAuth credentials from environment
LWA_APP_ID = os.getenv("LWA_APP_ID")
LWA_CLIENT_SECRET = os.getenv("LWA_CLIENT_SECRET")
REDIRECT_URI = os.getenv("REDIRECT_URI")
AUTH_URL = os.getenv("AUTH_URL")
TOKEN_URL = os.getenv("TOKEN_URL")
SP_API_BASE_URL = os.getenv("SP_API_BASE_URL")
APP_ID = os.getenv("APP_ID")


# ✅ Import models and initialize db
from models import db
db.init_app(app)  # ✅ Initialize db with the app

migrate = Migrate(app, db)

# ✅ Check database connection
with app.app_context():
    try:
        db.engine.connect()
        print("✅ Database connected successfully!")
    except Exception as e:
        print(f"❌ Database connection error: {e}")

if __name__ == "__main__":
    app.run(debug=True)


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


# Redis Connection
REDIS_URL = os.getenv("REDIS_URL")
redis_client = redis.StrictRedis.from_url(REDIS_URL, decode_responses=True)

@app.route('/get-orders', methods=['GET'])
def get_orders():
    """Fetch orders from Amazon SP-API and cache in Redis."""
    selling_partner_id = request.args.get("selling_partner_id")

    if not selling_partner_id:
        return jsonify({"error": "Missing selling_partner_id"}), 400

    # Check Redis Cache
    cache_key = f"orders_{selling_partner_id}"
    cached_orders = redis_client.get(cache_key)

    if cached_orders:
        print("✅ Returning cached orders")
        return jsonify({"orders": json.loads(cached_orders)})

    # Retrieve stored tokens
    stored_tokens = get_stored_tokens(selling_partner_id)
    if not stored_tokens:
        return jsonify({"error": "Missing authentication credentials"}), 400

    access_token, refresh_token, expires_at = stored_tokens

    if expires_at and datetime.utcnow() >= expires_at:
        access_token = refresh_access_token(selling_partner_id, refresh_token)

    # Fetch orders from Amazon API
    marketplace_id = "A1AM78C64UM0Y8"
    created_after = (datetime.utcnow() - timedelta(days=200)).isoformat() + "Z"

    amazon_orders_url = f"{SP_API_BASE_URL}/orders/v0/orders?MarketplaceIds={marketplace_id}&CreatedAfter={created_after}"

    headers = {
        "x-amz-access-token": access_token,
        "Content-Type": "application/json"
    }

    response = requests.get(amazon_orders_url, headers=headers)
    orders_data = response.json()

    if "payload" in orders_data and "Orders" in orders_data["payload"]:
        orders_list = orders_data["payload"]["Orders"]
        save_orders_to_db(orders_list, selling_partner_id)
        redis_client.set(cache_key, json.dumps(orders_list), ex=1800)  # Cache for 30 min
        return jsonify({"orders": orders_list})

    return jsonify({"error": "Failed to fetch orders", "details": orders_data}), 400
