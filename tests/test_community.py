"""Phase 7 tests: community, reviews/reports, messaging, lost & found."""
from __future__ import annotations

import io

from petship.extensions import db
from petship.models.community import Comment, Post, PostLike
from petship.models.lostfound import FoundPetTip, LostFoundReport, ReportKind
from petship.models.message import Message, Thread
from petship.models.reminder import Notification
from petship.models.report import AbuseReport, ReportTargetType
from petship.models.review import Review, ReviewTarget
from petship.models.shelter import Shelter
from petship.models.user import User, UserRole
from petship.seed import seed_data


def login(client, email="agalya@demo.petship"):
    seed_data()
    role = (
        "admin" if email.startswith("admin@")
        else "shelter" if email.startswith(("kavya@", "ravi@"))
        else "vet" if email.startswith(("ananya@", "vikram@", "sneha@"))
        else "adopter"
    )
    client.post(
        "/auth/login",
        data={"role": role, "email": email, "password": "password123"},
    )


# ---- Task 30: community ----
def test_feed_lists_posts(client, app):
    login(client)
    resp = client.get("/community/")
    assert resp.status_code == 200
    assert b"Max's first beach day" in resp.data or b"Max&#39;s first beach day" in resp.data


def test_feed_topic_filter(client, app):
    login(client)
    resp = client.get("/community/?topic=New adopters")
    assert b"won&#39;t stop hiding" in resp.data or b"stop hiding" in resp.data


def test_create_post(client, app):
    login(client)
    resp = client.post("/community/create",
                       data={"title": "Hello", "topic": "Training", "body": "My first post"},
                       follow_redirects=False)
    assert resp.status_code == 302
    post = db.session.scalar(db.select(Post).filter_by(title="Hello"))
    assert post is not None and post.topic == "Training"


def test_edit_marks_edited(client, app):
    login(client)
    post = db.session.scalar(db.select(Post))
    client.post(f"/community/post/{post.id}/edit",
                data={"title": post.title, "topic": post.topic, "body": "Updated body"})
    db.session.refresh(post)
    assert post.edited is True
    assert post.body == "Updated body"


def test_like_toggle(client, app):
    login(client)
    post = db.session.scalar(db.select(Post))
    client.post(f"/community/post/{post.id}/like", headers={"HX-Request": "true"})
    assert db.session.scalar(db.select(PostLike).filter_by(post_id=post.id)) is not None
    client.post(f"/community/post/{post.id}/like", headers={"HX-Request": "true"})
    assert db.session.scalar(db.select(PostLike).filter_by(post_id=post.id)) is None


def test_comment_on_post(client, app):
    login(client)
    post = db.session.scalar(db.select(Post))
    before = len(post.comments)
    client.post(f"/community/post/{post.id}/comment", data={"body": "Nice!"})
    db.session.refresh(post)
    assert len(post.comments) == before + 1


def test_discussion_shows_verified_vet_badge(client, app):
    login(client)
    # The seeded hiding-cat post has a vet comment.
    post = db.session.scalar(db.select(Post).filter(Post.topic == "New adopters"))
    resp = client.get(f"/community/post/{post.id}")
    assert b"Verified vet" in resp.data


# ---- Task 31: reviews & reports ----
def test_write_and_show_shelter_review(client, app):
    login(client)
    shelter = db.session.scalar(db.select(Shelter).filter_by(slug="happy-paws"))
    client.post(f"/reviews/shelter/{shelter.id}/write",
                data={"rating": "5", "body": "Wonderful, caring staff."})
    resp = client.get(f"/reviews/shelter/{shelter.id}")
    assert resp.status_code == 200
    assert b"Wonderful, caring staff." in resp.data
    assert b"5.0" in resp.data


def test_shelter_directory_search_links_to_reviews(client, app):
    login(client)
    response = client.get("/shelter/directory?q=Adyar")
    assert response.status_code == 200
    assert b"Happy Paws Shelter" in response.data
    assert b"Rate &amp; review" in response.data

    shelter = db.session.scalar(db.select(Shelter).filter_by(slug="happy-paws"))
    client.post(
        f"/reviews/shelter/{shelter.id}/write",
        data={"rating": "5", "body": "Caring team."},
    )
    response = client.get("/shelter/directory?q=Happy")
    assert b"5.0" in response.data
    assert b"1 review" in response.data


def test_shelter_directory_hides_unverified_and_deleted_shelters(client, app):
    login(client)
    from petship.models.shelter import Shelter

    deleted_shelter = Shelter(
        name="Deleted Shelter",
        slug="deleted-shelter",
        owner_id=None,
        is_verified=True,
    )
    unverified_shelter = Shelter(
        name="Unverified Shelter",
        slug="unverified-shelter",
        owner_id=db.session.scalar(
            db.select(User.id).filter_by(email="agalya@demo.petship")
        ),
        is_verified=False,
    )
    db.session.add_all([deleted_shelter, unverified_shelter])
    db.session.commit()

    response = client.get("/shelter/directory")
    assert response.status_code == 200
    assert b"Happy Paws Shelter" in response.data
    assert b"Deleted Shelter" not in response.data
    assert b"Unverified Shelter" not in response.data
    assert client.get("/shelter/deleted-shelter").status_code == 404
    assert client.get("/shelter/unverified-shelter").status_code == 404


