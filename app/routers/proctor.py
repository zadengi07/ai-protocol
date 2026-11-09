"""/api/proctor — brauzer proktoring hodisalarini qabul qilish va saqlash.

Mavjud mexanizmlar qayta ishlatiladi:
- Talaba urinishi `attempt_id` (uuid4 hex, /api/exam/start qaytaradi) orqali tanilib, boshqa endpointlar
  (/api/exam/save, /event) bilan bir xil tarzda ishlaydi. student_id/group/exam_id ni mijozdan EMAS, bazadagi
  urinishdan olamiz — boshqa talaba nomidan yozib bo'lmaydi.
- Hodisalarni o'qish faqat ustoz (exam._check — X-Teacher-Login/Password) uchun.
Imtihon jarayoniga ta'sir qilmaslik uchun: satr qulfi (FOR UPDATE) yo'q, tranzaksiya qisqa, xatolik 5xx qaytaradi
(klient jim e'tiborsiz qoldiradi va keyinroq qayta yuboradi).
"""
import json
from datetime import datetime, timedelta, timezone
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel, Field, ValidationError, field_validator
from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from ..db import engine, get_db
from ..models import KtAttempt
from ..proctor_models import KtProctorEvent
from .exam import _check

router = APIRouter(prefix="/api/proctor", tags=["proctor"])

EVENT_TYPES = {
    # sahifa holati
    "monitor_started", "window_blur", "window_focus", "tab_hidden", "tab_visible", "page_hide", "page_show",
    "before_unload", "page_reload", "multi_tab_detected", "fullscreen_enter", "fullscreen_exit",
    # nusxa / matn
    "copy", "cut", "paste", "contextmenu", "selectstart", "dragstart",
    "shortcut_select_all", "shortcut_copy", "shortcut_cut", "shortcut_paste",
    "shortcut_ctrl_insert", "shortcut_shift_insert", "shortcut_shift_delete",
    # DevTools / brauzer vositalari
    "devtools_shortcut", "view_source_shortcut", "save_shortcut", "print_shortcut", "screenshot_key",
    "devtools_suspected",
    # qurilma / tarmoq
    "orientation_change", "window_resize", "print_attempt", "network_offline", "network_online",
    "capability_unsupported",
}
SOURCES = ("detected", "inferred", "blocked_attempt", "unsupported")
SEVERITIES = ("info", "low", "medium", "high")
MAX_BATCH = 100
MAX_PER_ATTEMPT = 5000      # suiste'molga qarshi chegara
MAX_DETAILS_BYTES = 2000


class ProctorEventIn(BaseModel):
    event_id: UUID
    attempt_id: str = Field(min_length=8, max_length=64)
    event_type: str
    event_time: datetime
    exam_id: str | None = Field(default=None, max_length=64)       # ma'lumot uchun; server o'zinikini yozadi
    student_id: str | None = Field(default=None, max_length=200)   # —"—
    group_name: str | None = Field(default=None, max_length=20)    # —"—
    page_url: str | None = Field(default=None, max_length=500)
    browser_name: str | None = Field(default=None, max_length=60)
    operating_system: str | None = Field(default=None, max_length=60)
    device_type: str | None = Field(default=None, max_length=20)
    event_details: dict = Field(default_factory=dict)
    event_source: Literal["detected", "inferred", "blocked_attempt", "unsupported"]
    severity: Literal["info", "low", "medium", "high"] = "info"

    @field_validator("event_type")
    @classmethod
    def _type_known(cls, v: str) -> str:
        if v not in EVENT_TYPES:
            raise ValueError("noma'lum event_type")
        return v

    @field_validator("event_details")
    @classmethod
    def _details_small(cls, v: dict) -> dict:
        if len(json.dumps(v, ensure_ascii=False, default=str)) > MAX_DETAILS_BYTES:
            raise ValueError("event_details juda katta")
        return v


class SingleIn(ProctorEventIn):
    pass


class BatchIn(BaseModel):
    attempt_id: str = Field(min_length=8, max_length=64)
    events: list[dict] = Field(max_length=MAX_BATCH)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _aware(dt: datetime) -> datetime:
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _totals(db: Session, attempt_id: str) -> dict:
    rows = db.execute(
        select(KtProctorEvent.event_type, func.count()).where(KtProctorEvent.attempt_id == attempt_id)
        .group_by(KtProctorEvent.event_type)
    ).all()
    by_type = {t: n for t, n in rows}
    return {"total": sum(by_type.values()), "by_type": by_type}


def _insert_ignore(db: Session, rows: list[dict]) -> None:
    """Bir vaqtda kelgan takroriy UUID lar xato bermasligi uchun ON CONFLICT DO NOTHING."""
    if not rows:
        return
    name = engine.dialect.name
    for i in range(0, len(rows), 50):   # 50*15 ustun < 999: eski SQLite o'zgaruvchi limitiga ham sig'adi
        chunk = rows[i:i + 50]
        if name == "postgresql":
            db.execute(pg_insert(KtProctorEvent).values(chunk).on_conflict_do_nothing(index_elements=["event_id"]))
        elif name == "sqlite":
            db.execute(sqlite_insert(KtProctorEvent).values(chunk).on_conflict_do_nothing(index_elements=["event_id"]))
        else:  # boshqa dialektlar uchun oddiy yo'l
            db.add_all(KtProctorEvent(**r) for r in chunk)


