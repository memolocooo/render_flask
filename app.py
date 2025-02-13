import psycopg2
from datetime import datetime, timedelta
from flask import Flask, jsonify, request, redirect, session
import os
from dotenv import load_dotenv
from flask_cors import CORS
from flask_session import Session
import requests
import uuid

# Initialize Flask App
app = Flask(__name__)
app.secret_key = os.getenv("FLASK_SECRET_KEY")
CORS(app, supports_credentials=True, origins=["https://guillermos-amazing-site-b0c75a.webflow.io"])

# ✅ Ensure session is properly configured before using `Session(app)`
app.config["SESSION_TYPE"] = "filesystem"
app.config["SESSION_PERMANENT"] = False
app.config["SESSION_FILE_DIR"] = "./flask_session_data"  # Ensure this exists

# ✅ Initialize Flask-Session after setting config
Session(app)

# Load environment variables
load_dotenv()

# Utility function to generate a unique state
def generate_state():
    return str(uuid.uuid4())

print("✅ Connected to PostgreSQL!")

# Amazon OAuth Variables
LWA_APP_ID = os.getenv("LWA_APP_ID")
LWA_CLIENT_SECRET = os.getenv("LWA_CLIENT_SECRET")
REDIRECT_URI = os.getenv("REDIRECT_URI")
AUTH_URL = os.getenv("AUTH_URL")
TOKEN_URL = os.getenv("TOKEN_URL")
SP_API_BASE_URL = os.getenv("SP_API_BASE_URL")  # Amazon SP-API Endpoint
USE_SANDBOX = os.getenv("USE_SANDBOX", "False").lower() == "true"  # Convert to boolean

# Use Render's database URL
DATABASE_URL = os.getenv("DB_URL")

# Ensure DATABASE_URL is set correctly
if not DATABASE_URL:
    raise Exception("❌ DATABASE_URL is missing. Check Render Environment Variables.")

# Connect to PostgreSQL
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
    state = generate_state()
    session['oauth_state'] = state  # Store state in session

    amazon_auth_url = (
        f"{AUTH_URL}?"
        f"application_id={LWA_APP_ID}&"
        f"state={state}&"
        f"redirect_uri={REDIRECT_URI}&"
        f"version=beta"
    )

    print(f"🔗 OAuth Redirect URL: {amazon_auth_url}")  # Debugging
    return redirect(amazon_auth_url)


@app.route('/callback')
def callback():
    """Handles the OAuth callback and stores credentials in PostgreSQL."""
    auth_code = request.args.get("spapi_oauth_code")
    selling_partner_id = request.args.get("selling_partner_id")

    if not auth_code:
        return jsonify({"error": "Missing spapi_oauth_code"}), 400

    if not selling_partner_id:
        print("❌ ERROR: Missing selling_partner_id in callback")
        return jsonify({"error": "Missing selling_partner_id"}), 400

    print("🚀 Received auth_code:", auth_code)
    print("🔍 Received selling_partner_id:", selling_partner_id)

    payload = {
        "grant_type": "authorization_code",
        "code": auth_code,
        "redirect_uri": REDIRECT_URI,
        "client_id": LWA_APP_ID,
        "client_secret": LWA_CLIENT_SECRET,
    }
    headers = {"Content-Type": "application/x-www-form-urlencoded"}

    response = requests.post(TOKEN_URL, data=payload, headers=headers)
    token_data = response.json()

    if "access_token" not in token_data:
        print("❌ OAuth Token Exchange Failed:", token_data)
        return jsonify({"error": "Failed to exchange token", "details": token_data}), 400

    save_oauth_tokens(
        selling_partner_id,
        token_data["access_token"],
        token_data["refresh_token"],
        token_data["expires_in"]
    )

    session["access_token"] = token_data["access_token"]
    session["refresh_token"] = token_data["refresh_token"]
    session["selling_partner_id"] = selling_partner_id

    return redirect(f"https://guillermos-amazing-site-b0c75a.webflow.io/dashboard?selling_partner_id={selling_partner_id}")


@app.route("/sandbox-test")
def sandbox_test():
    """Test Amazon SP-API in Sandbox Mode"""
    if not USE_SANDBOX:
        return jsonify({"error": "Sandbox mode is disabled. Enable it in .env"}), 400

    url = f"{SP_API_BASE_URL}/sandbox/some-test-endpoint"
    headers = {"Authorization": f"Bearer {session.get('access_token')}"}

    response = requests.get(url, headers=headers)
    return jsonify(response.json())


if __name__ == "__main__":
    from os import environ
    app.run(host="0.0.0.0", port=int(environ.get("PORT", 5000)))
