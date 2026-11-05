"""Veterinarian profile model, linked one-to-one with a vet-role user."""
from __future__ import annotations

from sqlalchemy import JSON, Boolean, Float, ForeignKey, Integer, Numeric, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ..extensions import db
from .mixins import TimestampMixin

SPECIALTY_OPTIONS = [
    "General",
    "Cats",
    "Dogs",
    "Vaccination",
    "Surgery",
    "Dental",
    "Dermatology",
    "Orthopedics",
    "Exotic pets",
    "Senior pets",
]


class VetProfile(TimestampMixin, db.Model):
    __tablename__ = "vet_profiles"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), unique=True, nullable=False, index=True
    )

    display_name: Mapped[str] = mapped_column(String(160), nullable=False)
    slug: Mapped[str] = mapped_column(String(180), unique=True, index=True, nullable=False)
    qualifications: Mapped[str | None] = mapped_column(String(160), nullable=True)
    clinic_name: Mapped[str | None] = mapped_column(String(160), nullable=True)
    clinic_address: Mapped[str | None] = mapped_column(String(300), nullable=True)
    city: Mapped[str | None] = mapped_column(String(120), nullable=True)
    licence_no: Mapped[str | None] = mapped_column(String(80), nullable=True)
    experience_years: Mapped[int | None] = mapped_column(Integer, nullable=True)
    bio: Mapped[str | None] = mapped_column(Text, nullable=True)
    photo_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    certificate_url: Mapped[str | None] = mapped_column(String(500), nullable=True)

    specialties: Mapped[list | None] = mapped_column(JSON, default=list)
    languages: Mapped[list | None] = mapped_column(JSON, default=list)

    consult_fee: Mapped[float | None] = mapped_column(Numeric(10, 2), nullable=True)
    video_fee: Mapped[float | None] = mapped_column(Numeric(10, 2), nullable=True)

    rating: Mapped[float | None] = mapped_column(Float, nullable=True)
    reviews_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    pets_treated: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    distance_km: Mapped[float | None] = mapped_column(Float, nullable=True)

    is_verified: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    offers_video: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    offers_home_visits: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    offers_emergency: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    user = relationship("User", backref="vet_profile")

    def __repr__(self) -> str:  # pragma: no cover
        return f"<VetProfile {self.id} {self.display_name}>"
