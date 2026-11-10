"""6-bosqich: imtihon nusxalash va sinov rejimi."""
import hashlib
import os
import uuid

os.environ.setdefault("DATABASE_URL", "sqlite:///./test_copy.db")

from datetime import datetime, timedelta, timezone  # noqa: E402

from fastapi.testclient import TestClient  # noqa: E402

from app import proctor_models  # noqa: E402,F401
from app.db import Base, SessionLocal, engine  # noqa: E402
from app.main import app  # noqa: E402
from app.models import KtAttempt, KtExam, KtTeacher  # noqa: E402

Base.metadata.create_all(engine, checkfirst=True)
H = {"X-Teacher-Login": "cd-own", "X-Teacher-Password": "pw"}
O = {"X-Teacher-Login": "cd-oth", "X-Teacher-Password": "pw"}


def _qs():
    return [{"id": f"n{i}", "turi": "NAZARIY", "mavzu": "m", "savol": f"s{i}", "baholash": "2 ball", "faol": True} for i in range(3)] + \
           [{"id": f"a{i}", "turi": "AMALIY", "mavzu": "m", "savol": f"a{i}", "baholash": "2 ball", "faol": True} for i in range(2)]


def _teacher(db, lg):
    t = db.query(KtTeacher).filter_by(login=lg).first()
    if not t:
        t = KtTeacher(login=lg, password_hash=hashlib.sha256(b"pw").hexdigest(), name=lg); db.add(t); db.flush()
    return t


def test_copy_copies_bank_not_attempts_and_checks_owner():
    with SessionLocal() as db:
        own = _teacher(db, "cd-own"); _teacher(db, "cd-oth")
        src = KtExam(id=uuid.uuid4().hex, slug=f"cd-{uuid.uuid4().hex[:6]}", title="Asl imtihon", minutes=55, groups=["25-81"], questions=_qs(), status="finished", teacher_id=own.id)
        db.add(src); db.flush()
        now = datetime.now(timezone.utc)
        db.add(KtAttempt(id=uuid.uuid4().hex, exam_id=src.id, student="Eski", group="25-81", started_at=now, submitted=True,
                         deadline=now + timedelta(minutes=5), questions=["n0"], answers={"n0": "x"}, grades={"n0": 2}))
        db.commit(); src_id = src.id
    with TestClient(app) as c:
        r = c.post(f"/api/exam/teacher/exams/{src_id}/copy", headers=H, json={})
        assert r.status_code == 200, r.text
        new = r.json(); assert new["questions"] == 5 and new["title"] == "Asl imtihon (nusxa)" and new["is_drill"] is False
        ex = {e["id"]: e for e in c.get("/api/exam/teacher/exams", headers=H).json()}
        assert ex[new["id"]]["status"] == "draft" and ex[new["id"]]["groups"] == ["25-81"]
        qs = c.get(f"/api/exam/teacher/exams/{new['id']}/questions", headers=H).json()
        assert qs["count"] == 5
        s = c.get("/api/exam/teacher/summary", params={"exam_id": new["id"]}, headers=H).json()
        assert s["counts"]["total"] == 0                                          # urinishlar ko'chmagan
        s0 = c.get("/api/exam/teacher/summary", params={"exam_id": src_id}, headers=H).json()
        assert s0["counts"]["total"] == 1                                         # asl imtihon tegilmagan
        assert c.post(f"/api/exam/teacher/exams/{src_id}/copy", headers=O, json={}).status_code == 403
        assert c.post(f"/api/exam/teacher/exams/{src_id}/copy", json={}).status_code == 401


def test_drill_is_flagged_and_excluded_from_defaults():
    with SessionLocal() as db:
        t = _teacher(db, "cd-drl")
        real = KtExam(id=uuid.uuid4().hex, slug=f"r-{uuid.uuid4().hex[:6]}", title="Haqiqiy", minutes=80, groups=["25-81"], questions=_qs(), status="finished", teacher_id=t.id,
                      created_at=datetime.now(timezone.utc) - timedelta(days=1))
        db.add(real); db.commit()
    D = {"X-Teacher-Login": "cd-drl", "X-Teacher-Password": "pw"}
    with TestClient(app) as c:
        d = c.post("/api/exam/teacher/exams", headers=D, json={"title": "Sinov 2 daqiqa", "minutes": 2, "groups": ["25-81"], "is_drill": True}).json()
        assert d["is_drill"] is True
        ls = {e["id"]: e for e in c.get("/api/exam/teacher/exams", headers=D).json()}
        assert ls[d["id"]]["is_drill"] is True and ls[real.id if False else [k for k, v in ls.items() if v["title"] == "Haqiqiy"][0]]["is_drill"] is False
        # sinov imtihoni eng yangi, lekin faol emas -> standart ko'rinish sinov emas
        s = c.get("/api/exam/teacher/summary", headers=D).json()
        assert s["exam"]["is_drill"] is False and s["exam"]["id"] != d["id"]
        # sinov o'zi tanlansa ko'rinadi
        assert c.get("/api/exam/teacher/summary", params={"exam_id": d["id"]}, headers=D).json()["exam"]["is_drill"] is True
