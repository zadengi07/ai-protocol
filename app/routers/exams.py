from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .. import models, schemas
from ..db import get_db

router = APIRouter(prefix="/exams", tags=["exams"])


def _out(db: Session, e: models.Exam) -> schemas.ExamOut:
    n = db.scalar(select(func.count()).select_from(models.Student).where(models.Student.group == e.group)) or 0
    return schemas.ExamOut(id=e.id, title=e.title, group=e.group, date=e.date, minutes=e.minutes,
                           questions=e.questions, status=e.status, students=n)


@router.get("", response_model=list[schemas.ExamOut], summary="Imtihonlar ro'yxati")
def list_exams(status: str | None = None, group: str | None = None, db: Session = Depends(get_db)):
    q = select(models.Exam).order_by(models.Exam.date.desc(), models.Exam.id.desc())
    if status:
        q = q.where(models.Exam.status == status)
    if group:
        q = q.where(models.Exam.group == group)
    return [_out(db, e) for e in db.scalars(q)]


@router.post("", response_model=schemas.ExamOut, status_code=201, summary="Imtihon yaratish")
def create_exam(body: schemas.ExamIn, db: Session = Depends(get_db)):
    e = models.Exam(**body.model_dump())
    db.add(e)
    db.commit()
    return _out(db, e)
