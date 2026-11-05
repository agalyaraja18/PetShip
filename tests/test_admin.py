"""Phase 8 tests: admin dashboard, users, verification, moderation, analytics."""
from __future__ import annotations

from datetime import datetime, timezone

from petship.extensions import db
from petship.models.application import Application, ApplicationStage
from petship.models.pet import Pet, PetStatus
from petship.models.report import AbuseReport, AbuseStatus, ReportTargetType
from petship.models.shelter import Shelter
from petship.models.user import User, UserRole
from petship.models.vet import VetProfile
from petship.seed import seed_data


def login_admin(client):
    seed_data()
    client.post("/auth/login", data={"role": "admin", "email": "admin@demo.petship", "password": "password123"})


# ---- Access control ----
def test_admin_requires_admin_role(client, app):
    seed_data()
    client.post("/auth/login", data={"role": "adopter", "email": "agalya@demo.petship", "password": "password123"})
    assert client.get("/admin/").status_code == 403


def test_admin_dashboard_redirect(client, app):
    seed_data()
    client.post("/auth/login", data={"role": "admin", "email": "admin@demo.petship", "password": "password123"})
    resp = client.get("/auth/dashboard", follow_redirects=False)
    assert resp.status_code == 302
    assert "/admin" in resp.headers["Location"]


# ---- Task 34: dashboard + users ----
def test_dashboard_stats(client, app):
    login_admin(client)
    resp = client.get("/admin/")
    assert resp.status_code == 200
    assert b"Platform overview" in resp.data
    assert b"Users" in resp.data


def test_dashboard_verification_queue_excludes_deleted_shelter_accounts(client, app):
    login_admin(client)
    db.session.add(
        Shelter(
            owner_id=None,
            name="Pet's world",
            slug="pets-world-orphaned",
            is_verified=False,
        )
    )
    db.session.commit()

    response = client.get("/admin/")
    assert response.status_code == 200
    assert b"Pet&#39;s world" not in response.data
    assert b"Second Chance Home" in response.data


def test_user_management_list(client, app):
    login_admin(client)
    resp = client.get("/admin/users")
    assert resp.status_code == 200
    assert b"User management" in resp.data
    assert b"agalya@demo.petship" in resp.data


def test_user_search_and_role_filter(client, app):
    login_admin(client)
    resp = client.get("/admin/users?role=vet")
    assert b"ananya@demo.petship" in resp.data
    assert b"agalya@demo.petship" not in resp.data


def test_suspend_and_restore_user(client, app):
    login_admin(client)
    user = db.session.scalar(db.select(User).filter_by(email="agalya@demo.petship"))
    client.post(f"/admin/users/{user.id}/suspend")
    db.session.refresh(user)
    assert user.is_active is False
    client.post(f"/admin/users/{user.id}/suspend")
    db.session.refresh(user)
    assert user.is_active is True


def test_cannot_suspend_self(client, app):
    login_admin(client)
    admin = db.session.scalar(db.select(User).filter_by(email="admin@demo.petship"))
    client.post(f"/admin/users/{admin.id}/suspend")
    db.session.refresh(admin)
    assert admin.is_active is True


def test_users_csv_export(client, app):
    login_admin(client)
    resp = client.get("/admin/users.csv")
    assert resp.status_code == 200
    assert resp.mimetype == "text/csv"
    assert b"agalya@demo.petship" in resp.data


# ---- Task 35: verification ----
def test_approve_shelter(client, app):
    from datetime import timedelta

    login_admin(client)
    # Second Chance Home is seeded unverified.
    shelter = db.session.scalar(db.select(Shelter).filter_by(is_verified=False))
    assert shelter is not None
    shelter.verification_visit_at = datetime.now(timezone.utc) - timedelta(minutes=5)
    shelter.verification_visit_time_is_utc = True
    db.session.commit()
    client.post(f"/admin/verify/shelters/{shelter.id}", data={"decision": "approve"})
    db.session.refresh(shelter)
    assert shelter.is_verified is True


def test_verify_queue_lists_pending(client, app):
    login_admin(client)
    resp = client.get("/admin/verify/shelters")
    assert resp.status_code == 200
    assert b"Second Chance Home" in resp.data


