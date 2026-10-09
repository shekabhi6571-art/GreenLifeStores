import json
import hmac
import hashlib
import base64
import binascii
import os
import re
import secrets
import sqlite3
import time
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Generator, Literal
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request as UrlRequest, urlopen

from fastapi import Depends, FastAPI, HTTPException, Request, Response
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field


BASE_DIR = Path(__file__).resolve().parent
DATABASE_PATH = Path(os.environ.get("GREENLIFE_DB_PATH", BASE_DIR / "greenlife.db"))
SELLER_UPLOAD_DIR = BASE_DIR / "images" / "seller-submissions"
ADMIN_PASSWORD = os.environ.get("GREENLIFE_ADMIN_PASSWORD", "")
SESSION_SECRET = secrets.token_bytes(32)
ADMIN_SESSION_COOKIE = "greenlife_admin_session"
ADMIN_SESSION_SECONDS = 8 * 60 * 60
CUSTOMER_SESSION_COOKIE = "greenlife_customer_session"
CUSTOMER_SESSION_SECONDS = 30 * 24 * 60 * 60
MSG91_AUTH_KEY = os.environ.get("GREENLIFE_MSG91_AUTH_KEY", "")
MSG91_TEMPLATE_ID = os.environ.get("GREENLIFE_MSG91_TEMPLATE_ID", "")
MSG91_OTP_URL = "https://control.msg91.com/api/v5/otp"

DEFAULT_PRODUCTS = [
    {"id": 1, "name": "Organic Clay Water Bottle", "price": 599, "image": "images/clay-bottle-1.jpg", "category": "soil"},
    {"id": 2, "name": "Terracotta Travel Sipper Bottle", "price": 649, "image": "images/Terracotta Travel Sipper Bottle (750ml).jpg", "category": "soil"},
    {"id": 3, "name": "Hand-Painted Warli Art Clay Bottle", "price": 799, "image": "images/Hand-Painted Warli Art Clay Bottle.jpg", "category": "soil"},
    {"id": 4, "name": "Traditional Mitti Jug & Cup Set", "price": 799, "image": "images/Traditional Mitti Jug & Cup Set.jpg", "category": "soil"},
    {"id": 5, "name": "Clay Curd & Yogurt Handi Pot", "price": 499, "image": "images/Clay Curd & Yogurt Handi Pot.jpg", "category": "soil"},
    {"id": 6, "name": "Terracotta Water Matka Dispenser with Tap", "price": 999, "image": "images/Terracotta Water Matka Dispenser with Tap.jpg", "category": "soil"},
    {"id": 7, "name": "Bamboo Toothbrush (Pack of 4)", "price": 299, "image": "images/Bamboo Toothbrush (Pack of 4).jpg", "category": "care"},
    {"id": 8, "name": "Natural Neem & Bamboo Comb Set", "price": 349, "image": "images/Natural Neem & Bamboo Comb Set.jpg", "category": "care"},
    {"id": 9, "name": "Handwoven Bamboo Lamp Shade", "price": 1199, "image": "images/Handwoven Bamboo Lamp Shade.jpg", "category": "decor"},
    {"id": 10, "name": "Handcrafted Bamboo Storage Basket", "price": 899, "image": "images/Handcrafted Bamboo Storage Basket.jpg", "category": "decor"},
    {"id": 11, "name": "Bamboo Cooking Utensils Set (6 Pcs)", "price": 499, "image": "images/Bamboo Cooking Utensils Set (6 Pcs).jpg", "category": "kitchen"},
    {"id": 12, "name": "Artisan Clay Cooking Handi Pot", "price": 849, "image": "images/Artisan Clay Cooking Handi Pot.jpg", "category": "kitchen"},
]

app = FastAPI(title="GreenLife Organics API")


