"""Add purpose to scheduled next visits.

Revision ID: 20261104visitpurpose
Revises: 20261114vetplans
"""
from alembic import op
import sqlalchemy as sa


revision = "20261104visitpurpose"
down_revision = "20261114vetplans"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "health_plans",
        sa.Column("next_visit_purpose", sa.String(length=200), nullable=True),
    )


def downgrade():
    op.drop_column("health_plans", "next_visit_purpose")
