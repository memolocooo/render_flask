from flask_sqlalchemy import SQLAlchemy
from datetime import datetime

db = SQLAlchemy()  # ✅ Define db without app here, will be initialized in `app.py`

# 🔹 1. AMAZON CACHE
class AmazonCache(db.Model):
    __tablename__ = "amazon_cache"
    
    id = db.Column(db.Integer, primary_key=True)
    cache_key = db.Column(db.String(255), unique=True, nullable=False)
    data = db.Column(db.JSON, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

# 🔹 2. AMAZON FEES
class AmazonFees(db.Model):
    __tablename__ = "amazon_fees"
    
    id = db.Column(db.Integer, primary_key=True)
    order_id = db.Column(db.String(50), db.ForeignKey("amazon_orders.order_id"), nullable=False)
    fee_type = db.Column(db.String(255), nullable=False)  
    amount = db.Column(db.Numeric(10, 2), nullable=False)
    currency = db.Column(db.String(10), nullable=False)

# 🔹 3. AMAZON OAUTH TOKENS (✅ Fixed Table Name)
class AmazonOAuthTokens(db.Model):
    __tablename__ = "amazon_oauth_tokens"  # ✅ Fixed the table name
    
    id = db.Column(db.Integer, primary_key=True)
    seller_id = db.Column(db.String(50), db.ForeignKey("amazon_sellers.seller_id"), nullable=False)
    access_token = db.Column(db.Text, nullable=False)
    refresh_token = db.Column(db.Text, nullable=False)
    expires_at = db.Column(db.DateTime, nullable=False)

# 🔹 4. AMAZON ORDER ITEMS
class AmazonOrderItems(db.Model):
    __tablename__ = "amazon_order_items"
    
    id = db.Column(db.Integer, primary_key=True)
    order_id = db.Column(db.String(50), db.ForeignKey("amazon_orders.order_id"), nullable=False)
    product_id = db.Column(db.String(50), db.ForeignKey("amazon_products.product_id"), nullable=False)
    quantity = db.Column(db.Integer, nullable=False)
    price_per_unit = db.Column(db.Numeric(10, 2), nullable=False)

# 🔹 5. AMAZON ORDERS
class AmazonOrders(db.Model):
    __tablename__ = "amazon_orders"
    
    order_id = db.Column(db.String(50), primary_key=True)
    seller_id = db.Column(db.String(50), db.ForeignKey("amazon_sellers.seller_id"), nullable=False)
    total_amount = db.Column(db.Numeric(10, 2), nullable=False)
    currency = db.Column(db.String(10), nullable=False)
    order_status = db.Column(db.String(50), nullable=False)
    purchase_date = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)

# 🔹 6. AMAZON PRODUCTS
class AmazonProducts(db.Model):
    __tablename__ = "amazon_products"
    
    product_id = db.Column(db.String(50), primary_key=True)
    seller_id = db.Column(db.String(50), db.ForeignKey("amazon_sellers.seller_id"), nullable=False)
    title = db.Column(db.String(255), nullable=False)
    category = db.Column(db.String(100), nullable=True)
    price = db.Column(db.Numeric(10, 2), nullable=False)
    currency = db.Column(db.String(10), nullable=False)

# 🔹 7. AMAZON REFUNDS
class AmazonRefunds(db.Model):
    __tablename__ = "amazon_refunds"
    
    id = db.Column(db.Integer, primary_key=True)
    order_id = db.Column(db.String(50), db.ForeignKey("amazon_orders.order_id"), nullable=False)
    amount = db.Column(db.Numeric(10, 2), nullable=False)
    currency = db.Column(db.String(10), nullable=False)
    refund_date = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)

# 🔹 8. AMAZON SELLERS
class AmazonSellers(db.Model):
    __tablename__ = "amazon_sellers"
    
    seller_id = db.Column(db.String(50), primary_key=True)
    seller_name = db.Column(db.String(255), nullable=False)
    country = db.Column(db.String(50), nullable=False)