def test_shelter_verification_categories(client, app):
    from datetime import timedelta

    login_admin(client)
    owner = User(
        email="visit-category@example.com",
        first_name="Visit",
        last_name="Shelter",
        role=UserRole.SHELTER,
        registration_status="pending",
        is_active=False,
    )
    db.session.add(owner)
    db.session.flush()
    visit_shelter = Shelter(
        owner_id=owner.id,
        name="Visit Category Shelter",
        slug="visit-category-shelter",
        verification_visit_at=datetime.now(timezone.utc) + timedelta(days=1),
    )
    db.session.add(visit_shelter)
    db.session.commit()

    all_shelters = client.get("/admin/verify/shelters?view=all").data
    visits = client.get("/admin/verify/shelters?view=visit").data
    approved = client.get("/admin/verify/shelters?view=approved").data
    assert b"Visit Category Shelter" in all_shelters
    assert b"Approved Shelter" in all_shelters
    assert b"Visit Category Shelter" in visits
    assert b"Second Chance Home" not in visits
    assert b"Approved Shelter" in approved
    assert b"Visit Category Shelter" not in approved


def test_shelter_verification_excludes_profiles_with_deleted_owners(client, app):
    login_admin(client)
    orphan = Shelter(
        owner_id=None,
        name="Pet's world",
        slug="pets-world-deleted",
        address="Old shelter address",
        is_verified=False,
    )
    db.session.add(orphan)
    db.session.commit()

    all_shelters = client.get("/admin/verify/shelters?view=all").data
    visits = client.get("/admin/verify/shelters?view=visit").data
    approved = client.get("/admin/verify/shelters?view=approved").data
    assert b"Pet&#39;s world" not in all_shelters
    assert b"Pet&#39;s world" not in visits
    assert b"Pet&#39;s world" not in approved
    assert b"Second Chance Home" in all_shelters


def test_vet_verification_categories(client, app):
    login_admin(client)
    user = User(
        email="clinic-category@example.com",
        first_name="Clinic",
        last_name="Visit",
        role=UserRole.VET,
        registration_status="pending",
        is_active=False,
    )
    db.session.add(user)
    db.session.flush()
    vet = VetProfile(
        user_id=user.id,
        display_name="Dr. Clinic Category",
        slug="dr-clinic-category",
    )
    db.session.add(vet)
    db.session.commit()

    all_vets = client.get("/admin/verify/vets?view=all").data
    clinic_visits = client.get("/admin/verify/vets?view=visit").data
    approved = client.get("/admin/verify/vets?view=approved").data
    assert b"Dr. Clinic Category" in all_vets
    assert b"Approved Vet" in all_vets
    assert b"Dr. Clinic Category" in clinic_visits
    assert b"Dr. Ananya Rao" not in clinic_visits
    assert b"Dr. Ananya Rao" in approved
    assert b"Dr. Clinic Category" not in approved


