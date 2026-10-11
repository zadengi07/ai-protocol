from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from .risk import RULES

Decision = Literal["Qoniqarli", "Qo'shimcha tekshiruv", "Natija bekor"]
ExamStatus = Literal["Rejalashtirilgan", "Jarayonda", "Yakunlangan"]


class ORM(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class StudentIn(BaseModel):
    name: str = Field(min_length=2, max_length=120)
    group: str = Field(min_length=1, max_length=20)
    email: str = Field(min_length=3, max_length=160)


class StudentOut(ORM):
    id: int
    name: str
    group: str
    email: str
    exams: int = 0
    risk: int | None = None  # oxirgi yakunlangan sessiya bo'yicha
    last_session_id: int | None = None


class ExamIn(BaseModel):
    title: str = Field(min_length=2, max_length=200)
    group: str
    date: str = Field(pattern=r"^\d{4}-\d{2}-\d{2}$")
    minutes: int = Field(gt=0, le=600)
    questions: int = Field(gt=0, le=500)
    status: ExamStatus = "Rejalashtirilgan"


class ExamOut(ORM):
    id: int
    title: str
    group: str
    date: str
    minutes: int
    questions: int
    status: str
    students: int = 0


class SessionIn(BaseModel):
    student_id: int
    exam_id: int


class SessionOut(ORM):
    id: int
    student_id: int
    exam_id: int
    student_name: str
    student_group: str
    student_email: str
    exam_title: str
    exam_minutes: int
    status: str
    started_at: datetime
    finished_at: datetime | None
    decision: str | None
    note: str | None
    risk: int
    level: str
    events_count: int
    last_event_type: str | None = None
    last_event_label: str | None = None


class EventIn(BaseModel):
    type: str
    conf: float = Field(default=0.9, ge=0, le=1)
    t: float | None = Field(default=None, ge=0, description="Sessiya boshidan soniyalarda. Bo'sh bo'lsa server hisoblaydi.")

    @field_validator("type")
    @classmethod
    def known_type(cls, v: str) -> str:
        if v not in RULES:
            raise ValueError(f"Noma'lum hodisa turi. Ruxsat etilgan: {', '.join(RULES)}")
        return v


class EventPatch(BaseModel):
    fp: bool


class EventOut(ORM):
    id: int
    t: float
    type: str
    conf: float
    fp: bool


class ScoredEvent(EventOut):
    label: str
    score: float


class DecisionIn(BaseModel):
    decision: Decision
    note: str | None = Field(default=None, max_length=2000)


class ReportOut(BaseModel):
    session_id: int
    student: str
    group: str
    exam: str
    risk_score: int
    level: str
    correlation_bonus: int
    proctor_decision: str | None
    proctor_note: str | None
    events: list[ScoredEvent]
    disclaimer: str = "Tizim «aldadi» deb hukm chiqarmaydi: faqat xavf darajasi va dalillarni ko'rsatadi. Yakuniy qaror — inson."


class RecentEvent(BaseModel):
    id: int
    session_id: int
    student_name: str
    type: str
    label: str
    t: float
