"""Shelter organisation model.

A shelter is owned by a user with the SHELTER role and lists pets for
adoption. Verification state (Task 35) gates public listing.
"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, JSON, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ..extensions import db
from .mixins import TimestampMixin


class Shelter(TimestampMixin, db.Model):
    __tablename__ = "shelters"

    id: Mapped[int] = mapped_column(primary_key=True)
    owner_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )

    name: Mapped[str] = mapped_column(String(160), nullable=False)
    slug: Mapped[str] = mapped_column(String(180), unique=True, index=True, nullable=False)
    address: Mapped[str | None] = mapped_column(String(300), nullable=True)
    registration_photos: Mapped[list | None] = mapped_column(JSON, nullable=True)
    verification_visit_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    verification_visit_time_is_utc: Mapped[bool] = mapped_column(
        Boolean, default=False, nullable=False
    )
    verification_visit_completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    city: Mapped[str | None] = mapped_column(String(120), nullable=True)
    about: Mapped[str | None] = mapped_column(Text, nullable=True)
    logo_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    cover_url: Mapped[str | None] = mapped_column(String(500), nullable=True)

    registration_no: Mapped[str | None] = mapped_column(String(80), nullable=True)
    contact_name: Mapped[str | None] = mapped_column(String(120), nullable=True)
    capacity: Mapped[int | None] = mapped_column(Integer, nullable=True)
    operating_since: Mapped[int | None] = mapped_column(Integer, nullable=True)

    is_verified: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    avg_response_hours: Mapped[float | None] = mapped_column(Float, nullable=True)

    owner = relationship("User", backref="shelter_profile")
    pets = relationship(
        "Pet", back_populates="shelter", cascade="all, delete-orphan"
    )

    @property
    def available_count(self) -> int:
        from .pet import PetStatus

        return sum(1 for p in self.pets if p.status == PetStatus.AVAILABLE)

    def __repr__(self) -> str:  # pragma: no cover
        return f"<Shelter {self.id} {self.name}>"
