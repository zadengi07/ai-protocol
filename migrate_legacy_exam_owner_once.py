"""
BIR MARTALIK SKRIPT — eski (egasiz) imtihonlarni "rejabov.tict" ustoziga biriktiradi
va "25-80" guruh nomini "25-79" ga to'g'rilaydi.

NIMA QILADI:
  1. `kt_exams.teacher_id` NULL bo'lgan barcha imtihonlarni (migratsiyadan oldingi,
     ON-1 kabi tarixiy imtihonlar) login="rejabov.tict" bo'lgan ustozga biriktiradi.
  2. Guruh nomi "25-80" bo'lgan joylarni "25-79" ga almashtiradi:
       - kt_attempts.group ustuni
       - kt_exams.groups (JSON ro'yxat) ustuni
       - kt_settings["groups"] (umumiy ro'yxat)
     Javoblar, baholar, hodisalar — HECH NARSA TEGILMAYDI, faqat guruh YORLIG'I matni.

XAVFSIZLIK:
  - Avval DRY-RUN rejimida ishlaydi (hech narsa yozmaydi) — nima o'zgarishini ko'rsatadi.
  - Haqiqatan yozish uchun --apply bayrog'i bilan ishga tushiring.
  - Productionga ishlatishdan oldin backend/.env dagi DATABASE_URL ni tekshiring
    (Neon manziliga ko'rsatganiga ishonch hosil qiling), avval lokal/test bazada
    sinab ko'rish tavsiya etiladi.

ISHLATISH:
    cd backend
    python migrate_legacy_exam_owner_once.py            # dry-run (faqat ko'rsatadi)
    python migrate_legacy_exam_owner_once.py --apply     # haqiqiy yozish
"""
import sys

from sqlalchemy import inspect, text

from app.db import SessionLocal, engine
from app.models import Base, KtExam, KtAttempt, KtSetting, KtTeacher

TARGET_LOGIN = "rejabov.tict"
OLD_GROUP = "25-80"
NEW_GROUP = "25-79"


def _ensure_teacher_id_column():
    """Agar backend serveri hali bir marta ham ishga tushmagan bo'lsa (ya'ni main.py
    lifespan() orqali ALTER TABLE hali bajarilmagan bo'lsa), ustunni shu yerda ham
    qo'shib qo'yamiz — skript serverga bog'liq bo'lmasligi uchun."""
    Base.metadata.create_all(engine, checkfirst=True)
    columns = {c["name"] for c in inspect(engine).get_columns("kt_exams")}
    if "teacher_id" not in columns:
        with engine.begin() as conn:
            conn.execute(text("ALTER TABLE kt_exams ADD COLUMN teacher_id INTEGER REFERENCES kt_teachers(id)"))
        print("[info] kt_exams.teacher_id ustuni qo'shildi (bu safar birinchi marta).")


def main():
    apply = "--apply" in sys.argv
    _ensure_teacher_id_column()

    with SessionLocal() as db:
        teacher = db.query(KtTeacher).filter(KtTeacher.login == TARGET_LOGIN).first()
        if not teacher:
            print(f"XATO: login={TARGET_LOGIN!r} topilmadi. Hech narsa qilinmadi.")
            return

        orphan_exams = db.query(KtExam).filter(KtExam.teacher_id.is_(None)).all()
        print(f"1) Egasiz imtihonlar: {len(orphan_exams)} ta -> {TARGET_LOGIN} (id={teacher.id})")
        for e in orphan_exams:
            print(f"   - {e.id}  {e.title!r}  (slug={e.slug})")

        attempts_to_fix = db.query(KtAttempt).filter(KtAttempt.group == OLD_GROUP).all()
        print(f"\n2) '{OLD_GROUP}' guruhli urinishlar: {len(attempts_to_fix)} ta -> '{NEW_GROUP}'")

        exams_with_old_group = [e for e in db.query(KtExam).all() if e.groups and OLD_GROUP in e.groups]
        print(f"   '{OLD_GROUP}' ro'yxatida turgan imtihonlar: {len(exams_with_old_group)} ta")

        groups_setting = db.query(KtSetting).filter(KtSetting.key == "groups").first()
        has_old_in_settings = bool(groups_setting and OLD_GROUP in (groups_setting.value or []))
        print(f"   Umumiy guruhlar ro'yxatida '{OLD_GROUP}' bor: {has_old_in_settings}")

        if not apply:
            print("\n(DRY-RUN — hech narsa yozilmadi. Tasdiqlangandan so'ng --apply bilan qayta ishga tushiring.)")
            return

        for e in orphan_exams:
            e.teacher_id = teacher.id
        for a in attempts_to_fix:
            a.group = NEW_GROUP
        for e in exams_with_old_group:
            e.groups = [NEW_GROUP if g == OLD_GROUP else g for g in e.groups]
        if groups_setting and has_old_in_settings:
            groups_setting.value = [NEW_GROUP if g == OLD_GROUP else g for g in groups_setting.value]

        db.commit()
        print("\nBAJARILDI — yozildi.")


if __name__ == "__main__":
    main()
