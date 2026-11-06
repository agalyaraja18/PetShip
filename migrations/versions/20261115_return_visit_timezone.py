"""Store the timezone used to schedule return visits.

Revision ID: 20261115returntz
Revises: 20261105prescription
"""
from alembic import op
import sqlalchemy as sa


revision = "20261115returntz"
down_revision = "20261105prescription"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("applications") as batch_op:
        batch_op.add_column(
            sa.Column("return_visit_timezone", sa.String(length=64), nullable=True)
        )


def downgrade():
    with op.batch_alter_table("applications") as batch_op:
        batch_op.drop_column("return_visit_timezone")
