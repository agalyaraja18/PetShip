"""Add care schedules, adoption agreements, and application-linked visits.

Revision ID: 20261102care
Revises: 4c6df8c1b61a
"""
from alembic import op
import sqlalchemy as sa


revision = "20261102care"
down_revision = "4c6df8c1b61a"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("owned_pets") as batch_op:
        batch_op.add_column(sa.Column("care_schedule", sa.JSON(), nullable=True))
        batch_op.add_column(sa.Column("application_id", sa.Integer(), nullable=True))
        batch_op.create_unique_constraint(
            "uq_owned_pets_application_id", ["application_id"]
        )
        batch_op.create_foreign_key(
            "fk_owned_pets_application_id_applications",
            "applications",
            ["application_id"],
            ["id"],
            ondelete="SET NULL",
        )

    with op.batch_alter_table("appointments") as batch_op:
        batch_op.add_column(sa.Column("application_id", sa.Integer(), nullable=True))
        batch_op.create_index(
            "ix_appointments_application_id", ["application_id"], unique=False
        )
        batch_op.create_foreign_key(
            "fk_appointments_application_id_applications",
            "applications",
            ["application_id"],
            ["id"],
            ondelete="SET NULL",
        )

    op.create_table(
        "adoption_agreements",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("application_id", sa.Integer(), nullable=False),
        sa.Column("file_name", sa.String(length=255), nullable=False),
        sa.Column("original_filename", sa.String(length=255), nullable=False),
        sa.Column("shelter_signature", sa.String(length=120), nullable=True),
        sa.Column("shelter_signed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("adopter_signature", sa.String(length=120), nullable=True),
        sa.Column("adopter_signed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["application_id"], ["applications.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("application_id"),
    )

    bind = op.get_bind()
    lessons = sa.Table("lessons", sa.MetaData(), autoload_with=bind)
    progress = sa.Table("lesson_progress", sa.MetaData(), autoload_with=bind)
    paths = sa.Table("learning_paths", sa.MetaData(), autoload_with=bind)
    kept_by_title = {}
    rows = bind.execute(
        sa.select(lessons.c.id, lessons.c.path_id, lessons.c.title)
        .order_by(lessons.c.path_id, lessons.c.position, lessons.c.id)
    ).mappings()
    for row in rows:
        key = (row["path_id"], (row["title"] or "").strip().casefold())
        keep_id = kept_by_title.setdefault(key, row["id"])
        if keep_id == row["id"]:
            continue
        completed_users = bind.execute(
            sa.select(progress.c.user_id).where(progress.c.lesson_id == row["id"])
        ).scalars()
        for user_id in completed_users:
            already_completed = bind.execute(
                sa.select(progress.c.id).where(
                    progress.c.user_id == user_id,
                    progress.c.lesson_id == keep_id,
                )
            ).first()
            if already_completed:
                bind.execute(
                    progress.delete().where(
                        progress.c.user_id == user_id,
                        progress.c.lesson_id == row["id"],
                    )
                )
            else:
                bind.execute(
                    progress.update()
                    .where(
                        progress.c.user_id == user_id,
                        progress.c.lesson_id == row["id"],
                    )
                    .values(lesson_id=keep_id)
                )
        bind.execute(lessons.delete().where(lessons.c.id == row["id"]))

    guidance = {
        "dog": "Use short, reward-based practice and predictable routines. Watch for stress such as turning away, panting, or a tucked tail.",
        "cat": "Provide choice, quiet hiding places, and calm repetition. Monitor appetite, water intake, litter-box habits, and activity.",
        "rabbit": "Work at floor level, offer constant hay and water, and avoid lifting unless it is necessary and safely supported.",
        "hamster": "Respect daytime sleep and allow your hamster to wake and approach before handling. Keep the habitat quiet and provide deep bedding and hides.",
        "bird": "Use an avian veterinarian for health advice and keep smoke, aerosols, and non-stick cookware fumes away from birds.",
        "first-aid": "First aid is temporary support while you contact a veterinarian. Do not give human medicines or induce vomiting unless a veterinarian instructs you.",
        "nutrition": "Choose complete food formulated for the animal's species and life stage. Measure portions and ask a veterinarian before diet changes for a medical condition.",
    }
    bird_slugs = ("parrot", "lovebird", "dove", "pigeon", "macaw")
    remaining = bind.execute(
        sa.select(lessons.c.id, lessons.c.title, lessons.c.body, paths.c.slug)
        .join(paths, lessons.c.path_id == paths.c.id)
    ).mappings()
    for row in remaining:
        body = row["body"] or ""
        if len(body) >= 250:
            continue
        slug = row["slug"]
        key = (
            "first-aid" if slug == "pet-first-aid"
            else "nutrition" if "food-diet" in slug
            else "bird" if any(word in slug for word in bird_slugs)
            else slug.split("-")[0]
        )
        species_note = guidance.get(key, guidance["dog"])
        enhanced = (
            f"{body}\n\nPut it into practice: make one small, repeatable goal for "
            f"{(row['title'] or 'this topic').lower()}. Prepare the supplies or space, "
            "practise at a calm time, and keep sessions short. Reward relaxed "
            "behaviour and stop if your pet seems frightened, uncomfortable, or unwell.\n\n"
            f"Keep a note of what you tried and how your pet responded. {species_note} "
            "If a symptom persists or you are unsure whether a product or technique "
            "is safe, ask your veterinarian."
        )
        bind.execute(
            lessons.update().where(lessons.c.id == row["id"]).values(body=enhanced)
        )


def downgrade():
    op.drop_table("adoption_agreements")
    with op.batch_alter_table("appointments") as batch_op:
        batch_op.drop_constraint(
            "fk_appointments_application_id_applications", type_="foreignkey"
        )
        batch_op.drop_index("ix_appointments_application_id")
        batch_op.drop_column("application_id")
    with op.batch_alter_table("owned_pets") as batch_op:
        batch_op.drop_constraint(
            "fk_owned_pets_application_id_applications", type_="foreignkey"
        )
        batch_op.drop_constraint("uq_owned_pets_application_id", type_="unique")
        batch_op.drop_column("application_id")
        batch_op.drop_column("care_schedule")
