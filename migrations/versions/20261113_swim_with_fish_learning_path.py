"""Add the Swim with Fish learning path.

Revision ID: 20261113fishpath
Revises: 20261112visitutc
"""
from datetime import datetime, timezone

from alembic import op
import sqlalchemy as sa

from petship.learning_content import lesson_body


revision = "20261113fishpath"
down_revision = "20261112visitutc"
branch_labels = None
depends_on = None


LESSONS = [
    (
        "Setting up a safe aquarium",
        "Choose a suitable tank and cycle it before adding fish.",
    ),
    (
        "Keeping water healthy",
        "Test water regularly and make gradual, partial changes.",
    ),
    (
        "Choosing compatible fish",
        "Research adult size, temperament, and tank needs before combining species.",
    ),
    (
        "Feeding aquarium fish",
        "Offer an appropriate amount of species-specific food and remove leftovers.",
    ),
    (
        "Recognising fish health changes",
        "Observe swimming, appetite, breathing, and appearance each day.",
    ),
]


def upgrade():
    bind = op.get_bind()
    metadata = sa.MetaData()
    paths = sa.Table("learning_paths", metadata, autoload_with=bind)
    lessons = sa.Table("lessons", metadata, autoload_with=bind)

    path_id = bind.execute(
        sa.select(paths.c.id).where(paths.c.slug == "swim-with-fish")
    ).scalar_one_or_none()
    if path_id is not None:
        return

    now = datetime.now(timezone.utc)
    path_id = bind.execute(
        paths.insert().values(
            slug="swim-with-fish",
            title="Swim with Fish",
            level="Beginner",
            summary="Learn the essentials of setting up and caring for healthy aquarium fish.",
            duration_min=40,
            quiz_count=1,
            created_at=now,
            updated_at=now,
        )
    ).inserted_primary_key[0]

    bind.execute(
        lessons.insert(),
        [
            {
                "path_id": path_id,
                "position": position,
                "title": title,
                "body": lesson_body("swim-with-fish", title, summary),
                "created_at": now,
                "updated_at": now,
            }
            for position, (title, summary) in enumerate(LESSONS, start=1)
        ],
    )


def downgrade():
    bind = op.get_bind()
    metadata = sa.MetaData()
    paths = sa.Table("learning_paths", metadata, autoload_with=bind)
    lessons = sa.Table("lessons", metadata, autoload_with=bind)
    progress = sa.Table("lesson_progress", metadata, autoload_with=bind)

    path_id = bind.execute(
        sa.select(paths.c.id).where(paths.c.slug == "swim-with-fish")
    ).scalar_one_or_none()
    if path_id is None:
        return

    lesson_ids = sa.select(lessons.c.id).where(lessons.c.path_id == path_id)
    bind.execute(progress.delete().where(progress.c.lesson_id.in_(lesson_ids)))
    bind.execute(lessons.delete().where(lessons.c.path_id == path_id))
    bind.execute(paths.delete().where(paths.c.id == path_id))
