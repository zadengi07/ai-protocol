"""/api/kt — /exam-kt (talaba) va /teacher (ustoz).

Ma'lumot joylashuvi:
- Savollar: backend/data.json (shifrlangan). Tez ishlashi uchun xotirada keshlanadi,
  fayl o'zgarganda (mtime) avtomatik qayta o'qiladi.
- Qolgan hamma narsa (ustoz, guruhlar, imtihon holati, urinishlar, javoblar, baholar,
  ogohlantirishlar) — SQL baza (DATABASE_URL).
"""
import hashlib
import io
import json
import os
import random
import re
import threading
import uuid
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path

from cryptography.fernet import Fernet
from fastapi import APIRouter, Header, HTTPException
from fastapi.responses import Response
from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from pydantic import BaseModel, Field
from sqlalchemy import func, select

from ..db import SessionLocal
from ..models import KtAttempt, KtEvent, KtExam, KtSetting, KtTeacher
from ..proctor_risk import proctor_rows_bulk, proctor_summary, proctor_summary_from, proctor_timeline, proctor_timeline_from

router = APIRouter(prefix="/api/kt", tags=["kt"])
BASE = Path(__file__).resolve().parents[2]
DATA_FILE = BASE / "data.json"
KEY_FILE = BASE / ".kt_key"
LOG_FILE = BASE / "logs" / "imtihon.log"
_lock = threading.RLock()
_qcache: dict = {"mtime": None, "data": []}

DEFAULT_GROUPS = [f"25-{n}" for n in range(79, 86)]
LEGACY_KEYS = ("teacher", "attempts", "groups", "exam", "submissions")
# Hodisalar: kalit, nom, ball, FP (noto'g'ri signal ehtimoli, %)
EVENTS = {
    "face_disappeared": {"label": "Yuz ko'rinmadi", "points": 25, "fp": 15},
    "multiple_faces": {"label": "Bir nechta yuz", "points": 35, "fp": 10},
    "looking_away": {"label": "Chetga qarash", "points": 10, "fp": 30},
    "looking_down": {"label": "Pastga qarash", "points": 15, "fp": 25},
    "phone_detected": {"label": "Telefon", "points": 30, "fp": 8},
    "book_detected": {"label": "Kitob", "points": 25, "fp": 12},
    "laptop_detected": {"label": "Noutbuk", "points": 20, "fp": 15},
    "tab_switch": {"label": "Tab almashdi", "points": 8, "fp": 20},
    "focus_lost": {"label": "Fokus yo'qoldi", "points": 8, "fp": 20},
    "fullscreen_exit": {"label": "To'liq ekrandan chiqdi", "points": 12, "fp": 10},
    "clipboard_use": {"label": "Nusxa olish / qo'yish", "points": 5, "fp": 10},
}
DEFAULT_EXAM = {"open": False, "minutes": 80, "started_at": None, "deadline": None}


# ───────── yordamchilar ─────────

def _now_dt() -> datetime:
    return datetime.now(timezone.utc)


def _aware(dt: datetime) -> datetime:
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _iso(dt: datetime | None) -> str | None:
    return _aware(dt).isoformat(timespec="seconds") if dt else None


def _log(msg: str) -> None:
    LOG_FILE.parent.mkdir(exist_ok=True)
    with open(LOG_FILE, "a", encoding="utf-8") as f:
        f.write(f"{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}  {msg}\n")


@contextmanager
def _db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def _fernet() -> Fernet:
    key = os.getenv("KT_DATA_KEY")
    if not key:
        if KEY_FILE.exists():
            key = KEY_FILE.read_text().strip()
        else:
            key = Fernet.generate_key().decode()
            KEY_FILE.write_text(key)
    return Fernet(key)


def _max_score(criteria: str) -> float:
    nums = re.findall(r"(\d+(?:[.,]\d+)?)\s*ball", criteria or "")
    return float(sum(float(n.replace(",", ".")) for n in nums)) or 10.0


# ───────── savollar (data.json) ─────────

def _load_raw() -> dict:
    raw = DATA_FILE.read_bytes()
    # Yangi format oddiy JSON. Eski shifrlangan fayllar uchun vaqtinchalik o'qish mosligi.
    if raw.lstrip()[:1] == b"{":
        return json.loads(raw)
    return json.loads(_fernet().decrypt(raw))


