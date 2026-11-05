"""Add secure access codes for registration status lookup."""
from alembic import op
import sqlalchemy as sa


revision = "20261111statusaccess"
down_revision = "20261110roleauth"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("users") as batch_op:
        batch_op.add_column(
            sa.Column("registration_status_token_hash", sa.String(length=64), nullable=True)
        )


def downgrade():
    with op.batch_alter_table("users") as batch_op:
        batch_op.drop_column("registration_status_token_hash")
