"""Reminder and Notification models (Task 24).

Reminders are user-created care tasks (feeding, medication, grooming, vet) with
optional recurrence. The scheduler (APScheduler) materialises due reminders
into Notifications. Notifications are also used by the in-app notification
centre and bell dropdown (Task 32).
"""
from __future__ import annotations

import enum
from datetime import date, time as dt_time

from sqlalchemy import Boolean, Date, Enum, ForeignKey, String, Time
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ..extensions import db
from .mixins import TimestampMixin


class Recurrence(str, enum.Enum):
    ONCE = "once"
    DAILY = "daily"
    WEEKLY = "weekly"
    MONTHLY = "monthly"

    @property
    def label(self) -> str:
        return self.value.capitalize()


class Reminder(TimestampMixin, db.Model):
    __tablename__ = "reminders"

    id: Mapped[int] = mapped_column(primary_key=True)
    owner_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    pet_id: Mapped[int | None] = mapped_column(
        ForeignKey("owned_pets.id", ondelete="CASCADE"), nullable=True, index=True
    )

    title: Mapped[str] = mapped_column(String(160), nullable=False)
    category: Mapped[str] = mapped_column(String(40), default="care", nullable=False)
    recurrence: Mapped[Recurrence] = mapped_column(
        Enum(Recurrence, native_enum=False, length=20),
        default=Recurrence.ONCE,
        nullable=False,
    )
    at_time: Mapped[dt_time | None] = mapped_column(Time, nullable=True)
    next_due: Mapped[date | None] = mapped_column(Date, nullable=True, index=True)
    done: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    # Timestamp of the last notification we emitted (dedupe guard).
    last_notified_on: Mapped[date | None] = mapped_column(Date, nullable=True)

    pet = relationship("OwnedPet")

    def advance(self) -> None:
        """Move ``next_due`` forward by the recurrence interval, or mark done
        for one-off reminders."""
        from datetime import timedelta

        if self.recurrence == Recurrence.ONCE or self.next_due is None:
            self.done = True
            return
        step = {
            Recurrence.DAILY: timedelta(days=1),
            Recurrence.WEEKLY: timedelta(weeks=1),
            Recurrence.MONTHLY: timedelta(days=30),
        }[self.recurrence]
        self.next_due = self.next_due + step
        # Recurring reminders roll forward and stay active.
        self.done = False


class Notification(TimestampMixin, db.Model):
    __tablename__ = "notifications"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    category: Mapped[str] = mapped_column(String(40), default="general", nullable=False)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    body: Mapped[str | None] = mapped_column(String(400), nullable=True)
    link: Mapped[str | None] = mapped_column(String(300), nullable=True)
    read: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False, index=True)

    @staticmethod
    def push(user_id: int, title: str, body: str | None = None,
             category: str = "general", link: str | None = None) -> "Notification":
        n = Notification(user_id=user_id, title=title, body=body,
                         category=category, link=link)
        db.session.add(n)
        return n
