"""4-bosqich: baho o'zgarishlari tarixi."""
import hashlib
import os
import uuid

os.environ.setdefault("DATABASE_URL", "sqlite:///./test_gradelog.db")

from datetime import datetime, timedelta, timezone  # noqa: E402

from fastapi.testclient import TestClient  # noqa: E402

from app import proctor_models  # noqa: E402,F401
from app.db import Base, SessionLocal, engine  # noqa: E402
from app.main import app  # noqa: E402
from app.models import KtAttempt, KtExam, KtGradeLog, KtTeacher  # noqa: E402

Base.metadata.create_all(engine, checkfirst=True)
H = {"X-Teacher-Login": "gl-own", "X-Teacher-Password": "pw"}
O = {"X-Teacher-Login": "gl-oth", "X-Teacher-Password": "pw"}


def _setup():
    with SessionLocal() as db:
        for lg in ("gl-own", "gl-oth"):
            if not db.query(KtTeacher).filter_by(login=lg).first():
                db.add(KtTeacher(login=lg, password_hash=hashlib.sha256(b"pw").hexdigest(), name=f"Ustoz {lg}"))
        db.flush()
        own = db.query(KtTeacher).filter_by(login="gl-own").first()
        qs = [{"id": "q1", "turi": "NAZARIY", "mavzu": "m", "savol": "s", "baholash": "5 ball", "faol": True}]
        ex = KtExam(id=uuid.uuid4().hex, slug=f"gl-{uuid.uuid4().hex[:6]}", title="Gl", minutes=80, groups=["25-81"], questions=qs, status="finished", teacher_id=own.id)
        db.add(ex); db.flush()
        now = datetime.now(timezone.utc)
        a = KtAttempt(id=uuid.uuid4().hex, exam_id=ex.id, student="Gl Talaba", group="25-81", started_at=now, submitted=True,
                      deadline=now + timedelta(minutes=80), questions=["q1"], answers={"q1": "javob"}, grades={"q1": 2})   # eski baho: tarixsiz
        db.add(a); db.commit()
        return ex.id, a.id


def test_log_only_real_changes_and_existing_grades_untouched():
    ex, aid = _setup()
    with TestClient(app) as c:
        assert c.get(f"/api/exam/teacher/attempt/{aid}", headers=H).json()["grade_log"] == []     # eski baho uchun tarix yo'q
        g = lambda v, h=H: c.post("/api/exam/teacher/grade", json={"attempt_id": aid, "qid": "q1", "score": v}, headers=h)
        assert g(2).status_code == 200                                    # o'zgarmagan baho: yozuv yo'q
        assert g(4).status_code == 200 and g(4).status_code == 200        # 2 -> 4, qayta saqlash yozuv qo'shmaydi
        assert g(3.5).status_code == 200
        assert g(9).status_code == 400                                    # noto'g'ri ball: yozilmaydi
        att = c.get(f"/api/exam/teacher/attempt/{aid}", headers=H).json()
        log = att["grade_log"]
        assert [(r["old"], r["new"]) for r in log] == [(4, 3.5), (2, 4)]  # eng yangisi tepada
        assert log[0]["teacher"] == "Ustoz gl-own" and log[0]["at"].endswith("+00:00")
        assert att["items"][0]["score"] == 3.5
        assert c.post("/api/exam/teacher/grade", json={"attempt_id": aid, "qid": "q1", "score": 1}, headers=O).status_code == 403
        assert len(c.get(f"/api/exam/teacher/attempt/{aid}", headers=H).json()["grade_log"]) == 2
        # birinchi baho (old=None) va imtihonni o'chirish tarixni ham tozalaydi (FK xatosi yo'q)
        assert c.delete(f"/api/exam/teacher/exams/{ex}", headers=H).status_code == 200
    with SessionLocal() as db:
        assert db.query(KtGradeLog).filter_by(attempt_id=aid).count() == 0
