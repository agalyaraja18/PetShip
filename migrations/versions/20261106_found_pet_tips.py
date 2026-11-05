"""Store private found-pet tips for lost-pet owners.

Revision ID: 20261106tips
Revises: 20261105feedback
"""
from alembic import op
import sqlalchemy as sa


revision = "20261106tips"
down_revision = "20261105feedback"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "found_pet_tips",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("report_id", sa.Integer(), nullable=False),
        sa.Column("reporter_id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=160), nullable=False),
        sa.Column("contact", sa.String(length=200), nullable=False),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["report_id"], ["lostfound_reports.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(["reporter_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    with op.batch_alter_table("found_pet_tips") as batch_op:
        batch_op.create_index("ix_found_pet_tips_report_id", ["report_id"])
        batch_op.create_index("ix_found_pet_tips_reporter_id", ["reporter_id"])


def downgrade():
    op.drop_table("found_pet_tips")