class ProductInput(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    price: float = Field(gt=0)
    image: str = Field(min_length=1, max_length=500)
    category: str = Field(min_length=1, max_length=50)
    description: str = Field(default="", max_length=2000)


class Product(ProductInput):
    id: int


class AdminProductInput(ProductInput):
    image_data: str | None = Field(default=None, max_length=2_800_000)


class ProductSubmissionInput(BaseModel):
    seller_name: str = Field(min_length=2, max_length=120)
    seller_email: str = Field(min_length=6, max_length=254)
    seller_phone: str = Field(min_length=8, max_length=20)
    name: str = Field(min_length=2, max_length=200)
    price: float = Field(gt=0, le=1_000_000)
    category: Literal["soil", "care", "decor", "kitchen"]
    image_data: str = Field(min_length=1, max_length=2_800_000)


class OrderItemInput(BaseModel):
    product_id: int
    quantity: int = Field(ge=1, le=100)


class OrderInput(BaseModel):
    customer_name: str = Field(min_length=2, max_length=120)
    phone: str = Field(min_length=8, max_length=20)
    address: str = Field(min_length=8, max_length=500)
    items: list[OrderItemInput] = Field(min_length=1)
    promo_code: str = Field(default="", max_length=30)
    payment_method: Literal["COD"] = "COD"


class InquiryInput(BaseModel):
    name: str = Field(min_length=2, max_length=120)
    email: str = Field(min_length=5, max_length=254)
    subject: str = Field(min_length=1, max_length=100)
    message: str = Field(min_length=1, max_length=3000)


class AdminLoginInput(BaseModel):
    password: str = Field(min_length=1, max_length=256)


class CustomerRegistrationInput(BaseModel):
    name: str = Field(min_length=2, max_length=120)
    email: str = Field(min_length=6, max_length=254)
    phone: str = Field(min_length=10, max_length=20)
    password: str = Field(min_length=10, max_length=128)
    marketing_consent: bool = False


class CustomerOtpInput(BaseModel):
    phone: str = Field(min_length=10, max_length=20)
    otp: str = Field(pattern=r"^\d{6}$")


class CustomerLoginInput(BaseModel):
    identifier: str = Field(min_length=3, max_length=254)
    password: str = Field(min_length=1, max_length=128)


class CustomerConsentInput(BaseModel):
    marketing_consent: bool


def normalize_phone(phone: str) -> str:
    digits = re.sub(r"\D", "", phone)
    if len(digits) == 10:
        digits = f"91{digits}"
    if not 10 <= len(digits) <= 15:
        raise HTTPException(status_code=422, detail="Enter a valid phone number.")
    return digits


def normalize_gmail(email: str) -> str:
    normalized = email.strip().lower()
    if not re.fullmatch(r"[a-z0-9.!#$%&'*+/=?^_`{|}~-]+@gmail\.com", normalized):
        raise HTTPException(status_code=422, detail="Enter a valid Gmail address.")
    return normalized


def hash_password(password: str, salt: bytes | None = None) -> str:
    actual_salt = salt or secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac(
        "sha256", password.encode("utf-8"), actual_salt, 310_000
    )
    return f"{actual_salt.hex()}${digest.hex()}"


def check_password(password: str, encoded: str) -> bool:
    try:
        salt_hex, digest_hex = encoded.split("$", 1)
        salt = bytes.fromhex(salt_hex)
        expected = bytes.fromhex(digest_hex)
    except ValueError:
        return False
    actual = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, 310_000)
    return hmac.compare_digest(actual, expected)


def otp_digest(phone: str, otp: str) -> str:
    return hmac.new(
        SESSION_SECRET, f"customer-otp:{phone}:{otp}".encode("utf-8"), "sha256"
    ).hexdigest()


def send_customer_otp(phone: str, otp: str) -> None:
    if not MSG91_AUTH_KEY or not MSG91_TEMPLATE_ID:
        raise HTTPException(
            status_code=503,
            detail="SMS OTP is not configured yet. Add your MSG91 Auth Key and approved OTP Template ID to .env, then restart the server.",
        )
    query = urlencode(
        {
            "authkey": MSG91_AUTH_KEY,
            "template_id": MSG91_TEMPLATE_ID,
            "mobile": phone,
            "otp": otp,
            "otp_length": "6",
            "otp_expiry": "10",
        }
    )
    request = UrlRequest(f"{MSG91_OTP_URL}?{query}", method="GET")
    try:
        with urlopen(request, timeout=10) as response:
            result = json.loads(response.read())
    except HTTPError as error:
        error.close()
        raise HTTPException(
            status_code=502,
            detail="MSG91 could not send the OTP. Check your Auth Key, template approval, and MSG91 account balance.",
        ) from None
    except (URLError, TimeoutError, json.JSONDecodeError) as error:
        raise HTTPException(
            status_code=502,
            detail="Could not reach MSG91 to send the OTP. Check your internet connection and try again.",
        ) from error
    if not isinstance(result, dict) or result.get("type") != "success":
        raise HTTPException(
            status_code=502,
            detail="MSG91 did not accept the OTP request. Check your OTP template and account settings.",
        )


def create_customer_session(customer_id: int) -> str:
    issued_at = str(int(time.time()))
    payload = f"{issued_at}.{customer_id}.{secrets.token_urlsafe(32)}"
    signature = hmac.new(
        SESSION_SECRET, payload.encode("utf-8"), digestmod="sha256"
    ).hexdigest()
    return f"{payload}.{signature}"


