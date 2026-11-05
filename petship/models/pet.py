"""Pet listing model with species/age/size, traits, photos, and status."""
from __future__ import annotations

import enum

from sqlalchemy import (
    JSON,
    Enum,
    Float,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ..extensions import db
from .mixins import TimestampMixin


class Species(str, enum.Enum):
    DOG = "dog"
    CAT = "cat"
    RABBIT = "rabbit"
    BIRD = "bird"
    OTHER = "other"

    @property
    def label(self) -> str:
        return self.value.capitalize()


class AgeGroup(str, enum.Enum):
    BABY = "baby"
    YOUNG = "young"
    ADULT = "adult"
    SENIOR = "senior"

    @property
    def label(self) -> str:
        return self.value.capitalize()


class Size(str, enum.Enum):
    SMALL = "small"
    MEDIUM = "medium"
    LARGE = "large"

    @property
    def label(self) -> str:
        return self.value.capitalize()


class Sex(str, enum.Enum):
    MALE = "male"
    FEMALE = "female"
    UNKNOWN = "unknown"

    @property
    def label(self) -> str:
        return self.value.capitalize()


class PetStatus(str, enum.Enum):
    DRAFT = "draft"
    AVAILABLE = "available"
    RESERVED = "reserved"
    ADOPTED = "adopted"
    REMOVED = "removed"

    @property
    def label(self) -> str:
        return self.value.capitalize()

    @property
    def badge_variant(self) -> str:
        return {
            "draft": "neutral",
            "available": "success",
            "reserved": "warning",
            "adopted": "info",
            "removed": "danger",
        }[self.value]


class Pet(TimestampMixin, db.Model):
    __tablename__ = "pets"

    id: Mapped[int] = mapped_column(primary_key=True)
    shelter_id: Mapped[int] = mapped_column(
        ForeignKey("shelters.id", ondelete="CASCADE"), nullable=False, index=True
    )

    name: Mapped[str] = mapped_column(String(120), nullable=False)
    species: Mapped[Species] = mapped_column(
        Enum(Species, native_enum=False, length=20), nullable=False, index=True
    )
    breed: Mapped[str | None] = mapped_column(String(120), nullable=True)
    age_group: Mapped[AgeGroup] = mapped_column(
        Enum(AgeGroup, native_enum=False, length=20), nullable=False, index=True
    )
    age_text: Mapped[str | None] = mapped_column(String(40), nullable=True)  # "2 yrs"
    size: Mapped[Size] = mapped_column(
        Enum(Size, native_enum=False, length=20), nullable=False, index=True
    )
    sex: Mapped[Sex] = mapped_column(
        Enum(Sex, native_enum=False, length=20), default=Sex.UNKNOWN, nullable=False
    )
    weight_kg: Mapped[float | None] = mapped_column(Float, nullable=True)
    energy: Mapped[str | None] = mapped_column(String(20), nullable=True)  # low/medium/high

    description: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Tag lists stored as JSON (portable across SQLite + PostgreSQL).
    health_tags: Mapped[list | None] = mapped_column(JSON, default=list)
    personality_tags: Mapped[list | None] = mapped_column(JSON, default=list)
    good_with: Mapped[list | None] = mapped_column(JSON, default=list)  # kids/cats/dogs
    photos: Mapped[list | None] = mapped_column(JSON, default=list)

    distance_km: Mapped[float | None] = mapped_column(Float, nullable=True)
    adoption_fee: Mapped[float | None] = mapped_column(Numeric(10, 2), nullable=True)

    status: Mapped[PetStatus] = mapped_column(
        Enum(PetStatus, native_enum=False, length=20),
        default=PetStatus.DRAFT,
        nullable=False,
        index=True,
    )
    views: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    shelter = relationship("Shelter", back_populates="pets")

    # ---- Helpers ----
    @property
    def primary_photo(self) -> str | None:
        return self.photos[0] if self.photos else None

    @property
    def summary(self) -> str:
        bits = [self.breed or self.species.label, self.age_text, self.sex.label]
        return " · ".join(b for b in bits if b)

    def publish(self) -> None:
        self.status = PetStatus.AVAILABLE

    def reserve(self) -> None:
        self.status = PetStatus.RESERVED

    def mark_adopted(self) -> None:
        self.status = PetStatus.ADOPTED

    def __repr__(self) -> str:  # pragma: no cover
        return f"<Pet {self.id} {self.name} ({self.species.value})>"
