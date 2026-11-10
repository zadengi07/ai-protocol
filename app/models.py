from datetime import datetime, timezone
from typing import Any
from sqlalchemy import JSON, Boolean, DateTime, Float, ForeignKey, Index, Integer, String, text
from sqlalchemy.orm import Mapped, mapped_column, relationship
from .db import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


GROUPS = ["25-80", "25-81", "25-82", "25-83", "25-85"]


# ══════════════ Asosiy platforma (/api/exam) — savollar data.json da, qolgani shu yerda ══════════════
# Jadval nomlari (kt_*) ataylab o'zgartirilmagan: productiondagi Neon bazasida
# migratsiyasiz, xavfsiz qoladi. Faqat API yo'llari va fayl nomlari universal qilindi.

class KtTeacher(Base):
    __tablename__ = "kt_teachers"
    id: Mapped[int] = mapped_column(primary_key=True)
    login: Mapped[str] = mapped_column(String(80), unique=True)
    password_hash: Mapped[str] = mapped_column(String(128))  # sha256 hex
    name: Mapped[str] = mapped_column(String(200))
    role: Mapped[str] = mapped_column(String(20), default="teacher")  # teacher|superadmin
    institution: Mapped[str | None] = mapped_column(String(200), nullable=True)  # hozircha oddiy matn
    department: Mapped[str | None] = mapped_column(String(200), nullable=True)   # eski matn maydoni (fan->kafedra bog'langanda shundan foydalaniladi)
    subject_id: Mapped[int | None] = mapped_column(ForeignKey("kt_subjects.id"), nullable=True, index=True)  # ustoz biriktirilgan fan
    subject: Mapped["KtSubject | None"] = relationship(foreign_keys=[subject_id])


class KtLoginEvent(Base):
    """Kirish tarixi: har bir muvaffaqiyatli login shu yerga yoziladi (profil sahifasida ko'rsatish uchun)."""
    __tablename__ = "kt_login_events"
    id: Mapped[int] = mapped_column(primary_key=True)
    teacher_id: Mapped[int] = mapped_column(ForeignKey("kt_teachers.id"), index=True)
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    ip: Mapped[str | None] = mapped_column(String(64), nullable=True)
    user_agent: Mapped[str | None] = mapped_column(String(300), nullable=True)


class KtSetting(Base):
    """Kalit-qiymat: groups, exam ({open, minutes}), migrated."""
    __tablename__ = "kt_settings"
    key: Mapped[str] = mapped_column(String(60), primary_key=True)
    value: Mapped[Any] = mapped_column(JSON)


class KtDepartment(Base):
    """Kafedra (masalan: Avtomatlashtirish va raqamli boshqaruv). Institut hozircha ustozda matn sifatida."""
    __tablename__ = "kt_departments"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(200), unique=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class KtSubject(Base):
    """Fan (masalan: Kompyuter tarmoqlari, Ma'lumotlar bazasi) — bitta kafedraga bog'lanadi."""
    __tablename__ = "kt_subjects"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(200), unique=True)
    code: Mapped[str] = mapped_column(String(10), unique=True)  # masalan "mb", "kt" — kelajakda route prefiksi
    department_id: Mapped[int | None] = mapped_column(ForeignKey("kt_departments.id"), nullable=True, index=True)
    department: Mapped["KtDepartment | None"] = relationship()
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class KtTeacherSubject(Base):
    """Ustoz ko'pga-ko'pga fan biriktirish (bir ustoz bir nechta fan o'qitishi mumkin).
    KtTeacher.subject_id — ustozning "asosiy" fani (profil/eski joylarda ishlatiladi,
    orqaga moslik uchun saqlanadi). Bu jadval — qo'shimcha fanlar ro'yxati."""
    __tablename__ = "kt_teacher_subjects"
    id: Mapped[int] = mapped_column(primary_key=True)
    teacher_id: Mapped[int] = mapped_column(ForeignKey("kt_teachers.id"), index=True)
    subject_id: Mapped[int] = mapped_column(ForeignKey("kt_subjects.id"), index=True)


