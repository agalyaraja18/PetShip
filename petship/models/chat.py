"""AI chatbot conversation + message models (Task 28)."""
from __future__ import annotations

from sqlalchemy import Boolean, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ..extensions import db
from .mixins import TimestampMixin


class Conversation(TimestampMixin, db.Model):
    """A single Pawly chat thread for a user, optionally about one pet."""

    __tablename__ = "conversations"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    pet_id: Mapped[int | None] = mapped_column(
        ForeignKey("owned_pets.id", ondelete="SET NULL"), nullable=True
    )
    title: Mapped[str] = mapped_column(String(200), default="New chat", nullable=False)
    topic: Mapped[str | None] = mapped_column(String(40), nullable=True)
    saved: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    pet = relationship("OwnedPet")
    messages = relationship(
        "ChatMessage",
        back_populates="conversation",
        cascade="all, delete-orphan",
        order_by="ChatMessage.id",
    )

    @property
    def preview(self) -> str:
        if self.messages:
            return (self.messages[-1].content or "")[:80]
        return "No messages yet."


class ChatMessage(TimestampMixin, db.Model):
    __tablename__ = "chat_messages"

    id: Mapped[int] = mapped_column(primary_key=True)
    conversation_id: Mapped[int] = mapped_column(
        ForeignKey("conversations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    # "user" or "assistant"
    role: Mapped[str] = mapped_column(String(20), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)

    conversation = relationship("Conversation", back_populates="messages")
