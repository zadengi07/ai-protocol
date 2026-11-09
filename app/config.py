import os
from dotenv import load_dotenv

load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./aitech.db")

if DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace(
        "postgres://", "postgresql+psycopg://", 1
    )
elif DATABASE_URL.startswith("postgresql://"):
    DATABASE_URL = DATABASE_URL.replace(
        "postgresql://", "postgresql+psycopg://", 1
    )

CORS_ORIGINS = [
    o.strip()
    for o in os.getenv(
        "CORS_ORIGINS", "https://ai-proctor-beta.netlify.app"
    ).split(",")
    if o.strip()
]

# Admin panelidagi "Baza" bo'limi uchun — ixtiyoriy, .env orqali beriladi.
# Berilmasa, bo'lim "sozlanmagan" holatda ko'rsatiladi, hech narsa buzilmaydi.
NEON_API_KEY = os.getenv("NEON_API_KEY", "")
NEON_PROJECT_ID = os.getenv("NEON_PROJECT_ID", "")