def test_review_write_updates_existing_review(client, app):
    login(client)
    shelter = db.session.scalar(db.select(Shelter).filter_by(slug="happy-paws"))
    url = f"/reviews/shelter/{shelter.id}/write"
    client.post(url, data={"rating": "5", "body": "Wonderful, caring staff."})
    client.post(url, data={"rating": "4", "body": "Updated review."})
    rows = db.session.scalars(
        db.select(Review).filter_by(
            target_type=ReviewTarget.SHELTER,
            target_id=shelter.id,
        )
    ).all()
    assert len(rows) == 1
    assert rows[0].rating == 4
    assert rows[0].body == "Updated review."


def test_review_updates_vet_aggregate(client, app):
    login(client)
    from petship.models.vet import VetProfile
    vet = db.session.scalar(db.select(VetProfile).filter_by(slug="ananya-rao"))
    client.post(f"/reviews/vet/{vet.id}/write", data={"rating": "4", "body": "Good"})
    db.session.refresh(vet)
    # Aggregate now reflects real review rows (1 written), with avg = that rating.
    assert vet.reviews_count == 1
    assert vet.rating == 4.0


def test_shelter_and_vet_pages_link_to_reviews(client, app):
    login(client)
    assert b"Rate &amp; review" in client.get("/shelter/happy-paws").data
    assert b"Rate &amp; review" in client.get("/vets/ananya-rao").data


def test_adopter_can_report_fake_vet_or_shelter(client, app):
    login(client)
    shelter = db.session.scalar(db.select(Shelter).filter_by(slug="happy-paws"))
    from petship.models.vet import VetProfile

    vet = db.session.scalar(db.select(VetProfile).filter_by(slug="ananya-rao"))
    shelter_page = client.get(f"/shelter/{shelter.slug}")
    vet_page = client.get(f"/vets/{vet.slug}")
    assert b"Report a safety concern" in shelter_page.data
    assert b"Report a safety concern" in vet_page.data

    client.post(
        f"/reports/provider/shelter/{shelter.id}",
        data={
            "reason": "Fraud or payment scam",
            "details": "Asked for an unusual payment.",
        },
    )
    client.post(
        f"/reports/provider/vet/{vet.id}",
        data={
            "reason": "Fake identity or credentials",
            "details": "Licence details do not match.",
        },
    )
    reports = db.session.scalars(
        db.select(AbuseReport).filter(
            AbuseReport.target_type.in_(
                [ReportTargetType.SHELTER, ReportTargetType.VET]
            )
        )
    ).all()
    assert len(reports) == 2
    assert {report.target_type for report in reports} == {
        ReportTargetType.SHELTER,
        ReportTargetType.VET,
    }
    client.get("/auth/logout")
    login(client, "admin@demo.petship")
    admin_reports = client.get("/admin/reports?status=open")
    assert b"Happy Paws Shelter" in admin_reports.data
    assert b"Ananya Rao" in admin_reports.data
    assert b"Asked for an unusual payment." in admin_reports.data


def test_non_adopter_cannot_report_provider(client, app):
    login(client, "kavya@demo.petship")
    shelter = db.session.scalar(db.select(Shelter).filter_by(slug="happy-paws"))
    response = client.post(
        f"/reports/provider/shelter/{shelter.id}",
        data={"reason": "Fraud or payment scam"},
    )
    assert response.status_code == 403
    assert db.session.scalar(db.select(AbuseReport)) is None


def test_report_abuse(client, app):
    login(client)
    post = db.session.scalar(db.select(Post))
    client.post("/community/report",
                data={"target_type": "post", "target_id": post.id,
                      "reason": "Fake or misleading information",
                      "details": "Looks like spam"})
    report = db.session.scalar(db.select(AbuseReport))
    assert report is not None
    assert report.reason == "Fake or misleading information"


# ---- Task 32: messaging + notifications ----
def test_start_thread_and_send(client, app):
    login(client)
    vet = db.session.scalar(db.select(User).filter_by(email="ananya@demo.petship"))
    resp = client.get(f"/messages/start/{vet.id}", follow_redirects=False)
    assert resp.status_code == 302
    thread = db.session.scalar(db.select(Thread))
    assert thread is not None

    client.post(f"/messages/{thread.id}/send", data={"body": "Hi doctor"},
                headers={"HX-Request": "true"})
    msg = db.session.scalar(db.select(Message))
    assert msg.body == "Hi doctor"


def test_send_creates_recipient_notification(client, app):
    login(client)
    vet = db.session.scalar(db.select(User).filter_by(email="ananya@demo.petship"))
    client.get(f"/messages/start/{vet.id}")
    thread = db.session.scalar(db.select(Thread))
    client.post(f"/messages/{thread.id}/send", data={"body": "Hello"},
                headers={"HX-Request": "true"})
    notif = db.session.scalar(
        db.select(Notification).filter_by(user_id=vet.id, category="messages")
    )
    assert notif is not None


