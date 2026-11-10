"""Brauzer proktoring hodisalari uchun yangi jadval (mavjud modellarga tegilmaydi).

Eslatma: `proctor_events` nomi eski demo oqimida (ProctoringEvent) allaqachon band, shuning uchun
yangi jadval `kt_proctor_events` deb nomlandi — aks bo'lsa create_all eski jadvalni "mavjud" deb
topib, yangi ustunlarni yaratmay qo'yardi.
"""
from datetime import datetime
from typing import Any

from sqlalchemy import JSON, Boolean, DateTime, ForeignKey, Index, String
from sqlalchemy.orm import Mapped, mapped_column

from .db import Base
from .models import utcnow


class KtProctorEvent(Base):
    __tablename__ = "kt_proctor_events"

    event_id: Mapped[str] = mapped_column(String(36), primary_key=True)  # klient UUID — deduplikatsiya kaliti
    # ondelete=CASCADE: ustoz imtihonni o'chirganda (kt.delete_exam) urinishlar o'chadi, FK xatosi chiqmasligi uchun.
    attempt_id: Mapped[str] = mapped_column(ForeignKey("kt_attempts.id", ondelete="CASCADE"), index=True)
    exam_id: Mapped[str | None] = mapped_column(String(32), index=True, nullable=True)
    student_id: Mapped[str] = mapped_column(String(200))  # KT da talaba ID yo'q: urinishdagi ism-familiya
    group_name: Mapped[str] = mapped_column(String(20))
    event_type: Mapped[str] = mapped_column(String(40))
    event_time: Mapped[datetime] = mapped_column(DateTime(timezone=True))  # klient vaqti (cheklangan)
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    page_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    browser_name: Mapped[str | None] = mapped_column(String(60), nullable=True)
    operating_system: Mapped[str | None] = mapped_column(String(60), nullable=True)
    device_type: Mapped[str | None] = mapped_column(String(20), nullable=True)
    event_details: Mapped[Any] = mapped_column(JSON, default=dict)
    event_source: Mapped[str] = mapped_column(String(20))  # detected|inferred|blocked_attempt|unsupported
    severity: Mapped[str] = mapped_column(String(10))
    # 3-bosqich: ustoz tekshiruvi. NULL = hali tekshirilmagan (eski hodisalar ham shunday, riskka kiradi).
    # justified=True "asosli" (riskda qoladi), False "asossiz" (riskka kirmaydi). reviewed = ustoz belgilaganmi.
    reviewed: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    justified: Mapped[bool | None] = mapped_column(Boolean, nullable=True)

    __table_args__ = (
        Index("ix_kt_proctor_attempt_time", "attempt_id", "event_time"),
        Index("ix_kt_proctor_attempt_type", "attempt_id", "event_type"),
    )
