from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import models, schemas
from ..db import get_db
from ..risk import RULES

router = APIRouter(prefix="/events", tags=["events"])


@router.get("/recent", response_model=list[schemas.RecentEvent], summary="Oxirgi hodisalar oqimi (monitoring)")
def recent(limit: int = Query(8, ge=1, le=50), status: str = Query("active", pattern="^(active|finished)$"),
           db: Session = Depends(get_db)):
    q = (select(models.Event).join(models.ExamSession).where(models.ExamSession.status == status)
         .order_by(models.Event.id.desc()).limit(limit))
    return [schemas.RecentEvent(id=e.id, session_id=e.session_id, student_name=e.session.student.name,
                                type=e.type, label=RULES[e.type]["label"], t=e.t) for e in db.scalars(q)]
