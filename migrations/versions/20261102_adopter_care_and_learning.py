"""Split adopter care schedules and improve lesson guidance.

Revision ID: 20261102plans
Revises: 20261102care
"""
from alembic import op
import sqlalchemy as sa

from petship.learning_content import lesson_body


revision = "20261102plans"
down_revision = "20261102care"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    metadata = sa.MetaData()
    owned_pets = sa.Table("owned_pets", metadata, autoload_with=bind)
    for row in bind.execute(
        sa.select(owned_pets.c.id, owned_pets.c.care_schedule)
    ).mappings():
        schedule = row["care_schedule"]
        if isinstance(schedule, dict):
            continue
        legacy_rows = schedule if isinstance(schedule, list) else []
        diet_plan = []
        routine_lines = []
        for item in legacy_rows:
            if not isinstance(item, dict):
                continue
            diet_plan.append({
                "food": str(item.get("food") or ""),
                "quantity": "",
                "time": str(item.get("time") or ""),
            })
            activity = str(item.get("activity") or "").strip()
            notes = str(item.get("notes") or "").strip()
            if activity or notes:
                routine_lines.append(" · ".join(value for value in (activity, notes) if value))
        bind.execute(
            owned_pets.update()
            .where(owned_pets.c.id == row["id"])
            .values(care_schedule={
                "diet_plan": diet_plan,
                "routine_plan": "\n".join(routine_lines),
            })
        )

    lessons = sa.Table("lessons", metadata, autoload_with=bind)
    paths = sa.Table("learning_paths", metadata, autoload_with=bind)
    rows = bind.execute(
        sa.select(lessons.c.id, lessons.c.title, lessons.c.body, paths.c.slug)
        .join(paths, lessons.c.path_id == paths.c.id)
    ).mappings()
    for row in rows:
        summary = (row["body"] or "").split("\n\n", 1)[0]
        bind.execute(
            lessons.update()
            .where(lessons.c.id == row["id"])
            .values(body=lesson_body(row["slug"], row["title"], summary))
        )


def downgrade():
    bind = op.get_bind()
    metadata = sa.MetaData()
    owned_pets = sa.Table("owned_pets", metadata, autoload_with=bind)
    for row in bind.execute(
        sa.select(owned_pets.c.id, owned_pets.c.care_schedule)
    ).mappings():
        schedule = row["care_schedule"]
        if not isinstance(schedule, dict):
            continue
        legacy_rows = [
            {
                "time": item.get("time", ""),
                "food": item.get("food", ""),
                "activity": "",
                "notes": "",
            }
            for item in schedule.get("diet_plan", [])
            if isinstance(item, dict)
        ]
        routine = schedule.get("routine_plan", "")
        if routine:
            legacy_rows.append({
                "time": "",
                "food": "",
                "activity": routine,
                "notes": "",
            })
        bind.execute(
            owned_pets.update()
            .where(owned_pets.c.id == row["id"])
            .values(care_schedule=legacy_rows)
        )