def customer_id_from_session(session: str | None) -> int | None:
    if not session:
        return None
    try:
        issued_at, customer_id, token, signature = session.split(".", 3)
        issued_timestamp = int(issued_at)
        parsed_customer_id = int(customer_id)
    except ValueError:
        return None
    if not token or issued_timestamp > time.time():
        return None
    if time.time() - issued_timestamp > CUSTOMER_SESSION_SECONDS:
        return None
    payload = f"{issued_at}.{customer_id}.{token}"
    expected_signature = hmac.new(
        SESSION_SECRET, payload.encode("utf-8"), digestmod="sha256"
    ).hexdigest()
    if not hmac.compare_digest(signature, expected_signature):
        return None
    return parsed_customer_id


def set_customer_cookie(response: Response, request: Request, customer_id: int) -> None:
    response.set_cookie(
        key=CUSTOMER_SESSION_COOKIE,
        value=create_customer_session(customer_id),
        max_age=CUSTOMER_SESSION_SECONDS,
        httponly=True,
        secure=request.url.scheme == "https",
        samesite="lax",
        path="/",
    )


def customer_profile(row: sqlite3.Row) -> dict:
    return {
        "id": row["id"],
        "name": row["name"],
        "email": row["email"],
        "phone": row["phone"],
        "marketing_consent": bool(row["marketing_consent"]),
    }


def require_customer(request: Request) -> dict:
    customer_id = customer_id_from_session(
        request.cookies.get(CUSTOMER_SESSION_COOKIE)
    )
    if customer_id is None:
        raise HTTPException(status_code=401, detail="Please sign in to continue.")
    with database() as connection:
        row = connection.execute(
            "SELECT * FROM customers WHERE id = ?", (customer_id,)
        ).fetchone()
    if row is None:
        raise HTTPException(status_code=401, detail="Please sign in to continue.")
    return customer_profile(row)


def create_admin_session() -> str:
    issued_at = str(int(time.time()))
    payload = f"{issued_at}.{secrets.token_urlsafe(32)}"
    signature = hmac.new(
        SESSION_SECRET, payload.encode("utf-8"), digestmod="sha256"
    ).hexdigest()
    return f"{payload}.{signature}"


def is_valid_admin_session(session: str | None) -> bool:
    if not session:
        return False
    try:
        issued_at, token, signature = session.split(".", 2)
        issued_timestamp = int(issued_at)
    except ValueError:
        return False
    if not token or issued_timestamp > time.time():
        return False
    if time.time() - issued_timestamp > ADMIN_SESSION_SECONDS:
        return False
    payload = f"{issued_at}.{token}"
    expected_signature = hmac.new(
        SESSION_SECRET, payload.encode("utf-8"), digestmod="sha256"
    ).hexdigest()
    return hmac.compare_digest(signature, expected_signature)


def require_admin(request: Request) -> None:
    session = request.cookies.get(ADMIN_SESSION_COOKIE)
    if not is_valid_admin_session(session):
        raise HTTPException(status_code=401, detail="Admin login required")


@contextmanager
def database() -> Generator[sqlite3.Connection, None, None]:
    DATABASE_PATH.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(DATABASE_PATH, timeout=10)
    connection.row_factory = sqlite3.Row
    try:
        yield connection
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


