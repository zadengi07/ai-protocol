from sqlalchemy import select
from sqlalchemy.orm import Session

from . import models, schemas
from .risk import RULES, compute_risk, level_of


def ev_dicts(events) -> list[dict]:
    return [{"id": e.id, "t": e.t, "type": e.type, "conf": e.conf, "fp": e.fp} for e in events]


def session_risk(s: models.ExamSession):
    return compute_risk(ev_dicts(s.events))


def session_out(s: models.ExamSession) -> schemas.SessionOut:
    r = session_risk(s)
    last = max(s.events, key=lambda e: e.t) if s.events else None
    return schemas.SessionOut(
        id=s.id, student_id=s.student_id, exam_id=s.exam_id, student_name=s.student.name,
        student_group=s.student.group, student_email=s.student.email,
        exam_title=s.exam.title, exam_minutes=s.exam.minutes, status=s.status, started_at=s.started_at, finished_at=s.finished_at,
        decision=s.decision, note=s.note, risk=r.total, level=level_of(r.total), events_count=len(s.events),
        last_event_type=last.type if last else None,
        last_event_label=RULES[last.type]["label"] if last else None,
    )


def get_session_or_404(db: Session, sid: int) -> models.ExamSession:
    from fastapi import HTTPException
    s = db.get(models.ExamSession, sid)
    if not s:
        raise HTTPException(404, "Sessiya topilmadi")
    return s


def scored_events(s: models.ExamSession) -> tuple[list[schemas.ScoredEvent], object]:
    r = session_risk(s)
    out = [schemas.ScoredEvent(id=e["id"], t=e["t"], type=e["type"], conf=e["conf"], fp=e["fp"],
                               label=RULES[e["type"]]["label"], score=round(e["score"], 2)) for e in r.scored]
    return out, r


def student_stats(db: Session, student_id: int) -> tuple[int, int | None, int | None]:
    sess = db.scalars(select(models.ExamSession).where(models.ExamSession.student_id == student_id)
                      .order_by(models.ExamSession.started_at.desc())).all()
    finished = [s for s in sess if s.status == "finished"]
    risk = session_risk(finished[0]).total if finished else None
    return len(sess), risk, (finished[0].id if finished else None)
