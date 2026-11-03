from datetime import datetime, timezone
from typing import Any
from sqlalchemy import JSON, Boolean, DateTime, Float, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship
from .db import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


GROUPS = ["25-80", "25-81", "25-82", "25-83", "25-85"]


class Exam(Base):
    __tablename__ = "exams"
    id: Mapped[int] = mapped_column(primary_key=True)
    slug: Mapped[str] = mapped_column(String(60), unique=True, index=True)  # /exam-kt
    title: Mapped[str] = mapped_column(String(200))
    subject: Mapped[str] = mapped_column(String(100))
    duration_min: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(20), default="pending")  # pending|active|finished
    teacher_key: Mapped[str] = mapped_column(String(80))  # ustoz paroli
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    drop_after: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)  # finished_at + 24h
    dropped: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    questions: Mapped[list["Question"]] = relationship(back_populates="exam", cascade="all, delete-orphan", order_by="Question.order_num")
    sessions: Mapped[list["ExamSession"]] = relationship(back_populates="exam", cascade="all, delete-orphan")


class Question(Base):
    __tablename__ = "questions"
    id: Mapped[int] = mapped_column(primary_key=True)
    exam_id: Mapped[int] = mapped_column(ForeignKey("exams.id"), index=True)
    order_num: Mapped[int] = mapped_column(Integer)
    text: Mapped[str] = mapped_column(Text)
    points: Mapped[int] = mapped_column(Integer, default=1)
    exam: Mapped[Exam] = relationship(back_populates="questions")
    options: Mapped[list["Option"]] = relationship(back_populates="question", cascade="all, delete-orphan", order_by="Option.key")


class Option(Base):
    __tablename__ = "options"
    id: Mapped[int] = mapped_column(primary_key=True)
    question_id: Mapped[int] = mapped_column(ForeignKey("questions.id"), index=True)
    key: Mapped[str] = mapped_column(String(1))   # A B C D
    text: Mapped[str] = mapped_column(Text)
    is_correct: Mapped[bool] = mapped_column(Boolean, default=False)
    question: Mapped[Question] = relationship(back_populates="options")


class ExamSession(Base):
    __tablename__ = "sessions"
    id: Mapped[int] = mapped_column(primary_key=True)
    exam_id: Mapped[int] = mapped_column(ForeignKey("exams.id"), index=True)
    student_name: Mapped[str] = mapped_column(String(150))
    student_group: Mapped[str] = mapped_column(String(20), index=True)
    status: Mapped[str] = mapped_column(String(10), default="active")  # active|finished
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    score: Mapped[int | None] = mapped_column(Integer, nullable=True)
    total_points: Mapped[int | None] = mapped_column(Integer, nullable=True)
    risk_score: Mapped[int] = mapped_column(Integer, default=0)
    decision: Mapped[str | None] = mapped_column(String(40), nullable=True)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)

    __table_args__ = (
        UniqueConstraint("exam_id", "student_name", "student_group", name="uq_session_student"),
    )

    exam: Mapped[Exam] = relationship(back_populates="sessions")
    answers: Mapped[list["Answer"]] = relationship(back_populates="session", cascade="all, delete-orphan")
    events: Mapped[list["ProctoringEvent"]] = relationship(back_populates="session", cascade="all, delete-orphan", order_by="ProctoringEvent.t")


class Answer(Base):
    __tablename__ = "answers"
    id: Mapped[int] = mapped_column(primary_key=True)
    session_id: Mapped[int] = mapped_column(ForeignKey("sessions.id"), index=True)
    question_id: Mapped[int] = mapped_column(ForeignKey("questions.id"))
    option_id: Mapped[int | None] = mapped_column(ForeignKey("options.id"), nullable=True)

    __table_args__ = (UniqueConstraint("session_id", "question_id", name="uq_answer"),)

    session: Mapped[ExamSession] = relationship(back_populates="answers")
    question: Mapped[Question] = relationship()
    option: Mapped[Option | None] = relationship()


class ProctoringEvent(Base):
    __tablename__ = "proctor_events"
    id: Mapped[int] = mapped_column(primary_key=True)
    session_id: Mapped[int] = mapped_column(ForeignKey("sessions.id"), index=True)
    t: Mapped[float] = mapped_column(Float)
    type: Mapped[str] = mapped_column(String(40))
    conf: Mapped[float] = mapped_column(Float, default=1.0)
    fp: Mapped[bool] = mapped_column(Boolean, default=False)
    session: Mapped[ExamSession] = relationship(back_populates="events")


# ══════════════ KT (/api/kt) — savollar data.json da, qolgani shu yerda ══════════════

class KtTeacher(Base):
    __tablename__ = "kt_teachers"
    id: Mapped[int] = mapped_column(primary_key=True)
    login: Mapped[str] = mapped_column(String(80), unique=True)
    password_hash: Mapped[str] = mapped_column(String(128))  # sha256 hex
    name: Mapped[str] = mapped_column(String(200))


class KtSetting(Base):
    """Kalit-qiymat: groups, exam ({open, minutes}), migrated."""
    __tablename__ = "kt_settings"
    key: Mapped[str] = mapped_column(String(60), primary_key=True)
    value: Mapped[Any] = mapped_column(JSON)


class KtExam(Base):
    __tablename__ = "kt_exams"
    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    slug: Mapped[str] = mapped_column(String(80), unique=True, index=True)
    title: Mapped[str] = mapped_column(String(200))
    minutes: Mapped[int] = mapped_column(Integer, default=80)
    groups: Mapped[list] = mapped_column(JSON, default=list)
    status: Mapped[str] = mapped_column(String(20), default="draft")  # draft|active|finished
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    deadline: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


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
    exam: Mapped[KtExam | None] = relationship()
    events: Mapped[list["KtEvent"]] = relationship(back_populates="attempt", cascade="all, delete-orphan",
                                                   order_by="KtEvent.id")


class KtEvent(Base):
    __tablename__ = "kt_events"
    id: Mapped[int] = mapped_column(primary_key=True)
    attempt_id: Mapped[str] = mapped_column(ForeignKey("kt_attempts.id"), index=True)
    type: Mapped[str] = mapped_column(String(40))
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    attempt: Mapped[KtAttempt] = relationship(back_populates="events")
