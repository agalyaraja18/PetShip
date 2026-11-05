"""Schedule 7/15/30-day adoption check-ins and track returns.

Revision ID: 20261107returns
Revises: 20261106tips
"""
from datetime import timedelta, timezone

from alembic import op
import sqlalchemy as sa


revision = "20261107returns"
down_revision = "20261106tips"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("applications") as batch_op:
        batch_op.add_column(sa.Column("adopted_at", sa.DateTime(timezone=True), nullable=True))
        batch_op.add_column(sa.Column("returned_at", sa.DateTime(timezone=True), nullable=True))
        batch_op.add_column(sa.Column("return_reason", sa.Text(), nullable=True))

    bind = op.get_bind()
    applications = sa.table(
        "applications",
        sa.column("id", sa.Integer()),
        sa.column("stage", sa.String()),
        sa.column("updated_at", sa.DateTime(timezone=True)),
        sa.column("adopted_at", sa.DateTime(timezone=True)),
    )
    followups = sa.table(
        "followups",
        sa.column("id", sa.Integer()),
        sa.column("application_id", sa.Integer()),
        sa.column("milestone", sa.String()),
        sa.column("due_on", sa.DateTime(timezone=True)),
        sa.column("status", sa.String()),
        sa.column("created_at", sa.DateTime(timezone=True)),
        sa.column("updated_at", sa.DateTime(timezone=True)),
    )
    completed = bind.execute(
        sa.select(
            applications.c.id,
            applications.c.updated_at,
            applications.c.adopted_at,
        ).where(applications.c.stage.in_(("COMPLETE", "complete")))
    ).mappings().all()
    for application in completed:
        adopted_at = application["adopted_at"] or application["updated_at"]
        if adopted_at.tzinfo is None:
            adopted_at = adopted_at.replace(tzinfo=timezone.utc)
        if application["adopted_at"] is None:
            bind.execute(
                applications.update()
                .where(applications.c.id == application["id"])
                .values(adopted_at=adopted_at)
            )

        existing = bind.execute(
            sa.select(followups).where(
                followups.c.application_id == application["id"]
            )
        ).mappings().all()
        scheduled = {}
        for item in existing:
            milestone_key = (item["milestone"] or "").strip().lower()
            status = (item["status"] or "").lower()
            if status != "due":
                continue
            days = {
                "1 week": 7,
                "7 days": 7,
                "1 month": 30,
                "30 days": 30,
            }.get(milestone_key)
            if days is None:
                bind.execute(followups.delete().where(followups.c.id == item["id"]))
                continue
            milestone = f"{days} days"
            due_on = adopted_at + timedelta(days=days)
            bind.execute(
                followups.update()
                .where(followups.c.id == item["id"])
                .values(milestone=milestone, due_on=due_on)
            )
            scheduled[milestone] = True

        for milestone, days in (("7 days", 7), ("15 days", 15), ("30 days", 30)):
            if milestone not in scheduled:
                bind.execute(
                    followups.insert().values(
                        application_id=application["id"],
                        milestone=milestone,
                        due_on=adopted_at + timedelta(days=days),
                        status="DUE",
                        created_at=adopted_at,
                        updated_at=adopted_at,
                    )
                )


def downgrade():
    with op.batch_alter_table("applications") as batch_op:
        batch_op.drop_column("return_reason")
        batch_op.drop_column("returned_at")
        batch_op.drop_column("adopted_at")
