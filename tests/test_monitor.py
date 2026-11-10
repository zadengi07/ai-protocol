"""8-bosqich: kuzatuv paneli (uch holat)."""
import hashlib
import os
import time
import uuid

os.environ.setdefault("DATABASE_URL", "sqlite:///./test_monitor.db")

from datetime import datetime, timedelta, timezone  # noqa: E402

from fastapi.testclient import TestClient  # noqa: E402

from app import proctor_models  # noqa: E402,F401
from app.db import Base, SessionLocal, engine  # noqa: E402
from app.main import app  # noqa: E402
from app.models import KtAttempt, KtExam, KtTeacher  # noqa: E402
from app.routers import exam as em  # noqa: E402

Base.metadata.create_all(engine, checkfirst=True)
H = {"X-Teacher-Login": "mo-own", "X-Teacher-Password": "pw"}
O = {"X-Teacher-Login": "mo-oth", "X-Teacher-Password": "pw"}


def test_three_states_and_counts():
    with SessionLocal() as db:
        for lg in ("mo-own", "mo-oth"):
            if not db.query(KtTeacher).filter_by(login=lg).first():
                db.add(KtTeacher(login=lg, password_hash=hashlib.sha256(b"pw").hexdigest(), name=lg))
        db.flush()
        own = db.query(KtTeacher).filter_by(login="mo-own").first()
        ex = KtExam(id=uuid.uuid4().hex, slug=f"mo-{uuid.uuid4().hex[:6]}", title="Mo", minutes=80, groups=["25-81"], status="active", teacher_id=own.id)
        db.add(ex); db.flush()
        now = datetime.now(timezone.utc)
        ids = {}
        for nm, kw in {"Normal": {}, "Xavfli": {}, "Qayta": {"rejoin_count": 1}, "Limit": {"rejoin_count": 3}, "Aloqasiz": {}, "Topshirgan": {"submitted": True}}.items():
            a = KtAttempt(id=uuid.uuid4().hex, exam_id=ex.id, student=nm, group="25-81", started_at=now, deadline=now + timedelta(minutes=80),
                          questions=[], answers={}, grades={}, **kw)
            db.add(a); ids[nm] = a.id
        db.commit(); exam_id = ex.id
    with TestClient(app) as c:
        em.SERVER_START = time.time() - 1000                                       # server uzoq ishlayapti
        for nm, aid in ids.items():
            em._last_seen[aid] = time.time()                                       # hammasi hozir aloqada
        em._last_seen[ids["Aloqasiz"]] = time.time() - 150                          # 150 s jim
        ev = lambda t, src="blocked_attempt": {"event_id": str(uuid.uuid4()), "attempt_id": ids["Xavfli"], "event_type": t,
              "event_time": now.isoformat(), "event_source": src, "severity": "high", "event_details": {}}
        c.post("/api/proctor/events/batch", json={"attempt_id": ids["Xavfli"], "events": [ev("devtools_shortcut"), ev("copy"), ev("paste"), ev("devtools_shortcut")]})  # 20+10+12+20=62
        d = c.get("/api/exam/teacher/monitor", params={"exam_id": exam_id}, headers=H).json()
        st = {r["student"]: r for r in d["students"]}
        assert st["Xavfli"]["state"] == "problem" and st["Xavfli"]["risk"] == 62
        assert st["Limit"]["state"] == "problem" and "Qayta kirish limiti tugadi" in st["Limit"]["reasons"]
        assert st["Qayta"]["state"] == "attention" and st["Normal"]["state"] == "normal"
        assert st["Aloqasiz"]["lost"] is True and st["Aloqasiz"]["state"] == "attention"
        assert st["Topshirgan"]["state"] == "normal" and st["Topshirgan"]["lost"] is False
        assert d["counts"] == {"total": 6, "submitted": 1, "active": 5, "lost": 1, "problem": 2, "attention": 2}
        assert [r["state"] for r in d["students"]][:2] == ["problem", "problem"]     # muammolilar tepada
        em._last_seen[ids["Aloqasiz"]] = time.time() - 400                           # 400 s jim -> muammo
        assert next(r for r in c.get("/api/exam/teacher/monitor", params={"exam_id": exam_id}, headers=H).json()["students"] if r["student"] == "Aloqasiz")["state"] == "problem"
        # yurak urishi: talaba so'rovi aloqani tiklaydi
        c.get(f"/api/exam/attempt/{ids['Aloqasiz']}?light=true")
        assert next(r for r in c.get("/api/exam/teacher/monitor", params={"exam_id": exam_id}, headers=H).json()["students"] if r["student"] == "Aloqasiz")["lost"] is False
        assert c.get("/api/exam/teacher/monitor", params={"exam_id": exam_id}, headers=O).status_code == 403
        assert c.get("/api/exam/teacher/monitor", params={"exam_id": exam_id}).status_code == 401