def test_shelter_approval_requires_completed_visit_and_issues_credentials(
    client, app, monkeypatch
):
    from datetime import timedelta
    import petship.blueprints.admin as admin_module
    from petship.models.reminder import Notification

    login_admin(client)
    owner = User(
        email="new-shelter@example.com",
        first_name="New",
        last_name="Owner",
        role=UserRole.SHELTER,
        registration_status="pending",
        is_active=False,
    )
    db.session.add(owner)
    db.session.flush()
    shelter = Shelter(
        owner_id=owner.id,
        name="New Shelter",
        slug="new-shelter",
        address="20 Park Road",
    )
    db.session.add(shelter)
    db.session.commit()
    emails = []
    monkeypatch.setattr(
        admin_module,
        "send_email",
        lambda **kwargs: (emails.append(kwargs), "smtp")[1],
    )

    verification_page = client.get("/admin/verify/shelters")
    assert b"Approve shelter" in verification_page.data
    assert b'decision" value="approve" type="submit" disabled' not in verification_page.data
    assert b'name="scheduled_for_local" required' not in verification_page.data

    blocked = client.post(
        f"/admin/verify/shelters/{shelter.id}",
        data={"decision": "approve"},
        follow_redirects=True,
    )
    assert b"Schedule the in-person shelter visit" in blocked.data

    scheduled_for = datetime.now(timezone.utc) + timedelta(days=1)
    client.post(
        f"/admin/verify/shelters/{shelter.id}",
        data={
            "decision": "schedule_visit",
            "scheduled_for_utc": scheduled_for.isoformat(),
        },
    )
    db.session.refresh(shelter)
    assert shelter.verification_visit_at is not None
    assert shelter.verification_visit_time_is_utc
    assert emails[-1]["to"] == owner.email
    assert db.session.scalar(
        db.select(Notification).filter_by(
            user_id=owner.id,
            title="Shelter verification visit scheduled",
        )
    ) is not None

    early_approval = client.post(
        f"/admin/verify/shelters/{shelter.id}",
        data={"decision": "approve"},
        follow_redirects=True,
    )
    assert b"scheduled visit has not taken place yet" in early_approval.data
    assert shelter.is_verified is False

    shelter.verification_visit_at = datetime.now(timezone.utc) - timedelta(minutes=5)
    db.session.commit()
    client.post(
        f"/admin/verify/shelters/{shelter.id}",
        data={"decision": "approve"},
    )
    db.session.refresh(owner)
    db.session.refresh(shelter)
    assert shelter.is_verified
    assert shelter.verification_visit_completed_at is not None
    assert owner.is_active and owner.is_verified
    assert owner.registration_status == "approved"
    assert owner.force_password_reset
    assert owner.public_id.startswith("SHL-")
    credential_email = emails[-1]["body"]
    assert owner.public_id in credential_email
    assert "Registration Status page" in credential_email
    assert owner.password_hash is None
    assert db.session.scalar(
        db.select(Notification).filter_by(
            user_id=owner.id,
            title="Shelter registration approved",
        )
    ) is not None


def test_shelter_approval_converts_legacy_local_visit_time(client, app, monkeypatch):
    from datetime import timedelta
    from zoneinfo import ZoneInfo

    import petship.blueprints.admin as admin_module

    login_admin(client)
    owner = User(
        email="local-time-shelter@example.com",
        first_name="Local",
        role=UserRole.SHELTER,
        registration_status="pending",
        is_active=False,
    )
    db.session.add(owner)
    db.session.flush()
    shelter = Shelter(
        owner_id=owner.id,
        name="Local Time Shelter",
        slug="local-time-shelter",
        verification_visit_at=(
            datetime.now(ZoneInfo("Asia/Kolkata")).replace(tzinfo=None)
            - timedelta(minutes=5)
        ),
    )
    db.session.add(shelter)
    db.session.commit()
    monkeypatch.setattr(admin_module, "send_email", lambda **kwargs: "smtp")

    response = client.post(
        f"/admin/verify/shelters/{shelter.id}",
        data={"decision": "approve", "browser_timezone": "Asia/Kolkata"},
        follow_redirects=True,
    )
    db.session.refresh(shelter)
    assert b"Local Time Shelter approved" in response.data
    assert shelter.is_verified
    assert shelter.verification_visit_time_is_utc
    visit_at_utc = shelter.verification_visit_at.replace(tzinfo=timezone.utc)
    assert visit_at_utc < datetime.now(timezone.utc)


def test_vet_approval_issues_role_specific_login_credentials(client, app, monkeypatch):
    import petship.blueprints.admin as admin_module
    from petship.models.reminder import Notification

    login_admin(client)
    user = User(
        email="new-vet@example.com",
        first_name="New",
        last_name="Vet",
        role=UserRole.VET,
        registration_status="pending",
        is_active=False,
    )
    db.session.add(user)
    db.session.flush()
    vet = VetProfile(
        user_id=user.id,
        display_name="Dr. New Vet",
        slug="dr-new-vet",
        certificate_url="/static/certificate.png",
    )
    db.session.add(vet)
    db.session.commit()
    emails = []
    monkeypatch.setattr(
        admin_module,
        "send_email",
        lambda **kwargs: (emails.append(kwargs), "smtp")[1],
    )

    response = client.get("/admin/verify/vets")
    assert b"View certificate" in response.data
    client.post(
        f"/admin/verify/vets/{vet.id}",
        data={"decision": "approve"},
    )
    db.session.refresh(user)
    assert user.public_id.startswith("VET-")
    assert user.force_password_reset
    assert user.is_active
    assert emails[-1]["to"] == user.email
    assert user.password_hash is None
    assert db.session.scalar(
        db.select(Notification).filter_by(
            user_id=user.id,
            title="Veterinarian registration approved",
        )
    ) is not None


