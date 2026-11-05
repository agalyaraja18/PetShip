"""Allow public feedback and track admin handling.

Revision ID: 20261105feedback
Revises: 20261104platform
"""
from alembic import op
import sqlalchemy as sa


revision = "20261105feedback"
down_revision = "20261104platform"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("platform_feedback") as batch_op:
        batch_op.alter_column(
            "user_id",
            existing_type=sa.Integer(),
            nullable=True,
        )
        batch_op.add_column(
            sa.Column("handled", sa.Boolean(), nullable=False, server_default=sa.false())
        )
    with op.batch_alter_table("platform_feedback") as batch_op:
        batch_op.alter_column("handled", server_default=None)


def downgrade():
    bind = op.get_bind()
    feedback = sa.table(
        "platform_feedback",
        sa.column("user_id", sa.Integer()),
    )
    bind.execute(feedback.delete().where(feedback.c.user_id.is_(None)))
    with op.batch_alter_table("platform_feedback") as batch_op:
        batch_op.drop_column("handled")
        batch_op.alter_column(
            "user_id",
            existing_type=sa.Integer(),
            nullable=False,
        )
