from datetime import datetime
from pydantic import BaseModel, ConfigDict, Field, field_validator
from .risk import RULES, level_of


class ORM(BaseModel):
    model_config = ConfigDict(from_attributes=True)


# ── Exam ──
class ExamPublic(ORM):
    id: int
    slug: str
    title: str
    subject: str
    duration_min: int
    status: str
    started_at: datetime | None


class ExamCreate(BaseModel):
    slug: str = Field(min_length=2, max_length=60, pattern=r'^[a-z0-9\-]+$')
    title: str = Field(min_length=2, max_length=200)
    subject: str = Field(min_length=2, max_length=100)
    duration_min: int = Field(gt=0, le=600)
    teacher_key: str = Field(min_length=4, max_length=80)


class TeacherAuth(BaseModel):
    teacher_key: str


# ── Questions ──
class OptionOut(ORM):
    id: int
    key: str
    text: str


class OptionWithAnswer(OptionOut):
    is_correct: bool


class QuestionOut(BaseModel):
    id: int
    order_num: int
    text: str
    points: int
    options: list[OptionOut]


class QuestionWithAnswer(QuestionOut):
    options: list[OptionWithAnswer]


class QuestionCreate(BaseModel):
    text: str = Field(min_length=2)
    points: int = Field(default=1, ge=1)
    options: list[dict]  # [{key, text, is_correct}]


# ── Session ──
class SessionStart(BaseModel):
    student_name: str = Field(min_length=2, max_length=150)
    student_group: str


class SessionOut(ORM):
    id: int
    exam_id: int
    student_name: str
    student_group: str
    status: str
    started_at: datetime
    finished_at: datetime | None
    score: int | None
    total_points: int | None
    risk_score: int
    risk_level: str = ""
    decision: str | None
    note: str | None

    @classmethod
    def from_model(cls, s):
        o = cls.model_validate(s)
        o.risk_level = level_of(s.risk_score)
        return o


class AnswerIn(BaseModel):
    question_id: int
    option_id: int | None = None


class AnswersBatch(BaseModel):
    answers: list[AnswerIn]


class EventsBatch(BaseModel):
    events: list[dict]   # [{type, t?, conf?}]


class DecisionIn(BaseModel):
    decision: str
    note: str | None = None


# ── Teacher dashboard ──
class GroupStat(BaseModel):
    group: str
    total: int
    finished: int
    avg_score: float | None
    avg_risk: int


class ExamStats(BaseModel):
    exam: ExamPublic
    groups: list[GroupStat]
    sessions: list[SessionOut]


class ResultRow(BaseModel):
    student_name: str
    student_group: str
    score: int | None
    total_points: int | None
    pct: float | None
    risk_score: int
    risk_level: str
    decision: str | None