def initialize_database() -> None:
    with database() as connection:
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS products (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                price REAL NOT NULL CHECK(price > 0),
                image TEXT NOT NULL,
                category TEXT NOT NULL,
                description TEXT NOT NULL DEFAULT ''
            )
            """
        )
        product_columns = {
            row["name"] for row in connection.execute("PRAGMA table_info(products)")
        }
        if "description" not in product_columns:
            connection.execute(
                "ALTER TABLE products ADD COLUMN description TEXT NOT NULL DEFAULT ''"
            )
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS orders (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                customer_id INTEGER,
                customer_name TEXT NOT NULL,
                phone TEXT NOT NULL,
                address TEXT NOT NULL,
                items_json TEXT NOT NULL,
                subtotal REAL NOT NULL,
                discount REAL NOT NULL,
                shipping REAL NOT NULL,
                total REAL NOT NULL,
                payment_method TEXT NOT NULL DEFAULT 'COD',
                created_at TEXT NOT NULL
            )
            """
        )
        order_columns = {
            row["name"] for row in connection.execute("PRAGMA table_info(orders)")
        }
        if "payment_method" not in order_columns:
            connection.execute(
                "ALTER TABLE orders ADD COLUMN payment_method TEXT NOT NULL DEFAULT 'COD'"
            )
        if "customer_id" not in order_columns:
            connection.execute("ALTER TABLE orders ADD COLUMN customer_id INTEGER")
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS customers (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                email TEXT NOT NULL COLLATE NOCASE UNIQUE,
                phone TEXT NOT NULL UNIQUE,
                password_hash TEXT NOT NULL,
                marketing_consent INTEGER NOT NULL DEFAULT 0,
                verification_mode TEXT NOT NULL DEFAULT 'demo',
                created_at TEXT NOT NULL
            )
            """
        )
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS customer_registrations (
                phone TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                email TEXT NOT NULL COLLATE NOCASE,
                password_hash TEXT NOT NULL,
                marketing_consent INTEGER NOT NULL DEFAULT 0,
                otp_hash TEXT NOT NULL,
                expires_at INTEGER NOT NULL,
                attempts INTEGER NOT NULL DEFAULT 0,
                last_sent_at INTEGER NOT NULL,
                window_started_at INTEGER NOT NULL,
                sends_in_window INTEGER NOT NULL DEFAULT 1
            )
            """
        )
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS inquiries (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                email TEXT NOT NULL,
                subject TEXT NOT NULL,
                message TEXT NOT NULL,
                created_at TEXT NOT NULL
            )
            """
        )
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS product_submissions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                seller_name TEXT NOT NULL,
                seller_email TEXT NOT NULL,
                seller_phone TEXT NOT NULL,
                name TEXT NOT NULL,
                price REAL NOT NULL CHECK(price > 0),
                image TEXT NOT NULL,
                category TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'pending'
                    CHECK(status IN ('pending', 'approved', 'rejected')),
                submitted_at TEXT NOT NULL,
                reviewed_at TEXT
            )
            """
        )
        count = connection.execute("SELECT COUNT(*) FROM products").fetchone()[0]
        if count == 0:
            connection.executemany(
                """
                INSERT INTO products (id, name, price, image, category)
                VALUES (:id, :name, :price, :image, :category)
                """,
                DEFAULT_PRODUCTS,
            )


def product_from_row(row: sqlite3.Row) -> Product:
    return Product(**dict(row))


def save_product_image(encoded_image: str) -> str:
    image_match = re.fullmatch(
        r"data:image/(png|jpeg|webp);base64,([A-Za-z0-9+/]+={0,2})",
        encoded_image,
    )
    if image_match is None:
        raise HTTPException(
            status_code=422, detail="Upload a PNG, JPG, or WebP product image."
        )
    image_format, encoded_bytes = image_match.groups()
    try:
        image_bytes = base64.b64decode(encoded_bytes, validate=True)
    except binascii.Error as error:
        raise HTTPException(status_code=422, detail="Product image is invalid.") from error
    if not image_bytes or len(image_bytes) > 2 * 1024 * 1024:
        raise HTTPException(
            status_code=413, detail="Product image must be smaller than 2 MB."
        )
    valid_signature = (
        image_format == "png" and image_bytes.startswith(b"\x89PNG\r\n\x1a\n")
    ) or (
        image_format == "jpeg" and image_bytes.startswith(b"\xff\xd8\xff")
    ) or (
        image_format == "webp"
        and image_bytes.startswith(b"RIFF")
        and image_bytes[8:12] == b"WEBP"
    )
    if not valid_signature:
        raise HTTPException(status_code=422, detail="Image type does not match its data.")

    extension = "jpg" if image_format == "jpeg" else image_format
    filename = f"{secrets.token_hex(16)}.{extension}"
    image_path = SELLER_UPLOAD_DIR / filename
    SELLER_UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    try:
        image_path.write_bytes(image_bytes)
    except OSError as error:
        raise HTTPException(
            status_code=500, detail="Could not save the product image."
        ) from error
    return f"images/seller-submissions/{filename}"


def order_from_row(row: sqlite3.Row) -> dict:
    order = dict(row)
    order["items"] = json.loads(order.pop("items_json"))
    return order


initialize_database()


@app.get("/api/health")
def health_check() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/api/admin/login")
def admin_login(login: AdminLoginInput, request: Request, response: Response) -> dict[str, str]:
    if len(ADMIN_PASSWORD) < 10:
        raise HTTPException(
            status_code=503,
            detail="Admin password is not configured. Restart the server and set a password.",
        )
    if not secrets.compare_digest(login.password, ADMIN_PASSWORD):
        raise HTTPException(status_code=401, detail="Incorrect admin password")
    response.set_cookie(
        key=ADMIN_SESSION_COOKIE,
        value=create_admin_session(),
        max_age=ADMIN_SESSION_SECONDS,
        httponly=True,
        secure=request.url.scheme == "https",
        samesite="strict",
        path="/",
    )
    return {"status": "authenticated"}


