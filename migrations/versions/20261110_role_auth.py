"""Add role-specific login identifiers and registration review fields.

Revision ID: 20261110roleauth
Revises: 20261109shelteraddr
"""
from alembic import op
import sqlalchemy as sa


revision = "20261110roleauth"
down_revision = "20261109shelteraddr"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("users") as batch_op:
        batch_op.add_column(sa.Column("address", sa.String(length=300), nullable=True))
        batch_op.add_column(sa.Column("public_id", sa.String(length=24), nullable=True))
        batch_op.add_column(
            sa.Column(
                "registration_status",
                sa.String(length=20),
                nullable=False,
                server_default="approved",
            )
        )
        batch_op.add_column(
            sa.Column(
                "force_password_reset",
                sa.Boolean(),
                nullable=False,
                server_default=sa.false(),
            )
        )
        batch_op.create_index("ix_users_public_id", ["public_id"], unique=True)

    users = sa.table(
        "users",
        sa.column("id", sa.Integer()),
        sa.column("role", sa.String()),
        sa.column("public_id", sa.String()),
    )
    bind = op.get_bind()
    prefixes = {
        "adopter": "ADP",
        "shelter": "SHL",
        "vet": "VET",
        "admin": "ADM",
    }
    for row in bind.execute(sa.select(users.c.id, users.c.role)).mappings():
        prefix = prefixes.get(str(row["role"]).lower(), "USR")
        bind.execute(
            users.update()
            .where(users.c.id == row["id"])
            .values(public_id=f"{prefix}-{row['id']:08d}")
        )

    with op.batch_alter_table("shelters") as batch_op:
        batch_op.add_column(sa.Column("registration_photos", sa.JSON(), nullable=True))
        batch_op.add_column(
            sa.Column("verification_visit_at", sa.DateTime(timezone=True), nullable=True)
        )
        batch_op.add_column(
            sa.Column(
                "verification_visit_completed_at",
                sa.DateTime(timezone=True),
                nullable=True,
            )
        )

    with op.batch_alter_table("vet_profiles") as batch_op:
        batch_op.add_column(sa.Column("certificate_url", sa.String(length=500), nullable=True))


def downgrade():
    with op.batch_alter_table("vet_profiles") as batch_op:
        batch_op.drop_column("certificate_url")
    with op.batch_alter_table("shelters") as batch_op:
        batch_op.drop_column("verification_visit_completed_at")
        batch_op.drop_column("verification_visit_at")
        batch_op.drop_column("registration_photos")
    with op.batch_alter_table("users") as batch_op:
        batch_op.drop_index("ix_users_public_id")
        batch_op.drop_column("force_password_reset")
        batch_op.drop_column("registration_status")
        batch_op.drop_column("public_id")
        batch_op.drop_column("address")
