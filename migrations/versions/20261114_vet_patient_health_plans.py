"""Add linked vet patients and shareable health plans.

Revision ID: 20261114vetplans
Revises: 20261113fishpath
"""
from alembic import op
import sqlalchemy as sa


revision = "20261114vetplans"
down_revision = "20261113fishpath"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "vet_patients",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("vet_id", sa.Integer(), nullable=False),
        sa.Column("pet_id", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["vet_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["pet_id"], ["owned_pets.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("vet_id", "pet_id", name="uq_vet_patient"),
    )
    op.create_index("ix_vet_patients_vet_id", "vet_patients", ["vet_id"])
    op.create_index("ix_vet_patients_pet_id", "vet_patients", ["pet_id"])

    op.create_table(
        "health_plans",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("pet_id", sa.Integer(), nullable=False),
        sa.Column("vet_id", sa.Integer(), nullable=True),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("instructions", sa.Text(), nullable=True),
        sa.Column("prescribed_medicines", sa.Text(), nullable=True),
        sa.Column("next_visit_on", sa.Date(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["pet_id"], ["owned_pets.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["vet_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_health_plans_pet_id", "health_plans", ["pet_id"])
    op.create_index("ix_health_plans_vet_id", "health_plans", ["vet_id"])
    op.create_index("ix_health_plans_next_visit_on", "health_plans", ["next_visit_on"])


def downgrade():
    op.drop_index("ix_health_plans_next_visit_on", table_name="health_plans")
    op.drop_index("ix_health_plans_vet_id", table_name="health_plans")
    op.drop_index("ix_health_plans_pet_id", table_name="health_plans")
    op.drop_table("health_plans")
    op.drop_index("ix_vet_patients_pet_id", table_name="vet_patients")
    op.drop_index("ix_vet_patients_vet_id", table_name="vet_patients")
    op.drop_table("vet_patients")
