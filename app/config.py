import os
from dotenv import load_dotenv

load_dotenv()  # .env faylini o'qiydi (mavjud muhit o'zgaruvchilari ustiga yozmaydi)

DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./aitech.db")
CORS_ORIGINS = [o.strip() for o in os.getenv("CORS_ORIGINS", "http://localhost:5173").split(",") if o.strip()]
