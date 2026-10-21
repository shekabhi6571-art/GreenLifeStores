import os
import requests
from fastapi import FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pydantic import BaseModel
from typing import List, Optional

app = FastAPI(title="GreenLifeStores API")

# --- Fast2SMS Helper Function ---
def send_delivery_sms(phone_number: str, customer_name: str, delivery_days: str = "3-5 business days"):
    api_key = os.environ.get("FAST2SMS_API_KEY")
    if not api_key:
        print("Fast2SMS API Key missing in environment variables!")
        return False

    # Clean phone number (remove spaces, +91, etc.)
    clean_phone = ''.join(filter(str.isdigit, str(phone_number)))
    if len(clean_phone) > 10:
        clean_phone = clean_phone[-10:]

    # Message to be sent via Fast2SMS
    message = f"Hello {customer_name}, your GreenLifeStores order has been confirmed! Estimated delivery: {delivery_days}. Thank you for choosing sustainability!"

    url = "https://www.fast2sms.com/dev/bulkV2"
    payload = {
        "route": "q",
        "message": message,
        "language": "english",
        "flash": 0,
        "numbers": clean_phone
    }
    headers = {
        'authorization': api_key,
        'Content-Type': 'application/json'
    }

    try:
        response = requests.post(url, json=payload, headers=headers, timeout=10)
        res_data = response.json()
        print("Fast2SMS Response:", res_data)
        return True
    except Exception as e:
        print("Error triggering Fast2SMS:", e)
        return False

# --- Data Models ---
class OrderItem(BaseModel):
    id: int
    name: str
    price: float
    qty: int

class OrderCreate(BaseModel):
    name: str
    phone: str
    address: str
    payment_method: str
    items: List[OrderItem]
    total_amount: float

# --- In-Memory Database / Mock Data ---
products_db = [
    {
        "id": 1,
        "name": "Earthy Clay Water Bottle",
        "category": "soil",
        "price": 499,
        "description": "A reusable clay water bottle for keeping drinking water fresh and naturally cool.",
        "image": "/static/images/Earthy_Clay_Water_Bottle.jpg"
    },
    {
        "id": 2,
        "name": "Terracotta Travel Sipper",
        "category": "soil",
        "price": 599,
        "description": "A portable terracotta sipper bottle made for carrying water on commutes and travel.",
        "image": "/static/images/Terracotta_Travel_Sipper.jpg"
    },
    {
        "id": 3,
        "name": "Warli Art Terracotta Bottle",
        "category": "soil",
        "price": 699,
        "description": "A terracotta bottle decorated with traditional handcrafted art.",
        "image": "/static/images/Warli_Art_Terracotta_Bottle.jpg"
    },
    {
        "id": 4,
        "name": "Traditional Mitti Jug & Cup Set",
        "category": "soil",
        "price": 799,
        "description": "A traditional mitti jug paired with clay cups for serving water at home.",
        "image": "/static/images/Traditional_Mitti_Jug_%26_Cup_Set.jpg"
    },
    {
        "id": 5,
        "name": "Organic Neem Wooden Comb",
        "category": "care",
        "price": 249,
        "description": "Handcrafted neem wood comb for healthy hair and scalp care.",
        "image": "/static/images/Organic_Neem_Wooden_Comb.jpg"
    },
    {
        "id": 6,
        "name": "Bamboo Toothbrush Pack",
        "category": "care",
        "price": 199,
        "description": "Eco-friendly bamboo toothbrushes with soft bristles for daily personal hygiene.",
        "image": "/static/images/Bamboo_Toothbrush_Pack.jpg"
    },
    {
        "id": 7,
        "name": "Handmade Bamboo Lampshade",
        "category": "decor",
        "price": 899,
        "description": "Woven bamboo lampshade creating ambient lighting for home decor.",
        "image": "/static/images/Handmade_Bamboo_Lampshade.jpg"
    },
    {
        "id": 8,
        "name": "Terracotta Cooking Handi",
        "category": "kitchen",
        "price": 649,
        "description": "Traditional clay handi for cooking nutritious and flavorful meals.",
        "image": "/static/images/Terracotta_Cooking_Handi.jpg"
    }
]

orders_db = []

# --- Static Files & Frontend Routing ---
app.mount("/static", StaticFiles(directory="static"), name="static")

@app.get("/")
async def serve_index():
    return FileResponse("products.html")

@app.get("/products.html")
async def serve_products():
    return FileResponse("products.html")

@app.get("/account.html")
async def serve_account():
    return FileResponse("account.html")

@app.get("/orders.html")
async def serve_orders():
    return FileResponse("orders.html")

@app.get("/about.html")
async def serve_about():
    return FileResponse("about.html")

@app.get("/admin.html")
async def serve_admin():
    return FileResponse("admin.html")

# --- API Endpoints ---
@app.get("/api/products")
async def get_products():
    return products_db

@app.post("/api/orders")
async def create_order(order: OrderCreate):
    order_id = len(orders_db) + 1
    new_order = {
        "order_id": order_id,
        "name": order.name,
        "phone": order.phone,
        "address": order.address,
        "payment_method": order.payment_method,
        "items": [item.dict() for item in order.items],
        "total_amount": order.total_amount,
        "status": "Confirmed"
    }
    orders_db.append(new_order)

    # Trigger SMS notification via Fast2SMS
    sms_sent = send_delivery_sms(phone_number=order.phone, customer_name=order.name, delivery_days="3-5 business days")

    return {
        "status": "success",
        "order_id": order_id,
        "message": "Order placed successfully!",
        "sms_sent": sms_sent
    }

@app.get("/api/orders")
async def get_orders():
    return orders_db