def _store(db: Session, attempt_id: str, raw_events: list[dict]) -> dict:
    a = db.get(KtAttempt, attempt_id)
    if not a:
        raise HTTPException(404, "Urinish topilmadi")
    now = _now()
    rejected: list[dict] = []
    valid: dict[str, ProctorEventIn] = {}
    for raw in raw_events:
        eid = str(raw.get("event_id", "")) if isinstance(raw, dict) else ""
        try:
            ev = ProctorEventIn.model_validate(raw)
        except (ValidationError, TypeError):
            rejected.append({"event_id": eid or None, "reason": "validation"})
            continue
        if ev.attempt_id != attempt_id:
            rejected.append({"event_id": str(ev.event_id), "reason": "attempt_mismatch"})
            continue
        valid.setdefault(str(ev.event_id), ev)   # batch ichidagi takrorlar ham bir marta

    ids = list(valid)
    existing = set(db.scalars(select(KtProctorEvent.event_id).where(KtProctorEvent.event_id.in_(ids))).all()) if ids else set()
    fresh = [valid[i] for i in ids if i not in existing]
    room = max(0, MAX_PER_ATTEMPT - (db.scalar(select(func.count()).where(KtProctorEvent.attempt_id == attempt_id)) or 0))
    over = fresh[room:]
    fresh = fresh[:room]
    rejected += [{"event_id": str(e.event_id), "reason": "limit"} for e in over]

    rows = []
    for ev in fresh:
        t = _aware(ev.event_time)
        details = dict(ev.event_details)
        if abs(t - now) > timedelta(hours=24):       # soat noto'g'ri qurilma: vaqtni server vaqtiga tushiramiz
            details["_time_clamped"] = True
            t = now
        rows.append(dict(
            event_id=str(ev.event_id), attempt_id=a.id, exam_id=a.exam_id, student_id=a.student[:200],
            group_name=a.group, event_type=ev.event_type, event_time=t, received_at=now,
            page_url=ev.page_url, browser_name=ev.browser_name, operating_system=ev.operating_system,
            device_type=ev.device_type, event_details=details, event_source=ev.event_source, severity=ev.severity,
        ))
    _insert_ignore(db, rows)
    db.commit()
    return {"ok": True, "accepted": len(rows), "duplicates": len(existing),
            "rejected": rejected, "totals": _totals(db, attempt_id)}


def _guard(fn):
    try:
        return fn()
    except HTTPException:
        raise
    except SQLAlchemyError:
        raise HTTPException(503, "Hodisalarni saqlab bo'lmadi, keyinroq qayta uriniladi")


@router.post("/events")
def post_event(body: SingleIn, db: Session = Depends(get_db)):
    return _guard(lambda: _store(db, body.attempt_id, [body.model_dump(mode="json")]))


@router.post("/events/batch")
def post_batch(body: BatchIn, db: Session = Depends(get_db)):
    return _guard(lambda: _store(db, body.attempt_id, body.events))


@router.get("/events/{attempt_id}")
def get_events(attempt_id: str, limit: int = 500, offset: int = 0,
               x_teacher_login: str | None = Header(None), x_teacher_password: str | None = Header(None),
               db: Session = Depends(get_db)):
    """Faqat ustoz (mavjud exam._check). Talabalar hodisalarni o'qiy olmaydi."""
    _check(db, x_teacher_login, x_teacher_password)
    limit = max(1, min(limit, 1000))
    offset = max(0, offset)
    a = db.get(KtAttempt, attempt_id)
    if not a:
        raise HTTPException(404, "Urinish topilmadi")
    rows = db.scalars(select(KtProctorEvent).where(KtProctorEvent.attempt_id == attempt_id)
                      .order_by(KtProctorEvent.event_time, KtProctorEvent.event_id).limit(limit).offset(offset)).all()
    return {
        "attempt_id": a.id, "exam_id": a.exam_id, "student": a.student, "group": a.group,
        "totals": _totals(db, attempt_id),
        "events": [{
            "event_id": r.event_id, "event_type": r.event_type, "event_time": _aware(r.event_time).isoformat(),
            "received_at": _aware(r.received_at).isoformat(), "exam_id": r.exam_id, "attempt_id": r.attempt_id,
            "student_id": r.student_id, "group_name": r.group_name, "page_url": r.page_url,
            "browser_name": r.browser_name, "operating_system": r.operating_system, "device_type": r.device_type,
            "event_details": r.event_details, "event_source": r.event_source, "severity": r.severity,
        } for r in rows],
    }
