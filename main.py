import os
import httpx
from typing import List, Optional
from fastapi import FastAPI, HTTPException
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

# In-memory storage
fake_db = {
    "current_customer": None,
    "pending_customer": None,
    "otp_store": {},
    "orders": []
}

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

class CustomerRegisterSchema(BaseModel):
    name: str
    email: str
    phone: str
    password: str
    marketing_consent: bool = False

class OtpVerifySchema(BaseModel):
    phone: str
    otp: str

class CustomerLoginSchema(BaseModel):
    identifier: str
    password: str

class ConsentSchema(BaseModel):
    marketing_consent: bool

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

# --- Products API with Exact Original Image Filenames ---
@app.get("/api/products")
def get_products():
    return [
        {
            "id": 1, 
            "name": "Earthy Clay Water Bottle", 
            "category": "soil", 
            "price": 499, 
            "image": "images/clay-bottle-1.jpg", 
            "description": "A reusable clay water bottle for keeping drinking water fresh and naturally cool."
        },
        {
            "id": 2, 
            "name": "Terracotta Travel Sipper", 
            "category": "soil", 
            "price": 599, 
            "image": "images/Terracotta Travel Sipper Bottle.jpg", 
            "description": "A portable terracotta sipper bottle made for carrying water on commutes and travel."
        },
        {
            "id": 3, 
            "name": "Warli Art Terracotta Bottle", 
            "category": "soil", 
            "price": 699, 
            "image": "images/Hand-Painted Warli Art Clay Bottle.jpg", 
            "description": "A terracotta bottle decorated with traditional handcrafted art."
        },
        {
            "id": 4, 
            "name": "Traditional Mitti Jug & Cup Set", 
            "category": "soil", 
            "price": 799, 
            "image": "images/Traditional Mitti Jug & Cup Set.jpg", 
            "description": "A traditional mitti jug paired with clay cups for serving water at home."
        },
        {
            "id": 5, 
            "name": "Handcrafted Clay Curd Handi", 
            "category": "soil", 
            "price": 349, 
            "image": "images/Clay Curd & Yogurt Handi Pot.jpg", 
            "description": "A clay handi pot ideal for preparing and serving curd or yogurt."
        },
        {
            "id": 6, 
            "name": "Terracotta Water Dispenser", 
            "category": "soil", 
            "price": 1299, 
            "image": "images/Terracotta Water Matka Dispenser with Tap.jpg", 
            "description": "A terracotta water dispenser with tap for convenient household use."
        },
        {
            "id": 7, 
            "name": "Bamboo Toothbrush Pack of 4", 
            "category": "care", 
            "price": 299, 
            "image": "images/Bamboo Toothbrush (Pack of 4).jpg", 
            "description": "A pack of four eco-friendly bamboo toothbrushes for daily oral care."
        },
        {
            "id": 8, 
            "name": "Neem & Bamboo Comb Set", 
            "category": "care", 
            "price": 249, 
            "image": "images/Natural Neem & Bamboo Grooming Comb Set.jpg", 
            "description": "A natural neem and bamboo comb set for daily hair grooming."
        },
        {
            "id": 9, 
            "name": "Handwoven Bamboo Lamp Shade", 
            "category": "decor", 
            "price": 899, 
            "image": "images/Handwoven Bamboo Lamp Shade.jpg", 
            "description": "A handwoven bamboo lamp shade adding warmth and natural texture."
        },
        {
            "id": 10, 
            "name": "Bamboo Storage Basket", 
            "category": "decor", 
            "price": 649, 
            "image": "images/Handcrafted Bamboo Storage Basket.jpg", 
            "description": "A woven bamboo storage basket for home organization."
        },
        {
            "id": 11, 
            "name": "Bamboo Utensils Set of 6", 
            "category": "kitchen", 
            "price": 499, 
            "image": "images/Bamboo Cooking Utensils Set of 6.jpg", 
            "description": "A set of six lightweight bamboo cooking spoons and utensils."
        },
        {
            "id": 12, 
            "name": "Clay Cooking Handi Pot", 
            "category": "kitchen", 
            "price": 549, 
            "image": "images/Artisan Clay Cooking Handi Pot.jpg", 
            "description": "A traditional clay cooking pot for rustic home meals."
        }
    ]

# --- Customer Authentication APIs ---
@app.post("/api/customer/register")
async def customer_register(data: CustomerRegisterSchema):
    fake_db["pending_customer"] = data.dict()
    fake_db["otp_store"][data.phone] = "123456"
    return {"status": "success", "message": "OTP sent successfully! (Demo OTP: 123456)"}

@app.post("/api/customer/verify-otp")
async def verify_otp(data: OtpVerifySchema):
    if data.phone in fake_db["otp_store"] and data.otp == "123456":
        fake_db["current_customer"] = fake_db.get("pending_customer")
        return {"status": "success", "message": "Verified successfully"}
    raise HTTPException(status_code=400, detail="Invalid OTP")

@app.post("/api/customer/login")
async def customer_login(data: CustomerLoginSchema):
    fake_db["current_customer"] = {
        "name": "Abhishek Yadav",
        "email": data.identifier if "@" in data.identifier else "user@gmail.com",
        "phone": data.identifier if "@" not in data.identifier else "9801557358",
        "marketing_consent": True
    }
    return {"status": "success", "message": "Logged in successfully"}

@app.get("/api/customer/session")
async def customer_session():
    if fake_db["current_customer"]:
        return {"authenticated": True, "customer": fake_db["current_customer"]}
    return {"authenticated": False}

@app.get("/api/customer/orders")
async def customer_orders():
    return fake_db["orders"]

@app.patch("/api/customer/marketing-consent")
async def update_consent(data: ConsentSchema):
    if fake_db["current_customer"]:
        fake_db["current_customer"]["marketing_consent"] = data.marketing_consent
    return {"status": "success"}

@app.post("/api/customer/logout")
async def customer_logout():
    fake_db["current_customer"] = None
    return {"status": "success"}

# --- Checkout API ---
@app.post("/api/checkout")
async def checkout(order: OrderCreate):
    import random
    order_id = str(random.randint(100000, 999999))
    order_obj = {
        "id": order_id,
        "customer_name": order.customer_name,
        "phone": order.phone,
        "total": order.total_amount,
        "address": f"{order.address}, {order.city} - {order.pincode}",
        "items": [{"quantity": i.qty, "name": i.name, "price": i.price} for i in order.items],
        "created_at": "2026-10-20T12:00:00"
    }
    fake_db["orders"].append(order_obj)
    if order.phone:
        await send_order_sms(phone_number=order.phone, order_id=order_id, amount=str(order.total_amount))
    return {"status": "success", "order_id": order_id, "message": "Order placed successfully!"}

# --- Static Files Mount ---
app.mount("/", StaticFiles(directory=".", html=True), name="static")