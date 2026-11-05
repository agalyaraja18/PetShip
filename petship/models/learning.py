"""Pet care learning paths: paths, lessons, and per-user progress (Task 25)."""
from __future__ import annotations

from sqlalchemy import Boolean, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ..extensions import db
from .mixins import TimestampMixin


class LearningPath(TimestampMixin, db.Model):
    __tablename__ = "learning_paths"

    id: Mapped[int] = mapped_column(primary_key=True)
    slug: Mapped[str] = mapped_column(String(180), unique=True, index=True, nullable=False)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    level: Mapped[str] = mapped_column(String(40), default="Beginner", nullable=False)
    summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    duration_min: Mapped[int] = mapped_column(Integer, default=30, nullable=False)
    quiz_count: Mapped[int] = mapped_column(Integer, default=1, nullable=False)

    lessons = relationship(
        "Lesson", back_populates="path", cascade="all, delete-orphan",
        order_by="Lesson.position",
    )

    @property
    def lesson_count(self) -> int:
        return len(self.lessons)


class Lesson(TimestampMixin, db.Model):
    __tablename__ = "lessons"

    id: Mapped[int] = mapped_column(primary_key=True)
    path_id: Mapped[int] = mapped_column(
        ForeignKey("learning_paths.id", ondelete="CASCADE"), nullable=False, index=True
    )
    position: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    body: Mapped[str | None] = mapped_column(Text, nullable=True)

    path = relationship("LearningPath", back_populates="lessons")


class LessonProgress(TimestampMixin, db.Model):
    """Marks a lesson complete for a given user."""

    __tablename__ = "lesson_progress"
    __table_args__ = (
        UniqueConstraint("user_id", "lesson_id", name="uq_progress_user_lesson"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    lesson_id: Mapped[int] = mapped_column(
        ForeignKey("lessons.id", ondelete="CASCADE"), nullable=False, index=True
    )
    completed: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