# ---- Task 36: moderation ----
def test_listing_moderation_remove(client, app):
    login_admin(client)
    pet = db.session.scalar(db.select(Pet).filter_by(name="Bruno"))
    response = client.get("/admin/listings")
    assert pet.photos
    assert pet.primary_photo.encode() in response.data
    assert b'alt="Bruno"' in response.data
    client.post(f"/admin/listings/{pet.id}/action", data={"action": "remove"})
    db.session.refresh(pet)
    assert pet.status is PetStatus.REMOVED


def test_adoptions_kanban_renders(client, app):
    login_admin(client)
    resp = client.get("/admin/adoptions")
    assert resp.status_code == 200
    assert b"Adoption management" in resp.data


def test_reports_queue(client, app):
    login_admin(client)
    reporter = db.session.scalar(db.select(User).filter_by(email="agalya@demo.petship"))
    db.session.add(AbuseReport(
        reporter_id=reporter.id, target_type=ReportTargetType.POST, target_id=1,
        reason="Spam", priority="urgent",
    ))
    db.session.commit()
    resp = client.get("/admin/reports")
    assert b"Spam" in resp.data


def test_resolve_report(client, app):
    login_admin(client)
    reporter = db.session.scalar(db.select(User).filter_by(email="agalya@demo.petship"))
    report = AbuseReport(reporter_id=reporter.id, target_type=ReportTargetType.POST,
                         target_id=1, reason="Spam")
    db.session.add(report)
    db.session.commit()
    client.post(f"/admin/reports/{report.id}/resolve", data={"decision": "resolve"})
    db.session.refresh(report)
    assert report.status is AbuseStatus.RESOLVED


def test_community_moderation_hide_post(client, app):
    login_admin(client)
    from petship.models.community import Post
    post = db.session.scalar(db.select(Post))
    client.post(f"/admin/community/post/{post.id}/action", data={"action": "hide"})
    db.session.refresh(post)
    assert post.hidden is True


def test_review_moderation_hide(client, app):
    login_admin(client)
    from petship.models.review import Review, ReviewTarget
    reviewer = db.session.scalar(db.select(User).filter_by(email="agalya@demo.petship"))
    shelter = db.session.scalar(db.select(Shelter))
    review = Review(author_id=reviewer.id, target_type=ReviewTarget.SHELTER,
                    target_id=shelter.id, rating=1, body="bad")
    db.session.add(review)
    db.session.commit()
    client.post(f"/admin/reviews/{review.id}/action", data={"action": "hide"})
    db.session.refresh(review)
    assert review.hidden is True


# ---- Task 37: analytics ----
def test_analytics_renders(client, app):
    login_admin(client)
    resp = client.get("/admin/analytics")
    assert resp.status_code == 200
    assert b"Platform analytics" in resp.data
    assert b"Adoption funnel" in resp.data
    assert b"Adoptions by species" in resp.data
    assert b"Adopter registrations" in resp.data
    assert b"AI match usage" in resp.data
    assert b"Returned pets" in resp.data


def test_analytics_counts_pet_returns_and_rate(client, app):
    login_admin(client)
    adopter = db.session.scalar(db.select(User).filter_by(email="agalya@demo.petship"))
    pets = db.session.scalars(db.select(Pet).limit(2)).all()
    now = datetime.now(timezone.utc)
    returned_application = Application(
        reference="PS-RET001",
        applicant_id=adopter.id,
        pet_id=pets[0].id,
        stage=ApplicationStage.COMPLETE,
        adopted_at=now,
        returned_at=now,
        return_reason="Needs a different home.",
    )
    active_application = Application(
        reference="PS-RET002",
        applicant_id=adopter.id,
        pet_id=pets[1].id,
        stage=ApplicationStage.COMPLETE,
        adopted_at=now,
    )
    db.session.add_all([returned_application, active_application])
    db.session.commit()

    resp = client.get("/admin/analytics?period=30d")
    assert resp.status_code == 200
    assert b"Returned pets" in resp.data
    assert b"Return rate" in resp.data
    assert b"50.0%" in resp.data
    assert b"Lost rate" in resp.data
    assert b"Reunited rate" in resp.data
    assert b"admin-lostfound-map" not in resp.data  # no geocoded reports yet