class KtExam(Base):
    __tablename__ = "kt_exams"
    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    slug: Mapped[str] = mapped_column(String(80), unique=True, index=True)
    title: Mapped[str] = mapped_column(String(200))
    subject_id: Mapped[int | None] = mapped_column(ForeignKey("kt_subjects.id"), nullable=True, index=True)
    # Imtihonni kim yaratgan/boshqaradi — egalik shu yerda belgilanadi (fan darajasida emas).
    # NULL = eski/umumiy imtihon (migratsiyadan oldingi), hammaga ko'rinadi.
    teacher_id: Mapped[int | None] = mapped_column(ForeignKey("kt_teachers.id"), nullable=True, index=True)
    minutes: Mapped[int] = mapped_column(Integer, default=80)
    groups: Mapped[list] = mapped_column(JSON, default=list)
    questions: Mapped[list] = mapped_column(JSON, default=list)  # imtihonga xos savollar banki (bo'sh = eski umumiy data.json bankidan foydalanadi)
    status: Mapped[str] = mapped_column(String(20), default="draft")  # draft|active|finished
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    deadline: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    # 6-bosqich: sinov (drill) imtihoni — urinishlari haqiqiy hisobot/statistikaga aralashmaydi. Eski imtihonlarda False.
    is_drill: Mapped[bool] = mapped_column(Boolean, default=False, server_default=text("0"))


class KtAttempt(Base):
    __tablename__ = "kt_attempts"
    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    exam_id: Mapped[str | None] = mapped_column(ForeignKey("kt_exams.id"), nullable=True, index=True)
    student: Mapped[str] = mapped_column(String(200), index=True)
    group: Mapped[str] = mapped_column(String(20), index=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    deadline: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    submitted: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    reason: Mapped[str | None] = mapped_column(String(100), nullable=True)
    questions: Mapped[list] = mapped_column(JSON, default=list)   # tanlangan savol id lari
    answers: Mapped[dict] = mapped_column(JSON, default=dict)     # {qid: javob}
    grades: Mapped[dict] = mapped_column(JSON, default=dict)      # {qid: ball}
    # Qayta kirish (1b-bosqich): talaba nechta marta qayta kirgan va ustoz qo'shimcha nechta ruxsat bergan.
    # Eski yozuvlarda 0 bo'lib qoladi (migrate_rejoin_columns.py: ADD COLUMN ... DEFAULT 0).
    rejoin_count: Mapped[int] = mapped_column(Integer, default=0, server_default=text("0"))
    rejoin_allowed: Mapped[int] = mapped_column(Integer, default=0, server_default=text("0"))
    exam: Mapped[KtExam | None] = relationship()
    grade_log: Mapped[list["KtGradeLog"]] = relationship(cascade="all, delete-orphan")
    events: Mapped[list["KtEvent"]] = relationship(back_populates="attempt", cascade="all, delete-orphan",
                                                   order_by="KtEvent.id")


class KtEvent(Base):
    __tablename__ = "kt_events"
    id: Mapped[int] = mapped_column(primary_key=True)
    attempt_id: Mapped[str] = mapped_column(ForeignKey("kt_attempts.id"), index=True)
    type: Mapped[str] = mapped_column(String(40))
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    attempt: Mapped[KtAttempt] = relationship(back_populates="events")


class KtGradeLog(Base):
    """4-bosqich: baho o'zgarishlari tarixi (apellyatsiya uchun). Faqat qo'shiladi; yangi jadval, mavjudlariga tegmaydi.
    old_score NULL = birinchi marta baho qo'yilgan."""
    __tablename__ = "kt_grade_log"
    id: Mapped[int] = mapped_column(primary_key=True)
    attempt_id: Mapped[str] = mapped_column(ForeignKey("kt_attempts.id", ondelete="CASCADE"))
    qid: Mapped[str] = mapped_column(String(80))
    old_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    new_score: Mapped[float] = mapped_column(Float)
    teacher_id: Mapped[int | None] = mapped_column(ForeignKey("kt_teachers.id"), nullable=True)
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    __table_args__ = (Index("ix_kt_grade_log_attempt_at", "attempt_id", "at"),)
