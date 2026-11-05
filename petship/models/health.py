"""Owned pets and their health records: medical records + vaccinations.

An OwnedPet is a pet a user actually owns (adopted or otherwise), distinct from
the adoptable shelter Pet listings. Health data hangs off OwnedPet. (Task 21;
the management UI is Task 22.)
"""
from __future__ import annotations

import enum
from datetime import date

from sqlalchemy import (
    JSON,
    Date,
    Enum,
    Float,
    ForeignKey,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ..extensions import db
from .mixins import TimestampMixin


class OwnedPet(TimestampMixin, db.Model):
    __tablename__ = "owned_pets"

    id: Mapped[int] = mapped_column(primary_key=True)
    owner_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )

    name: Mapped[str] = mapped_column(String(120), nullable=False)
    species: Mapped[str | None] = mapped_column(String(40), nullable=True)
    breed: Mapped[str | None] = mapped_column(String(120), nullable=True)
    sex: Mapped[str | None] = mapped_column(String(20), nullable=True)
    date_of_birth: Mapped[date | None] = mapped_column(Date, nullable=True)
    weight_kg: Mapped[float | None] = mapped_column(Float, nullable=True)
    microchip_id: Mapped[str | None] = mapped_column(String(60), nullable=True)
    photo_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    primary_vet: Mapped[str | None] = mapped_column(String(160), nullable=True)
    personality_tags: Mapped[list | None] = mapped_column(JSON, default=list)
    diet_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    care_schedule: Mapped[dict | list | None] = mapped_column(JSON, default=dict, nullable=True)
    adopted_on: Mapped[date | None] = mapped_column(Date, nullable=True)
    application_id: Mapped[int | None] = mapped_column(
        ForeignKey("applications.id", ondelete="SET NULL"), unique=True, nullable=True
    )

    owner = relationship("User", backref="owned_pets")
    application = relationship("Application", back_populates="owned_pet")
    health_plans = relationship(
        "HealthPlan", back_populates="pet", cascade="all, delete-orphan"
    )
    medical_records = relationship(
        "MedicalRecord", back_populates="pet", cascade="all, delete-orphan"
    )
    vaccinations = relationship(
        "Vaccination", back_populates="pet", cascade="all, delete-orphan"
    )

    @property
    def age_text(self) -> str:
        if not self.date_of_birth:
            return "Unknown age"
        today = date.today()
        years = today.year - self.date_of_birth.year - (
            (today.month, today.day) < (self.date_of_birth.month, self.date_of_birth.day)
        )
        if years >= 1:
            return f"{years} yr{'s' if years != 1 else ''}"
        months = (today.year - self.date_of_birth.year) * 12 + today.month - self.date_of_birth.month
        return f"{max(months, 0)} mo"

    @property
    def public_pet_id(self) -> str:
        return f"PET-{self.id:08d}"

    @property
    def unique_vaccination_count(self) -> int:
        names = {
            vaccination.name.strip().casefold()
            for vaccination in self.vaccinations
            if vaccination.name and vaccination.name.strip()
        }
        return len(names)


class VetPatient(TimestampMixin, db.Model):
    __tablename__ = "vet_patients"
    __table_args__ = (
        UniqueConstraint("vet_id", "pet_id", name="uq_vet_patient"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    vet_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    pet_id: Mapped[int] = mapped_column(
        ForeignKey("owned_pets.id", ondelete="CASCADE"), nullable=False, index=True
    )

    vet = relationship("User")
    pet = relationship("OwnedPet")


class HealthPlan(TimestampMixin, db.Model):
    __tablename__ = "health_plans"

    id: Mapped[int] = mapped_column(primary_key=True)
    pet_id: Mapped[int] = mapped_column(
        ForeignKey("owned_pets.id", ondelete="CASCADE"), nullable=False, index=True
    )
    vet_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    instructions: Mapped[str | None] = mapped_column(Text, nullable=True)
    prescribed_medicines: Mapped[str | None] = mapped_column(Text, nullable=True)
    next_visit_on: Mapped[date | None] = mapped_column(Date, nullable=True, index=True)
    next_visit_purpose: Mapped[str | None] = mapped_column(String(200), nullable=True)
    prescription_start_on: Mapped[date | None] = mapped_column(Date, nullable=True, index=True)
    prescription_end_on: Mapped[date | None] = mapped_column(Date, nullable=True, index=True)

    pet = relationship("OwnedPet", back_populates="health_plans")
    vet = relationship("User")


class RecordType(str, enum.Enum):
    CONSULTATION = "consultation"
    LAB = "lab"
    PRESCRIPTION = "prescription"
    IMAGING = "imaging"
    SURGERY = "surgery"
    EXAM = "exam"

    @property
    def label(self) -> str:
        return self.value.capitalize()


class MedicalRecord(TimestampMixin, db.Model):
    __tablename__ = "medical_records"

    id: Mapped[int] = mapped_column(primary_key=True)
    pet_id: Mapped[int] = mapped_column(
        ForeignKey("owned_pets.id", ondelete="CASCADE"), nullable=False, index=True
    )
    vet_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )

    record_type: Mapped[RecordType] = mapped_column(
        Enum(RecordType, native_enum=False, length=20),
        default=RecordType.CONSULTATION,
        nullable=False,
    )
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    record_date: Mapped[date] = mapped_column(Date, nullable=False)
    vet_name: Mapped[str | None] = mapped_column(String(160), nullable=True)
    findings: Mapped[str | None] = mapped_column(Text, nullable=True)
    diagnosis: Mapped[str | None] = mapped_column(Text, nullable=True)
    summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    attachments: Mapped[list | None] = mapped_column(JSON, default=list)
    shared_with_owner: Mapped[bool] = mapped_column(
        db.Boolean, default=True, nullable=False
    )

    pet = relationship("OwnedPet", back_populates="medical_records")


class VaccineStatus(str, enum.Enum):
    DONE = "done"
    DUE = "due"
    OVERDUE = "overdue"
    UPCOMING = "upcoming"

    @property
    def label(self) -> str:
        return self.value.capitalize()

    @property
    def badge_variant(self) -> str:
        return {
            "done": "success",
            "due": "warning",
            "overdue": "danger",
            "upcoming": "info",
        }[self.value]


class Vaccination(TimestampMixin, db.Model):
    __tablename__ = "vaccinations"

    id: Mapped[int] = mapped_column(primary_key=True)
    pet_id: Mapped[int] = mapped_column(
        ForeignKey("owned_pets.id", ondelete="CASCADE"), nullable=False, index=True
    )

    name: Mapped[str] = mapped_column(String(120), nullable=False)
    kind: Mapped[str | None] = mapped_column(String(60), nullable=True)  # core / non-core
    schedule: Mapped[str | None] = mapped_column(String(60), nullable=True)  # yearly etc.
    last_given: Mapped[date | None] = mapped_column(Date, nullable=True)
    due_on: Mapped[date | None] = mapped_column(Date, nullable=True)
    batch: Mapped[str | None] = mapped_column(String(40), nullable=True)

    pet = relationship("OwnedPet", back_populates="vaccinations")

    @property
    def status(self) -> VaccineStatus:
        if self.due_on is None:
            return VaccineStatus.DONE
        today = date.today()
        if self.due_on < today:
            return VaccineStatus.OVERDUE
        delta = (self.due_on - today).days
        if delta <= 30:
            return VaccineStatus.DUE
        return VaccineStatus.UPCOMING
