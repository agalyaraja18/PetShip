"""Adoption application model with a staged status timeline (Task 13)."""
from __future__ import annotations

import enum
from datetime import datetime

from sqlalchemy import JSON, DateTime, Enum, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ..extensions import db
from .mixins import TimestampMixin


class ApplicationStage(str, enum.Enum):
    """Ordered stages of an adoption application."""

    DRAFT = "draft"
    SUBMITTED = "submitted"
    REVIEW = "review"
    CONFIRMED = "confirmed"
    HOME_VISIT = "home_visit"
    AGREEMENT = "agreement"
    COMPLETE = "complete"
    DECLINED = "declined"

    @property
    def label(self) -> str:
        return {
            "draft": "Draft",
            "submitted": "Application submitted",
            "review": "Application review",
            "confirmed": "Application confirmed",
            "home_visit": "Home visit",
            "agreement": "Adoption agreement",
            "complete": "Welcome home",
            "declined": "Declined",
        }[self.value]


class ReturnStatus(str, enum.Enum):
    SUBMITTED = "submitted"
    SHELTER_REVIEW = "shelter_review"
    SHELTER_CONFIRMED = "shelter_confirmed"
    RETURN_VISIT = "return_visit"
    RETURNED_SHELTER = "returned_shelter"

    @property
    def label(self) -> str:
        return {
            "submitted": "Return submitted",
            "shelter_review": "Shelter review",
            "shelter_confirmed": "Shelter confirmed",
            "return_visit": "Return visit",
            "returned_shelter": "Returned shelter",
        }[self.value]


# The linear progression shown on the tracking stepper (excludes draft/declined).
TIMELINE_STAGES = [
    ApplicationStage.SUBMITTED,
    ApplicationStage.REVIEW,
    ApplicationStage.CONFIRMED,
    ApplicationStage.HOME_VISIT,
    ApplicationStage.AGREEMENT,
    ApplicationStage.COMPLETE,
]


class Application(TimestampMixin, db.Model):
    __tablename__ = "applications"

    id: Mapped[int] = mapped_column(primary_key=True)
    reference: Mapped[str] = mapped_column(String(20), unique=True, index=True, nullable=False)

    applicant_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    pet_id: Mapped[int] = mapped_column(
        ForeignKey("pets.id", ondelete="CASCADE"), nullable=False, index=True
    )

    stage: Mapped[ApplicationStage] = mapped_column(
        Enum(ApplicationStage, native_enum=False, length=20),
        default=ApplicationStage.DRAFT,
        nullable=False,
        index=True,
    )
    # Wizard answers kept as JSON so the form can evolve without migrations.
    answers: Mapped[dict | None] = mapped_column(JSON, default=dict)
    # Highest wizard step reached (for resuming drafts): 1..4.
    step: Mapped[int] = mapped_column(Integer, default=1, nullable=False)

    home_visit_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    adopted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    returned_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    return_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    return_status: Mapped[str | None] = mapped_column(String(30), nullable=True)
    return_requested_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    return_visit_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    applicant = relationship("User", backref="applications")
    pet = relationship("Pet")
    agreement = relationship(
        "AdoptionAgreement", back_populates="application", uselist=False,
        cascade="all, delete-orphan",
    )
    owned_pet = relationship("OwnedPet", back_populates="application", uselist=False)
    followups = relationship(
        "FollowUp", back_populates="application", cascade="all, delete-orphan"
    )

    # ---- Stage helpers ----
    @property
    def current_index(self) -> int:
        """0-based index into TIMELINE_STAGES, or the last if complete."""
        if self.stage in (ApplicationStage.DRAFT, ApplicationStage.DECLINED):
            return 0
        return TIMELINE_STAGES.index(self.stage)

    @property
    def step_number(self) -> int:
        """1-based stage number shown in the six-step application tracker."""
        return self.current_index + 1

    def advance(self) -> None:
        idx = self.current_index
        if self.stage == ApplicationStage.DRAFT:
            self.stage = ApplicationStage.SUBMITTED
        elif idx < len(TIMELINE_STAGES) - 1:
            self.stage = TIMELINE_STAGES[idx + 1]

    def submit_return(self, reason: str, requested_at: datetime) -> None:
        self.return_reason = reason
        self.return_status = ReturnStatus.SUBMITTED.value
        self.return_requested_at = requested_at

    def mark_returned(self, returned_at: datetime) -> None:
        self.return_status = ReturnStatus.RETURNED_SHELTER.value
        self.returned_at = returned_at
        self.pet.publish()

    def __repr__(self) -> str:  # pragma: no cover
        return f"<Application {self.reference} {self.stage.value}>"


class AdoptionAgreement(TimestampMixin, db.Model):
    """Shelter-uploaded agreement and both parties' electronic signatures."""

    __tablename__ = "adoption_agreements"

    id: Mapped[int] = mapped_column(primary_key=True)
    application_id: Mapped[int] = mapped_column(
        ForeignKey("applications.id", ondelete="CASCADE"),
        unique=True,
        nullable=False,
    )
    file_name: Mapped[str] = mapped_column(String(255), nullable=False)
    original_filename: Mapped[str] = mapped_column(String(255), nullable=False)
    shelter_signature: Mapped[str | None] = mapped_column(String(120), nullable=True)
    shelter_signed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    adopter_signature: Mapped[str | None] = mapped_column(String(120), nullable=True)
    adopter_signed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    application = relationship("Application", back_populates="agreement")

    @property
    def is_fully_signed(self) -> bool:
        return bool(self.shelter_signature and self.adopter_signature)
