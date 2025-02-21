from app import app
from amazon_api import fetch_orders_from_amazon
from models import db, AmazonOAuthTokens, AmazonOrders
from datetime import datetime, timedelta

selling_partner_id = "A3IW67JB0KIPK8"

with app.app_context():
    # ✅ Step 1: Retrieve OAuth token
    token_entry = AmazonOAuthTokens.query.filter_by(selling_partner_id=selling_partner_id).first()

    if not token_entry:
        print("❌ No OAuth token found for seller!")
    else:
        access_token = token_entry.access_token
        created_after = (datetime.utcnow() - timedelta(days=365)).isoformat()
        
        print(f"🔍 Fetching orders for seller {selling_partner_id} since {created_after}")

        # ✅ Step 2: Fetch orders from Amazon
        orders = fetch_orders_from_amazon(selling_partner_id, access_token, created_after)

        if not orders:
            print("❌ No orders returned from Amazon API!")
        else:
            print(f"✅ Amazon returned {len(orders)} orders!")

            # ✅ Step 3: Store orders in PostgreSQL
            for order in orders:
                new_order = AmazonOrders(
                    order_id=order.get("AmazonOrderId"),
                    marketplace_id=order.get("MarketplaceId"),
                    selling_partner_id=selling_partner_id,
                    number_of_items_shipped=order.get("NumberOfItemsShipped", 0),
                    order_status=order.get("OrderStatus"),
                    total_amount=order.get("OrderTotal", {}).get("Amount", 0),
                    currency=order.get("OrderTotal", {}).get("CurrencyCode"),
                    purchase_date=datetime.strptime(order["PurchaseDate"], "%Y-%m-%dT%H:%M:%SZ"),
                    created_at=datetime.utcnow(),
                )
                db.session.add(new_order)

            try:
                db.session.commit()
                print("✅ Orders successfully saved to database!")
            except Exception as e:
                db.session.rollback()
                print(f"❌ Error saving orders: {e}")
