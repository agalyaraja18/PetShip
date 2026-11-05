"""Direct messaging models for real-time chat (Task 32)."""
from __future__ import annotations

from sqlalchemy import Boolean, ForeignKey, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ..extensions import db
from .mixins import TimestampMixin


class Thread(TimestampMixin, db.Model):
    """A 1:1 conversation between two users."""

    __tablename__ = "message_threads"
    __table_args__ = (
        UniqueConstraint("user_a_id", "user_b_id", name="uq_thread_pair"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    # Stored with user_a_id < user_b_id so a pair maps to one thread.
    user_a_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    user_b_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    subject: Mapped[str | None] = mapped_column(String(200), nullable=True)

    messages = relationship(
        "Message", back_populates="thread", cascade="all, delete-orphan",
        order_by="Message.id",
    )

    def other(self, user_id: int):
        from .user import User

        other_id = self.user_b_id if self.user_a_id == user_id else self.user_a_id
        return db.session.get(User, other_id)

    @property
    def last_message(self):
        return self.messages[-1] if self.messages else None


class Message(TimestampMixin, db.Model):
    __tablename__ = "messages"

    id: Mapped[int] = mapped_column(primary_key=True)
    thread_id: Mapped[int] = mapped_column(
        ForeignKey("message_threads.id", ondelete="CASCADE"), nullable=False, index=True
    )
    sender_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    body: Mapped[str] = mapped_column(Text, nullable=False)
    image_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    read: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    thread = relationship("Thread", back_populates="messages")
