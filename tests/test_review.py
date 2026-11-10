"""3-bosqich: hodisalarni asosli/asossiz belgilash va riskni qayta hisoblash."""
import hashlib
import os
import uuid

os.environ.setdefault("DATABASE_URL", "sqlite:///./test_review.db")

from datetime import datetime, timedelta, timezone  # noqa: E402

from fastapi.testclient import TestClient  # noqa: E402

from app import proctor_models  # noqa: E402,F401
from app.db import Base, SessionLocal, engine  # noqa: E402
from app.main import app  # noqa: E402
from app.models import KtAttempt, KtExam, KtTeacher  # noqa: E402

Base.metadata.create_all(engine, checkfirst=True)
OWN = {"X-Teacher-Login": "rv-own", "X-Teacher-Password": "pw"}
OTH = {"X-Teacher-Login": "rv-oth", "X-Teacher-Password": "pw"}


def _setup():
    with SessionLocal() as db:
        for lg in ("rv-own", "rv-oth"):
            if not db.query(KtTeacher).filter_by(login=lg).first():
                db.add(KtTeacher(login=lg, password_hash=hashlib.sha256(b"pw").hexdigest(), name=lg))
        db.flush()
        own = db.query(KtTeacher).filter_by(login="rv-own").first()
        ex = KtExam(id=uuid.uuid4().hex, slug=f"rv-{uuid.uuid4().hex[:6]}", title="Rv", minutes=80, groups=["25-81"], status="finished", teacher_id=own.id)
        db.add(ex); db.flush()
        now = datetime.now(timezone.utc)
        a = KtAttempt(id=uuid.uuid4().hex, exam_id=ex.id, student="Rv Talaba", group="25-81", started_at=now,
                      deadline=now + timedelta(minutes=80), questions=[], answers={}, grades={})
        db.add(a); db.commit()
        return ex.id, a.id


def _ev(aid, t, sec, **kw):
    d = {"event_id": str(uuid.uuid4()), "attempt_id": aid, "event_type": t, "event_source": "detected", "severity": "low",
         "event_time": (datetime.now(timezone.utc) + timedelta(seconds=sec)).isoformat(), "event_details": {"tab_id": "t1", "episode": sec}}
    d.update(kw)
    return d


def test_review_recalculates_risk_and_keeps_events():
    ex, aid = _setup()
    with TestClient(app) as c:
        copy = _ev(aid, "copy", 1, event_source="blocked_attempt", event_details={})
        blur = _ev(aid, "window_blur", 10)
        focus = _ev(aid, "window_focus", 75, event_details={"tab_id": "t1"})
        c.post("/api/proctor/events/batch", json={"attempt_id": aid, "events": [copy, blur, focus]})
        att = c.get(f"/api/exam/teacher/attempt/{aid}", headers=OWN).json()
        assert att["risk"]["score"] == 18                                   # copy 10 + blur 8
        tl = {e["type"]: e for e in att["proctor_events"]}
        assert tl["window_blur"]["duration_s"] == 65 and tl["window_blur"]["points"] == 8
        assert tl["copy"]["justified"] is None and "window_focus" not in tl
        assert {i["type"]: i["points"] for i in att["risk_detail"]["items"]} == {"copy": 10, "window_blur": 8}
        # kalkulyator ochgan: "asossiz"
        r = c.post("/api/exam/teacher/events/review", json={"attempt_id": aid, "event_ids": [blur["event_id"]], "justified": False}, headers=OWN).json()
        assert r["updated"] == 1 and r["risk"]["score"] == 10 and r["risk_detail"]["excluded"] == 1
        att = c.get(f"/api/exam/teacher/attempt/{aid}", headers=OWN).json()
        assert att["risk"]["score"] == 10
        assert len(att["proctor_events"]) == 2                               # hodisa o'chmaydi, ko'rinib turadi
        assert next(e for e in att["proctor_events"] if e["type"] == "window_blur")["points"] == 0
        # dashboard (light) ham yangi riskni ko'radi
        d = c.get("/api/exam/teacher/dashboard", params={"exam_id": ex, "light": 1}, headers=OWN).json()
        assert d["students"][0]["risk"]["score"] == 10
        # bekor qilish -> qaytadi
        r = c.post("/api/exam/teacher/events/review", json={"attempt_id": aid, "event_ids": [blur["event_id"]], "justified": None}, headers=OWN).json()
        assert r["risk"]["score"] == 18


def test_review_requires_ownership():
    ex, aid = _setup()
    with TestClient(app) as c:
        e = _ev(aid, "copy", 1, event_source="blocked_attempt", event_details={})
        c.post("/api/proctor/events/batch", json={"attempt_id": aid, "events": [e]})
        body = {"attempt_id": aid, "event_ids": [e["event_id"]], "justified": False}
        assert c.post("/api/exam/teacher/events/review", json=body).status_code == 401
        assert c.post("/api/exam/teacher/events/review", json=body, headers=OTH).status_code == 403   # boshqa ustoz
        assert c.get(f"/api/exam/teacher/attempt/{aid}", headers=OWN).json()["risk"]["score"] == 10    # o'zgarmagan


def test_timeline_times_carry_timezone():
    ex, aid = _setup()
    with TestClient(app) as c:
        c.post("/api/proctor/events/batch", json={"attempt_id": aid, "events": [_ev(aid, "copy", 1, event_source="blocked_attempt", event_details={})]})
        at = c.get(f"/api/exam/teacher/attempt/{aid}", headers=OWN).json()["proctor_events"][0]["at"]
        assert at.endswith("+00:00")
