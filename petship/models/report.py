"""Abuse/fraud report model (Task 31).

Users report listings, posts, comments, reviews, or other users. Reports feed
the admin moderation queues (Task 36).
"""
from __future__ import annotations

import enum

from sqlalchemy import Enum, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ..extensions import db
from .mixins import TimestampMixin


class ReportTargetType(str, enum.Enum):
    LISTING = "listing"
    POST = "post"
    COMMENT = "comment"
    REVIEW = "review"
    USER = "user"
    SHELTER = "shelter"
    VET = "vet"

    @property
    def label(self) -> str:
        return self.value.capitalize()


class AbuseStatus(str, enum.Enum):
    OPEN = "open"
    RESOLVED = "resolved"
    DISMISSED = "dismissed"

    @property
    def label(self) -> str:
        return self.value.capitalize()


class AbuseReport(TimestampMixin, db.Model):
    __tablename__ = "abuse_reports"

    id: Mapped[int] = mapped_column(primary_key=True)
    reporter_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )
    target_type: Mapped[ReportTargetType] = mapped_column(
        Enum(ReportTargetType, native_enum=False, length=20), nullable=False, index=True
    )
    target_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    target_label: Mapped[str | None] = mapped_column(String(200), nullable=True)
    reason: Mapped[str] = mapped_column(String(120), nullable=False)
    details: Mapped[str | None] = mapped_column(Text, nullable=True)
    priority: Mapped[str] = mapped_column(String(20), default="medium", nullable=False)
    status: Mapped[AbuseStatus] = mapped_column(
        Enum(AbuseStatus, native_enum=False, length=20),
        default=AbuseStatus.OPEN,
        nullable=False,
        index=True,
    )

    reporter = relationship("User")
