"""
/api/exam/{slug}          — talaba uchun
/api/teacher/{slug}       — ustoz uchun (teacher_key talab qilinadi)
"""
from datetime import datetime, timedelta, timezone
from fastapi import APIRouter, Depends, HTTPException, Header
from sqlalchemy import select
from sqlalchemy.orm import Session
from .. import models, schemas
from ..db import get_db
from ..risk import RULES, compute_risk, level_of

router = APIRouter(tags=["exam"])
GROUPS = ["25-79", "25-80", "25-81", "25-82", "25-83", "25-85"]


def _utc():
    return datetime.now(timezone.utc)


def _get_exam(slug: str, db: Session) -> models.Exam:
    e = db.scalar(select(models.Exam).where(models.Exam.slug == slug))
    if not e:
        raise HTTPException(404, "Imtihon topilmadi")
    return e


def _require_teacher(exam: models.Exam, key: str | None):
    if not key or key != exam.teacher_key:
        raise HTTPException(403, "Ustoz kaliti noto'g'ri")


def _session_out(s: models.ExamSession) -> schemas.SessionOut:
    return schemas.SessionOut.from_model(s)


def _compute_score(session: models.ExamSession) -> tuple[int, int]:
    score = 0
    total = 0
    for a in session.answers:
        q = a.question
        total += q.points
        if a.option and a.option.is_correct:
            score += q.points
    return score, total


# ══════════════════════════════════════════
# TEACHER ENDPOINTS
# ══════════════════════════════════════════

@router.post("/api/teacher/create", response_model=schemas.ExamPublic, status_code=201)
def create_exam(body: schemas.ExamCreate, db: Session = Depends(get_db)):
    if db.scalar(select(models.Exam).where(models.Exam.slug == body.slug)):
        raise HTTPException(409, f"'{body.slug}' slug allaqachon mavjud")
    e = models.Exam(**body.model_dump())
    db.add(e)
    db.commit()
    return e


@router.post("/api/teacher/{slug}/start", response_model=schemas.ExamPublic)
def start_exam(slug: str, body: schemas.TeacherAuth, db: Session = Depends(get_db)):
    e = _get_exam(slug, db)
    _require_teacher(e, body.teacher_key)
    if e.status == "active":
        raise HTTPException(409, "Imtihon allaqachon boshlangan")
    if e.status == "finished":
        raise HTTPException(409, "Imtihon tugagan")
    e.status = "active"
    e.started_at = _utc()
    db.commit()
    return e


@router.post("/api/teacher/{slug}/finish", response_model=schemas.ExamPublic)
def finish_exam(slug: str, body: schemas.TeacherAuth, db: Session = Depends(get_db)):
    e = _get_exam(slug, db)
    _require_teacher(e, body.teacher_key)
    if e.status != "active":
        raise HTTPException(409, "Imtihon faol emas")
    e.status = "finished"
    e.finished_at = _utc()
    e.drop_after = e.finished_at + timedelta(hours=24)
    # Barcha faol sessiyalarni yakunla + hisobla
    for s in e.sessions:
        if s.status == "active":
            s.status = "finished"
            s.finished_at = _utc()
            sc, tot = _compute_score(s)
            s.score, s.total_points = sc, tot
    db.commit()
    return e


@router.post("/api/teacher/{slug}/questions")
def add_questions(slug: str, body: schemas.TeacherAuth, questions: list[schemas.QuestionCreate],
                  db: Session = Depends(get_db)):
    e = _get_exam(slug, db)
    _require_teacher(e, body.teacher_key)
    if e.status != "pending":
        raise HTTPException(409, "Imtihon boshlangandan keyin savol qo'shib bo'lmaydi")
    # Avvalgi savollarni o'chir
    for q in e.questions:
        db.delete(q)
    db.flush()
    for i, qd in enumerate(questions, 1):
        q = models.Question(exam_id=e.id, order_num=i, text=qd.text, points=qd.points)
        db.add(q)
        db.flush()
        for op in qd.options:
            db.add(models.Option(question_id=q.id, key=op["key"], text=op["text"],
                                  is_correct=op.get("is_correct", False)))
    db.commit()
    return {"added": len(questions)}


