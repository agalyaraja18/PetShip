"""Task 23 tests: expense calculator and pet-friendly places map."""
from __future__ import annotations

from petship.extensions import db
from petship.models.lifestyle import ExpenseFrequency, ExpenseItem, Place
from petship.seed import seed_data


def login_agalya(client):
    seed_data()
    client.post("/auth/login", data={"role": "adopter", "email": "agalya@demo.petship", "password": "password123"})


# ---- Model math ----
def test_monthly_yearly_conversion(app):
    monthly = ExpenseItem(owner_id=1, label="Food", amount=1800,
                          frequency=ExpenseFrequency.MONTHLY)
    yearly = ExpenseItem(owner_id=1, label="Insurance", amount=3600,
                         frequency=ExpenseFrequency.YEARLY)
    assert monthly.monthly_amount == 1800
    assert monthly.yearly_amount == 21600
    assert yearly.monthly_amount == 300
    assert yearly.yearly_amount == 3600


# ---- Expense calculator ----
def test_expenses_page_totals(client, app):
    login_agalya(client)
    resp = client.get("/lifestyle/expenses")
    assert resp.status_code == 200
    assert b"Pet expense calculator" in resp.data
    # Seeded items: 1800 + 700 + 300 monthly + (6000+2400+3600)/12 yearly
    # = 2800 + 1000 = 3800 monthly.
    assert b"3,800" in resp.data


def test_add_expense(client, app):
    login_agalya(client)
    client.post("/lifestyle/expenses/add",
                data={"label": "Daycare", "category": "other", "amount": "500",
                      "frequency": "monthly"})
    item = db.session.scalar(db.select(ExpenseItem).filter_by(label="Daycare"))
    assert item is not None
    assert item.monthly_amount == 500


def test_delete_expense(client, app):
    login_agalya(client)
    item = db.session.scalar(db.select(ExpenseItem))
    client.post(f"/lifestyle/expenses/{item.id}/delete")
    assert db.session.get(ExpenseItem, item.id) is None


def test_cannot_delete_others_expense(client, app):
    login_agalya(client)
    from petship.models.user import User
    other = User(email="z@example.com", first_name="Z")
    other.set_password("password123"); other.is_active = True
    db.session.add(other); db.session.commit()
    theirs = ExpenseItem(owner_id=other.id, label="X", amount=100,
                         frequency=ExpenseFrequency.MONTHLY)
    db.session.add(theirs); db.session.commit()
    resp = client.post(f"/lifestyle/expenses/{theirs.id}/delete")
    assert resp.status_code == 404


# ---- Places map ----
def test_places_page_renders(client, app):
    login_agalya(client)
    resp = client.get("/lifestyle/places")
    assert resp.status_code == 200
    assert b"Pet-friendly places" in resp.data
    assert b"places-map" in resp.data
    assert b"leaflet" in resp.data.lower()


def test_places_json_feed(client, app):
    login_agalya(client)
    resp = client.get("/lifestyle/places.json")
    assert resp.status_code == 200
    data = resp.get_json()
    # Non-emergency places only.
    names = {p["name"] for p in data}
    assert "Theosophical Society Gardens" in names
    assert "Madras Veterinary College ER" not in names  # emergency-only
    for p in data:
        assert "lat" in p and "lng" in p


def test_places_json_category_filter(client, app):
    login_agalya(client)
    resp = client.get("/lifestyle/places.json?category=cafe")
    data = resp.get_json()
    assert all(p["category"] == "cafe" for p in data)
    assert any(p["name"] == "Paws & Brews Café" for p in data)


def test_places_requires_login(client, app):
    seed_data()
    resp = client.get("/lifestyle/places", follow_redirects=False)
    assert resp.status_code == 302
    assert "/auth/login" in resp.headers["Location"]
