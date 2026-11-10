"""Savollar faylini yuklash: aniq xatolar va ishlatilgan savollarni himoyalash."""
import json
import os
import uuid

os.environ.setdefault("DATABASE_URL", "sqlite:///./test_qup.db")

from datetime import datetime, timedelta, timezone  # noqa: E402

from fastapi.testclient import TestClient  # noqa: E402

from app import proctor_models  # noqa: E402,F401
from app.db import Base, SessionLocal, engine  # noqa: E402
from app.main import app  # noqa: E402
from app.models import KtAttempt, KtExam  # noqa: E402
from tests.test_copy_drill import H, _qs, _teacher  # noqa: E402

Base.metadata.create_all(engine, checkfirst=True)


def _exam(with_attempt=False):
    with SessionLocal() as db:
        t = _teacher(db, "cd-own")
        e = KtExam(id=uuid.uuid4().hex, slug=f"qu-{uuid.uuid4().hex[:6]}", title="QU", minutes=55, groups=["25-81"], questions=_qs(), status="draft", teacher_id=t.id)
        db.add(e); db.flush()
        if with_attempt:
            now = datetime.now(timezone.utc)
            db.add(KtAttempt(id=uuid.uuid4().hex, exam_id=e.id, student="X", group="25-81", started_at=now, submitted=True,
                             deadline=now + timedelta(minutes=5), questions=["n0", "a0"], answers={}, grades={}))
        db.commit(); return e.id


def _post(c, eid, raw):
    return c.post(f"/api/exam/teacher/exams/{eid}/questions", headers=H, json={"questions_json": raw})


def test_errors_are_specific_and_nothing_changes():
    eid = _exam()
    bad = [{"id": "x1", "turi": "NAZARIY", "mavzu": "m", "savol": "s", "baholash": "ball yo'q"}]
    with TestClient(app) as c:
        r = _post(c, eid, json.dumps(bad))
        assert r.status_code == 400
        assert "1-savol (id: x1)" in r.json()["detail"] and "'baholash'" in r.json()["detail"] and "Kamida 3 ta NAZARIY" in r.json()["detail"]
        assert "JSON formatida xatolik" in _post(c, eid, "{bad").json()["detail"]
        assert c.get(f"/api/exam/teacher/exams/{eid}/questions", headers=H).json()["count"] == 5   # eski savollar joyida


def test_valid_file_saved_and_listing_is_short():
    eid = _exam()
    new = [{**q, "id": "z" + q["id"]} for q in _qs()]
    with TestClient(app) as c:
        assert _post(c, eid, json.dumps(new)).json() == {"ok": True, "count": 5}
        g = c.get(f"/api/exam/teacher/exams/{eid}/questions", headers=H).json()
        assert g["count"] == 5 and "questions_json" not in g and g["items"][0]["id"] == "zn0"


def test_cannot_drop_questions_students_already_got():
    eid = _exam(with_attempt=True)
    new = [{**q, "id": "z" + q["id"]} for q in _qs()]
    with TestClient(app) as c:
        r = _post(c, eid, json.dumps(new))
        assert r.status_code == 409 and "a0" in r.json()["detail"] and "n0" in r.json()["detail"]
        assert c.get(f"/api/exam/teacher/exams/{eid}/questions", headers=H).json()["items"][0]["id"] == "n0"
        assert _post(c, eid, json.dumps(_qs())).status_code == 200                                  # xuddi shu id lar bilan — mumkin


def test_scoring_only_load_gives_same_score_as_full_load():
    from app.proctor_models import KtProctorEvent
    from app.proctor_risk import proctor_rows_bulk, proctor_summary_from
    eid = _exam(with_attempt=True)
    with SessionLocal() as db:
        a = db.query(KtAttempt).filter_by(exam_id=eid).first()
        now = datetime.now(timezone.utc)
        spec = [("paste", "blocked_attempt", {}, None), ("window_blur", "detected", {"tab_id": "t", "episode": 1}, None),
                ("tab_hidden", "detected", {"tab_id": "t", "episode": 1}, None), ("window_focus", "detected", {}, None),
                ("window_resize", "inferred", {}, None), ("copy", "detected", {}, False), ("fullscreen_exit", "detected", {}, None),
                ("devtools_suspected", "inferred", {}, None)]
        for i, (typ, src, det, just) in enumerate(spec):
            db.add(KtProctorEvent(event_id=str(uuid.uuid4()), attempt_id=a.id, exam_id=eid, student_id="X", group_name="25-81", event_type=typ,
                                  event_time=now + timedelta(seconds=i), received_at=now, event_details=det, event_source=src, severity="info", justified=just))
        db.commit()
        full = proctor_summary_from(proctor_rows_bulk(db, [a.id])[a.id])
        lite = proctor_summary_from(proctor_rows_bulk(db, [a.id], scoring_only=True)[a.id])
        assert full["score"] == lite["score"] == 12 + 8 + 12      # paste + 1 epizod (blur/hidden) + fullscreen_exit; copy "asossiz"
        assert lite["total"] < full["total"]
