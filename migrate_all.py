"""Barcha yangi ustunlarni BIR buyruq bilan qo'shadi (REJA 1, 3, 6-bosqichlar). Faqat QO'SHIMCHA o'zgarish:
mavjud ustun/ma'lumotga tegilmaydi, ON-1 yozuvlari 0 / NULL / false bo'lib qoladi. Qayta ishga tushirish xavfsiz.

    python migrate_all.py            # dry-run: faqat nima qilinishini ko'rsatadi, bazaga yozmaydi
    python migrate_all.py --apply    # haqiqatan qo'shadi

DATABASE_URL .env dan o'qiladi (productionda Neon). Yangi jadval (kt_grade_log) ilova ishga tushganda o'zi yaratiladi.
"""
import sys

from sqlalchemy import inspect, text

from app.db import engine

FALSE = "0" if engine.dialect.name == "sqlite" else "FALSE"
# (jadval, ustun, SQL turi)
COLUMNS = [
    ("kt_attempts", "rejoin_count", "INTEGER NOT NULL DEFAULT 0"),
    ("kt_attempts", "rejoin_allowed", "INTEGER NOT NULL DEFAULT 0"),
    ("kt_proctor_events", "reviewed", "BOOLEAN"),
    ("kt_proctor_events", "justified", "BOOLEAN"),
    ("kt_exams", "is_drill", f"BOOLEAN NOT NULL DEFAULT {FALSE}"),
]


def main() -> None:
    apply = "--apply" in sys.argv
    insp = inspect(engine)
    tables = set(insp.get_table_names())
    print(f"Baza: {engine.dialect.name}  |  rejim: {'APPLY' if apply else 'DRY-RUN'}")
    stmts = []
    for table, col, typ in COLUMNS:
        if table not in tables:
            print(f"- {table}: jadval yo'q (ilova ishga tushganda yaratiladi) — o'tkazib yuborildi")
            continue
        if col in {c["name"] for c in insp.get_columns(table)}:
            print(f"- {table}.{col}: mavjud")
            continue
        stmts.append(f"ALTER TABLE {table} ADD COLUMN {col} {typ}")
    for s in stmts:
        print(("BAJARILADI: " if apply else "bajariladi (dry-run): ") + s)
    if not stmts:
        print("Qiladigan ish yo'q.")
        return
    if not apply:
        print("Hech narsa o'zgarmadi. Haqiqatan qo'shish uchun: python migrate_all.py --apply")
        return
    with engine.begin() as conn:   # bitta tranzaksiya: yo hammasi, yo hech nima
        for s in stmts:
            conn.execute(text(s))
    print("Tayyor.")


if __name__ == "__main__":
    main()