@app.get("/api/admin/session")
def admin_session(request: Request) -> dict[str, bool]:
    return {
        "authenticated": is_valid_admin_session(
            request.cookies.get(ADMIN_SESSION_COOKIE)
        )
    }


@app.post("/api/customer/register", status_code=202)
def customer_register(registration: CustomerRegistrationInput) -> dict:
    phone = normalize_phone(registration.phone)
    email = normalize_gmail(registration.email)
    now = int(time.time())
    otp = f"{secrets.randbelow(1_000_000):06d}"
    with database() as connection:
        existing = connection.execute(
            "SELECT 1 FROM customers WHERE email = ? COLLATE NOCASE OR phone = ?",
            (email, phone),
        ).fetchone()
        pending_conflict = connection.execute(
            """
            SELECT 1 FROM customer_registrations
            WHERE (email = ? COLLATE NOCASE AND phone != ?) OR
                  (phone = ? AND email != ? COLLATE NOCASE)
            """,
            (email, phone, phone, email),
        ).fetchone()
        if existing or pending_conflict:
            raise HTTPException(
                status_code=409,
                detail="An account already uses that Gmail address or phone number.",
            )

        pending = connection.execute(
            "SELECT * FROM customer_registrations WHERE phone = ?", (phone,)
        ).fetchone()
        if pending and now - pending["last_sent_at"] < 60:
            raise HTTPException(
                status_code=429, detail="Wait 60 seconds before requesting another code."
            )
        if pending and now - pending["window_started_at"] < 3600:
            if pending["sends_in_window"] >= 5:
                raise HTTPException(
                    status_code=429,
                    detail="Too many codes requested. Try again in an hour.",
                )
            sends_in_window = pending["sends_in_window"] + 1
            window_started_at = pending["window_started_at"]
        else:
            sends_in_window = 1
            window_started_at = now

        send_customer_otp(phone, otp)
        values = (
            registration.name.strip(),
            email,
            hash_password(registration.password),
            int(registration.marketing_consent),
            otp_digest(phone, otp),
            now + 600,
            now,
            window_started_at,
            sends_in_window,
            phone,
        )
        connection.execute(
            """
            INSERT INTO customer_registrations (
                name, email, password_hash, marketing_consent, otp_hash,
                expires_at, attempts, last_sent_at, window_started_at,
                sends_in_window, phone
            ) VALUES (?, ?, ?, ?, ?, ?, 0, ?, ?, ?, ?)
            ON CONFLICT(phone) DO UPDATE SET
                name = excluded.name,
                email = excluded.email,
                password_hash = excluded.password_hash,
                marketing_consent = excluded.marketing_consent,
                otp_hash = excluded.otp_hash,
                expires_at = excluded.expires_at,
                attempts = 0,
                last_sent_at = excluded.last_sent_at,
                window_started_at = excluded.window_started_at,
                sends_in_window = excluded.sends_in_window
            """,
            values,
        )
    return {
        "status": "otp_sent",
        "message": "A verification code was sent to your phone number.",
        "expires_in_seconds": 600,
        "resend_after_seconds": 60,
    }


@app.post("/api/customer/verify-otp")
def customer_verify_otp(
    verification: CustomerOtpInput, request: Request, response: Response
) -> dict:
    phone = normalize_phone(verification.phone)
    now = int(time.time())
    failure_status = 0
    customer_id = None
    with database() as connection:
        pending = connection.execute(
            "SELECT * FROM customer_registrations WHERE phone = ?", (phone,)
        ).fetchone()
        if pending is None:
            failure_status = 400
        elif pending["expires_at"] <= now:
            failure_status = 400
        elif pending["attempts"] >= 5:
            failure_status = 429
        elif not hmac.compare_digest(
            pending["otp_hash"], otp_digest(phone, verification.otp)
        ):
            attempts = pending["attempts"] + 1
            connection.execute(
                "UPDATE customer_registrations SET attempts = ? WHERE phone = ?",
                (attempts, phone),
            )
            failure_status = 400
        else:
            created_at = datetime.now(timezone.utc).isoformat()
            cursor = connection.execute(
                """
                INSERT INTO customers (
                    name, email, phone, password_hash, marketing_consent,
                    verification_mode, created_at
                ) VALUES (?, ?, ?, ?, ?, 'msg91', ?)
                """,
                (
                    pending["name"],
                    pending["email"],
                    phone,
                    pending["password_hash"],
                    pending["marketing_consent"],
                    created_at,
                ),
            )
            customer_id = cursor.lastrowid
            connection.execute(
                "DELETE FROM customer_registrations WHERE phone = ?", (phone,)
            )
    if failure_status == 429:
        raise HTTPException(
            status_code=429, detail="Too many attempts. Request a new SMS code."
        )
    if failure_status:
        raise HTTPException(status_code=400, detail="Invalid or expired SMS code.")
    set_customer_cookie(response, request, customer_id)
    with database() as connection:
        row = connection.execute(
            "SELECT * FROM customers WHERE id = ?", (customer_id,)
        ).fetchone()
    return {"status": "authenticated", "customer": customer_profile(row)}


