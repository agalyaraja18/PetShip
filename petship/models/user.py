"""User account model with roles, auth, verification and reset support."""
from __future__ import annotations

import enum
from datetime import datetime, timedelta

from flask_login import UserMixin
from sqlalchemy import JSON, Boolean, DateTime, Enum, String, Text
from sqlalchemy.orm import Mapped, mapped_column
from werkzeug.security import check_password_hash, generate_password_hash

from ..extensions import db
from .mixins import TimestampMixin, utcnow

# Default notification preferences (mirrors the settings screen toggles).
DEFAULT_NOTIFICATION_PREFS = {
    "adoption_updates": True,
    "return_requests": True,
    "health_reminders": True,
    "vet_appointments": True,
    "smart_reminders": True,
    "sms_alerts": False,
}

# Lifestyle tags offered on the Edit Profile screen.
LIFESTYLE_TAGS = [
    "Apartment",
    "House with yard",
    "Has kids",
    "Works from home",
    "Has dogs",
    "Has cats",
    "First-time owner",
]


class UserRole(str, enum.Enum):
    """The four PetShip account roles."""

    ADOPTER = "adopter"
    SHELTER = "shelter"
    VET = "vet"
    ADMIN = "admin"

    @property
    def label(self) -> str:
        return {
            "adopter": "Adopter",
            "shelter": "Shelter",
            "vet": "Veterinarian",
            "admin": "Admin",
        }[self.value]


# Roles a user may self-select at registration (admin is provisioned, not signed up).
SIGNUP_ROLES = (UserRole.ADOPTER, UserRole.SHELTER, UserRole.VET)


class User(TimestampMixin, UserMixin, db.Model):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    public_id: Mapped[str | None] = mapped_column(String(24), unique=True, index=True, nullable=True)
    email: Mapped[str] = mapped_column(
        String(255), unique=True, index=True, nullable=False
    )
    password_hash: Mapped[str | None] = mapped_column(String(255), nullable=True)
    first_name: Mapped[str | None] = mapped_column(String(80), nullable=True)
    last_name: Mapped[str | None] = mapped_column(String(80), nullable=True)
    role: Mapped[UserRole] = mapped_column(
        Enum(UserRole, native_enum=False, length=20),
        default=UserRole.ADOPTER,
        nullable=False,
    )
    # Mapped column named ``is_active`` overrides UserMixin.is_active so
    # Flask-Login reflects the account's real active state (suspended users
    # cannot log in).
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    is_verified: Mapped[bool] = mapped_column(
        Boolean, default=False, nullable=False
    )
    registration_status: Mapped[str] = mapped_column(
        String(20), default="approved", nullable=False
    )
    force_password_reset: Mapped[bool] = mapped_column(
        Boolean, default=False, nullable=False
    )
    registration_status_token_hash: Mapped[str | None] = mapped_column(
        String(64), nullable=True
    )

    # OAuth linkage (Google) — set when a user signs in via a provider.
    oauth_provider: Mapped[str | None] = mapped_column(String(40), nullable=True)
    oauth_sub: Mapped[str | None] = mapped_column(String(255), nullable=True)

    # Email verification (6-digit code flow, Task 7).
    verification_code: Mapped[str | None] = mapped_column(String(12), nullable=True)
    verification_sent_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    # Password reset (Task 7).
    reset_token: Mapped[str | None] = mapped_column(
        String(255), index=True, nullable=True
    )
    reset_sent_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    # ---- Profile (Task 8) ----
    avatar_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    phone: Mapped[str | None] = mapped_column(String(40), nullable=True)
    address: Mapped[str | None] = mapped_column(String(300), nullable=True)
    city: Mapped[str | None] = mapped_column(String(120), nullable=True)
    bio: Mapped[str | None] = mapped_column(Text, nullable=True)
    lifestyle_tags: Mapped[list | None] = mapped_column(JSON, default=list, nullable=True)

    # ---- Settings (Task 8) ----
    notification_prefs: Mapped[dict | None] = mapped_column(
        JSON, default=lambda: dict(DEFAULT_NOTIFICATION_PREFS), nullable=True
    )
    two_factor_enabled: Mapped[bool] = mapped_column(
        Boolean, default=False, nullable=False
    )
    profile_is_public: Mapped[bool] = mapped_column(
        Boolean, default=True, nullable=False
    )

    # ---- Password helpers ----
    def set_password(self, password: str) -> None:
        self.password_hash = generate_password_hash(password)

    def check_password(self, password: str) -> bool:
        if not self.password_hash:
            return False
        return check_password_hash(self.password_hash, password)

    @property
    def has_password(self) -> bool:
        return bool(self.password_hash)

    # ---- Display helpers ----
    @property
    def full_name(self) -> str:
        name = " ".join(filter(None, [self.first_name, self.last_name])).strip()
        return name or self.email.split("@")[0]

    @property
    def initials(self) -> str:
        parts = [p for p in [self.first_name, self.last_name] if p]
        if parts:
            return "".join(p[0].upper() for p in parts)[:2]
        return self.email[0].upper()

    # ---- Profile / settings helpers ----
    @property
    def tags(self) -> list[str]:
        return self.lifestyle_tags or []

    def has_tag(self, tag: str) -> bool:
        return tag in (self.lifestyle_tags or [])

    @property
    def prefs(self) -> dict:
        """Notification preferences with defaults merged for missing keys."""
        merged = dict(DEFAULT_NOTIFICATION_PREFS)
        stored = self.notification_prefs or {}
        merged.update(stored)
        return merged

    # ---- Role checks ----
    @property
    def is_admin(self) -> bool:
        return self.role is UserRole.ADMIN

    def has_role(self, *roles: UserRole) -> bool:
        return self.role in roles

    # ---- Verification / reset token helpers ----
    def start_verification(self, code: str) -> None:
        self.verification_code = code
        self.verification_sent_at = utcnow()

    def verification_is_fresh(self, max_age: timedelta = timedelta(minutes=15)) -> bool:
        if not self.verification_sent_at:
            return False
        sent = self.verification_sent_at
        if sent.tzinfo is None:
            from datetime import timezone

            sent = sent.replace(tzinfo=timezone.utc)
        return utcnow() - sent <= max_age

    def start_reset(self, token: str) -> None:
        self.reset_token = token
        self.reset_sent_at = utcnow()

    def reset_is_fresh(self, max_age: timedelta = timedelta(hours=1)) -> bool:
        if not self.reset_sent_at:
            return False
        sent = self.reset_sent_at
        if sent.tzinfo is None:
            from datetime import timezone

            sent = sent.replace(tzinfo=timezone.utc)
        return utcnow() - sent <= max_age

    def clear_reset(self) -> None:
        self.reset_token = None
        self.reset_sent_at = None

    def __repr__(self) -> str:  # pragma: no cover - debug helper
        return f"<User {self.id} {self.email} ({self.role.value})>"
