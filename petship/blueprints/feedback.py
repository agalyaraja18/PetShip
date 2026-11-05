"""Public platform feedback submission."""
from __future__ import annotations

from flask import Blueprint, flash, redirect, render_template, request, url_for
from flask_login import current_user

from ..extensions import db
from ..models.platform import PlatformFeedback

feedback_bp = Blueprint("feedback", __name__, url_prefix="/feedback")


@feedback_bp.route("", methods=["GET", "POST"])
def submit():
    if request.method == "POST":
        name = (request.form.get("name") or "").strip()
        body = (request.form.get("body") or "").strip()
        try:
            rating = int(request.form.get("rating", ""))
        except ValueError:
            rating = 0
        if not name or len(name) > 160:
            flash("Enter your name using 160 characters or fewer.", "warning")
        elif not 1 <= rating <= 5:
            flash("Choose a star rating from 1 to 5.", "warning")
        elif not body or len(body) > 2000:
            flash("Feedback is required and must be 2,000 characters or fewer.", "warning")
        else:
            db.session.add(
                PlatformFeedback(
                    user_id=current_user.id if current_user.is_authenticated else None,
                    name=name,
                    rating=rating,
                    body=body,
                )
            )
            db.session.commit()
            flash("Thank you for sharing your feedback.", "success")
            return redirect(url_for("feedback.submit"))

    return render_template(
        "feedback/submit.html",
        name=current_user.full_name if current_user.is_authenticated else "",
        active_nav="",
    )
