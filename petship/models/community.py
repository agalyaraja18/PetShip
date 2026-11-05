"""Community models: posts, comments, likes, follows (Task 30).

Reports/abuse (Task 31) and reviews (already in review.py) round out the
community domain.
"""
from __future__ import annotations

from sqlalchemy import Boolean, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ..extensions import db
from .mixins import TimestampMixin

POST_TOPICS = [
    "New adopters",
    "Show & tell",
    "Health & vet",
    "Training",
    "Nutrition",
    "Cats",
    "Dogs",
    "Small pets",
]


class Post(TimestampMixin, db.Model):
    __tablename__ = "posts"

    id: Mapped[int] = mapped_column(primary_key=True)
    author_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    title: Mapped[str | None] = mapped_column(String(200), nullable=True)
    topic: Mapped[str] = mapped_column(String(40), default="Show & tell", nullable=False, index=True)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    photos: Mapped[list | None] = mapped_column(db.JSON, default=list)
    edited: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    hidden: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    author = relationship("User")
    comments = relationship(
        "Comment", back_populates="post", cascade="all, delete-orphan",
        order_by="Comment.id",
    )
    likes = relationship("PostLike", back_populates="post", cascade="all, delete-orphan")

    @property
    def like_count(self) -> int:
        return len(self.likes)

    @property
    def comment_count(self) -> int:
        return len(self.comments)


class Comment(TimestampMixin, db.Model):
    __tablename__ = "comments"

    id: Mapped[int] = mapped_column(primary_key=True)
    post_id: Mapped[int] = mapped_column(
        ForeignKey("posts.id", ondelete="CASCADE"), nullable=False, index=True
    )
    author_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    parent_id: Mapped[int | None] = mapped_column(
        ForeignKey("comments.id", ondelete="CASCADE"), nullable=True
    )
    body: Mapped[str] = mapped_column(Text, nullable=False)
    hidden: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    post = relationship("Post", back_populates="comments")
    author = relationship("User")


class PostLike(TimestampMixin, db.Model):
    __tablename__ = "post_likes"
    __table_args__ = (
        UniqueConstraint("post_id", "user_id", name="uq_like_post_user"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    post_id: Mapped[int] = mapped_column(
        ForeignKey("posts.id", ondelete="CASCADE"), nullable=False, index=True
    )
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )

    post = relationship("Post", back_populates="likes")


class Follow(TimestampMixin, db.Model):
    __tablename__ = "follows"
    __table_args__ = (
        UniqueConstraint("follower_id", "following_id", name="uq_follow"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    follower_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    following_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
