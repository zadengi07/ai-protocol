"""1b-bosqich: qayta kirish va javoblarni saqlash. Ishga tushirish: DATABASE_URL=sqlite:///./test_tmp.db python -m pytest tests -q"""
import hashlib
import os
import uuid

os.environ.setdefault("DATABASE_URL", "sqlite:///./test_rejoin.db")

from datetime import datetime, timedelta, timezone  # noqa: E402

from fastapi.testclient import TestClient  # noqa: E402

from app.db import Base, SessionLocal, engine  # noqa: E402
from app import proctor_models  # noqa: E402,F401
from app.main import app  # noqa: E402
from app.models import KtAttempt, KtExam, KtTeacher  # noqa: E402
from app.routers import exam as exam_mod  # noqa: E402

Base.metadata.create_all(engine, checkfirst=True)

OWNER = {"X-Teacher-Login": "rj-owner", "X-Teacher-Password": "pw"}
OTHER = {"X-Teacher-Login": "rj-other", "X-Teacher-Password": "pw"}


def _questions():
    qs = []
    for i in range(3):
        qs.append({"id": f"n{i}", "turi": "NAZARIY", "mavzu": "m", "savol": f"nazariy {i}", "baholash": "2 ball", "faol": True})
    for i in range(2):
        qs.append({"id": f"a{i}", "turi": "AMALIY", "mavzu": "m", "savol": f"amaliy {i}", "baholash": "2 ball", "faol": True})
    return qs


def _setup():
    with SessionLocal() as db:
        for login in ("rj-owner", "rj-other"):
            if not db.query(KtTeacher).filter_by(login=login).first():
                db.add(KtTeacher(login=login, password_hash=hashlib.sha256(b"pw").hexdigest(), name=login))
        db.flush()
        owner = db.query(KtTeacher).filter_by(login="rj-owner").first()
        exam = KtExam(id=uuid.uuid4().hex, slug=f"rj-{uuid.uuid4().hex[:8]}", title="Rejoin test", minutes=80,
                      groups=["25-81"], questions=_questions(), status="active", teacher_id=owner.id)
        db.add(exam)
        db.commit()
        return exam.id, exam.slug


def _start(c, slug, name):
    return c.post("/api/exam/start", json={"student": name, "group": "25-81", "exam_slug": slug})


def test_rejoin_returns_same_attempt_and_counts():
    exam_id, slug = _setup()
    name = f"Qayta Kirdi {uuid.uuid4().hex[:4]}"
    with TestClient(app) as c:
        first = _start(c, slug, name).json()
        assert first["rejoin_count"] == 0 and "rejoined" not in first
        aid = first["attempt_id"]
        assert c.post("/api/exam/save", json={"attempt_id": aid, "answers": {first["questions"][0]["id"]: "javob A"}}).json() == {"ok": True}
        again = _start(c, slug, name).json()
        assert again["rejoined"] is True and again["rejoin_count"] == 1
        assert again["attempt_id"] == aid
        assert [q["id"] for q in again["questions"]] == [q["id"] for q in first["questions"]]   # savollar almashmaydi
        assert again["answers"] == {first["questions"][0]["id"]: "javob A"}                      # javoblar joyida
        assert again["deadline"] == first["deadline"]                                            # vaqt to'xtamaydi / uzaymaydi
        # proktoring hodisasi yozilgan va ustoz ko'radi
        ev = c.get(f"/api/proctor/events/{aid}", headers=OWNER).json()
        assert [e["event_type"] for e in ev["events"]] == ["rejoin"]
        att = c.get(f"/api/exam/teacher/attempt/{aid}", headers=OWNER).json()
        assert att["rejoin_count"] == 1
        assert any(e["label"] == "Imtihonga qayta kirdi" for e in att["proctor_events"])
        assert att["risk"]["score"] == 0     # qayta kirish o'zi ball qo'shmaydi


