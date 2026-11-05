"""Lifestyle models: pet expense line items and pet-friendly places (Task 23)."""
from __future__ import annotations

import enum

from sqlalchemy import Boolean, Enum, Float, ForeignKey, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ..extensions import db
from .mixins import TimestampMixin


class ExpenseFrequency(str, enum.Enum):
    MONTHLY = "monthly"
    YEARLY = "yearly"

    @property
    def label(self) -> str:
        return self.value.capitalize()


# Category colours used in the Chart.js donut.
EXPENSE_CATEGORIES = {
    "food": "Food & treats",
    "vet": "Vet visits & vaccines",
    "grooming": "Litter & grooming",
    "medication": "Medication",
    "toys": "Toys & accessories",
    "insurance": "Pet insurance",
    "other": "Other",
}


class ExpenseItem(TimestampMixin, db.Model):
    __tablename__ = "expense_items"

    id: Mapped[int] = mapped_column(primary_key=True)
    owner_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    label: Mapped[str] = mapped_column(String(120), nullable=False)
    category: Mapped[str] = mapped_column(String(40), default="other", nullable=False)
    amount: Mapped[float] = mapped_column(Numeric(10, 2), nullable=False)
    frequency: Mapped[ExpenseFrequency] = mapped_column(
        Enum(ExpenseFrequency, native_enum=False, length=20),
        default=ExpenseFrequency.MONTHLY,
        nullable=False,
    )

    @property
    def monthly_amount(self) -> float:
        amt = float(self.amount)
        return amt if self.frequency == ExpenseFrequency.MONTHLY else amt / 12

    @property
    def yearly_amount(self) -> float:
        amt = float(self.amount)
        return amt * 12 if self.frequency == ExpenseFrequency.MONTHLY else amt


class PlaceCategory(str, enum.Enum):
    PARK = "park"
    CAFE = "cafe"
    VET = "vet"
    GROOMING = "grooming"
    BOARDING = "boarding"

    @property
    def label(self) -> str:
        return {
            "park": "Parks",
            "cafe": "Cafés",
            "vet": "Vets",
            "grooming": "Grooming",
            "boarding": "Boarding",
        }[self.value]


class Place(TimestampMixin, db.Model):
    """A pet-friendly location shown on the map."""

    __tablename__ = "places"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    category: Mapped[PlaceCategory] = mapped_column(
        Enum(PlaceCategory, native_enum=False, length=20), nullable=False, index=True
    )
    city: Mapped[str | None] = mapped_column(String(120), nullable=True)
    address: Mapped[str | None] = mapped_column(String(300), nullable=True)
    lat: Mapped[float] = mapped_column(Float, nullable=False)
    lng: Mapped[float] = mapped_column(Float, nullable=False)
    rating: Mapped[float | None] = mapped_column(Float, nullable=True)
    note: Mapped[str | None] = mapped_column(String(200), nullable=True)
    distance_km: Mapped[float | None] = mapped_column(Float, nullable=True)
    emergency_24h: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
