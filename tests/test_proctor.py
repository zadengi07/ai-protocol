"""Proktoring hodisalari testlari. Ishga tushirish (backend papkasidan): python -m pytest tests/test_proctor.py -q"""
from app import proctor_models
from app.db import Base, engine
Base.metadata.create_all(engine, checkfirst=True)
import hashlib
import os
import uuid

os.environ.setdefault("DATABASE_URL", "sqlite:///./test_proctor.db")

from datetime import datetime, timedelta, timezone  # noqa: E402

from fastapi.testclient import TestClient  # noqa: E402

from app.db import SessionLocal  # noqa: E402
from app.main import app  # noqa: E402
from app.models import KtAttempt, KtExam, KtTeacher  # noqa: E402

T = {"X-Teacher-Login": "ustoz-test", "X-Teacher-Password": "parol-test"}


def _ev(attempt_id, etype="window_blur", **kw):
    d = {"event_id": str(uuid.uuid4()), "attempt_id": attempt_id, "event_type": etype,
         "event_time": datetime.now(timezone.utc).isoformat(), "event_source": "detected", "severity": "low",
         "event_details": {"episode": 1}, "page_url": "https://x.test/exam-kt", "browser_name": "Chrome 126",
         "operating_system": "Windows", "device_type": "desktop"}
    d.update(kw)
    return d


def _setup():
    with SessionLocal() as db:
        exam = KtExam(id=uuid.uuid4().hex, slug=f"t-{uuid.uuid4().hex[:8]}", title="Test", minutes=80, groups=["25-80"], status="finished")
        db.add(exam)
        db.flush()
        now = datetime.now(timezone.utc)
        ids = []
        for name in ("Ali Valiyev", "Vali Aliyev"):
            a = KtAttempt(id=uuid.uuid4().hex, exam_id=exam.id, student=f"{name} {uuid.uuid4().hex[:4]}", group="25-80",
                          started_at=now, deadline=now + timedelta(minutes=80), questions=[], answers={}, grades={})
            db.add(a)
            ids.append(a.id)
        if not db.query(KtTeacher).filter_by(login="ustoz-test").first():
            db.add(KtTeacher(login="ustoz-test", password_hash=hashlib.sha256(b"parol-test").hexdigest(), name="Test"))
        db.commit()
        return exam.id, ids


def test_batch_dedup_validation_and_isolation():
    exam_id, (a, b) = _setup()
    with TestClient(app) as c:
        e1, e2 = _ev(a), _ev(a, "tab_hidden")
        bad_type = _ev(a, "nope")
        other = _ev(b)                      # B ning eventi A nomidan yuborilmoqchi
        r = c.post("/api/proctor/events/batch", json={"attempt_id": a, "events": [e1, e2, e1, bad_type, other]})
        assert r.status_code == 200, r.text
        d = r.json()
        assert d["accepted"] == 2 and len(d["rejected"]) == 2
        assert {x["reason"] for x in d["rejected"]} == {"validation", "attempt_mismatch"}
        assert d["totals"]["total"] == 2
        # xuddi shu batch qayta yuborilsa: bazaga qayta yozilmaydi
        r2 = c.post("/api/proctor/events/batch", json={"attempt_id": a, "events": [e1, e2]}).json()
        assert r2["accepted"] == 0 and r2["duplicates"] == 2 and r2["totals"]["total"] == 2
        # yakka endpoint ham deduplikatsiya qiladi
        assert c.post("/api/proctor/events", json=e1).json()["accepted"] == 0
        # ikkinchi talaba alohida hisoblanadi
        rb = c.post("/api/proctor/events/batch", json={"attempt_id": b, "events": [_ev(b, "copy", event_source="blocked_attempt")]}).json()
        assert rb["totals"]["total"] == 1 and rb["totals"]["by_type"] == {"copy": 1}
        # noma'lum urinish
        assert c.post("/api/proctor/events/batch", json={"attempt_id": "f" * 32, "events": [_ev("f" * 32)]}).status_code == 404
        # noto'g'ri manba / og'irlik => yakka endpointda 422, batchda rejected
        assert c.post("/api/proctor/events", json=_ev(a, event_source="confirmed")).status_code == 422


def test_server_overrides_identity_and_get_is_teacher_only():
    exam_id, (a, b) = _setup()
    with TestClient(app) as c:
        ev = _ev(a, student_id="BOSHQA TALABA", group_name="99-99", exam_id="x")
        assert c.post("/api/proctor/events", json=ev).status_code == 200
        assert c.get(f"/api/proctor/events/{a}").status_code == 401                              # talaba/begona o'qiy olmaydi
        assert c.get(f"/api/proctor/events/{a}", headers={"X-Teacher-Login": "ustoz-test", "X-Teacher-Password": "x"}).status_code == 401
        r = c.get(f"/api/proctor/events/{a}", headers=T)
        assert r.status_code == 200
        row = r.json()["events"][0]
        assert row["student_id"] != "BOSHQA TALABA" and row["group_name"] == "25-80" and row["exam_id"] == exam_id
        assert c.get(f"/api/proctor/events/{b}", headers=T).json()["totals"]["total"] == 0


def test_existing_endpoints_still_work():
    with TestClient(app) as c:
        assert c.get("/health").json() == {"status": "ok"}
        assert c.get("/api/kt/meta").status_code == 200


def test_exam_delete_still_works_with_proctor_rows():
    exam_id, (a, _) = _setup()
    with TestClient(app) as c:
        c.post("/api/proctor/events", json=_ev(a))
        r = c.delete(f"/api/kt/teacher/exams/{exam_id}", headers=T)
        assert r.status_code == 200 and r.json()["deleted_attempts"] == 2

def test_teacher_risk_comes_from_proctor_events():
    exam_id, (a, _) = _setup()
    with TestClient(app) as c:
        c.post("/api/proctor/events/batch", json={"attempt_id": a, "events": [
            _ev(a, "copy", event_source="blocked_attempt"),
            _ev(a, "devtools_shortcut", event_source="blocked_attempt"),
            _ev(a, "devtools_suspected", event_source="inferred"),   # ballga kirmaydi
        ]})
        r = c.get("/api/kt/teacher/dashboard", params={"exam_id": exam_id}, headers=T).json()
        st = next(s for s in r["students"] if s["id"] == a)
        assert st["risk"]["source"] == "proctor"
        assert st["risk"]["score"] == 30   # copy 10 + devtools 20

def test_dashboard_light_mode_is_lean_and_matches_full():
    exam_id, (a, _) = _setup()
    with TestClient(app) as c:
        c.post("/api/proctor/events/batch", json={"attempt_id": a, "events": [
            _ev(a, "copy", event_source="blocked_attempt"),
        ]})
        full = c.get("/api/kt/teacher/dashboard", params={"exam_id": exam_id}, headers=T).json()
        light = c.get("/api/kt/teacher/dashboard", params={"exam_id": exam_id, "light": 1}, headers=T).json()
        assert "questions" in full and "questions" not in light
        fs = {s["id"]: s for s in full["students"]}
        for s in light["students"]:
            assert "items" not in s and "proctor_events" not in s and "events" not in s
            assert s["item_count"] == len(fs[s["id"]]["items"])
            assert s["risk"] == fs[s["id"]]["risk"]
            assert s["answered"] == fs[s["id"]]["answered"] and s["total_max"] == fs[s["id"]]["total_max"]