@router.get("/api/teacher/{slug}/stats", response_model=schemas.ExamStats)
def exam_stats(slug: str, key: str, db: Session = Depends(get_db)):
    e = _get_exam(slug, db)
    _require_teacher(e, key)
    groups_data: dict[str, dict] = {}
    for g in GROUPS:
        groups_data[g] = {"total": 0, "finished": 0, "scores": [], "risks": []}
    for s in e.sessions:
        g = s.student_group
        if g not in groups_data:
            groups_data[g] = {"total": 0, "finished": 0, "scores": [], "risks": []}
        groups_data[g]["total"] += 1
        if s.status == "finished":
            groups_data[g]["finished"] += 1
            if s.score is not None:
                groups_data[g]["scores"].append(s.score)
            groups_data[g]["risks"].append(s.risk_score)
    groups = []
    for g, d in groups_data.items():
        avg_sc = round(sum(d["scores"]) / len(d["scores"]), 1) if d["scores"] else None
        avg_risk = round(sum(d["risks"]) / len(d["risks"])) if d["risks"] else 0
        groups.append(schemas.GroupStat(group=g, total=d["total"], finished=d["finished"],
                                         avg_score=avg_sc, avg_risk=avg_risk))
    return schemas.ExamStats(
        exam=e,
        groups=groups,
        sessions=[_session_out(s) for s in e.sessions]
    )


@router.get("/api/teacher/{slug}/results", response_model=list[schemas.ResultRow])
def exam_results(slug: str, key: str, db: Session = Depends(get_db)):
    e = _get_exam(slug, db)
    _require_teacher(e, key)
    rows = []
    for s in sorted(e.sessions, key=lambda x: (x.student_group, x.student_name)):
        pct = round(s.score / s.total_points * 100, 1) if s.score is not None and s.total_points else None
        rows.append(schemas.ResultRow(
            student_name=s.student_name, student_group=s.student_group,
            score=s.score, total_points=s.total_points, pct=pct,
            risk_score=s.risk_score, risk_level=level_of(s.risk_score), decision=s.decision))
    return rows


@router.get("/api/teacher/{slug}/session/{sid}/events")
def session_events(slug: str, sid: int, key: str, db: Session = Depends(get_db)):
    e = _get_exam(slug, db)
    _require_teacher(e, key)
    s = db.get(models.ExamSession, sid)
    if not s or s.exam_id != e.id:
        raise HTTPException(404, "Sessiya topilmadi")
    return [{"id": ev.id, "t": ev.t, "type": ev.type, "label": RULES.get(ev.type, {}).get("label", ev.type),
             "conf": ev.conf, "fp": ev.fp} for ev in s.events]


@router.post("/api/teacher/{slug}/session/{sid}/decision")
def set_decision(slug: str, sid: int, body: schemas.DecisionIn, key: str,
                 db: Session = Depends(get_db)):
    e = _get_exam(slug, db)
    _require_teacher(e, key)
    s = db.get(models.ExamSession, sid)
    if not s or s.exam_id != e.id:
        raise HTTPException(404, "Sessiya topilmadi")
    s.decision = body.decision
    s.note = body.note
    db.commit()
    return {"ok": True}


@router.post("/api/teacher/{slug}/drop")
def drop_exam(slug: str, body: schemas.TeacherAuth, db: Session = Depends(get_db)):
    e = _get_exam(slug, db)
    _require_teacher(e, body.teacher_key)
    if e.dropped:
        raise HTTPException(409, "Allaqachon o'chirilgan")
    if e.status != "finished":
        raise HTTPException(409, "Avval imtihonni yakunlang")
    if e.drop_after and _utc() < e.drop_after:
        remaining = (e.drop_after - _utc()).seconds // 3600
        raise HTTPException(400, f"DROP {remaining} soatdan keyin mumkin (24 soat kutish kerak)")
    # O'chirish: savollar, variantlar, sessiyalar ichidagi javoblar va loglar
    # final_results (score) sessions jadvalida qoladi, boshqasi o'chadi
    for s in e.sessions:
        s.answers.clear()
        for ev in s.events:
            db.delete(ev)
        s.events.clear()
    for q in e.questions:
        db.delete(q)
    e.dropped = True
    db.commit()
    return {"ok": True, "message": "Barcha vaqtinchalik ma'lumotlar o'chirildi. Natijalar saqlanib qoldi."}


# ══════════════════════════════════════════
# STUDENT ENDPOINTS
# ══════════════════════════════════════════

@router.get("/api/exam/{slug}", response_model=schemas.ExamPublic)
def get_exam_public(slug: str, db: Session = Depends(get_db)):
    return _get_exam(slug, db)


