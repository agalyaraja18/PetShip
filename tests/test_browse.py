"""Task 10 tests: public Home and Browse with filters, sort, and htmx."""
from __future__ import annotations

from petship.seed import seed_data


def test_home_renders_with_featured(client, app):
    seed_data()
    resp = client.get("/")
    assert resp.status_code == 200
    assert b"loving home" in resp.data
    assert b"Pets waiting for a family" not in resp.data


def test_home_stats_present(client, app):
    seed_data()
    resp = client.get("/")
    # Hero shows the real live count of available pets.
    assert b"pets available right now" in resp.data


def test_home_uses_local_pet_photos_when_no_listings_exist(client, app):
    seed_data()
    from petship.extensions import db
    from petship.models.pet import Pet, PetStatus

    db.session.query(Pet).filter_by(status=PetStatus.AVAILABLE).delete()
    db.session.commit()

    response = client.get("/")
    assert response.status_code == 200
    assert b"img/pets/milo.jpg" in response.data
    assert b"img/pets/mochi.jpg" in response.data
    assert b"img/pets/snow.jpg" in response.data
    assert b"collage-placeholder" not in response.data


def test_browse_lists_available_only(client, app):
    seed_data()
    resp = client.get("/browse")
    assert resp.status_code == 200
    # Adopted Luna and draft Rocky should not appear.
    assert b"Luna" not in resp.data
    assert b"Rocky" not in resp.data
    # Available ones do.
    assert b"Bruno" in resp.data


def test_filter_by_species(client, app):
    seed_data()
    resp = client.get("/browse?species=cat")
    body = resp.data
    assert b"Mochi" in body  # a cat
    assert b"Bruno" not in body  # a dog


def test_filter_by_size(client, app):
    seed_data()
    resp = client.get("/browse?size=large")
    body = resp.data
    assert b"Max" in body  # large labrador
    assert b"Mochi" not in body  # small cat


def test_filter_by_distance(client, app):
    seed_data()
    resp = client.get("/browse?distance=4")
    body = resp.data
    assert b"Bruno" in body  # 3 km
    assert b"Luna" not in body  # adopted anyway, and 12 km


def test_filter_good_with_kids(client, app):
    seed_data()
    resp = client.get("/browse?good_with=kids")
    body = resp.data
    assert b"Bruno" in body
    # Ginger is good_with cats only.
    assert b"Ginger" not in body


def test_combined_filters(client, app):
    seed_data()
    resp = client.get("/browse?species=dog&size=small")
    body = resp.data
    assert b"Coco" in body  # small dog
    assert b"Max" not in body  # large dog


def test_htmx_returns_partial_only(client, app):
    seed_data()
    resp = client.get("/browse", headers={"HX-Request": "true"})
    assert resp.status_code == 200
    body = resp.data
    # Partial has the grid but not the full page chrome (no sidebar filters form).
    assert b"pet-grid" in body
    assert b'id="filters"' not in body


def test_sort_popular_orders_by_views(client, app):
    seed_data()
    resp = client.get("/browse?sort=popular", headers={"HX-Request": "true"})
    body = resp.data.decode()
    # Bruno (1240 views) should appear before Ginger (300 views).
    assert body.index("Bruno") < body.index("Ginger")


def test_empty_result_message(client, app):
    seed_data()
    resp = client.get("/browse?species=bird&size=large")
    assert b"No pets match" in resp.data