@app.post("/api/customer/login")
def customer_login(
    login: CustomerLoginInput, request: Request, response: Response
) -> dict:
    identifier = login.identifier.strip()
    if "@" in identifier:
        identifier = normalize_gmail(identifier)
        lookup = "email = ? COLLATE NOCASE"
    else:
        identifier = normalize_phone(identifier)
        lookup = "phone = ?"
    with database() as connection:
        row = connection.execute(
            f"SELECT * FROM customers WHERE {lookup}", (identifier,)
        ).fetchone()
    if row is None or not check_password(login.password, row["password_hash"]):
        raise HTTPException(status_code=401, detail="Incorrect Gmail/phone or password.")
    set_customer_cookie(response, request, row["id"])
    return {"status": "authenticated", "customer": customer_profile(row)}


@app.get("/api/customer/session")
def customer_session(request: Request) -> dict:
    customer_id = customer_id_from_session(
        request.cookies.get(CUSTOMER_SESSION_COOKIE)
    )
    if customer_id is None:
        return {"authenticated": False, "customer": None}
    with database() as connection:
        row = connection.execute(
            "SELECT * FROM customers WHERE id = ?", (customer_id,)
        ).fetchone()
    if row is None:
        return {"authenticated": False, "customer": None}
    return {"authenticated": True, "customer": customer_profile(row)}


@app.post("/api/customer/logout")
def customer_logout(response: Response) -> dict[str, str]:
    response.delete_cookie(
        key=CUSTOMER_SESSION_COOKIE, httponly=True, samesite="lax", path="/"
    )
    return {"status": "logged_out"}


@app.patch("/api/customer/marketing-consent")
def update_marketing_consent(
    consent: CustomerConsentInput, customer: dict = Depends(require_customer)
) -> dict:
    with database() as connection:
        connection.execute(
            "UPDATE customers SET marketing_consent = ? WHERE id = ?",
            (int(consent.marketing_consent), customer["id"]),
        )
        row = connection.execute(
            "SELECT * FROM customers WHERE id = ?", (customer["id"],)
        ).fetchone()
    return {"customer": customer_profile(row)}


@app.get("/api/customer/orders")
def get_customer_orders(customer: dict = Depends(require_customer)) -> list[dict]:
    with database() as connection:
        rows = connection.execute(
            "SELECT * FROM orders WHERE customer_id = ? ORDER BY id DESC",
            (customer["id"],),
        ).fetchall()
    return [order_from_row(row) for row in rows]


@app.get("/api/admin/customers", dependencies=[Depends(require_admin)])
def get_customers() -> list[dict]:
    with database() as connection:
        rows = connection.execute(
            """
            SELECT id, name, email, phone, marketing_consent, verification_mode, created_at
            FROM customers ORDER BY id DESC
            """
        ).fetchall()
    return [
        dict(row) | {"marketing_consent": bool(row["marketing_consent"])}
        for row in rows
    ]


@app.post("/api/admin/logout", dependencies=[Depends(require_admin)])
def admin_logout(response: Response) -> dict[str, str]:
    response.delete_cookie(
        key=ADMIN_SESSION_COOKIE, httponly=True, samesite="strict", path="/"
    )
    return {"status": "logged_out"}


@app.get("/api/products", response_model=list[Product])
def get_products() -> list[Product]:
    with database() as connection:
        rows = connection.execute("SELECT * FROM products ORDER BY id").fetchall()
    return [product_from_row(row) for row in rows]


