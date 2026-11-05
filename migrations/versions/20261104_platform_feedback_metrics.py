"""Add platform feedback and metric event storage.

Revision ID: 20261104platform
Revises: 20261103visit
"""
from alembic import op
import sqlalchemy as sa


revision = "20261104platform"
down_revision = "20261103visit"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "platform_feedback",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=160), nullable=False),
        sa.Column("rating", sa.Integer(), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    with op.batch_alter_table("platform_feedback") as batch_op:
        batch_op.create_index("ix_platform_feedback_user_id", ["user_id"])

    op.create_table(
        "platform_metric_events",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("event_type", sa.String(length=40), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    with op.batch_alter_table("platform_metric_events") as batch_op:
        batch_op.create_index("ix_platform_metric_events_event_type", ["event_type"])
        batch_op.create_index("ix_platform_metric_events_user_id", ["user_id"])


def downgrade():
    op.drop_table("platform_metric_events")
    op.drop_table("platform_feedback")
