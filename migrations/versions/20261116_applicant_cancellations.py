"""Distinguish adopter-cancelled applications from shelter declines.

Revision ID: 20261116cancelled
Revises: 20261115returntz
"""
from alembic import op
import sqlalchemy as sa


revision = "20261116cancelled"
down_revision = "20261115returntz"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("applications") as batch_op:
        batch_op.add_column(
            sa.Column(
                "applicant_cancelled",
                sa.Boolean(),
                nullable=False,
                server_default=sa.false(),
            )
        )

    applications = sa.table(
        "applications",
        sa.column("id", sa.Integer()),
        sa.column("reference", sa.String()),
        sa.column("applicant_id", sa.Integer()),
        sa.column("applicant_cancelled", sa.Boolean()),
    )
    notifications = sa.table(
        "notifications",
        sa.column("user_id", sa.Integer()),
        sa.column("category", sa.String()),
        sa.column("body", sa.String()),
    )
    cancellation_notice = sa.exists(
        sa.select(1)
        .select_from(notifications)
        .where(
            notifications.c.user_id == applications.c.applicant_id,
            notifications.c.category == "adoption",
            notifications.c.body.like(
                sa.literal("%")
                + applications.c.reference
                + sa.literal("% was cancelled by you.")
            ),
        )
    )
    op.get_bind().execute(
        applications.update()
        .where(cancellation_notice)
        .values(applicant_cancelled=True)
    )


def downgrade():
    with op.batch_alter_table("applications") as batch_op:
        batch_op.drop_column("applicant_cancelled")
