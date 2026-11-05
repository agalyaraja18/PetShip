"""Task 18 tests: vet directory, detail, and profile management."""
from __future__ import annotations

from petship.extensions import db
from petship.models.vet import VetProfile
from petship.seed import seed_data


def test_directory_lists_verified_vets(client, app):
    seed_data()
    resp = client.get("/vets/")
    assert resp.status_code == 200
    assert b"Find a trusted vet" in resp.data
    assert b"Dr. Ananya Rao" in resp.data
    assert b"Dr. Vikram Iyer" in resp.data


def test_directory_search_by_name(client, app):
    seed_data()
    resp = client.get("/vets/?q=ananya")
    assert b"Dr. Ananya Rao" in resp.data
    assert b"Dr. Vikram Iyer" not in resp.data


def test_directory_filter_by_specialty(client, app):
    seed_data()
    resp = client.get("/vets/?specialty=Surgery")
    assert b"Dr. Sneha Menon" in resp.data
    assert b"Dr. Ananya Rao" not in resp.data


def test_directory_video_filter(client, app):
    seed_data()
    resp = client.get("/vets/?video=1")
    # Sneha has video_fee 0 / offers_video False -> excluded.
    assert b"Dr. Ananya Rao" in resp.data
    assert b"Dr. Sneha Menon" not in resp.data


def test_vet_detail_renders(client, app):
    seed_data()
    resp = client.get("/vets/ananya-rao")
    assert resp.status_code == 200
    assert b"Dr. Ananya Rao" in resp.data
    assert b"feline medicine" in resp.data
    assert b"Services" in resp.data
    assert b"Rate &amp; review" in resp.data


def test_vet_detail_404(client, app):
    resp = client.get("/vets/nobody")
    assert resp.status_code == 404


def test_manage_profile_requires_vet(client, app):
    seed_data()
    client.post("/auth/login", data={"role": "adopter", "email": "agalya@demo.petship", "password": "password123"})
    assert client.get("/vets/manage/profile").status_code == 403


def test_vet_can_edit_profile(client, app):
    seed_data()
    client.post("/auth/login", data={"role": "vet", "email": "ananya@demo.petship", "password": "password123"})
    resp = client.post(
        "/vets/manage/profile?edit=1",
        data={
            "display_name": "Dr. Ananya Rao",
            "qualifications": "BVSc, MVSc",
            "clinic_name": "CareVet Clinic",
            "experience_years": "13",
            "bio": "Updated bio.",
            "specialties": ["General", "Cats"],
            "languages": "Tamil, English",
            "consult_fee": "550",
            "offers_video": "on",
        },
        follow_redirects=False,
    )
    assert resp.status_code == 302
    profile = db.session.scalar(db.select(VetProfile).filter_by(slug="ananya-rao"))
    assert profile.experience_years == 13
    assert profile.bio == "Updated bio."
    assert set(profile.specialties) == {"General", "Cats"}
    assert profile.consult_fee == 550


def test_public_nav_links_to_directory(client, app):
    seed_data()
    resp = client.get("/vets/")
    # The public nav "Vets" link resolves (no url build error).
    assert b"/vets/" in resp.data


def test_adopter_sidebar_links_to_vets(client, app):
    seed_data()
    client.post("/auth/login", data={"role": "adopter", "email": "agalya@demo.petship", "password": "password123"})
    resp = client.get("/me/dashboard")
    assert b"Find Vet" in resp.data
    assert b'href="/vets/"' in resp.data


def test_directory_links_to_vet_reviews(client, app):
    seed_data()
    resp = client.get("/vets/")
    assert b"Rate &amp; review" in resp.data
    assert b"/reviews/vet/" in resp.data
