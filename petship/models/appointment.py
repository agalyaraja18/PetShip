"""Appointment model shared by shelter visits and vet bookings.

Shelter appointments (Task 17): meet & greet, home visit, pick-up.
Vet appointments (Task 19): check-up, vaccination, etc. The ``vet_id`` and
``service`` fields are used by the vet flow; ``shelter_id`` by the shelter flow.
"""
from __future__ import annotations

import enum
from datetime import datetime

from sqlalchemy import Boolean, DateTime, Enum, ForeignKey, Numeric, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ..extensions import db
from .mixins import TimestampMixin


class AppointmentKind(str, enum.Enum):
    MEET_GREET = "meet_greet"
    HOME_VISIT = "home_visit"
    PICKUP = "pickup"
    VET_VISIT = "vet_visit"

    @property
    def label(self) -> str:
        return {
            "meet_greet": "Meet & greet",
            "home_visit": "Home visit",
            "pickup": "Pick-up",
            "vet_visit": "Vet visit",
        }[self.value]


class AppointmentStatus(str, enum.Enum):
    PENDING = "pending"
    CONFIRMED = "confirmed"
    CHECKED_IN = "checked_in"
    COMPLETED = "completed"
    CANCELLED = "cancelled"

    @property
    def label(self) -> str:
        return self.value.replace("_", " ").capitalize()

    @property
    def badge_variant(self) -> str:
        return {
            "pending": "warning",
            "confirmed": "success",
            "checked_in": "info",
            "completed": "neutral",
            "cancelled": "danger",
        }[self.value]


class Appointment(TimestampMixin, db.Model):
    __tablename__ = "appointments"

    id: Mapped[int] = mapped_column(primary_key=True)
    kind: Mapped[AppointmentKind] = mapped_column(
        Enum(AppointmentKind, native_enum=False, length=20), nullable=False
    )
    status: Mapped[AppointmentStatus] = mapped_column(
        Enum(AppointmentStatus, native_enum=False, length=20),
        default=AppointmentStatus.CONFIRMED,
        nullable=False,
        index=True,
    )
    scheduled_for: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True
    )
    adopter_confirmed: Mapped[bool] = mapped_column(
        Boolean, default=False, nullable=False
    )

    # Participants / subjects (nullable so one model serves both flows).
    shelter_id: Mapped[int | None] = mapped_column(
        ForeignKey("shelters.id", ondelete="CASCADE"), nullable=True, index=True
    )
    vet_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )
    user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )
    pet_id: Mapped[int | None] = mapped_column(
        ForeignKey("pets.id", ondelete="SET NULL"), nullable=True, index=True
    )
    application_id: Mapped[int | None] = mapped_column(
        ForeignKey("applications.id", ondelete="SET NULL"), nullable=True, index=True
    )

    service: Mapped[str | None] = mapped_column(String(80), nullable=True)
    location: Mapped[str | None] = mapped_column(String(200), nullable=True)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    price: Mapped[float | None] = mapped_column(Numeric(10, 2), nullable=True)
    reference: Mapped[str | None] = mapped_column(String(20), nullable=True)

    shelter = relationship("Shelter")
    pet = relationship("Pet")
    user = relationship("User", foreign_keys=[user_id])
    vet = relationship("User", foreign_keys=[vet_id])
    application = relationship("Application")

    def __repr__(self) -> str:  # pragma: no cover
        return f"<Appointment {self.id} {self.kind.value} {self.status.value}>"
