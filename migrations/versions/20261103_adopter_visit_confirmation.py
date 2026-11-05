"""Track adopter availability confirmation for home visits.

Revision ID: 20261103visit
Revises: 20261102plans
"""
from alembic import op
import sqlalchemy as sa


revision = "20261103visit"
down_revision = "20261102plans"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("appointments") as batch_op:
        batch_op.add_column(
            sa.Column("adopter_confirmed", sa.Boolean(), nullable=False, server_default=sa.false())
        )
    with op.batch_alter_table("appointments") as batch_op:
        batch_op.alter_column("adopter_confirmed", server_default=None)


def downgrade():
    with op.batch_alter_table("appointments") as batch_op:
        batch_op.drop_column("adopter_confirmed")
