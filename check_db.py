"""Bazaga ulanishni tekshirish: python check_db.py  (backend papkasidan, .env bilan)"""
import time
from dotenv import load_dotenv
load_dotenv()
from sqlalchemy import create_engine, text
from app.config import DATABASE_URL

safe = DATABASE_URL.split("@")[-1] if "@" in DATABASE_URL else DATABASE_URL
print("Ulanish manzili (parolsiz):", safe, flush=True)
t0 = time.time()
engine = create_engine(DATABASE_URL, connect_args={"connect_timeout": 10} if not DATABASE_URL.startswith("sqlite") else {})
try:
    with engine.connect() as conn:
        print(f"1) Ulanish: OK ({time.time()-t0:.1f} s)", flush=True)
        conn.execute(text("SELECT 1"))
        print(f"2) SELECT 1: OK ({time.time()-t0:.1f} s)", flush=True)
except Exception as e:
    print(f"XATO ({time.time()-t0:.1f} s): {type(e).__name__}: {str(e)[:400]}", flush=True)
