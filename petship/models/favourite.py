"""Favourite (wishlist) join model between a user and a pet."""
from __future__ import annotations

from sqlalchemy import ForeignKey, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ..extensions import db
from .mixins import TimestampMixin


class Favourite(TimestampMixin, db.Model):
    __tablename__ = "favourites"
    __table_args__ = (
        UniqueConstraint("user_id", "pet_id", name="uq_favourite_user_pet"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    pet_id: Mapped[int] = mapped_column(
        ForeignKey("pets.id", ondelete="CASCADE"), nullable=False, index=True
    )

    user = relationship("User", backref="favourites")
    pet = relationship("Pet")
