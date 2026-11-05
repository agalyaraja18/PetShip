"""Profile and account settings blueprint (Task 8).

Covers the adopter-facing profile view, edit profile (with avatar upload via
the storage wrapper), the public community profile, and the account settings
screen (notification, privacy, security tabs).
"""
from __future__ import annotations

from flask import (
    Blueprint,
    abort,
    flash,
    redirect,
    render_template,
    request,
    url_for,
)
from flask_login import current_user, login_required
from flask_wtf import FlaskForm
from flask_wtf.file import FileAllowed, FileField
from wtforms import StringField, TextAreaField
from wtforms.validators import Length, Optional

from ..extensions import db
from ..models.application import Application
from ..models.health import OwnedPet
from ..models.shelter import Shelter
from ..models.user import DEFAULT_NOTIFICATION_PREFS, LIFESTYLE_TAGS, User
from ..services.storage import save_image
from ..validators import validate_phone_number

profile_bp = Blueprint("profile", __name__, url_prefix="/profile")


class EditProfileForm(FlaskForm):
    first_name = StringField("Full name", validators=[Length(max=80)])
    last_name = StringField("Last name", validators=[Length(max=80)])
    phone = StringField(
        "Phone",
        validators=[Optional(), Length(max=40), validate_phone_number],
        render_kw={"type": "tel", "autocomplete": "tel", "inputmode": "tel"},
    )
    address = StringField("Address", validators=[Optional(), Length(max=300)])
    city = StringField("City", validators=[Optional(), Length(max=120)])
    bio = TextAreaField("Bio", validators=[Optional(), Length(max=1000)])
    avatar = FileField(
        "Change photo",
        validators=[
            Optional(),
            FileAllowed(
                ["png", "jpg", "jpeg", "gif", "webp"], "Images only (PNG/JPG/GIF/WebP)."
            ),
        ],
    )


@profile_bp.route("/")
@login_required
def view():
    pets = db.session.scalars(
        db.select(OwnedPet)
        .outerjoin(Application, OwnedPet.application_id == Application.id)
        .filter(
            OwnedPet.owner_id == current_user.id,
            db.or_(
                OwnedPet.application_id.is_(None),
                Application.returned_at.is_(None),
            ),
        )
        .order_by(OwnedPet.name.asc())
    ).all()
    return render_template(
        "profile/view.html", user=current_user, pets=pets, active_nav="profile"
    )


@profile_bp.route("/edit", methods=["GET", "POST"])
@login_required
def edit():
    form = EditProfileForm(obj=current_user)
    if form.validate_on_submit():
        current_user.first_name = form.first_name.data.strip() or None
        current_user.last_name = form.last_name.data.strip() or None
        current_user.phone = (form.phone.data or "").strip() or None
        current_user.address = (form.address.data or "").strip() or None
        current_user.city = (form.city.data or "").strip() or None
        current_user.bio = (form.bio.data or "").strip() or None

        # Lifestyle tags come from checkbox group (not a WTForms field).
        selected = request.form.getlist("lifestyle_tags")
        current_user.lifestyle_tags = [t for t in selected if t in LIFESTYLE_TAGS]

        # Avatar upload (Firebase or local fallback).
        file = form.avatar.data
        if file and getattr(file, "filename", ""):
            url = save_image(file, folder="avatars")
            if url:
                current_user.avatar_url = url
            else:
                flash("That image couldn't be uploaded. Please try another.", "warning")

        db.session.commit()
        flash("Your profile has been updated.", "success")
        return redirect(url_for("profile.view"))

    return render_template(
        "profile/edit.html",
        form=form,
        user=current_user,
        all_tags=LIFESTYLE_TAGS,
        active_nav="profile",
    )


@profile_bp.route("/u/<int:user_id>")
def community(user_id: int):
    """Public-facing community profile."""
    user = db.session.get(User, user_id)
    if user is None:
        abort(404)
    if not user.profile_is_public and (
        not current_user.is_authenticated or current_user.id != user.id
    ):
        abort(403)
    return render_template("profile/community.html", profile_user=user)


# ---------------------------------------------------------------------------
# Account settings
# ---------------------------------------------------------------------------
@profile_bp.route("/settings", methods=["GET"])
@login_required
def settings():
    return render_template(
        "profile/settings.html",
        user=current_user,
        pref_keys=list(DEFAULT_NOTIFICATION_PREFS.keys()),
        active_nav="settings",
    )


@profile_bp.route("/settings/notifications", methods=["POST"])
@login_required
def update_notifications():
    prefs = {}
    for key in DEFAULT_NOTIFICATION_PREFS:
        prefs[key] = request.form.get(key) == "on"
    current_user.notification_prefs = prefs
    db.session.commit()
    flash("Notification preferences saved.", "success")
    return redirect(url_for("profile.settings"))


@profile_bp.route("/settings/privacy", methods=["POST"])
@login_required
def update_privacy():
    current_user.profile_is_public = request.form.get("profile_is_public") == "on"
    db.session.commit()
    flash("Privacy settings saved.", "success")
    return redirect(url_for("profile.settings"))


@profile_bp.route("/settings/security/2fa", methods=["POST"])
@login_required
def toggle_2fa():
    # Placeholder toggle; full TOTP enrolment is out of scope for Task 8.
    current_user.two_factor_enabled = request.form.get("two_factor_enabled") == "on"
    db.session.commit()
    state = "enabled" if current_user.two_factor_enabled else "disabled"
    flash(f"Two-factor authentication {state}.", "info")
    return redirect(url_for("profile.settings"))


@profile_bp.route("/settings/delete", methods=["POST"])
@login_required
def delete_account():
    user = current_user._get_current_object()
    from flask_login import logout_user

    shelter = db.session.scalar(db.select(Shelter).filter_by(owner_id=user.id))
    if shelter is not None:
        db.session.delete(shelter)
    logout_user()
    db.session.execute(
        db.delete(User)
        .where(User.id == user.id)
        .execution_options(synchronize_session=False)
    )
    db.session.commit()
    flash("Your account has been permanently deleted.", "info")
    return redirect(url_for("pets.home"))
