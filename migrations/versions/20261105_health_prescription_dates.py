"""Add prescription duration dates to health plans.

Revision ID: 20261105prescription
Revises: 20261104visitpurpose
"""
from alembic import op
import sqlalchemy as sa


revision = "20261105prescription"
down_revision = "20261104visitpurpose"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("health_plans") as batch_op:
        batch_op.add_column(sa.Column("prescription_start_on", sa.Date(), nullable=True))
        batch_op.add_column(sa.Column("prescription_end_on", sa.Date(), nullable=True))
    op.create_index("ix_health_plans_prescription_start_on", "health_plans", ["prescription_start_on"])
    op.create_index("ix_health_plans_prescription_end_on", "health_plans", ["prescription_end_on"])


def downgrade():
    op.drop_index("ix_health_plans_prescription_end_on", table_name="health_plans")
    op.drop_index("ix_health_plans_prescription_start_on", table_name="health_plans")
    with op.batch_alter_table("health_plans") as batch_op:
        batch_op.drop_column("prescription_end_on")
        batch_op.drop_column("prescription_start_on")
