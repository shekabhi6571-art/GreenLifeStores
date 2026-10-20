import os
import httpx
from typing import List
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

app = FastAPI(title="GreenLifeStores API")

# CORS Middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

FAST2SMS_API_KEY = os.getenv("FAST2SMS_API_KEY", "YOUR_FAST2SMS_API_KEY_HERE")

class OrderItem(BaseModel):
    id: int
    name: str
    price: float
    qty: int

class OrderCreate(BaseModel):
    customer_name: str
    phone: str
    address: str
    city: str
    pincode: str
    total_amount: float
    items: List[OrderItem]

async def send_order_sms(phone_number: str, order_id: str, amount: str):
    url = "https://www.fast2sms.com/dev/bulkV2"
    clean_phone = "".join(filter(str.isdigit, phone_number))[-10:]
    message = f"Thank you! Your order #{order_id} of Rs.{amount} has been placed successfully on GreenLifeStores."
    
    payload = {
        "route": "v3",
        "sender_id": "TXTIND",
        "message": message,
        "language": "english",
        "flash": 0,
        "numbers": clean_phone
    }
    headers = {
        "authorization": FAST2SMS_API_KEY,
        "Content-Type": "application/x-www-form-urlencoded"
    }

    async with httpx.AsyncClient() as client:
        try:
            response = await client.post(url, data=payload, headers=headers)
            return response.json()
        except Exception as e:
            print(f"SMS Error: {e}")
            return None

# --- API Endpoints ---
@app.get("/api/products")
def get_products():
    return [
        {"id": 1, "name": "Earthy Clay Water Bottle", "category": "soil", "price": 499, "image": "https://via.placeholder.com/200"},
        {"id": 2, "name": "Terracotta Travel Sipper Bottle", "category": "soil", "price": 599, "image": "https://via.placeholder.com/200"},
        {"id": 3, "name": "Warli Art Terracotta Bottle", "category": "soil", "price": 699, "image": "https://via.placeholder.com/200"},
        {"id": 4, "name": "Traditional Mitti Jug & Cup Set", "category": "soil", "price": 799, "image": "https://via.placeholder.com/200"},
        {"id": 5, "name": "Handcrafted Clay Curd Handi", "category": "soil", "price": 349, "image": "https://via.placeholder.com/200"},
        {"id": 6, "name": "Terracotta Water Dispenser", "category": "soil", "price": 1299, "image": "https://via.placeholder.com/200"},
        {"id": 7, "name": "Bamboo Toothbrush Pack of 4", "category": "care", "price": 299, "image": "https://via.placeholder.com/200"},
        {"id": 8, "name": "Neem & Bamboo Grooming Comb Set", "category": "care", "price": 249, "image": "https://via.placeholder.com/200"},
        {"id": 9, "name": "Handwoven Bamboo Lamp Shade", "category": "decor", "price": 899, "image": "https://via.placeholder.com/200"},
        {"id": 10, "name": "Handcrafted Bamboo Storage Basket", "category": "decor", "price": 649, "image": "https://via.placeholder.com/200"},
        {"id": 11, "name": "Bamboo Cooking Utensils Set of 6", "category": "kitchen", "price": 499, "image": "https://via.placeholder.com/200"},
        {"id": 12, "name": "Clay Cooking Handi Pot", "category": "kitchen", "price": 549, "image": "https://via.placeholder.com/200"}
    ]

@app.post("/api/checkout")
async def checkout(order: OrderCreate):
    import random
    order_id = str(random.randint(100000, 999999))
    if order.phone:
        await send_order_sms(phone_number=order.phone, order_id=order_id, amount=str(order.total_amount))
    return {"status": "success", "order_id": order_id, "message": "Order placed successfully!"}

# --- Static Files Mount (Sabse Last Mein) ---
app.mount("/", StaticFiles(directory=".", html=True), name="static")