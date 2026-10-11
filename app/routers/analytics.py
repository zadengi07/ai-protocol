from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import models
from ..db import get_db
from ..risk import RULES, level_of
from ..services import session_risk

router = APIRouter(prefix="/analytics", tags=["analytics"])
DAYS = ["Du", "Se", "Ch", "Pa", "Ju", "Sh", "Ya"]


@router.get("/overview", summary="Statistika (Dashboard)")
def overview(db: Session = Depends(get_db)):
    sessions = db.scalars(select(models.ExamSession)).all()
    exams = db.scalars(select(models.Exam)).all()
    n_students = len(db.scalars(select(models.Student.id)).all())
    finished = [s for s in sessions if s.status == "finished"]
    risks = {s.id: session_risk(s).total for s in sessions}

    avg = round(sum(risks[s.id] for s in finished) / len(finished)) if finished else 0
    dist = {n: 0 for n in ("Past", "O'rta", "Yuqori", "Kritik")}
    for s in finished:
        dist[level_of(risks[s.id])] += 1

    types: dict[str, int] = {}
    for s in sessions:
        for e in s.events:
            if not e.fp:
                types[e.type] = types.get(e.type, 0) + 1
    top = [{"type": t, "label": RULES[t]["label"], "count": c} for t, c in sorted(types.items(), key=lambda x: -x[1])[:6]]

    today = datetime.now(timezone.utc).date()
    week = []
    for i in range(6, -1, -1):
        d = today - timedelta(days=i)
        cnt = sum(1 for s in sessions if s.started_at.date() == d)
        week.append({"date": d.isoformat(), "day": DAYS[d.weekday()], "sessions": cnt})

    flagged = sorted(sessions, key=lambda s: -risks[s.id])[:5]
    return {
        "active_exams": sum(1 for e in exams if e.status == "Jarayonda"),
        "students": n_students,
        "exams": len(exams),
        "avg_risk": avg,
        "weekly_sessions": week,
        "risk_distribution": [{"level": k, "count": v} for k, v in dist.items()],
        "top_events": top,
        "flagged": [{"session_id": s.id, "student_id": s.student_id, "name": s.student.name, "group": s.student.group,
                     "risk": risks[s.id], "level": level_of(risks[s.id]), "events_count": len(s.events)} for s in flagged],
    }
