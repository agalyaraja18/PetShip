"""Track whether shelter visit times are stored in UTC."""
from alembic import op
import sqlalchemy as sa


revision = "20261112visitutc"
down_revision = "20261111statusaccess"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("shelters") as batch_op:
        batch_op.add_column(
            sa.Column(
                "verification_visit_time_is_utc",
                sa.Boolean(),
                nullable=False,
                server_default=sa.false(),
            )
        )


def downgrade():
    with op.batch_alter_table("shelters") as batch_op:
        batch_op.drop_column("verification_visit_time_is_utc")
