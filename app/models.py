from datetime import datetime, timezone

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .db import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Student(Base):
    __tablename__ = "students"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(120))
    group: Mapped[str] = mapped_column(String(20), index=True)
    email: Mapped[str] = mapped_column(String(160), unique=True)


class Exam(Base):
    __tablename__ = "exams"
    id: Mapped[int] = mapped_column(primary_key=True)
    title: Mapped[str] = mapped_column(String(200))
    group: Mapped[str] = mapped_column(String(20))
    date: Mapped[str] = mapped_column(String(10))  # YYYY-MM-DD
    minutes: Mapped[int] = mapped_column(Integer)
    questions: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(20), default="Rejalashtirilgan")


class ExamSession(Base):
    __tablename__ = "sessions"
    id: Mapped[int] = mapped_column(primary_key=True)
    student_id: Mapped[int] = mapped_column(ForeignKey("students.id"), index=True)
    exam_id: Mapped[int] = mapped_column(ForeignKey("exams.id"), index=True)
    status: Mapped[str] = mapped_column(String(10), default="active")  # active | finished
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    decision: Mapped[str | None] = mapped_column(String(40), nullable=True)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    student: Mapped[Student] = relationship()
    exam: Mapped[Exam] = relationship()
    events: Mapped[list["Event"]] = relationship(
        back_populates="session", cascade="all, delete-orphan", order_by="Event.t"
    )


class Event(Base):
    __tablename__ = "events"
    id: Mapped[int] = mapped_column(primary_key=True)
    session_id: Mapped[int] = mapped_column(ForeignKey("sessions.id"), index=True)
    t: Mapped[float] = mapped_column(Float)  # sessiya boshidan soniyalarda
    type: Mapped[str] = mapped_column(String(40))
    conf: Mapped[float] = mapped_column(Float)
    fp: Mapped[bool] = mapped_column(Boolean, default=False)

    session: Mapped[ExamSession] = relationship(back_populates="events")
