"""Lost & Found pet reports (model in Task 29; UI in Task 33).

Each report stores a perceptual hash of its photo so the matching engine can
suggest possible lost/found pairs.
"""
from __future__ import annotations

import enum

from sqlalchemy import Enum, Float, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ..extensions import db
from .mixins import TimestampMixin


class ReportKind(str, enum.Enum):
    LOST = "lost"
    FOUND = "found"

    @property
    def label(self) -> str:
        return self.value.capitalize()


class ReportStatus(str, enum.Enum):
    ACTIVE = "active"
    REUNITED = "reunited"
    CLOSED = "closed"

    @property
    def label(self) -> str:
        return self.value.capitalize()


class LostFoundReport(TimestampMixin, db.Model):
    __tablename__ = "lostfound_reports"

    id: Mapped[int] = mapped_column(primary_key=True)
    reporter_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    kind: Mapped[ReportKind] = mapped_column(
        Enum(ReportKind, native_enum=False, length=10), nullable=False, index=True
    )
    status: Mapped[ReportStatus] = mapped_column(
        Enum(ReportStatus, native_enum=False, length=10),
        default=ReportStatus.ACTIVE,
        nullable=False,
        index=True,
    )

    pet_name: Mapped[str | None] = mapped_column(String(120), nullable=True)
    species: Mapped[str | None] = mapped_column(String(40), nullable=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    location: Mapped[str | None] = mapped_column(String(200), nullable=True)
    lat: Mapped[float | None] = mapped_column(Float, nullable=True)
    lng: Mapped[float | None] = mapped_column(Float, nullable=True)
    photo_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    photo_hash: Mapped[str | None] = mapped_column(String(32), nullable=True, index=True)

    reporter = relationship("User")

    @property
    def opposite_kind(self) -> ReportKind:
        return ReportKind.FOUND if self.kind == ReportKind.LOST else ReportKind.LOST


class FoundPetTip(TimestampMixin, db.Model):
    """Private contact information sent to the owner of an active lost-pet post."""

    __tablename__ = "found_pet_tips"

    id: Mapped[int] = mapped_column(primary_key=True)
    report_id: Mapped[int] = mapped_column(
        ForeignKey("lostfound_reports.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    reporter_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    contact: Mapped[str] = mapped_column(String(200), nullable=False)
    message: Mapped[str] = mapped_column(Text, nullable=False)

    report = relationship("LostFoundReport", backref="found_tips")
    reporter = relationship("User")
