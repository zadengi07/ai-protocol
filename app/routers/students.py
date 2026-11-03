from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .. import models, schemas
from ..db import get_db
from ..services import student_stats

router = APIRouter(prefix="/students", tags=["students"])


def _out(db: Session, s: models.Student) -> schemas.StudentOut:
    n, risk, last_id = student_stats(db, s.id)
    return schemas.StudentOut(id=s.id, name=s.name, group=s.group, email=s.email, exams=n, risk=risk, last_session_id=last_id)


@router.get("", response_model=list[schemas.StudentOut], summary="Talabalar ro'yxati")
def list_students(group: str | None = None, q: str | None = None, db: Session = Depends(get_db)):
    stmt = select(models.Student).order_by(models.Student.id)
    if group:
        stmt = stmt.where(models.Student.group == group)
    if q:
        stmt = stmt.where(models.Student.name.ilike(f"%{q}%") | models.Student.email.ilike(f"%{q}%"))
    return [_out(db, s) for s in db.scalars(stmt)]


@router.post("", response_model=schemas.StudentOut, status_code=201, summary="Talaba qo'shish")
def create_student(body: schemas.StudentIn, db: Session = Depends(get_db)):
    s = models.Student(**body.model_dump())
    db.add(s)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, "Bu email allaqachon mavjud")
    return _out(db, s)
