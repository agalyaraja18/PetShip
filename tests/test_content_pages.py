"""Task 11 tests: pet detail, search, stories, blog, about, contact, FAQ."""
from __future__ import annotations

from petship.extensions import db
from petship.models.content import BlogPost, ContactMessage
from petship.models.pet import Pet, PetStatus
from petship.seed import seed_data


def _pet(name):
    return db.session.scalar(db.select(Pet).filter_by(name=name))


# ---- Pet detail ----
def test_pet_detail_renders(client, app):
    seed_data()
    pet = _pet("Bruno")
    resp = client.get(f"/pets/{pet.id}")
    assert resp.status_code == 200
    assert b"Meet Bruno" in resp.data
    assert b"Happy Paws Shelter" in resp.data  # shelter card
    assert b"Vaccinated" in resp.data  # trait tag


def test_pet_detail_counts_view(client, app):
    seed_data()
    pet = _pet("Daisy")
    before = pet.views
    client.get(f"/pets/{pet.id}")
    db.session.refresh(pet)
    assert pet.views == before + 1


def test_pet_detail_draft_is_404(client, app):
    seed_data()
    rocky = _pet("Rocky")  # draft
    resp = client.get(f"/pets/{rocky.id}")
    assert resp.status_code == 404


def test_pet_detail_shows_similar(client, app):
    seed_data()
    mochi = _pet("Mochi")  # cat
    resp = client.get(f"/pets/{mochi.id}")
    # Similar cats section present (Ginger is another cat).
    assert b"More cats to meet" in resp.data


# ---- Search ----
def test_search_by_text(client, app):
    seed_data()
    resp = client.get("/search?q=calm")
    assert resp.status_code == 200
    # Coco's description mentions "relaxed"; Mochi/Pixie mention calm.
    assert b"Mochi" in resp.data or b"Pixie" in resp.data


def test_search_matches_breed(client, app):
    seed_data()
    resp = client.get("/search?q=beagle")
    assert b"Bruno" in resp.data


def test_search_no_results(client, app):
    seed_data()
    resp = client.get("/search?q=dinosaur")
    assert b"No pets matched" in resp.data


# ---- Stories ----
def test_stories_page(client, app):
    seed_data()
    resp = client.get("/stories")
    assert resp.status_code == 200
    assert b"Happy tails" in resp.data
    assert b"Featured story" in resp.data


# ---- Blog ----
def test_blog_list(client, app):
    seed_data()
    resp = client.get("/blog")
    assert resp.status_code == 200
    assert b"The Petship Journal" in resp.data
    assert b"rescue dog" in resp.data


def test_blog_category_filter(client, app):
    seed_data()
    resp = client.get("/blog?category=Health")
    body = resp.data
    assert b"Vaccination schedule" in body
    assert b"Leash training" not in body  # Training category


def test_blog_post_detail(client, app):
    seed_data()
    resp = client.get("/blog/first-30-days-rescue-dog")
    assert resp.status_code == 200
    assert b"Week one: decompress" in resp.data


def test_blog_post_does_not_repeat_body_excerpt_or_tile_cover_image(client, app):
    body = (
        "Keep your cat healthy with balanced meals and fresh water.\n\n"
        "Schedule routine veterinary check-ups and provide daily play."
    )
    post = BlogPost(
        slug="healthy-cat-blog-image-test",
        title="How to take care of a cat",
        category="Health",
        author="Agalya",
        excerpt=body[:160],
        body=body,
        cover_url="/static/uploads/blog/test-cover.jpg",
        published=True,
    )
    db.session.add(post)
    db.session.commit()

    response = client.get(f"/blog/{post.slug}")

    assert response.status_code == 200
    assert response.data.count(b"Keep your cat healthy with balanced meals and fresh water.") == 1
    assert b'<img class="blog-hero-image" src="/static/uploads/blog/test-cover.jpg"' in response.data
    assert b"background-image:url('/static/uploads/blog/test-cover.jpg')" not in response.data


def test_blog_unknown_slug_404(client, app):
    resp = client.get("/blog/nope")
    assert resp.status_code == 404


# ---- About ----
def test_about_page(client, app):
    resp = client.get("/about")
    assert resp.status_code == 200
    assert b"It's a Family" in resp.data or b"It&#39;s a Family" in resp.data


# ---- Contact ----
def test_contact_page_renders(client, app):
    resp = client.get("/contact")
    assert resp.status_code == 200
    assert b"Send us a message" in resp.data


def test_contact_submission_stored(client, app):
    resp = client.post(
        "/contact",
        data={
            "name": "Agalya",
            "email": "agalya@example.com",
            "topic": "Adoption question",
            "message": "How do I adopt Bruno?",
        },
        follow_redirects=False,
    )
    assert resp.status_code == 302
    msg = db.session.scalar(db.select(ContactMessage))
    assert msg is not None
    assert msg.email == "agalya@example.com"
    assert "Bruno" in msg.message


def test_contact_validation(client, app):
    resp = client.post("/contact", data={"name": "", "email": "bad", "message": ""})
    assert resp.status_code == 200
    assert db.session.scalar(db.select(ContactMessage)) is None


# ---- FAQ / Help ----
def test_help_page(client, app):
    seed_data()
    resp = client.get("/help")
    assert resp.status_code == 200
    assert b"How can we help" in resp.data
    assert b"adoption process" in resp.data


def test_help_search_filters(client, app):
    seed_data()
    resp = client.get("/help?q=password", headers={"HX-Request": "true"})
    body = resp.data
    assert b"reset my password" in body
    assert b"adoption process" not in body


def test_help_search_no_match(client, app):
    seed_data()
    resp = client.get("/help?q=zzzznope", headers={"HX-Request": "true"})
    assert b"No help articles match" in resp.data
