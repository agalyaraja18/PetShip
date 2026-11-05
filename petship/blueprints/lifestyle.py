"""Lifestyle tools: expense calculator + pet-friendly places map (Task 23)."""
from __future__ import annotations

from flask import (
    Blueprint,
    abort,
    jsonify,
    redirect,
    render_template,
    request,
    url_for,
)
from flask_login import current_user, login_required

from ..extensions import db
from ..models.lifestyle import (
    EXPENSE_CATEGORIES,
    ExpenseFrequency,
    ExpenseItem,
    Place,
    PlaceCategory,
)

lifestyle_bp = Blueprint("lifestyle", __name__, url_prefix="/lifestyle")

# Category -> colour for the donut chart.
CATEGORY_COLOURS = {
    "food": "#a85d43",
    "vet": "#d99b7c",
    "grooming": "#46352f",
    "medication": "#c97a2b",
    "toys": "#e6d8c7",
    "insurance": "#5a7fa3",
    "other": "#b3a79e",
}


def _expense_summary(items):
    monthly = sum(i.monthly_amount for i in items)
    yearly = sum(i.yearly_amount for i in items)
    # Breakdown by category (monthly basis) for the donut.
    by_cat: dict[str, float] = {}
    for i in items:
        by_cat[i.category] = by_cat.get(i.category, 0) + i.monthly_amount
    breakdown = [
        {
            "category": cat,
            "label": EXPENSE_CATEGORIES.get(cat, cat.title()),
            "amount": round(amt),
            "colour": CATEGORY_COLOURS.get(cat, "#b3a79e"),
            "percent": round(100 * amt / monthly) if monthly else 0,
        }
        for cat, amt in sorted(by_cat.items(), key=lambda t: t[1], reverse=True)
    ]
    return round(monthly), round(yearly), breakdown


# ---- Expense calculator ----
@lifestyle_bp.route("/expenses")
@login_required
def expenses():
    items = db.session.scalars(
        db.select(ExpenseItem).filter_by(owner_id=current_user.id).order_by(ExpenseItem.id)
    ).all()
    monthly, yearly, breakdown = _expense_summary(items)
    return render_template(
        "lifestyle/expenses.html",
        items=items,
        monthly=monthly,
        yearly=yearly,
        breakdown=breakdown,
        categories=EXPENSE_CATEGORIES,
        active_nav="expenses",
    )


@lifestyle_bp.route("/expenses/add", methods=["POST"])
@login_required
def add_expense():
    try:
        amount = float(request.form.get("amount") or 0)
    except ValueError:
        amount = 0
    freq = request.form.get("frequency", "monthly")
    item = ExpenseItem(
        owner_id=current_user.id,
        label=(request.form.get("label") or "Expense").strip(),
        category=request.form.get("category", "other"),
        amount=amount,
        frequency=ExpenseFrequency(freq if freq in ("monthly", "yearly") else "monthly"),
    )
    db.session.add(item)
    db.session.commit()
    return redirect(url_for("lifestyle.expenses"))


@lifestyle_bp.route("/expenses/<int:item_id>/delete", methods=["POST"])
@login_required
def delete_expense(item_id: int):
    item = db.session.get(ExpenseItem, item_id)
    if item is None or item.owner_id != current_user.id:
        abort(404)
    db.session.delete(item)
    db.session.commit()
    return redirect(url_for("lifestyle.expenses"))


# ---- Pet-friendly places map ----
@lifestyle_bp.route("/places")
@login_required
def places():
    return render_template(
        "lifestyle/places.html",
        categories=list(PlaceCategory),
        active_nav="places",
    )


@lifestyle_bp.route("/places.json")
@login_required
def places_json():
    """GeoJSON-ish feed for the Leaflet map, optionally filtered by category."""
    category = request.args.get("category")
    query = db.select(Place).filter_by(emergency_24h=False)
    if category and category != "all":
        try:
            query = query.filter_by(category=PlaceCategory(category))
        except ValueError:
            pass
    places = db.session.scalars(query).all()
    return jsonify(
        [
            {
                "id": p.id,
                "name": p.name,
                "category": p.category.value,
                "category_label": p.category.label,
                "address": p.address,
                "lat": p.lat,
                "lng": p.lng,
                "rating": p.rating,
                "note": p.note,
                "distance_km": p.distance_km,
            }
            for p in places
        ]
    )
