"""
BIR MARTALIK SKRIPT — birinchi Super Admin hisobini yaratadi/tiklaydi.

ISHLATISH:
    cd backend
    python create_superadmin_once.py

MUHIM XAVFSIZLIK ESLATMASI:
  - Bu faylda parol OCHIQ (plaintext) holda yozilgan. Shu sababli ishga tushirilgandan
    so'ng fayl AVTOMATIK O'CHADI (diskdan o'chiriladi).
  - Buni productionga (Heroku/GitHub) UMUMAN DEPLOY/PUSH QILMANG. Faqat o'z
    kompyuteringizda, production DATABASE_URL bilan (.env orqali) bir marta
    ishga tushiring, keyin git holatini tekshirib, bu fayl commit qilinmaganini
    tasdiqlang.
  - Agar productiondagi Neon bazaga to'g'ridan-to'g'ri ulanish kerak bo'lsa,
    backend/.env faylidagi DATABASE_URL production manzilga ko'rsatganiga ishonch
    hosil qiling, so'ng shu skriptni ishga tushiring.
"""
import hashlib
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app.db import SessionLocal, Base, engine  # noqa: E402
from app.models import KtTeacher  # noqa: E402
from sqlalchemy import select  # noqa: E402

LOGIN = "337251101785"
PASSWORD = "Asadbek2007"
NAME = "Super Admin"


def main() -> None:
    # Jadvallar hali yo'q bo'lsa (masalan, mahalliy bo'sh baza bilan sinov), yaratib qo'yamiz.
    Base.metadata.create_all(engine, checkfirst=True)

    db = SessionLocal()
    try:
        row = db.scalar(select(KtTeacher).where(KtTeacher.login == LOGIN))
        if row:
            row.password_hash = hashlib.sha256(PASSWORD.encode()).hexdigest()
            row.role = "superadmin"
            if not row.name:
                row.name = NAME
            db.commit()
            print(f"[OK] Mavjud hisob '{LOGIN}' Super Admin sifatida yangilandi.")
        else:
            db.add(KtTeacher(
                login=LOGIN,
                password_hash=hashlib.sha256(PASSWORD.encode()).hexdigest(),
                name=NAME,
                role="superadmin",
            ))
            db.commit()
            print(f"[OK] Yangi Super Admin hisobi yaratildi: login={LOGIN}")
    finally:
        db.close()

    # O'zini o'chiradi — parol ochiq holda qolmasin.
    try:
        os.remove(os.path.abspath(__file__))
        print("[OK] Skript o'z-o'zini o'chirdi (xavfsizlik uchun).")
    except OSError as e:
        print(f"[DIQQAT] Skriptni o'chirib bo'lmadi, qo'lda o'chiring: {e}")


if __name__ == "__main__":
    main()
