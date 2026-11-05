"""Add full addresses to adopter and shelter profiles.

Revision ID: 20261109shelteraddr
Revises: 20261108return
"""
from alembic import op
import sqlalchemy as sa


revision = "20261109shelteraddr"
down_revision = "20261108return"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("shelters") as batch_op:
        batch_op.add_column(sa.Column("address", sa.String(length=300), nullable=True))


def downgrade():
    with op.batch_alter_table("shelters") as batch_op:
        batch_op.drop_column("address")