def test_limit_blocks_then_teacher_can_allow():
    exam_id, slug = _setup()
    name = f"Limit Talaba {uuid.uuid4().hex[:4]}"
    with TestClient(app) as c:
        aid = _start(c, slug, name).json()["attempt_id"]
        for n in range(1, exam_mod.MAX_SELF_REJOINS + 1):
            assert _start(c, slug, name).json()["rejoin_count"] == n
        r = _start(c, slug, name)                                   # limitdan keyingi urinish
        assert r.status_code == 403 and "ustozga murojaat" in r.json()["detail"].lower()
        # hisoblagich oshmagan
        assert c.get(f"/api/exam/teacher/attempt/{aid}", headers=OWNER).json()["rejoin_count"] == exam_mod.MAX_SELF_REJOINS
        rj = c.get("/api/exam/teacher/rejoins", params={"exam_id": exam_id}, headers=OWNER).json()
        row = next(s for s in rj["students"] if s["id"] == aid)
        assert row["blocked"] is True and row["rejoin_count"] == exam_mod.MAX_SELF_REJOINS
        # boshqa ustoz ruxsat bera olmaydi
        assert c.post(f"/api/exam/teacher/attempt/{aid}/allow-rejoin", headers=OTHER).status_code == 403
        assert c.post(f"/api/exam/teacher/attempt/{aid}/allow-rejoin").status_code == 401
        ok = c.post(f"/api/exam/teacher/attempt/{aid}/allow-rejoin", headers=OWNER).json()
        assert ok["limit"] == exam_mod.MAX_SELF_REJOINS + exam_mod.REJOIN_GRANT_STEP
        assert _start(c, slug, name).json()["rejoin_count"] == exam_mod.MAX_SELF_REJOINS + 1
        rj = c.get("/api/exam/teacher/rejoins", params={"exam_id": exam_id}, headers=OWNER).json()
        assert next(s for s in rj["students"] if s["id"] == aid)["blocked"] is False
        # boshqa ustozning /rejoins ro'yxatida ko'rinmaydi (imtihon unga tegishli emas)
        assert c.get("/api/exam/teacher/rejoins", params={"exam_id": exam_id}, headers=OTHER).status_code == 403


def test_rejoin_after_deadline_submits_and_does_not_count():
    exam_id, slug = _setup()
    name = f"Kech Qoldi {uuid.uuid4().hex[:4]}"
    with TestClient(app) as c:
        aid = _start(c, slug, name).json()["attempt_id"]
        with SessionLocal() as db:
            a = db.get(KtAttempt, aid)
            a.deadline = datetime.now(timezone.utc) - timedelta(seconds=5)
            db.commit()
        d = _start(c, slug, name).json()
        assert d["submitted"] is True and d["rejoin_count"] == 0
        # topshirilgandan keyin qayta kirib bo'lmaydi
        assert _start(c, slug, name).status_code == 409


def test_save_is_idempotent_and_old_attempts_default_zero():
    exam_id, slug = _setup()
    name = f"Saqlash {uuid.uuid4().hex[:4]}"
    with TestClient(app) as c:
        d = _start(c, slug, name).json()
        aid, qid = d["attempt_id"], d["questions"][0]["id"]
        body = {"attempt_id": aid, "answers": {qid: "bir xil javob"}}
        for _ in range(3):                                           # bir xil so'rov qayta-qayta kelsa ham muammo yo'q
            assert c.post("/api/exam/save", json=body).json() == {"ok": True}
        assert _start(c, slug, name).json()["answers"] == {qid: "bir xil javob"}
        body["answers"][qid] = "yangilandi"
        c.post("/api/exam/save", json=body)
        assert _start(c, slug, name).json()["answers"] == {qid: "yangilandi"}
    # ustun qiymatlarisiz yaratilgan (eski uslubdagi) urinish 0 bo'lib qoladi
    with SessionLocal() as db:
        now = datetime.now(timezone.utc)
        old = KtAttempt(id=uuid.uuid4().hex, exam_id=exam_id, student="Eski Yozuv", group="25-81", started_at=now,
                        deadline=now + timedelta(minutes=5), questions=[], answers={}, grades={})
        db.add(old); db.commit()
        db.refresh(old)
        assert old.rejoin_count == 0 and old.rejoin_allowed == 0


def test_rejoin_keeps_risk_score_and_log():
    """Qayta kirganda talaba ekranidagi xavf balli 0 ga tushmasligi kerak: server ball va hodisalarni qaytaradi."""
    exam_id, slug = _setup()
    name = f"Ball Saqlansin {uuid.uuid4().hex[:4]}"
    with TestClient(app) as c:
        aid = _start(c, slug, name).json()["attempt_id"]
        now = datetime.now(timezone.utc).isoformat()
        ev = {"event_id": str(uuid.uuid4()), "attempt_id": aid, "event_type": "paste", "event_time": now, "event_source": "blocked_attempt"}
        assert c.post("/api/proctor/events/batch", json={"attempt_id": aid, "events": [ev]}).status_code == 200
        again = _start(c, slug, name).json()
        assert again["risk"]["score"] == 12
        assert [(e["label"], e["points"]) for e in again["risk_log"]] == [("Joylashtirishga urinish", 12)]