@router.post("/api/exam/{slug}/start", response_model=schemas.SessionOut, status_code=201)
def student_start(slug: str, body: schemas.SessionStart, db: Session = Depends(get_db)):
    e = _get_exam(slug, db)
    if e.status != "active":
        raise HTTPException(400, "Imtihon hozir faol emas. Ustoz hali boshlamagan bo'lishi mumkin.")
    if body.student_group not in GROUPS:
        raise HTTPException(400, "Noto'g'ri guruh")
    # Takroriy kirish tekshiruvi
    existing = db.scalar(select(models.ExamSession).where(
        models.ExamSession.exam_id == e.id,
        models.ExamSession.student_name == body.student_name.strip(),
        models.ExamSession.student_group == body.student_group))
    if existing:
        raise HTTPException(409, "Siz ushbu imtihonni allaqachon boshlagansiz. Test faqat bir marta olinadi.")
    s = models.ExamSession(exam_id=e.id, student_name=body.student_name.strip(),
                            student_group=body.student_group)
    db.add(s)
    db.commit()
    return _session_out(s)


@router.get("/api/exam/{slug}/questions/{session_id}", response_model=list[schemas.QuestionOut])
def get_questions(slug: str, session_id: int, db: Session = Depends(get_db)):
    e = _get_exam(slug, db)
    s = db.get(models.ExamSession, session_id)
    if not s or s.exam_id != e.id:
        raise HTTPException(404, "Sessiya topilmadi")
    if s.status != "active":
        raise HTTPException(400, "Sessiya yakunlangan")
    # To'g'ri javoblar YUBORILMAYDI
    return [schemas.QuestionOut(id=q.id, order_num=q.order_num, text=q.text, points=q.points,
                                 options=[schemas.OptionOut(id=o.id, key=o.key, text=o.text)
                                          for o in q.options]) for q in e.questions]


@router.post("/api/exam/{slug}/answers/{session_id}")
def save_answers(slug: str, session_id: int, body: schemas.AnswersBatch, db: Session = Depends(get_db)):
    e = _get_exam(slug, db)
    s = db.get(models.ExamSession, session_id)
    if not s or s.exam_id != e.id:
        raise HTTPException(404)
    if s.status != "active":
        raise HTTPException(400, "Sessiya yakunlangan")
    for a in body.answers:
        existing = db.scalar(select(models.Answer).where(
            models.Answer.session_id == session_id,
            models.Answer.question_id == a.question_id))
        if existing:
            existing.option_id = a.option_id
        else:
            db.add(models.Answer(session_id=session_id, question_id=a.question_id,
                                  option_id=a.option_id))
    db.commit()
    return {"saved": len(body.answers)}


@router.post("/api/exam/{slug}/events/{session_id}")
def save_events(slug: str, session_id: int, body: schemas.EventsBatch, db: Session = Depends(get_db)):
    e = _get_exam(slug, db)
    s = db.get(models.ExamSession, session_id)
    if not s or s.exam_id != e.id:
        raise HTTPException(404)
    now = _utc()
    started = s.started_at if s.started_at.tzinfo else s.started_at.replace(tzinfo=timezone.utc)
    for ev in body.events:
        t = ev.get("t") or max(0.0, (now - started).total_seconds())
        db.add(models.ProctoringEvent(session_id=session_id, t=round(t, 1),
                                       type=ev["type"], conf=ev.get("conf", 1.0)))
    db.flush()
    # Risk score yangilash
    all_ev = [{"t": ev.t, "type": ev.type, "conf": ev.conf, "fp": ev.fp} for ev in s.events]
    s.risk_score = compute_risk(all_ev).total
    db.commit()
    return {"saved": len(body.events)}


@router.post("/api/exam/{slug}/finish/{session_id}", response_model=schemas.SessionOut)
def student_finish(slug: str, session_id: int, db: Session = Depends(get_db)):
    e = _get_exam(slug, db)
    s = db.get(models.ExamSession, session_id)
    if not s or s.exam_id != e.id:
        raise HTTPException(404)
    if s.status == "finished":
        return _session_out(s)
    s.status = "finished"
    s.finished_at = _utc()
    sc, tot = _compute_score(s)
    s.score, s.total_points = sc, tot
    db.commit()
    return _session_out(s)


@router.get("/api/exam/{slug}/result/{session_id}")
def get_result(slug: str, session_id: int, db: Session = Depends(get_db)):
    e = _get_exam(slug, db)
    s = db.get(models.ExamSession, session_id)
    if not s or s.exam_id != e.id:
        raise HTTPException(404)
    if s.status != "finished":
        return {"status": "active"}
    pct = round(s.score / s.total_points * 100, 1) if s.score is not None and s.total_points else None
    return {"status": "finished", "score": s.score, "total": s.total_points, "pct": pct,
            "student_name": s.student_name, "student_group": s.student_group, "exam_title": e.title}
