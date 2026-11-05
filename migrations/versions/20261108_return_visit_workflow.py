"""Track return requests through shelter review and collection.

Revision ID: 20261108return
Revises: 20261107returns
"""
from alembic import op
import sqlalchemy as sa


revision = "20261108return"
down_revision = "20261107returns"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("applications") as batch_op:
        batch_op.add_column(sa.Column("return_status", sa.String(length=30), nullable=True))
        batch_op.add_column(sa.Column("return_requested_at", sa.DateTime(timezone=True), nullable=True))
        batch_op.add_column(sa.Column("return_visit_at", sa.DateTime(timezone=True), nullable=True))

    applications = sa.table(
        "applications",
        sa.column("returned_at", sa.DateTime(timezone=True)),
        sa.column("return_status", sa.String(length=30)),
        sa.column("return_requested_at", sa.DateTime(timezone=True)),
    )
    op.get_bind().execute(
        applications.update()
        .where(applications.c.returned_at.is_not(None))
        .values(
            return_status="returned_shelter",
            return_requested_at=applications.c.returned_at,
        )
    )


def downgrade():
    with op.batch_alter_table("applications") as batch_op:
        batch_op.drop_column("return_visit_at")
        batch_op.drop_column("return_requested_at")
        batch_op.drop_column("return_status")
