import os
os.environ["DATABASE_URL"] = "sqlite:///./test.db"
if os.path.exists("test.db"):
    os.remove("test.db")

from fastapi.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402
from app.risk import compute_risk  # noqa: E402

B = "/api/v1"


def test_all_flow():
    with TestClient(app) as c:
        # students / exams / analytics
        st = c.get(f"{B}/students").json()
        assert len(st) == 24 and st[0]["exams"] >= 1
        assert len(c.get(f"{B}/students", params={"group": "DI-21"}).json()) == 6
        ex = c.post(f"{B}/exams", json={"title": "Test", "group": "AT-21", "date": "2026-11-01", "minutes": 30, "questions": 10})
        assert ex.status_code == 201 and ex.json()["students"] == 6
        exam_id = ex.json()["id"]
        assert c.post(f"{B}/exams", json={"title": "x", "group": "A", "date": "bad", "minutes": 1, "questions": 1}).status_code == 422
        ov = c.get(f"{B}/analytics/overview").json()
        assert ov["students"] == 24 and len(ov["weekly_sessions"]) == 7 and len(ov["flagged"]) == 5

        # session flow
        s = c.post(f"{B}/sessions", json={"student_id": 1, "exam_id": exam_id})
        assert s.status_code == 201
        sid = s.json()["id"]
        assert c.post(f"{B}/sessions", json={"student_id": 1, "exam_id": exam_id}).status_code == 409
        assert c.post(f"{B}/sessions/{sid}/events", json={"type": "nope"}).status_code == 422
        e1 = c.post(f"{B}/sessions/{sid}/events", json={"type": "phone_detected", "conf": 0.9, "t": 100})
        c.post(f"{B}/sessions/{sid}/events", json={"type": "looking_down", "conf": 0.8, "t": 110})
        assert e1.status_code == 201
        rep = c.get(f"{B}/sessions/{sid}/report").json()
        assert rep["risk_score"] > 0 and rep["correlation_bonus"] > 0 and len(rep["events"]) == 2
        before = rep["risk_score"]
        p = c.patch(f"{B}/sessions/{sid}/events/{e1.json()['id']}", json={"fp": True})
        assert p.json()["fp"] is True and p.json()["score"] == 0
        assert c.get(f"{B}/sessions/{sid}/report").json()["risk_score"] < before
        d = c.post(f"{B}/sessions/{sid}/decision", json={"decision": "Qoniqarli", "note": "ok"})
        assert d.json()["decision"] == "Qoniqarli"
        assert c.post(f"{B}/sessions/{sid}/decision", json={"decision": "xato"}).status_code == 422
        assert c.post(f"{B}/sessions/{sid}/finish").json()["status"] == "finished"
        assert c.post(f"{B}/sessions/{sid}/events", json={"type": "tab_switch"}).status_code == 409
        assert c.get(f"{B}/sessions/999").status_code == 404
        act = c.get(f"{B}/sessions", params={"status": "active"}).json()
        assert len(act) == 6 and act[0]["student_group"] == "DI-22" and act[0]["exam_minutes"] == 45
        assert c.get(f"{B}/students").json()[0]["last_session_id"] is not None
        rec = c.get(f"{B}/events/recent").json()
        assert isinstance(rec, list)


def test_risk_matches_frontend():
    # Frontend bilan qo'lda tekshirilgan: phone(30*.9*.92)=24.84 + down(15*.8*.75)=9 ; bonus .5*33.84=16.92 -> 24.84+9+16.92 = 51 (bonus 17)
    r = compute_risk([{"id": 1, "t": 100, "type": "phone_detected", "conf": .9, "fp": False},
                      {"id": 2, "t": 110, "type": "looking_down", "conf": .8, "fp": False}])
    assert r.bonus == 17 and r.total == 51