@app.post(
    "/api/products",
    response_model=Product,
    status_code=201,
    dependencies=[Depends(require_admin)],
)
def add_product(product: AdminProductInput) -> Product:
    image = product.image
    if isinstance(product, AdminProductInput) and product.image_data:
        image = save_product_image(product.image_data)
    image_path = BASE_DIR / image if image.startswith("images/seller-submissions/") else None
    try:
        with database() as connection:
            cursor = connection.execute(
                """
                INSERT INTO products (name, price, image, category, description)
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    product.name,
                    product.price,
                    image,
                    product.category,
                    product.description,
                ),
            )
            row = connection.execute(
                "SELECT * FROM products WHERE id = ?", (cursor.lastrowid,)
            ).fetchone()
    except sqlite3.Error as error:
        if image_path is not None:
            image_path.unlink(missing_ok=True)
        raise HTTPException(
            status_code=500, detail="Could not save the product."
        ) from error
    return product_from_row(row)


@app.post("/api/product-submissions", status_code=201)
def submit_product(submission: ProductSubmissionInput) -> dict:
    seller_email = submission.seller_email.strip().lower()
    if not re.fullmatch(
        r"[a-z0-9.!#$%&'*+/=?^_`{|}~-]+@[a-z0-9.-]+\.[a-z]{2,}",
        seller_email,
    ):
        raise HTTPException(status_code=422, detail="Enter a valid email address.")
    image = save_product_image(submission.image_data)
    image_path = BASE_DIR / image

    try:
        with database() as connection:
            cursor = connection.execute(
                """
                INSERT INTO product_submissions (
                    seller_name, seller_email, seller_phone, name, price,
                    image, category, submitted_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    submission.seller_name.strip(),
                    seller_email,
                    submission.seller_phone.strip(),
                    submission.name.strip(),
                    submission.price,
                    image,
                    submission.category,
                    datetime.now(timezone.utc).isoformat(),
                ),
            )
            submission_id = cursor.lastrowid
    except sqlite3.Error as error:
        image_path.unlink(missing_ok=True)
        raise HTTPException(
            status_code=500, detail="Could not save the product submission."
        ) from error
    return {
        "id": submission_id,
        "status": "pending",
        "message": "Product submitted for admin approval. It is not public yet.",
    }


@app.get(
    "/api/admin/product-submissions",
    dependencies=[Depends(require_admin)],
)
def get_product_submissions() -> list[dict]:
    with database() as connection:
        rows = connection.execute(
            "SELECT * FROM product_submissions ORDER BY id DESC"
        ).fetchall()
    return [dict(row) for row in rows]


@app.post(
    "/api/admin/product-submissions/{submission_id}/approve",
    dependencies=[Depends(require_admin)],
)
def approve_product_submission(submission_id: int) -> dict:
    with database() as connection:
        submission = connection.execute(
            "SELECT * FROM product_submissions WHERE id = ?", (submission_id,)
        ).fetchone()
        if submission is None:
            raise HTTPException(status_code=404, detail="Submission not found.")
        if submission["status"] != "pending":
            raise HTTPException(
                status_code=409, detail="This submission has already been reviewed."
            )
        cursor = connection.execute(
            "INSERT INTO products (name, price, image, category) VALUES (?, ?, ?, ?)",
            (
                submission["name"],
                submission["price"],
                submission["image"],
                submission["category"],
            ),
        )
        connection.execute(
            """
            UPDATE product_submissions
            SET status = 'approved', reviewed_at = ? WHERE id = ?
            """,
            (datetime.now(timezone.utc).isoformat(), submission_id),
        )
        row = connection.execute(
            "SELECT * FROM products WHERE id = ?", (cursor.lastrowid,)
        ).fetchone()
    return {"product": product_from_row(row), "status": "approved"}


@app.post(
    "/api/admin/product-submissions/{submission_id}/reject",
    dependencies=[Depends(require_admin)],
)
def reject_product_submission(submission_id: int) -> dict[str, str]:
    with database() as connection:
        cursor = connection.execute(
            """
            UPDATE product_submissions
            SET status = 'rejected', reviewed_at = ?
            WHERE id = ? AND status = 'pending'
            """,
            (datetime.now(timezone.utc).isoformat(), submission_id),
        )
        if cursor.rowcount == 0:
            exists = connection.execute(
                "SELECT 1 FROM product_submissions WHERE id = ?", (submission_id,)
            ).fetchone()
            if exists is None:
                raise HTTPException(status_code=404, detail="Submission not found.")
            raise HTTPException(
                status_code=409, detail="This submission has already been reviewed."
            )
    return {"status": "rejected"}


@app.delete(
    "/api/products/{product_id}",
    status_code=204,
    dependencies=[Depends(require_admin)],
)
def delete_product(product_id: int) -> None:
    with database() as connection:
        cursor = connection.execute("DELETE FROM products WHERE id = ?", (product_id,))
        if cursor.rowcount == 0:
            raise HTTPException(status_code=404, detail="Product not found")