def _save_questions(qs: list[dict]) -> None:
    tmp = DATA_FILE.with_name("data.tmp")
    tmp.write_text(json.dumps({"questions": qs}, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, DATA_FILE)
    _qcache.update(mtime=None, data=qs)


def _questions() -> list[dict]:
    mtime = DATA_FILE.stat().st_mtime_ns
    if _qcache["mtime"] != mtime:
        qs = _load_raw()["questions"]
        for q in qs:
            q.setdefault("max", _max_score(q.get("baholash", "")))
        _qcache.update(mtime=mtime, data=qs)
    return _qcache["data"]


def _q(qid: str) -> dict:
    q = next((q for q in _questions() if q["id"] == qid), None)
    if not q:
        raise HTTPException(404, "Savol topilmadi")
    return q


def _public(ids: list[str]) -> list[dict]:
    return [{"id": i, "turi": _q(i)["turi"], "mavzu": _q(i)["mavzu"], "savol": _q(i)["savol"]} for i in ids]


# ───────── sozlamalar / ustoz (DB) ─────────

def _get_setting(db, key: str, default):
    row = db.get(KtSetting, key)
    return row.value if row else default


def _put_setting(db, key: str, value) -> None:
    row = db.get(KtSetting, key)
    if row:
        row.value = value
    else:
        db.add(KtSetting(key=key, value=value))


def _check(db, login: str | None, password: str | None) -> KtTeacher:
    t = db.scalar(select(KtTeacher).where(KtTeacher.login == login)) if login and password else None
    if not t or hashlib.sha256(password.encode()).hexdigest() != t.password_hash:
        raise HTTPException(401, "Login yoki parol noto'g'ri")
    return t


def bootstrap() -> None:
    """Ishga tushganda: eski data.json dagi ustoz/urinish/sozlamalarni bazaga bir marta ko'chiradi."""
    with _lock, _db() as db:
        migrated = db.get(KtSetting, "migrated") is not None
        raw = _load_raw() if DATA_FILE.exists() else {"questions": []}
        if migrated:
            # Guruhlar ro'yxatini 25-80 dan 25-85 gacha bir xilda saqlaymiz.
            current_groups = _get_setting(db, "groups", [])
            _put_setting(db, "groups", list(dict.fromkeys([*current_groups, *DEFAULT_GROUPS])))
            # Avvalgi bazadagi barcha urinishlarni bir marta legacy imtihonga bog'laymiz.
            legacy = db.scalar(select(KtExam).where(KtExam.slug == "legacy-exam"))
            if legacy is None:
                old_exam = _get_setting(db, "exam", DEFAULT_EXAM)
                legacy = KtExam(id=uuid.uuid4().hex, slug="legacy-exam", title="Eski imtihon",
                                minutes=int(old_exam.get("minutes", 80)), status="finished")
                db.add(legacy); db.flush()
            for attempt in db.scalars(select(KtAttempt).where(KtAttempt.exam_id.is_(None))).all():
                attempt.exam_id = legacy.id
            db.commit()
            return
        t = raw.get("teacher")
        if t and not db.scalar(select(KtTeacher.id).limit(1)):
            db.add(KtTeacher(login=t["login"], password_hash=t["password_hash"], name=t.get("name", t["login"])))
        for a in raw.get("attempts", []):
            row = KtAttempt(
                id=a["id"], student=a["student"], group=a["group"],
                started_at=datetime.fromisoformat(a["started_at"]), deadline=datetime.fromisoformat(a["deadline"]),
                submitted=a["submitted"],
                submitted_at=datetime.fromisoformat(a["submitted_at"]) if a.get("submitted_at") else None,
                reason=a.get("reason"), questions=a["questions"], answers=a.get("answers", {}),
                grades=a.get("grades", {}))
            row.events = [KtEvent(type=e["type"], at=datetime.fromisoformat(e["at"])) for e in a.get("events", [])]
            db.add(row)
        initial_groups = raw.get("groups", DEFAULT_GROUPS)
        _put_setting(db, "groups", list(dict.fromkeys([*initial_groups, *DEFAULT_GROUPS])))
        legacy = db.scalar(select(KtExam).where(KtExam.slug == "legacy-exam"))
        old_exam = raw.get("exam", DEFAULT_EXAM)
        if legacy is None:
            legacy = KtExam(id=uuid.uuid4().hex, slug="legacy-exam", title="Eski imtihon",
                            minutes=int(old_exam.get("minutes", 80)),
                            status="active" if old_exam.get("open") else "finished",
                            started_at=datetime.fromisoformat(old_exam["started_at"]) if old_exam.get("started_at") else None,
                            deadline=datetime.fromisoformat(old_exam["deadline"]) if old_exam.get("deadline") else None)
            db.add(legacy)
            db.flush()
        for attempt in db.scalars(select(KtAttempt).where(KtAttempt.exam_id.is_(None))).all():
            attempt.exam_id = legacy.id
        _put_setting(db, "exam", old_exam)  # eski frontend mosligi uchun saqlanadi
        _put_setting(db, "migrated", True)
        db.commit()


# ───────── urinishlar (DB) ─────────

def _risk(types: list[str]) -> dict:
    score = sum(EVENTS[t]["points"] for t in types if t in EVENTS)
    level = "past" if score < 30 else ("o'rta" if score < 60 else ("yuqori" if score < 100 else "kritik"))
    return {"score": score, "level": level}


def _attempt(db, aid: str, *, for_update: bool = False) -> KtAttempt:
    if for_update:
        a = db.scalar(select(KtAttempt).where(KtAttempt.id == aid).with_for_update())
    else:
        a = db.get(KtAttempt, aid)
    if not a:
        raise HTTPException(404, "Urinish topilmadi")
    return a


def _attempt_risk(db, a: KtAttempt, prows=None, types=None) -> dict:
    """Xavf balli: avval brauzer proktoring hodisalaridan, bo'lmasa eski kt_events dan.
    prows/types berilsa (bulk yuklangan), qo'shimcha so'rov yuborilmaydi."""
    ps = proctor_summary_from(prows) if prows is not None else proctor_summary(db, a.id)
    if ps["total"]:
        return {"score": ps["score"], "level": ps["level"], "source": "proctor"}
    return _risk(types if types is not None else [e.type for e in a.events])


def _preload(db, attempts) -> tuple[dict, dict]:
    """Urinishlar uchun proktoring qatorlari va kt_events ni 2 ta so'rovda yuklaydi (N+1 yo'q)."""
    ids = [a.id for a in attempts]
    prow = proctor_rows_bulk(db, ids)
    evs: dict = {}
    if ids:
        for e in db.scalars(select(KtEvent).where(KtEvent.attempt_id.in_(ids)).order_by(KtEvent.id)).all():
            evs.setdefault(e.attempt_id, []).append(e)
    return prow, evs


def _finalize(db, a: KtAttempt, reason: str) -> None:
    if a.submitted:
        return
    answers = dict(a.answers or {})
    grades = dict(a.grades or {})
    for qid in a.questions:
        txt = (answers.get(qid) or "").strip()
        answers[qid] = txt
        if not txt and qid not in grades:
            grades[qid] = 0
    a.answers, a.grades = answers, grades
    a.submitted = True
    a.submitted_at = _now_dt()
    a.reason = reason
    answered = sum(1 for qid in a.questions if answers.get(qid))
    _log(f"TOPSHIRDI   {a.student} ({a.group}) | sabab: {reason} | javob: {answered}/5")


def _sweep(db) -> bool:
    """Vaqti tugagan urinishlarni avtomatik topshiradi. O'zgarish bo'lsa True."""
    changed = False
    now = _now_dt()
    # Faqat muddati tugagan urinishlarni indeks orqali olamiz.
    expired = db.scalars(
        select(KtAttempt).where(
            KtAttempt.submitted.is_(False),
            KtAttempt.deadline <= now,
        ).with_for_update(skip_locked=True)
    ).all()
    for a in expired:
        _finalize(db, a, "vaqt tugadi")
        changed = True
    return changed


def _attempt_view(db, a: KtAttempt) -> dict:
    return {"attempt_id": a.id, "questions": _public(a.questions), "answers": a.answers or {},
            "deadline": _iso(a.deadline), "now": _iso(_now_dt()), "submitted": a.submitted,
            "reason": a.reason, "risk": _attempt_risk(db, a)}


class StartIn(BaseModel):
    student: str
    group: str
    exam_slug: str | None = None


class AnswersIn(BaseModel):
    attempt_id: str
    answers: dict[str, str]


class EventIn(BaseModel):
    attempt_id: str
    type: str


class GradeIn(BaseModel):
    attempt_id: str
    qid: str
    score: float


class Login(BaseModel):
    login: str
    password: str


class Toggle(BaseModel):
    faol: bool


class ExamIn(BaseModel):
    open: bool
    minutes: int | None = Field(default=None, strict=True, ge=1, le=300)


class CreateExamIn(BaseModel):
    title: str = Field(min_length=3, max_length=200)
    minutes: int = Field(default=80, strict=True, ge=1, le=300)
    groups: list[str] = Field(min_length=1)


# ───────── Talaba ─────────

@router.get("/meta")
def meta(exam_slug: str | None = None):
    with _db() as db:
        groups = _get_setting(db, "groups", DEFAULT_GROUPS)
        if exam_slug:
            exam = db.scalar(select(KtExam).where(KtExam.slug == exam_slug))
        else:
            active_exams = db.scalars(select(KtExam).where(KtExam.status == "active").order_by(KtExam.created_at.desc())).all()
            exam = active_exams[0] if len(active_exams) == 1 else None
        if exam_slug and exam is None:
            raise HTTPException(404, "Imtihon havolasi topilmadi")
    exam_groups = (exam.groups or groups) if exam else groups
    return {"groups": exam_groups, "exam_open": bool(exam and exam.status == "active"),
            "minutes": exam.minutes if exam else None, "deadline": _iso(exam.deadline) if exam and exam.deadline else None,
            "started_at": _iso(exam.started_at) if exam and exam.started_at else None,
            "exam": {"id": exam.id, "slug": exam.slug, "title": exam.title} if exam else None,
            "events": [{"key": k, **v} for k, v in EVENTS.items()]}


@router.post("/start")
def start(body: StartIn):
    name = " ".join(body.student.split())
    group = body.group.strip()
    with _lock, _db() as db:
        if len(name) < 3:
            raise HTTPException(400, "Ism-familiyangizni to'liq kiriting")
        if group not in _get_setting(db, "groups", DEFAULT_GROUPS):
            raise HTTPException(400, "Guruhni ro'yxatdan tanlang")
        if body.exam_slug:
            exam = db.scalar(select(KtExam).where(KtExam.slug == body.exam_slug))
        else:
            active_exams = db.scalars(select(KtExam).where(KtExam.status == "active").order_by(KtExam.created_at.desc())).all()
            exam = active_exams[0] if len(active_exams) == 1 else None
        if not exam or exam.status != "active":
            raise HTTPException(403, "Bu imtihon hozir faol emas")
        if group not in (exam.groups or _get_setting(db, "groups", DEFAULT_GROUPS)):
            raise HTTPException(400, "Bu imtihon sizning guruhingiz uchun ochilmagan")
        same = db.scalars(select(KtAttempt).where(KtAttempt.exam_id == exam.id,
            func.lower(KtAttempt.student) == name.lower())).all()
        if same:
            a = same[0]
            if a.group != group:
                raise HTTPException(409, f"Bu ism ushbu imtihonda {a.group} guruhi bilan ro'yxatdan o'tgan.")
            if a.submitted:
                raise HTTPException(409, "Siz bu imtihonni allaqachon topshirgansiz. Har bir imtihonga faqat bir marta kirish mumkin.")
            return _attempt_view(db, a)
        qs = _questions()
        th = [q for q in qs if q.get("faol", True) and q["turi"] == "NAZARIY"]
        pr = [q for q in qs if q.get("faol", True) and q["turi"] in ("AMALIY", "FIKRLASH")]
        if len(th) < 3 or len(pr) < 2:
            raise HTTPException(400, "Faol savollar yetarli emas")
        picked = [q["id"] for q in random.sample(th, 3) + random.sample(pr, 2)]
        now = _now_dt()
        deadline = _aware(exam.deadline) if exam.deadline else now + timedelta(minutes=exam.minutes)
        if now >= deadline:
            exam.status = "finished"
            db.commit()
            raise HTTPException(403, "Imtihon vaqti tugagan")
        a = KtAttempt(id=uuid.uuid4().hex, exam_id=exam.id, student=name, group=group,
                      started_at=now, deadline=deadline, submitted=False,
                      questions=picked, answers={}, grades={})
        db.add(a)
        db.commit()
        _log(f"BOSHLADI    {name} ({group}) | {exam.title}")
        return _attempt_view(db, a)


@router.get("/attempt/{aid}")
def attempt_status(aid: str):
    with _db() as db:
        a = _attempt(db, aid, for_update=True)
        # Status tekshiruvi faqat shu urinishni tekshiradi.
        if not a.submitted and _now_dt() >= _aware(a.deadline):
            _finalize(db, a, "vaqt tugadi")
            db.commit()
        return _attempt_view(db, a)


@router.post("/save")
def save(body: AnswersIn):
    with _db() as db:
        a = _attempt(db, body.attempt_id, for_update=True)
        if a.submitted:
            return {"ok": False, "submitted": True}
        if _now_dt() >= _aware(a.deadline):
            _finalize(db, a, "vaqt tugadi")
            db.commit()
            return {"ok": False, "submitted": True, "reason": "vaqt tugadi"}
        answers = dict(a.answers or {})
        for qid in a.questions:
            if qid in body.answers:
                answers[qid] = body.answers[qid][:4000]
        a.answers = answers
        db.commit()
    return {"ok": True}


@router.post("/submit")
def submit(body: AnswersIn):
    with _db() as db:
        a = _attempt(db, body.attempt_id, for_update=True)
        if not a.submitted and _now_dt() >= _aware(a.deadline):
            _finalize(db, a, "vaqt tugadi")
            db.commit()
            return {"ok": True, "submitted": True, "reason": "vaqt tugadi"}
        if not a.submitted:
            answers = dict(a.answers or {})
            for qid in a.questions:
                if qid in body.answers:
                    answers[qid] = body.answers[qid][:4000]
            a.answers = answers
            _finalize(db, a, "talaba topshirdi")
            db.commit()
    return {"ok": True}


@router.post("/event")
def event(body: EventIn):
    if body.type not in EVENTS:
        raise HTTPException(400, "Noma'lum hodisa")
    with _db() as db:
        a = _attempt(db, body.attempt_id, for_update=True)
        if a.submitted:
            return {"ok": True}
        if _now_dt() >= _aware(a.deadline):
            _finalize(db, a, "vaqt tugadi")
            db.commit()
            return {"ok": True, "submitted": True}
        db.add(KtEvent(attempt_id=a.id, type=body.type, at=_now_dt()))
        db.commit()
        student, group = a.student, a.group
    _log(f"OGOHLANTIRISH {student} ({group}) | {EVENTS[body.type]['label']}")
    return {"ok": True}


# ───────── Ustoz ─────────

@router.post("/teacher/login")
def teacher_login(body: Login):
    with _db() as db:
        t = _check(db, body.login, body.password)
        return {"ok": True, "name": t.name}


class PasswordIn(BaseModel):
    old_password: str = Field(min_length=1, max_length=200)
    new_password: str = Field(min_length=8, max_length=200)


@router.get("/teacher/me")
def teacher_me(x_teacher_login: str | None = Header(None), x_teacher_password: str | None = Header(None)):
    """Joriy ustoz profili (login va ism)."""
    with _db() as db:
        t = _check(db, x_teacher_login, x_teacher_password)
        return {"login": t.login, "name": t.name}


@router.post("/teacher/password")
def teacher_change_password(body: PasswordIn, x_teacher_login: str | None = Header(None), x_teacher_password: str | None = Header(None)):
    """Ustoz parolini o'zgartirish. Joriy parol tekshiriladi, yangi parol eskisidan farq qilishi kerak."""
    with _db() as db:
        t = _check(db, x_teacher_login, x_teacher_password)
        if hashlib.sha256(body.old_password.encode()).hexdigest() != t.password_hash:
            raise HTTPException(400, "Joriy parol noto'g'ri")
        if body.new_password == body.old_password:
            raise HTTPException(400, "Yangi parol eskisidan farq qilishi kerak")
        t.password_hash = hashlib.sha256(body.new_password.encode()).hexdigest()
        db.commit()
        return {"ok": True}


def _exam_scope(db, exam_id):
    """Imtihon va guruhlar ro'yxati (dashboard bilan bir xil tanlov mantig'i)."""
    groups = _get_setting(db, "groups", DEFAULT_GROUPS)
    exams = db.scalars(select(KtExam).order_by(KtExam.created_at.desc())).all()
    exam = db.get(KtExam, exam_id) if exam_id else next((e for e in exams if e.status == "active"), exams[0] if exams else None)
    stmt = select(KtAttempt).order_by(KtAttempt.started_at)
    if exam:
        stmt = stmt.where(KtAttempt.exam_id == exam.id)
        groups = exam.groups or groups
    return exam, exams, groups, stmt


def _exam_payload(exam, groups):
    if exam:
        return {"id": exam.id, "slug": exam.slug, "title": exam.title, "minutes": exam.minutes, "groups": exam.groups or groups,
                "status": exam.status, "open": exam.status == "active", "deadline": _iso(exam.deadline) if exam.deadline else None}
    return {"open": False, "minutes": 80, "groups": groups}


def _graded_complete(a, qmap) -> bool:
    answered = [qid for qid in a.questions if (a.answers or {}).get(qid)]
    return bool(answered) and all((a.grades or {}).get(qid) is not None for qid in answered)


@router.get("/teacher/summary")
def teacher_summary(exam_id: str | None = None, x_teacher_login: str | None = Header(None), x_teacher_password: str | None = Header(None)):
    """Imtihonlar sahifasi uchun faqat sonlar: talabalar soni, topshirganlar, yuqori xavf, guruhlar kesimi."""
    with _db() as db:
        t = _check(db, x_teacher_login, x_teacher_password)
        if _sweep(db):
            db.commit()
        exam, exams, groups, stmt = _exam_scope(db, exam_id)
        attempts = db.scalars(stmt).all()
        prow, evs = _preload(db, attempts)
        qmap = {q["id"]: q for q in _questions()}
        high = 0
        stats: dict[str, dict] = {g: {"group": g, "total": 0, "submitted": 0, "graded_complete": 0} for g in groups}
        for a in attempts:
            st = stats.setdefault(a.group, {"group": a.group, "total": 0, "submitted": 0, "graded_complete": 0})
            st["total"] += 1
            if a.submitted:
                st["submitted"] += 1
                if _graded_complete(a, qmap):
                    st["graded_complete"] += 1
            risk = _attempt_risk(db, a, prow.get(a.id, []), [e.type for e in evs.get(a.id, [])])
            if risk["score"] >= 60:
                high += 1
        submitted = sum(1 for a in attempts if a.submitted)
        return {
            "teacher": t.name, "groups": groups, "exam": _exam_payload(exam, groups),
            "exams": [{"id": e.id, "slug": e.slug, "title": e.title, "minutes": e.minutes, "status": e.status, "created_at": _iso(e.created_at)} for e in exams],
            "counts": {"total": len(attempts), "submitted": submitted, "active": len(attempts) - submitted, "high_risk": high},
            "group_stats": [stats[g] for g in sorted(stats) if g in groups or stats[g]["total"]],
        }


@router.get("/teacher/group")
def teacher_group(group: str, exam_id: str | None = None, x_teacher_login: str | None = Header(None), x_teacher_password: str | None = Header(None)):
    """Bitta guruh talabalari (faqat ro'yxat ma'lumoti: ism, holat, ball, xavf)."""
    with _db() as db:
        _check(db, x_teacher_login, x_teacher_password)
        exam, _, _, stmt = _exam_scope(db, exam_id)
        attempts = [a for a in db.scalars(stmt.where(KtAttempt.group == group)).all()]
        prow, evs = _preload(db, attempts)
        qmap = {q["id"]: q for q in _questions()}
        rows = []
        for a in attempts:
            items = [qmap.get(qid) or _q(qid) for qid in a.questions]
            total_max = sum(q["max"] for q in items)
            total = sum((a.grades or {}).get(qid) or 0 for qid in a.questions)
            answered = sum(1 for qid in a.questions if (a.answers or {}).get(qid))
            graded = sum(1 for qid in a.questions if (a.answers or {}).get(qid) and (a.grades or {}).get(qid) is not None)
            rows.append({
                "id": a.id, "student": a.student, "group": a.group, "submitted": a.submitted,
                "submitted_at": _iso(a.submitted_at), "answered": answered, "graded": graded,
                "item_count": len(a.questions), "total": total, "total_max": total_max,
                "risk": _attempt_risk(db, a, prow.get(a.id, []), [e.type for e in evs.get(a.id, [])]),
            })
        return {"group": group, "students": rows}


@router.get("/teacher/attempt/{attempt_id}")
def teacher_attempt(attempt_id: str, x_teacher_login: str | None = Header(None), x_teacher_password: str | None = Header(None)):
    """Bitta talabaning to'liq ma'lumoti: javoblar, baholar, hodisalar va proktoring jadvali."""
    with _db() as db:
        _check(db, x_teacher_login, x_teacher_password)
        a = db.get(KtAttempt, attempt_id)
        if not a:
            raise HTTPException(404, "Urinish topilmadi")
        prow, evs = _preload(db, [a])
        qmap = {q["id"]: q for q in _questions()}
        my_events = evs.get(a.id, [])
        items = []
        for qid in a.questions:
            q = qmap.get(qid) or _q(qid)
            txt = (a.answers or {}).get(qid, "")
            items.append({"qid": qid, "turi": q["turi"], "mavzu": q["mavzu"], "savol": q["savol"],
                          "answered": bool(txt), "answer": txt, "criteria": q["baholash"],
                          "score": (a.grades or {}).get(qid), "max": q["max"]})
        return {
            "id": a.id, "student": a.student, "group": a.group, "submitted": a.submitted,
            "submitted_at": _iso(a.submitted_at), "reason": a.reason, "items": items,
            "graded": sum(1 for i in items if i["answered"] and i["score"] is not None),
            "answered": sum(1 for i in items if i["answered"]),
            "total": sum(i["score"] or 0 for i in items), "total_max": sum(i["max"] for i in items),
            "risk": _attempt_risk(db, a, prow.get(a.id, []), [e.type for e in my_events]),
            "events": [{"type": e.type, "label": EVENTS.get(e.type, {}).get("label", e.type),
                        "points": EVENTS.get(e.type, {}).get("points", 0),
                        "fp": EVENTS.get(e.type, {}).get("fp", 0), "at": _iso(e.at)} for e in my_events],
            "proctor_events": proctor_timeline_from(prow.get(a.id, [])),
        }


@router.get("/teacher/dashboard")
def dashboard(exam_id: str | None = None, light: bool = False, x_teacher_login: str | None = Header(None), x_teacher_password: str | None = Header(None)):
    with _db() as db:
        t = _check(db, x_teacher_login, x_teacher_password)
        if _sweep(db):
            db.commit()
        groups = _get_setting(db, "groups", DEFAULT_GROUPS)
        exams = db.scalars(select(KtExam).order_by(KtExam.created_at.desc())).all()
        exam = db.get(KtExam, exam_id) if exam_id else next((e for e in exams if e.status == "active"), exams[0] if exams else None)
        students = []
        stmt = select(KtAttempt).order_by(KtAttempt.started_at)
        if exam:
            stmt = stmt.where(KtAttempt.exam_id == exam.id)
        attempts = db.scalars(stmt).all()
        prow, evs = _preload(db, attempts)
        qmap = {q["id"]: q for q in _questions()}
        for a in attempts:
            items = []
            my_events = evs.get(a.id, [])
            my_rows = prow.get(a.id, [])
            for qid in a.questions:
                q = qmap.get(qid) or _q(qid)
                txt = (a.answers or {}).get(qid, "")
                items.append({"qid": qid, "turi": q["turi"], "mavzu": q["mavzu"], "savol": q["savol"],
                              "answered": bool(txt), "answer": txt, "criteria": q["baholash"],
                              "score": (a.grades or {}).get(qid), "max": q["max"]})
            graded = sum(1 for i in items if i["answered"] and i["score"] is not None)
            row = {
                "id": a.id, "student": a.student, "group": a.group, "submitted": a.submitted,
                "submitted_at": _iso(a.submitted_at), "reason": a.reason,
                "graded": graded, "answered": sum(1 for i in items if i["answered"]),
                "item_count": len(items),
                "total": sum(i["score"] or 0 for i in items), "total_max": sum(i["max"] for i in items),
                "risk": _attempt_risk(db, a, my_rows, [e.type for e in my_events]),
            }
            if not light:
                # To'liq rejim: javoblar, hodisalar va proktoring jadvali (baholash sahifasi uchun)
                row["items"] = items
                row["events"] = [{"type": e.type, "label": EVENTS.get(e.type, {}).get("label", e.type),
                                  "points": EVENTS.get(e.type, {}).get("points", 0),
                                  "fp": EVENTS.get(e.type, {}).get("fp", 0), "at": _iso(e.at)} for e in my_events]
                row["proctor_events"] = proctor_timeline_from(my_rows)
            students.append(row)
        exam_data = ({"id": exam.id, "slug": exam.slug, "title": exam.title, "minutes": exam.minutes, "groups": exam.groups or groups, "status": exam.status, "open": exam.status == "active", "deadline": _iso(exam.deadline) if exam.deadline else None} if exam else {"open": False, "minutes": 80, "groups": groups})
        groups = exam.groups or groups if exam else groups
        exams_data = [{"id": e.id, "slug": e.slug, "title": e.title, "minutes": e.minutes, "status": e.status, "created_at": _iso(e.created_at)} for e in exams]
        result = {"teacher": t.name, "groups": groups, "exam": exam_data, "exams": exams_data,
                  "students": students}
        if not light:
            result["questions"] = _questions()
        return result


@router.get("/teacher/exams")
def list_exams(x_teacher_login: str | None = Header(None), x_teacher_password: str | None = Header(None)):
    with _db() as db:
        _check(db, x_teacher_login, x_teacher_password)
        rows = db.scalars(select(KtExam).order_by(KtExam.created_at.desc())).all()
        return [{"id": e.id, "slug": e.slug, "title": e.title, "minutes": e.minutes,
                 "groups": e.groups or DEFAULT_GROUPS, "status": e.status, "url": f"/exam-kt-link?exam={e.slug}"} for e in rows]


@router.post("/teacher/exams")
def create_exam(body: CreateExamIn, x_teacher_login: str | None = Header(None), x_teacher_password: str | None = Header(None)):
    with _lock, _db() as db:
        _check(db, x_teacher_login, x_teacher_password)
        base = re.sub(r"[^a-z0-9]+", "-", body.title.lower()).strip("-")[:55] or "imtihon"
        slug = base
        n = 2
        while db.scalar(select(KtExam.id).where(KtExam.slug == slug)):
            slug = f"{base}-{n}"; n += 1
        allowed = set(_get_setting(db, "groups", DEFAULT_GROUPS))
        chosen = list(dict.fromkeys(g for g in body.groups if g in allowed))
        if not chosen:
            raise HTTPException(400, "Kamida bitta guruhni tanlang")
        row = KtExam(id=uuid.uuid4().hex, slug=slug, title=body.title.strip(), minutes=body.minutes, groups=chosen, status="draft")
        db.add(row); db.commit()
        return {"id": row.id, "slug": row.slug, "title": row.title, "minutes": row.minutes,
                "groups": row.groups, "status": row.status, "url": f"/exam-kt-link?exam={row.slug}"}


@router.delete("/teacher/exams/{exam_id}")
def delete_exam(exam_id: str, x_teacher_login: str | None = Header(None), x_teacher_password: str | None = Header(None)):
    with _lock, _db() as db:
        _check(db, x_teacher_login, x_teacher_password)
        row = db.get(KtExam, exam_id)
        if not row:
            raise HTTPException(404, "Imtihon topilmadi")
        if row.status == "active":
            raise HTTPException(409, "Avval faol imtihonni yoping")
        attempts = db.scalars(select(KtAttempt).where(KtAttempt.exam_id == exam_id)).all()
        for attempt in attempts:
            db.delete(attempt)  # bog'liq hodisalar cascade orqali o'chadi
        db.delete(row)
        db.commit()
        return {"ok": True, "deleted_attempts": len(attempts)}


@router.post("/teacher/exams/{exam_id}/activate")
def activate_exam(exam_id: str, minutes: int | None = None, x_teacher_login: str | None = Header(None), x_teacher_password: str | None = Header(None)):
    with _lock, _db() as db:
        _check(db, x_teacher_login, x_teacher_password)
        row = db.get(KtExam, exam_id)
        if not row: raise HTTPException(404, "Imtihon topilmadi")
        if row.status == "finished": raise HTTPException(409, "Yakunlangan imtihonni qayta ochib bo'lmaydi")
        if minutes is not None:
            if not 1 <= minutes <= 300: raise HTTPException(400, "Davomiylik 1–300 daqiqa bo'lishi kerak")
            row.minutes = minutes
        now = _now_dt()
        row.status = "active"; row.started_at = now; row.deadline = now + timedelta(minutes=row.minutes)
        db.commit()
        return {"ok": True, "exam": {"id": row.id, "slug": row.slug, "title": row.title, "deadline": _iso(row.deadline)}}


@router.post("/teacher/exams/{exam_id}/finish")
def finish_exam(exam_id: str, x_teacher_login: str | None = Header(None), x_teacher_password: str | None = Header(None)):
    with _lock, _db() as db:
        _check(db, x_teacher_login, x_teacher_password)
        row = db.get(KtExam, exam_id)
        if not row: raise HTTPException(404, "Imtihon topilmadi")
        for a in db.scalars(select(KtAttempt).where(KtAttempt.exam_id == exam_id, KtAttempt.submitted.is_(False))).all():
            _finalize(db, a, "ustoz imtihonni yopdi")
        row.status = "finished"; db.commit()
        return {"ok": True}


@router.post("/teacher/exam")
def set_exam(body: ExamIn, x_teacher_login: str | None = Header(None), x_teacher_password: str | None = Header(None)):
    with _lock, _db() as db:
        _check(db, x_teacher_login, x_teacher_password)
        exam = dict(_get_setting(db, "exam", DEFAULT_EXAM))
        closed = 0
        if body.open:
            if body.minutes is None or isinstance(body.minutes, bool) or not 1 <= body.minutes <= 300:
                raise HTTPException(400, "Davomiylik 1 dan 300 daqiqagacha butun son bo'lishi kerak")
            if exam.get("open"):
                raise HTTPException(409, "Imtihon allaqachon ochilgan")
            started = _now_dt()
            deadline = started + timedelta(minutes=body.minutes)
            exam.update({"open": True, "minutes": body.minutes,
                         "started_at": _iso(started), "deadline": _iso(deadline)})
            _log(f"IMTIHON OCHILDI — {body.minutes} daqiqa")
        else:
            exam.update({"open": False})
            for a in db.scalars(
                select(KtAttempt).where(KtAttempt.submitted.is_(False)).with_for_update()
            ).all():
                _finalize(db, a, "ustoz imtihonni yopdi")
                closed += 1
            _log(f"IMTIHON YOPILDI — {closed} ta talaba avtomatik topshirildi")
        _put_setting(db, "exam", exam)
        db.commit()
    return {"ok": True, "auto_submitted": closed, "exam": exam}


@router.post("/teacher/grade")
def grade(body: GradeIn, x_teacher_login: str | None = Header(None), x_teacher_password: str | None = Header(None)):
    with _lock, _db() as db:
        _check(db, x_teacher_login, x_teacher_password)
        a = _attempt(db, body.attempt_id)
        q = _q(body.qid)
        if body.qid not in a.questions:
            raise HTTPException(400, "Bu savol bu talabaga tegishli emas")
        if not 0 <= body.score <= q["max"]:
            raise HTTPException(400, f"Ball 0 dan {q['max']} gacha bo'lishi kerak")
        grades = dict(a.grades or {})
        grades[body.qid] = round(body.score, 2)
        a.grades = grades
        db.commit()
        student, group = a.student, a.group
    _log(f"BAHO        {student} ({group}) | {body.qid} | {round(body.score, 2)}/{q['max']}")
    return {"ok": True}


@router.get("/teacher/export")
def export(group: str | None = None, exam_id: str | None = None, x_teacher_login: str | None = Header(None), x_teacher_password: str | None = Header(None)):
    g = (group or "").strip()
    with _db() as db:
        _check(db, x_teacher_login, x_teacher_password)
        all_groups = _get_setting(db, "groups", DEFAULT_GROUPS)
        export_stmt = select(KtAttempt).where(KtAttempt.submitted.is_(True))
        selected_groups = all_groups
        if exam_id:
            export_stmt = export_stmt.where(KtAttempt.exam_id == exam_id)
            selected_exam = db.get(KtExam, exam_id)
            if selected_exam:
                selected_groups = selected_exam.groups or all_groups
        done = db.scalars(export_stmt).all()
        prow, evs = _preload(db, done)
        qmap = {q["id"]: q for q in _questions()}
        # Har guruh: talabalar (ism bo'yicha), har talaba uchun savol/javob/ball bloki
        data_by_group: dict[str, list[dict]] = {}
        for grp in ([g] if g else sorted(selected_groups)):
            members = sorted((a for a in done if a.group == grp), key=lambda a: a.student.lower())
            data_by_group[grp] = [{
                "student": a.student,
                "total": sum((a.grades or {}).get(qid, 0) or 0 for qid in a.questions),
                "risk": _attempt_risk(db, a, prow.get(a.id, []), [e.type for e in evs.get(a.id, [])])["score"],
                "items": [{
                    "savol": (qmap.get(qid) or {}).get("savol", qid),
                    "javob": (a.answers or {}).get(qid, "") or "",
                    "ball": (a.grades or {}).get(qid),
                    "max": (qmap.get(qid) or {}).get("max", 0),
                } for qid in a.questions],
            } for a in members]

    wb = Workbook()
    wb.remove(wb.active)
    head_fill = PatternFill("solid", fgColor="E7E5E4")
    name_fill = PatternFill("solid", fgColor="D1FAE5")
    bold = Font(bold=True)
    wrap = Alignment(wrap_text=True, vertical="top")

    for grp, students in data_by_group.items():
        ws = wb.create_sheet(title=grp[:31])
        ws.append(["№", "Savol", "Talaba javobi", "Ball", "Xavf bali"])
        for c in ws[1]:
            c.fill = head_fill
            c.font = bold
            c.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
        ws.freeze_panes = "A2"
        for s in students:
            ws.append([])
            ws.append([s["student"], grp])
            top = ws.max_row
            for col in range(1, 5):
                ws.cell(row=top, column=col).font = bold
                ws.cell(row=top, column=col).fill = name_fill
            first = ws.max_row + 1
            for n, it in enumerate(s["items"], 1):
                ws.append([n, it["savol"], it["javob"] or "(javob berilmagan)",
                           it["ball"] if it["ball"] is not None else None])
                row = ws.max_row
                ws.cell(row=row, column=2).alignment = wrap
                ws.cell(row=row, column=3).alignment = wrap
                ws.cell(row=row, column=4).number_format = "0.0"
            last = ws.max_row
            ws.append(["", "Jami ball", "", f"=SUM(D{first}:D{last})" if s["items"] else 0, s["risk"]])
            jami = ws.max_row
            for col in range(1, 6):
                ws.cell(row=jami, column=col).font = bold
            ws.cell(row=jami, column=4).number_format = "0.0"
        for col, w in zip("ABCDE", (8, 55, 60, 12, 12)):
            ws.column_dimensions[col].width = w

    if not wb.sheetnames:
        wb.create_sheet(title="Bo'sh")

    buf = io.BytesIO()
    wb.save(buf)
    name = f"baholar_{g or 'barcha'}.xlsx"
    return Response(buf.getvalue(),
                    media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    headers={"Content-Disposition": f"attachment; filename={name}"})


@router.patch("/teacher/questions/{qid}")
def toggle(qid: str, body: Toggle, x_teacher_login: str | None = Header(None), x_teacher_password: str | None = Header(None)):
    with _lock, _db() as db:
        _check(db, x_teacher_login, x_teacher_password)
        qs = _questions()
        _q(qid)["faol"] = body.faol
        _save_questions(qs)
    return {"ok": True}