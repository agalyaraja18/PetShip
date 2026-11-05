"""Learning paths + emergency vet finder (Task 25)."""
from __future__ import annotations

from flask import Blueprint, abort, redirect, render_template, url_for
from flask_login import current_user, login_required

from ..extensions import db
from ..models.learning import LearningPath, Lesson, LessonProgress
from ..models.lifestyle import Place, PlaceCategory

learning_bp = Blueprint("learning", __name__, url_prefix="/lifestyle")

LEARNING_PATH_COVERS = {
    "dog-parent": ("img/pets/blog_adoption.jpg", "Two dogs enjoying time together"),
    "cat-parent": ("img/pets/blog_health.jpg", "Orange cat looking up"),
    "rabbit-bonding": ("img/pets/blog_care.jpg", "White rabbit outdoors"),
    "swim-with-fish": ("img/learning/fish.png", "Clownfish swimming underwater"),
    "hamster-care": ("img/learning/hamster.png", "Hamster standing upright"),
    "parrot-care": ("img/learning/parrot.png", "Green parrot perched on a branch"),
    "lovebirds": ("img/learning/lovebirds.png", "Pair of yellow lovebirds"),
    "doves": ("img/learning/dove.png", "Dove perched among greenery"),
    "pigeons": ("img/learning/dove.png", "Dove perched among greenery"),
    "macaws": ("img/learning/macaw.png", "Red macaw in flight"),
    "pet-first-aid": ("img/learning/first-aid.png", "Veterinarian examining a dog"),
    "paws-food-diet": ("img/learning/dog-nutrition.png", "Puppy eating from a food bowl"),
    "claws-food-diet": ("img/learning/cat-nutrition.png", "Cat beside a balanced meal"),
}


def _completed_lesson_ids() -> set[int]:
    rows = db.session.scalars(
        db.select(LessonProgress.lesson_id).filter_by(
            user_id=current_user.id, completed=True
        )
    ).all()
    return set(rows)


def _path_progress(path: LearningPath, done_ids: set[int]) -> int:
    lessons = _unique_lessons(path)
    if not lessons:
        return 0
    done = sum(1 for lesson in lessons if lesson.id in done_ids)
    return round(100 * done / len(lessons))


def _unique_lessons(path: LearningPath) -> list[Lesson]:
    seen_titles: set[str] = set()
    lessons = []
    for lesson in path.lessons:
        title_key = lesson.title.strip().casefold()
        if title_key not in seen_titles:
            seen_titles.add(title_key)
            lessons.append(lesson)
    return lessons


# ---- Learning paths ----
@learning_bp.route("/learning")
@login_required
def paths():
    all_paths = db.session.scalars(
        db.select(LearningPath).order_by(LearningPath.id)
    ).all()
    done_ids = _completed_lesson_ids()
    cards = [
        {
            "path": p,
            "progress": _path_progress(p, done_ids),
            "cover_image": LEARNING_PATH_COVERS.get(
                p.slug, ("img/pets/blog_adoption.jpg", "Pet care learning path")
            ),
        }
        for p in all_paths
    ]
    # "Continue learning" = the first in-progress path, else the first path.
    in_progress = next((c for c in cards if 0 < c["progress"] < 100), None)
    resume = in_progress or (cards[0] if cards else None)
    return render_template(
        "lifestyle/learning.html", cards=cards, resume=resume, active_nav="learning"
    )


@learning_bp.route("/learning/<slug>")
@login_required
def path_detail(slug: str):
    path = db.session.scalar(db.select(LearningPath).filter_by(slug=slug))
    if path is None:
        abort(404)
    done_ids = _completed_lesson_ids()

    unique_lessons = _unique_lessons(path)

    # Progress is based only on unique lessons.
    done_count = sum(1 for le in unique_lessons if le.id in done_ids)
    pct = round(100 * done_count / len(unique_lessons)) if unique_lessons else 0

    return render_template(
        "lifestyle/learning_path.html",
        path=path,
        unique_lessons=unique_lessons,
        done_ids=done_ids,
        pct=pct,
        completed=(pct == 100),
        active_nav="learning",
    )


@learning_bp.route("/learning/lesson/<int:lesson_id>")
@login_required
def lesson_view(lesson_id: int):
    """Full lesson reading page."""
    lesson = db.session.get(Lesson, lesson_id)
    if lesson is None:
        abort(404)
    canonical = next(
        (item for item in _unique_lessons(lesson.path)
         if item.title.strip().casefold() == lesson.title.strip().casefold()),
        lesson,
    )
    if canonical.id != lesson.id:
        return redirect(url_for("learning.lesson_view", lesson_id=canonical.id))
    done_ids = _completed_lesson_ids()
    is_done = lesson_id in done_ids
    return render_template(
        "lifestyle/lesson_view.html",
        lesson=lesson,
        unique_lessons=_unique_lessons(lesson.path),
        is_done=is_done,
        cover_image=LEARNING_PATH_COVERS.get(lesson.path.slug),
        active_nav="learning",
    )


@learning_bp.route("/learning/lesson/<int:lesson_id>/complete", methods=["POST"])
@login_required
def complete_lesson(lesson_id: int):
    lesson = db.session.get(Lesson, lesson_id)
    if lesson is None:
        abort(404)
    canonical = next(
        (item for item in _unique_lessons(lesson.path)
         if item.title.strip().casefold() == lesson.title.strip().casefold()),
        lesson,
    )
    if canonical.id != lesson.id:
        return redirect(url_for("learning.lesson_view", lesson_id=canonical.id))
    existing = db.session.scalar(
        db.select(LessonProgress).filter_by(
            user_id=current_user.id, lesson_id=lesson_id
        )
    )
    if existing is None:
        db.session.add(
            LessonProgress(user_id=current_user.id, lesson_id=lesson_id, completed=True)
        )
        db.session.commit()
    return redirect(url_for("learning.path_detail", slug=lesson.path.slug))


# ---- Emergency vet finder ----
@learning_bp.route("/emergency")
@login_required
def emergency():
    clinics = db.session.scalars(
        db.select(Place)
        .filter_by(category=PlaceCategory.VET, emergency_24h=True)
        .order_by(Place.distance_km.asc().nullslast())
    ).all()
    return render_template(
        "lifestyle/emergency.html", clinics=clinics, active_nav="places"
    )


@learning_bp.route("/emergency.json")
@login_required
def emergency_json():
    from flask import jsonify

    clinics = db.session.scalars(
        db.select(Place).filter_by(category=PlaceCategory.VET, emergency_24h=True)
    ).all()
    return jsonify(
        [
            {
                "id": c.id, "name": c.name, "address": c.address,
                "lat": c.lat, "lng": c.lng, "distance_km": c.distance_km,
                "note": c.note,
            }
            for c in clinics
        ]
    )
