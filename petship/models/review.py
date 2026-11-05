"""Review and post-adoption follow-up models (Task 17)."""
from __future__ import annotations

import enum
from datetime import datetime

from sqlalchemy import DateTime, Enum, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ..extensions import db
from .mixins import TimestampMixin


class ReviewTarget(str, enum.Enum):
    SHELTER = "shelter"
    VET = "vet"


class Review(TimestampMixin, db.Model):
    __tablename__ = "reviews"

    id: Mapped[int] = mapped_column(primary_key=True)
    author_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    target_type: Mapped[ReviewTarget] = mapped_column(
        Enum(ReviewTarget, native_enum=False, length=20), nullable=False, index=True
    )
    target_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)

    rating: Mapped[int] = mapped_column(Integer, nullable=False)  # 1..5
    body: Mapped[str | None] = mapped_column(Text, nullable=True)
    reply: Mapped[str | None] = mapped_column(Text, nullable=True)
    hidden: Mapped[bool] = mapped_column(db.Boolean, default=False, nullable=False)

    author = relationship("User")


class FollowUpStatus(str, enum.Enum):
    DUE = "due"
    DONE = "done"
    NEEDS_SUPPORT = "needs_support"

    @property
    def label(self) -> str:
        return self.value.replace("_", " ").capitalize()


class FollowUp(TimestampMixin, db.Model):
    """A scheduled post-adoption check-in."""

    __tablename__ = "followups"

    id: Mapped[int] = mapped_column(primary_key=True)
    application_id: Mapped[int] = mapped_column(
        ForeignKey("applications.id", ondelete="CASCADE"), nullable=False, index=True
    )
    milestone: Mapped[str] = mapped_column(String(40), nullable=False)
    due_on: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    status: Mapped[FollowUpStatus] = mapped_column(
        Enum(FollowUpStatus, native_enum=False, length=20),
        default=FollowUpStatus.DUE,
        nullable=False,
        index=True,
    )
    response: Mapped[str | None] = mapped_column(Text, nullable=True)
    mood: Mapped[str | None] = mapped_column(String(20), nullable=True)

    application = relationship("Application", back_populates="followups")