def test_cannot_open_others_thread(client, app):
    login(client)
    # Thread between two other users.
    u1 = db.session.scalar(db.select(User).filter_by(email="kavya@demo.petship"))
    u2 = db.session.scalar(db.select(User).filter_by(email="ravi@demo.petship"))
    t = Thread(user_a_id=min(u1.id, u2.id), user_b_id=max(u1.id, u2.id))
    db.session.add(t)
    db.session.commit()
    assert client.get(f"/messages/{t.id}").status_code == 404


def test_bell_shows_unread(client, app):
    login(client)
    me = db.session.scalar(db.select(User).filter_by(email="agalya@demo.petship"))
    Notification.push(me.id, "Test notif", "body", "health")
    db.session.commit()
    resp = client.get("/messages/bell")
    assert resp.status_code == 200
    assert b"Test notif" in resp.data


# ---- Task 33: lost & found ----
def test_lostfound_list(client, app):
    seed_data()
    resp = client.get("/lost-found/")
    assert resp.status_code == 200
    assert b"Lost &amp; Found" in resp.data or b"Lost & Found" in resp.data
    assert b"+ Report lost or found pet" in resp.data
    assert b"Lost &amp; Found" in client.get("/").data


def _lost_pet_photo():
    from PIL import Image

    photo = io.BytesIO()
    Image.new("RGB", (32, 32), "orange").save(photo, format="PNG")
    photo.seek(0)
    return photo


def test_create_lost_report(client, app):
    login(client)
    resp = client.post("/lost-found/report",
                       data={"kind": "lost", "pet_name": "Toffee",
                             "species": "Dog", "location": "Besant Nagar",
                             "photo": (_lost_pet_photo(), "toffee.png")},
                       content_type="multipart/form-data",
                       follow_redirects=False)
    assert resp.status_code == 302
    report = db.session.scalar(db.select(LostFoundReport).filter_by(pet_name="Toffee"))
    assert report is not None
    assert report.kind is ReportKind.LOST
    assert report.photo_url
    assert report.photo_hash


def test_lost_pet_requires_photo_and_location(client, app):
    login(client)
    response = client.post(
        "/lost-found/report",
        data={"kind": "lost", "species": "Cat", "location": "Park"},
        follow_redirects=True,
    )
    assert b"Add a photo of the lost pet" in response.data
    assert db.session.scalar(db.select(LostFoundReport)) is None


def test_other_adopter_can_send_private_found_pet_tip(client, app):
    login(client)
    owner = db.session.scalar(db.select(User).filter_by(email="agalya@demo.petship"))
    lost = LostFoundReport(
        reporter_id=owner.id,
        kind=ReportKind.LOST,
        pet_name="Bella",
        species="Dog",
        location="Adyar",
    )
    finder = User(
        email="finder@example.com",
        first_name="Finder",
        role=UserRole.ADOPTER,
        is_active=True,
    )
    finder.set_password("password123")
    db.session.add_all([lost, finder])
    db.session.commit()
    lost_id = lost.id

    client.get("/auth/logout")
    client.post(
        "/auth/login",
        data={"role": "adopter", "email": "finder@example.com", "password": "password123"},
    )
    response = client.get(f"/lost-found/{lost_id}")
    assert b"Found this pet?" in response.data
    response = client.post(
        f"/lost-found/{lost_id}/found-tip",
        data={"contact": "finder@example.com", "message": "Saw Bella near Adyar."},
        follow_redirects=True,
    )
    assert response.status_code == 200
    tip = db.session.scalar(db.select(FoundPetTip))
    assert tip is not None
    assert tip.report_id == lost_id

    owner_page = client.get(f"/lost-found/{lost_id}")
    assert b"finder@example.com" not in owner_page.data
    client.get("/auth/logout")
    client.post(
        "/auth/login",
        data={"role": "adopter", "email": "agalya@demo.petship", "password": "password123"},
    )
    owner_page = client.get(f"/lost-found/{lost_id}")
    assert b"finder@example.com" in owner_page.data
    assert b"Saw Bella near Adyar." in owner_page.data


def test_lostfound_detail_and_matches(client, app):
    login(client)
    me = db.session.scalar(db.select(User).filter_by(email="agalya@demo.petship"))
    lost = LostFoundReport(reporter_id=me.id, kind=ReportKind.LOST, pet_name="Bella")
    db.session.add(lost)
    db.session.commit()
    resp = client.get(f"/lost-found/{lost.id}")
    assert resp.status_code == 200
    assert b"Possible matches" in resp.data


def test_mark_reunited(client, app):
    login(client)
    me = db.session.scalar(db.select(User).filter_by(email="agalya@demo.petship"))
    r = LostFoundReport(reporter_id=me.id, kind=ReportKind.FOUND, pet_name="Found cat")
    db.session.add(r)
    db.session.commit()
    client.post(f"/lost-found/{r.id}/reunite")
    db.session.refresh(r)
    from petship.models.lostfound import ReportStatus
    assert r.status is ReportStatus.REUNITED
