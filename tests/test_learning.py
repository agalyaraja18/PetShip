"""Task 25 tests: learning paths, lesson progress, emergency vet finder."""
from __future__ import annotations

from petship.extensions import db
from petship.models.learning import LearningPath, Lesson, LessonProgress
from petship.learning_content import LESSON_PRACTICES
from petship.seed import seed_data


def login_agalya(client):
    seed_data()
    client.post("/auth/login", data={"role": "adopter", "email": "agalya@demo.petship", "password": "password123"})


def a_path():
    return db.session.scalar(db.select(LearningPath).filter_by(slug="dog-parent"))


def test_learning_requires_login(client, app):
    seed_data()
    resp = client.get("/lifestyle/learning", follow_redirects=False)
    assert resp.status_code == 302


def test_paths_list(client, app):
    login_agalya(client)
    resp = client.get("/lifestyle/learning")
    assert resp.status_code == 200
    assert b"Pet care learning paths" in resp.data
    assert b"Dog Parent" in resp.data
    assert b"Cat Parent" in resp.data
    assert b"Rabbit Bonding" in resp.data
    assert b"Swim with Fish" in resp.data
    paths = db.session.scalars(db.select(LearningPath)).all()
    assert resp.data.count(b'class="learning-cover"') == len(paths)
    assert b"img/pets/blog_adoption.jpg" in resp.data
    assert b"img/pets/blog_health.jpg" in resp.data
    assert b"img/pets/blog_care.jpg" in resp.data
    assert b"img/learning/hamster.png" in resp.data
    assert b"img/learning/parrot.png" in resp.data
    assert b"img/learning/lovebirds.png" in resp.data
    assert b"img/learning/dove.png" in resp.data
    assert b"img/learning/macaw.png" in resp.data
    assert b"img/learning/first-aid.png" in resp.data
    assert b"img/learning/dog-nutrition.png" in resp.data
    assert b"img/learning/cat-nutrition.png" in resp.data
    assert b"img/learning/fish.png" in resp.data


def test_swim_with_fish_path_and_lesson_image(client, app):
    login_agalya(client)
    path = db.session.scalar(
        db.select(LearningPath).filter_by(slug="swim-with-fish")
    )
    assert path is not None
    assert len(path.lessons) == 7
    assert all(lesson.title in LESSON_PRACTICES[path.slug] for lesson in path.lessons)

    detail = client.get("/lifestyle/learning/swim-with-fish")
    assert detail.status_code == 200
    assert b"Understanding Aquarium Fish" in detail.data

    lesson_page = client.get(
        f"/lifestyle/learning/lesson/{path.lessons[0].id}"
    )
    assert lesson_page.status_code == 200
    assert b"img/learning/fish.png" in lesson_page.data
    assert b"Clownfish swimming underwater" in lesson_page.data


def test_path_detail_lists_lessons(client, app):
    login_agalya(client)
    resp = client.get("/lifestyle/learning/dog-parent")
    assert resp.status_code == 200
    assert b"House Training Basics" in resp.data
    assert b"Your progress" in resp.data
    assert b"House training teaches your dog" in resp.data


def test_lesson_content_teaches_its_topic(client, app):
    login_agalya(client)
    lesson = db.session.scalar(
        db.select(Lesson).filter_by(title="House Training Basics")
    )
    resp = client.get(f"/lifestyle/learning/lesson/{lesson.id}")
    assert resp.status_code == 200
    assert b"after waking" in resp.data
    assert b"Never punish" in resp.data
    assert b"Keep a simple note" not in resp.data


def test_every_seeded_lesson_has_topic_specific_guidance(client, app):
    login_agalya(client)
    paths = db.session.scalars(db.select(LearningPath)).all()
    for path in paths:
        mapped_titles = LESSON_PRACTICES.get(path.slug, {})
        assert path.lessons
        assert all(lesson.title in mapped_titles for lesson in path.lessons), path.slug


def test_duplicate_lesson_is_hidden_and_redirected(client, app):
    login_agalya(client)
    path = a_path()
    original = next(le for le in path.lessons if le.title == "House Training Basics")
    duplicate = Lesson(
        path_id=path.id,
        position=99,
        title="  HOUSE TRAINING BASICS ",
        body="Duplicate lesson",
    )
    db.session.add(duplicate)
    db.session.commit()

    page = client.get(f"/lifestyle/learning/{path.slug}")
    assert page.data.count(b"House Training Basics") == 1
    response = client.get(f"/lifestyle/learning/lesson/{duplicate.id}")
    assert response.status_code == 302
    assert response.headers["Location"].endswith(
        f"/lifestyle/learning/lesson/{original.id}"
    )


def test_path_404(client, app):
    login_agalya(client)
    assert client.get("/lifestyle/learning/nope").status_code == 404


def test_complete_lesson_updates_progress(client, app):
    login_agalya(client)
    path = a_path()
    lesson = path.lessons[0]
    client.post(f"/lifestyle/learning/lesson/{lesson.id}/complete")
    prog = db.session.scalar(
        db.select(LessonProgress).filter_by(lesson_id=lesson.id)
    )
    assert prog is not None
    assert prog.completed is True


def test_completing_all_earns_certificate(client, app):
    login_agalya(client)
    path = a_path()
    for lesson in path.lessons:
        client.post(f"/lifestyle/learning/lesson/{lesson.id}/complete")
    resp = client.get(f"/lifestyle/learning/{path.slug}")
    assert b"Certificate earned" in resp.data
    assert b"100%" in resp.data


def test_complete_lesson_idempotent(client, app):
    login_agalya(client)
    lesson = a_path().lessons[0]
    client.post(f"/lifestyle/learning/lesson/{lesson.id}/complete")
    client.post(f"/lifestyle/learning/lesson/{lesson.id}/complete")
    count = db.session.scalar(
        db.select(db.func.count()).select_from(LessonProgress).filter_by(lesson_id=lesson.id)
    )
    assert count == 1


# ---- Emergency vet finder ----
def test_emergency_page(client, app):
    login_agalya(client)
    resp = client.get("/lifestyle/emergency")
    assert resp.status_code == 200
    assert b"Emergency clinics open now" in resp.data
    # Seeded 24/7 clinics appear.
    assert b"Chennai Pet Emergency Hospital" in resp.data


def test_emergency_json_only_24h(client, app):
    login_agalya(client)
    resp = client.get("/lifestyle/emergency.json")
    data = resp.get_json()
    names = {c["name"] for c in data}
    assert "Chennai Pet Emergency Hospital" in names
    # A non-emergency vet is excluded.
    assert "CareVet Clinic" not in names


def test_emergency_requires_login(client, app):
    seed_data()
    resp = client.get("/lifestyle/emergency", follow_redirects=False)
    assert resp.status_code == 302