def test_admin_lost_found_overview_and_map_analytics(client, app):
    from datetime import datetime, timezone

    from petship.models.lostfound import LostFoundReport, ReportKind, ReportStatus

    login_admin(client)
    reporter = db.session.scalar(
        db.select(User).filter_by(email="agalya@demo.petship")
    )
    lost = LostFoundReport(
        reporter_id=reporter.id,
        kind=ReportKind.LOST,
        pet_name="Bella",
        species="Dog",
        location="Adyar",
        lat=13.001,
        lng=80.250,
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )
    found = LostFoundReport(
        reporter_id=reporter.id,
        kind=ReportKind.FOUND,
        pet_name="Unknown cat",
        species="Cat",
        location="Besant Nagar",
        lat=13.002,
        lng=80.251,
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )
    reunited = LostFoundReport(
        reporter_id=reporter.id,
        kind=ReportKind.LOST,
        status=ReportStatus.REUNITED,
        pet_name="Returned Bella",
        species="Dog",
        location="Adyar",
        lat=13.003,
        lng=80.252,
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )
    db.session.add_all([lost, found, reunited])
    db.session.commit()

    overview = client.get("/admin/lost-found")
    assert overview.status_code == 200
    assert b"Lost &amp; Found overview" in overview.data
    assert b"Bella" in overview.data
    assert b"Besant Nagar" in overview.data
    assert b"Recent (3)" in overview.data
    assert b"Lost (1)" in overview.data
    assert b"Reunited (2)" in overview.data
    lost_view = client.get("/admin/lost-found?view=lost")
    assert b"Bella" in lost_view.data
    assert b"Unknown cat" not in lost_view.data
    reunited_view = client.get("/admin/lost-found?view=reunited")
    assert b"Unknown cat" in reunited_view.data
    assert b"Returned Bella" in reunited_view.data

    analytics = client.get("/admin/analytics?period=30d")
    assert analytics.status_code == 200
    assert b"Lost rate" in analytics.data
    assert b"33.3%" in analytics.data
    assert b"Reunited rate" in analytics.data
    assert b"admin-lostfound-map" in analytics.data
    assert b"13.001" in analytics.data


def test_analytics_period_filter(client, app):
    login_admin(client)
    resp = client.get("/admin/analytics?period=7d")
    assert resp.status_code == 200


def test_admin_feedback_page_lists_platform_ratings(client, app):
    from petship.models.platform import PlatformFeedback

    login_admin(client)
    user = db.session.scalar(db.select(User).filter_by(email="agalya@demo.petship"))
    db.session.add(
        PlatformFeedback(
            user_id=user.id,
            name=user.full_name,
            rating=5,
            body="Easy to use.",
        )
    )
    db.session.commit()

    response = client.get("/admin/feedback")
    assert response.status_code == 200
    assert b"Platform feedback" in response.data
    assert b"Easy to use." in response.data
    assert b"5.0 / 5" in response.data
    assert b"Needs review" in response.data
    client.post(
        f"/admin/feedback/{db.session.scalar(db.select(PlatformFeedback)).id}/action",
        data={"action": "handled"},
    )
    db.session.refresh(db.session.scalar(db.select(PlatformFeedback)))
    assert b"Handled" in client.get("/admin/feedback").data


def test_admin_contact_messages_and_handling(client, app):
    from petship.models.content import ContactMessage

    login_admin(client)
    message = ContactMessage(
        name="Agalya",
        email="agalya@example.com",
        topic="Adoption question",
        message="Can you help me?",
    )
    db.session.add(message)
    db.session.commit()

    response = client.get("/admin/messages")
    assert response.status_code == 200
    assert b"Can you help me?" in response.data
    client.post(f"/admin/messages/{message.id}/action", data={"action": "handled"})
    db.session.refresh(message)
    assert message.handled is True


def test_admin_sidebar_hides_community_and_shows_admin_inboxes(client, app):
    login_admin(client)
    response = client.get("/admin/")
    assert b">Feedback</a>" in response.data
    assert b">Messages</a>" in response.data
    assert b">Community</a>" not in response.data