@app.post(
    "/api/products/reset",
    response_model=list[Product],
    dependencies=[Depends(require_admin)],
)
def reset_products() -> list[Product]:
    with database() as connection:
        connection.execute("DELETE FROM products")
        connection.executemany(
            """
            INSERT INTO products (id, name, price, image, category)
            VALUES (:id, :name, :price, :image, :category)
            """,
            DEFAULT_PRODUCTS,
        )
        rows = connection.execute("SELECT * FROM products ORDER BY id").fetchall()
    return [product_from_row(row) for row in rows]


@app.get("/api/orders", dependencies=[Depends(require_admin)])
def get_orders() -> list[dict]:
    with database() as connection:
        rows = connection.execute("SELECT * FROM orders ORDER BY id DESC").fetchall()
    return [order_from_row(row) for row in rows]


@app.post("/api/orders", status_code=201)
def create_order(
    order: OrderInput, customer: dict = Depends(require_customer)
) -> dict:
    promo_code = order.promo_code.strip().upper()
    if promo_code and promo_code != "GREEN10":
        raise HTTPException(status_code=400, detail="Invalid promo code")

    quantities: dict[int, int] = {}
    for item in order.items:
        quantities[item.product_id] = quantities.get(item.product_id, 0) + item.quantity

    with database() as connection:
        placeholders = ",".join("?" for _ in quantities)
        product_rows = connection.execute(
            f"SELECT * FROM products WHERE id IN ({placeholders})",
            tuple(quantities),
        ).fetchall()
        products_by_id = {row["id"]: row for row in product_rows}
        missing_ids = set(quantities) - products_by_id.keys()
        if missing_ids:
            raise HTTPException(
                status_code=404,
                detail=f"Product not found: {min(missing_ids)}",
            )

        items = []
        subtotal = 0.0
        for product_id, quantity in quantities.items():
            product = dict(products_by_id[product_id])
            subtotal += product["price"] * quantity
            items.append({**product, "quantity": quantity})

        discount = round(subtotal * 0.1, 2) if promo_code == "GREEN10" else 0.0
        discounted_subtotal = subtotal - discount
        shipping = 0.0 if discounted_subtotal > 500 else 50.0
        total = round(discounted_subtotal + shipping)
        created_at = datetime.now(timezone.utc).isoformat()
        cursor = connection.execute(
            """
            INSERT INTO orders (
                customer_id, customer_name, phone, address, items_json, subtotal,
                discount, shipping, total, payment_method, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                customer["id"],
                customer["name"],
                customer["phone"],
                order.address,
                json.dumps(items),
                subtotal,
                discount,
                shipping,
                total,
                order.payment_method,
                created_at,
            ),
        )
        saved_order = connection.execute(
            "SELECT * FROM orders WHERE id = ?", (cursor.lastrowid,)
        ).fetchone()
    return order_from_row(saved_order)


@app.get("/api/inquiries", dependencies=[Depends(require_admin)])
def get_inquiries() -> list[dict]:
    with database() as connection:
        rows = connection.execute(
            "SELECT * FROM inquiries ORDER BY id DESC"
        ).fetchall()
    return [dict(row) for row in rows]


@app.post("/api/inquiries", status_code=201)
def create_inquiry(inquiry: InquiryInput) -> dict:
    with database() as connection:
        cursor = connection.execute(
            """
            INSERT INTO inquiries (name, email, subject, message, created_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                inquiry.name,
                inquiry.email,
                inquiry.subject,
                inquiry.message,
                datetime.now(timezone.utc).isoformat(),
            ),
        )
        saved_inquiry = connection.execute(
            "SELECT * FROM inquiries WHERE id = ?", (cursor.lastrowid,)
        ).fetchone()
    return dict(saved_inquiry)


@app.get("/", include_in_schema=False)
def serve_homepage() -> FileResponse:
    return FileResponse(BASE_DIR / "index.html")


@app.get("/home.html", include_in_schema=False)
def serve_home_page() -> FileResponse:
    return FileResponse(BASE_DIR / "index.html")


@app.get("/api.js", include_in_schema=False)
def serve_api_client() -> FileResponse:
    return FileResponse(BASE_DIR / "api.js")


@app.get("/{page_name}.html", include_in_schema=False)
def serve_page(page_name: str) -> FileResponse:
    allowed_pages = {
        "index", "about", "products", "cart", "contact", "admin", "account",
        "seller"
    }
    if page_name not in allowed_pages:
        raise HTTPException(status_code=404, detail="Page not found")
    return FileResponse(BASE_DIR / f"{page_name}.html")


app.mount(
    "/images",
    StaticFiles(directory=BASE_DIR / "images"),
    name="images",
)
