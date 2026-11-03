from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import models, schemas
from ..db import get_db
from ..services import get_session_or_404, scored_events, session_out

router = APIRouter(prefix="/sessions", tags=["sessions"])


@router.post("", response_model=schemas.SessionOut, status_code=201, summary="Yangi sessiya boshlash")
def start_session(body: schemas.SessionIn, db: Session = Depends(get_db)):
    if not db.get(models.Student, body.student_id):
        raise HTTPException(404, "Talaba topilmadi")
    exam = db.get(models.Exam, body.exam_id)
    if not exam:
        raise HTTPException(404, "Imtihon topilmadi")
    active = db.scalar(select(models.ExamSession).where(
        models.ExamSession.student_id == body.student_id, models.ExamSession.exam_id == body.exam_id,
        models.ExamSession.status == "active"))
    if active:
        raise HTTPException(409, f"Faol sessiya allaqachon mavjud (id={active.id})")
    s = models.ExamSession(student_id=body.student_id, exam_id=body.exam_id)
    exam.status = "Jarayonda" if exam.status == "Rejalashtirilgan" else exam.status
    db.add(s)
    db.commit()
    return session_out(s)


@router.get("", response_model=list[schemas.SessionOut], summary="Sessiyalar ro'yxati (jonli monitoring uchun)")
def list_sessions(status: str | None = Query(None, pattern="^(active|finished)$"), exam_id: int | None = None,
                  student_id: int | None = None, db: Session = Depends(get_db)):
    q = select(models.ExamSession).order_by(models.ExamSession.started_at.desc())
    if status:
        q = q.where(models.ExamSession.status == status)
    if exam_id:
        q = q.where(models.ExamSession.exam_id == exam_id)
    if student_id:
        q = q.where(models.ExamSession.student_id == student_id)
    return [session_out(s) for s in db.scalars(q)]


@router.get("/{sid}", response_model=schemas.SessionOut, summary="Sessiya tafsilotlari")
def get_session(sid: int, db: Session = Depends(get_db)):
    return session_out(get_session_or_404(db, sid))


@router.post("/{sid}/finish", response_model=schemas.SessionOut, summary="Sessiyani yakunlash")
def finish(sid: int, db: Session = Depends(get_db)):
    s = get_session_or_404(db, sid)
    if s.status == "finished":
        raise HTTPException(409, "Sessiya allaqachon yakunlangan")
    s.status, s.finished_at = "finished", datetime.now(timezone.utc)
    db.commit()
    return session_out(s)


@router.get("/{sid}/events", response_model=list[schemas.ScoredEvent], summary="Sessiya eventlari")
def list_events(sid: int, db: Session = Depends(get_db)):
    return scored_events(get_session_or_404(db, sid))[0]


@router.post("/{sid}/events", response_model=schemas.ScoredEvent, status_code=201, summary="Event qo'shish")
def add_event(sid: int, body: schemas.EventIn, db: Session = Depends(get_db)):
    s = get_session_or_404(db, sid)
    if s.status != "active":
        raise HTTPException(409, "Yakunlangan sessiyaga event qo'shib bo'lmaydi")
    t = body.t
    if t is None:
        started = s.started_at if s.started_at.tzinfo else s.started_at.replace(tzinfo=timezone.utc)
        t = max(0.0, (datetime.now(timezone.utc) - started).total_seconds())
    e = models.Event(session_id=sid, t=round(t, 1), type=body.type, conf=body.conf)
    db.add(e)
    db.commit()
    db.refresh(s)
    return next(x for x in scored_events(s)[0] if x.id == e.id)


@router.patch("/{sid}/events/{eid}", response_model=schemas.ScoredEvent, summary="Eventni noto'g'ri signal (FP) deb belgilash")
def patch_event(sid: int, eid: int, body: schemas.EventPatch, db: Session = Depends(get_db)):
    s = get_session_or_404(db, sid)
    e = db.get(models.Event, eid)
    if not e or e.session_id != sid:
        raise HTTPException(404, "Event topilmadi")
    e.fp = body.fp
    db.commit()
    db.refresh(s)
    return next(x for x in scored_events(s)[0] if x.id == eid)


@router.get("/{sid}/report", response_model=schemas.ReportOut, summary="AI hisobot")
def report(sid: int, db: Session = Depends(get_db)):
    s = get_session_or_404(db, sid)
    evs, r = scored_events(s)
    return schemas.ReportOut(
        session_id=s.id, student=s.student.name, group=s.student.group, exam=s.exam.title,
        risk_score=r.total, level=r.level, correlation_bonus=r.bonus,
        proctor_decision=s.decision, proctor_note=s.note, events=evs)


@router.post("/{sid}/decision", response_model=schemas.SessionOut, summary="Proktor qarori")
def decision(sid: int, body: schemas.DecisionIn, db: Session = Depends(get_db)):
    s = get_session_or_404(db, sid)
    s.decision, s.note, s.decided_at = body.decision, body.note, datetime.now(timezone.utc)
    db.commit()
    return session_out(s)
