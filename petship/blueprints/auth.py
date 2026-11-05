"""Authentication blueprint: registration, login/logout, email verification,
and password reset. OAuth (Task 8) is added next. The split-image auth layout
is shared across all auth screens.
"""
from __future__ import annotations

import hashlib
import hmac
import secrets
from datetime import datetime, timedelta, timezone
from urllib.parse import urlparse

from flask import (
    Blueprint,
    current_app,
    flash,
    redirect,
    render_template,
    request,
    session,
    url_for,
)
from flask_login import current_user, login_user, logout_user
from flask_wtf import FlaskForm
from flask_wtf.file import FileField
from wtforms import BooleanField, EmailField, PasswordField, SelectField, StringField
from wtforms.validators import DataRequired, Email, EqualTo, Length, Optional

from ..extensions import db
from ..models.shelter import Shelter
from ..models.user import SIGNUP_ROLES, User, UserRole
from ..models.vet import VetProfile
from ..services.mail import send_email
from ..services.storage import save_image
from ..services.tokens import generate_code
from ..validators import validate_phone_number

auth_bp = Blueprint("auth", __name__, url_prefix="/auth")


def _is_safe_next(target: str | None) -> bool:
    """Only allow same-site relative redirects for the ``next`` parameter."""
    if not target:
        return False
    parsed = urlparse(target)
    return not parsed.netloc and not parsed.scheme and target.startswith("/")


class RegistrationForm(FlaskForm):
    role = SelectField(
        "I am joining as",
        choices=[(r.value, r.label) for r in SIGNUP_ROLES],
        default=UserRole.ADOPTER.value,
        validators=[DataRequired()],
    )
    full_name = StringField("Full name", validators=[Optional(), Length(max=160)])
    first_name = StringField("First name", validators=[Optional(), Length(max=80)])
    last_name = StringField("Last name", validators=[Optional(), Length(max=80)])
    email = EmailField(
        "Email",
        filters=[lambda value: value.strip() if value else value],
        validators=[DataRequired(), Email(), Length(max=255)],
    )
    password = PasswordField(
        "Password",
        validators=[Optional(), Length(min=8, message="At least 8 characters")],
    )
    phone = StringField(
        "Phone number",
        validators=[Optional(), Length(max=40), validate_phone_number],
        render_kw={"type": "tel", "autocomplete": "tel", "inputmode": "tel"},
    )
    address = StringField("Address", validators=[Optional(), Length(max=300)])
    shelter_name = StringField("Shelter name", validators=[Optional(), Length(max=160)])
    owner_name = StringField("Shelter owner name", validators=[Optional(), Length(max=160)])
    vet_name = StringField("Veterinarian name", validators=[Optional(), Length(max=160)])
    clinic_name = StringField("Clinic name", validators=[Optional(), Length(max=160)])
    clinic_address = StringField("Clinic address", validators=[Optional(), Length(max=300)])
    shelter_photos = FileField("Shelter photos")
    certificate_photo = FileField("Doctor certificate photo")
    agree = BooleanField(
        "I agree to the Terms & Conditions and Privacy Policy",
        validators=[DataRequired(message="Please accept the terms to continue")],
    )
    # Note: SelectField enforces that `role` is one of the signup choices, so
    # ADMIN can never be self-assigned at registration — it's rejected outright.


@auth_bp.route("/register", methods=["GET", "POST"])
def register():
    form = RegistrationForm()
    # Allow pre-selecting the role from a query string (?role=shelter).
    if request.method == "GET":
        requested = request.args.get("role")
        if requested in {r.value for r in SIGNUP_ROLES}:
            form.role.data = requested

    if form.validate_on_submit():
        role = UserRole(form.role.data)
        name = (
            (form.full_name.data or "").strip()
            or " ".join(
                filter(None, [
                    (form.first_name.data or "").strip(),
                    (form.last_name.data or "").strip(),
                ])
            )
        )
        if role == UserRole.SHELTER:
            name = (form.owner_name.data or "").strip() or name
        elif role == UserRole.VET:
            name = (form.vet_name.data or "").strip() or name

        validation_error = _registration_error(form, role, name)
        if validation_error:
            flash(validation_error, "warning")
            return render_template("auth/register.html", form=form)

        email = form.email.data.lower().strip()
        existing = db.session.scalar(db.select(User).filter_by(email=email))
        if existing:
            flash(
                "An account with that email already exists. Use Registration Status "
                "to check a shelter or vet application, or try logging in.",
                "warning",
            )
            return render_template("auth/register.html", form=form)
        if _duplicate_provider_registration(role, form, name):
            flash(
                "A registration for this shelter or veterinarian is already on file. "
                "Use Registration Status to check its progress.",
                "warning",
            )
            return render_template("auth/register.html", form=form)

        first_name, _, last_name = name.partition(" ")
        adopter = role == UserRole.ADOPTER
        registration_code = secrets.token_urlsafe(24) if not adopter else None
        user = User(
            email=email,
            first_name=first_name,
            last_name=last_name or None,
            role=role,
            phone=(form.phone.data or "").strip() or None,
            address=(form.address.data or "").strip() or None,
            registration_status="approved" if adopter else "pending",
            is_active=adopter,
            registration_status_token_hash=(
                _registration_status_hash(registration_code)
                if registration_code else None
            ),
        )
        if adopter:
            user.set_password(form.password.data)
        db.session.add(user)
        db.session.flush()

        if role == UserRole.SHELTER:
            photos = []
            for photo in request.files.getlist("shelter_photos"):
                if not photo.filename:
                    continue
                photo_url = save_image(photo, folder="shelters")
                if photo_url is None:
                    flash("Upload shelter photos as PNG, JPG, GIF, or WebP images.", "warning")
                    db.session.rollback()
                    return render_template("auth/register.html", form=form)
                photos.append(photo_url)
            db.session.add(Shelter(
                owner_id=user.id,
                name=form.shelter_name.data.strip(),
                slug=f"shelter-{secrets.token_hex(8)}",
                contact_name=name,
                address=form.address.data.strip(),
                registration_photos=photos,
            ))
        elif role == UserRole.VET:
            certificate = form.certificate_photo.data
            certificate_url = save_image(certificate, folder="vet-certificates")
            if certificate_url is None:
                db.session.rollback()
                flash("Upload a valid doctor certificate image (PNG, JPG, GIF, or WebP).", "warning")
                return render_template("auth/register.html", form=form)
            db.session.add(VetProfile(
                user_id=user.id,
                display_name=name,
                slug=f"vet-{secrets.token_hex(8)}",
                clinic_name=form.clinic_name.data.strip(),
                clinic_address=form.clinic_address.data.strip(),
                certificate_url=certificate_url,
            ))

        db.session.commit()
        if adopter:
            _send_verification_code(user)
            session["pending_verification_user_id"] = user.id
            flash("We've sent a 6-digit verification code to your email.", "success")
            return redirect(url_for("auth.verify_email"))

        delivery = send_email(
            to=user.email,
            subject="PetShip registration request received",
            body=(
                f"Hello {user.full_name},\n\n"
                "Your registration request is with PetShip's admin team for review. "
                "We will email you when there is an update."
            ),
        )
        flash("Your registration request was sent to the admin team for review.", "success")
        if delivery == "console":
            flash(
                "Email delivery is not configured, so you will not receive review "
                "updates or login credentials by email. Contact the site administrator.",
                "warning",
            )
        session["new_registration_status"] = {
            "user_id": user.id,
            "access_code": registration_code,
        }
        return redirect(url_for("auth.registration_received"))

    return render_template("auth/register.html", form=form)


def _registration_error(form: RegistrationForm, role: UserRole, name: str) -> str | None:
    if not name:
        return "Enter your name."
    if not form.agree.data:
        return "Please accept the terms to continue."
    if role == UserRole.ADOPTER:
        if not (form.phone.data or "").strip() or not (form.address.data or "").strip():
            return "Enter your phone number and address."
        if not form.password.data:
            return "Choose a password with at least 8 characters."
    elif role == UserRole.SHELTER:
        if not (form.shelter_name.data or "").strip():
            return "Enter the shelter name."
        if not (form.phone.data or "").strip() or not (form.address.data or "").strip():
            return "Enter the shelter phone number and address."
        if not any(photo.filename for photo in request.files.getlist("shelter_photos")):
            return "Upload at least one shelter photo."
    elif role == UserRole.VET:
        if not (form.clinic_name.data or "").strip():
            return "Enter the clinic name."
        if not (form.phone.data or "").strip() or not (form.clinic_address.data or "").strip():
            return "Enter the phone number and clinic address."
        if not form.certificate_photo.data or not form.certificate_photo.data.filename:
            return "Upload a doctor certificate photo."
    return None


def _registration_status_hash(code: str) -> str:
    return hashlib.sha256(code.encode("utf-8")).hexdigest()


def _duplicate_provider_registration(
    role: UserRole, form: RegistrationForm, name: str
) -> bool:
    if role == UserRole.SHELTER:
        shelter_name = (form.shelter_name.data or "").strip().casefold()
        address = (form.address.data or "").strip().casefold()
        statement = (
            db.select(Shelter.id)
            .join(User, Shelter.owner_id == User.id)
            .where(
                db.func.lower(Shelter.name) == shelter_name,
                db.func.lower(Shelter.address) == address,
                User.registration_status.in_(("pending", "approved")),
            )
        )
        return db.session.scalar(statement) is not None
    if role == UserRole.VET:
        clinic_name = (form.clinic_name.data or "").strip().casefold()
        clinic_address = (form.clinic_address.data or "").strip().casefold()
        vet_name = name.strip().casefold()
        statement = (
            db.select(VetProfile.id)
            .join(User, VetProfile.user_id == User.id)
            .where(
                db.func.lower(VetProfile.display_name) == vet_name,
                db.func.lower(VetProfile.clinic_name) == clinic_name,
                db.func.lower(VetProfile.clinic_address) == clinic_address,
                User.registration_status.in_(("pending", "approved")),
            )
        )
        return db.session.scalar(statement) is not None
    return False


@auth_bp.route("/registration-received")
def registration_received():
    issued = session.pop("new_registration_status", None)
    if not issued or not issued.get("access_code"):
        return redirect(url_for("auth.registration_status"))
    return render_template(
        "auth/registration_received.html",
        access_code=issued["access_code"],
        status_url=url_for("auth.registration_status"),
    )


class RegistrationStatusForm(FlaskForm):
    role = SelectField(
        "Registration type",
        choices=[("vet", "Vet"), ("shelter", "Shelter")],
        validators=[DataRequired()],
    )
    email = EmailField(
        "Registered email",
        filters=[lambda value: value.strip() if value else value],
        validators=[DataRequired(), Email(), Length(max=255)],
    )
    access_code = StringField(
        "Registration access code",
        validators=[DataRequired(), Length(min=20, max=64)],
    )


class RegistrationPasswordForm(FlaskForm):
    password = PasswordField(
        "Create a password",
        validators=[DataRequired(), Length(min=8, message="At least 8 characters")],
    )
    confirm = PasswordField(
        "Confirm password",
        validators=[DataRequired(), EqualTo("password", message="Passwords must match")],
    )


@auth_bp.route("/registration-status", methods=["GET", "POST"])
def registration_status():
    status_form = RegistrationStatusForm()
    password_form = RegistrationPasswordForm()
    result = None

    if request.method == "POST" and request.form.get("action") == "set_password":
        user_id = session.get("registration_status_user_id")
        user = db.session.get(User, user_id) if user_id else None
        if (
            user is None
            or user.registration_status != "approved"
            or user.role not in (UserRole.SHELTER, UserRole.VET)
            or not user.force_password_reset
        ):
            session.pop("registration_status_user_id", None)
            flash("Check your registration status using your access code first.", "warning")
            return redirect(url_for("auth.registration_status"))
        if password_form.validate_on_submit():
            user.set_password(password_form.password.data)
            user.force_password_reset = False
            db.session.commit()
            session.pop("registration_status_user_id", None)
            login_user(user)
            flash("Password created. You are now logged in.", "success")
            return redirect(url_for("auth.dashboard"))
        result = _registration_status_result(user)
        return render_template(
            "auth/registration_status.html",
            form=status_form,
            password_form=password_form,
            result=result,
        )

    if request.method == "POST" and status_form.validate_on_submit():
        email = status_form.email.data.lower()
        user = db.session.scalar(
            db.select(User).filter_by(email=email, role=UserRole(status_form.role.data))
        )
        provided_hash = _registration_status_hash(status_form.access_code.data.strip())
        if (
            user is None
            or user.registration_status_token_hash is None
            or not hmac.compare_digest(
                provided_hash, user.registration_status_token_hash
            )
        ):
            flash("Those registration details could not be verified.", "warning")
        else:
            session["registration_status_user_id"] = user.id
            result = _registration_status_result(user)

    return render_template(
        "auth/registration_status.html",
        form=status_form,
        password_form=password_form,
        result=result,
    )


def _registration_status_result(user: User) -> dict:
    if user.registration_status == "rejected":
        status = "Not approved"
    elif user.registration_status == "approved":
        status = "Approved"
    else:
        status = "Under review"

    profile = None
    if user.role == UserRole.SHELTER:
        profile = db.session.scalar(
            db.select(Shelter).filter_by(owner_id=user.id)
        )
    else:
        profile = db.session.scalar(
            db.select(VetProfile).filter_by(user_id=user.id)
        )

    return {
        "role": user.role.value,
        "status": status,
        "user_id": user.public_id if user.registration_status == "approved" else None,
        "display_name": (
            profile.name if user.role == UserRole.SHELTER and profile
            else profile.clinic_name if profile
            else ("your shelter" if user.role == UserRole.SHELTER else "your clinic")
        ),
        "visit_at": profile.verification_visit_at
        if user.role == UserRole.SHELTER and profile else None,
        "visit_completed": bool(
            profile and user.role == UserRole.SHELTER
            and profile.verification_visit_completed_at
        ),
        "can_set_password": (
            user.registration_status == "approved" and user.force_password_reset
        ),
    }


def _send_verification_code(user: User) -> None:
    """Generate, store, and email a fresh 6-digit verification code.

    When no real email provider is configured (dev default), the code is also
    surfaced on-screen via a flash so the account can actually be verified
    without an inbox. With a real provider (SMTP/Resend) this does not happen.
    """
    from flask import current_app

    code = generate_code()
    user.start_verification(code)
    db.session.commit()
    delivery = send_email(
        to=user.email,
        subject="Your PetShip verification code",
        body=(
            f"Hi {user.first_name or 'there'},\n\n"
            f"Your PetShip verification code is: {code}\n\n"
            "It expires in 15 minutes. If you didn't request this, you can "
            "ignore this email."
        ),
    )
    if delivery == "console":
        flash(
            f"No email was sent because email delivery is unavailable. "
            f"Your verification code is: {code}",
            "info",
        )


class LoginForm(FlaskForm):
    role = SelectField(
        "I am logging in as",
        choices=[(role.value, role.label) for role in UserRole],
        default=UserRole.ADOPTER.value,
        validators=[DataRequired()],
    )
    email = StringField("User ID or email", validators=[DataRequired(), Length(max=255)])
    password = PasswordField("Password", validators=[DataRequired()])
    remember = BooleanField("Remember me")


@auth_bp.route("/login", methods=["GET", "POST"])
def login():
    if current_user.is_authenticated:
        return redirect(url_for("auth.dashboard"))

    form = LoginForm()
    if request.method == "GET":
        requested_role = request.args.get("role")
        if requested_role in {role.value for role in UserRole}:
            form.role.data = requested_role
    role_hint = form.role.data or UserRole.ADOPTER.value

    if form.validate_on_submit():
        identifier = form.email.data.strip()
        user = db.session.scalar(
            db.select(User).filter(
                db.or_(
                    User.public_id == identifier.upper(),
                    User.email == identifier.lower(),
                )
            )
        )
        if user is not None and user.role.value != form.role.data:
            flash("Those credentials didn't match. Please try again.", "danger")
            return render_template("auth/login.html", form=form, role_hint=role_hint)
        if user is not None and user.registration_status == "pending":
            flash("Your registration is awaiting admin approval.", "info")
            return render_template("auth/login.html", form=form, role_hint=role_hint)
        if user is not None and user.registration_status == "rejected":
            flash("This registration request was not approved. Contact support for help.", "warning")
            return render_template("auth/login.html", form=form, role_hint=role_hint)
        if user is None or not user.check_password(form.password.data):
            flash("Those credentials didn't match. Please try again.", "danger")
            return render_template("auth/login.html", form=form, role_hint=role_hint)
        if not user.is_active:
            flash("This account has been suspended. Contact support.", "warning")
            return render_template("auth/login.html", form=form, role_hint=role_hint)
        if (
            user.role == UserRole.ADOPTER
            and not user.is_verified
            and user.verification_code is not None
        ):
            flash("Verify your email before logging in.", "warning")
            return render_template("auth/login.html", form=form, role_hint=role_hint)

        login_user(user, remember=form.remember.data)
        if user.force_password_reset:
            return redirect(url_for("auth.first_login_password"))
        flash(f"Welcome back, {user.first_name or 'friend'}!", "success")

        next_url = request.args.get("next")
        if _is_safe_next(next_url):
            return redirect(next_url)
        return redirect(url_for("auth.dashboard"))

    return render_template("auth/login.html", form=form, role_hint=role_hint)


@auth_bp.before_app_request
def enforce_temporary_password_reset():
    if not current_user.is_authenticated or not current_user.force_password_reset:
        return None
    if request.endpoint in {
        "auth.first_login_password",
        "auth.logout",
        "static",
    }:
        return None
    return redirect(url_for("auth.first_login_password"))


def _assign_public_id(user: User) -> str:
    if user.public_id:
        return user.public_id
    prefix = {
        UserRole.ADOPTER: "ADP",
        UserRole.SHELTER: "SHL",
        UserRole.VET: "VET",
        UserRole.ADMIN: "ADM",
    }[user.role]
    user.public_id = f"{prefix}-{user.id:08d}"
    return user.public_id


class FirstLoginPasswordForm(FlaskForm):
    password = PasswordField(
        "New password",
        validators=[DataRequired(), Length(min=8, message="At least 8 characters")],
    )
    confirm = PasswordField(
        "Confirm password",
        validators=[DataRequired(), EqualTo("password", message="Passwords must match")],
    )


@auth_bp.route("/first-login-password", methods=["GET", "POST"])
def first_login_password():
    if not current_user.is_authenticated:
        return redirect(url_for("auth.login"))
    form = FirstLoginPasswordForm()
    if form.validate_on_submit():
        current_user.set_password(form.password.data)
        current_user.force_password_reset = False
        db.session.commit()
        flash("Your password has been updated. Welcome to PetShip!", "success")
        return redirect(url_for("auth.dashboard"))
    return render_template("auth/first_login_password.html", form=form)


@auth_bp.route("/logout")
def logout():
    logout_user()
    flash("You've been logged out.", "info")
    return redirect(url_for("pets.home"))


@auth_bp.route("/dashboard")
def dashboard():
    """Role-aware landing that renders the correct shell for the current user.

    This is the layout resolver for Task 6. Each role's full dashboard is built
    in its own phase; here we prove the shell routing works end to end.
    """
    if not current_user.is_authenticated:
        return redirect(url_for("auth.login", next=url_for("auth.dashboard")))

    # Role-specific full dashboards.
    if current_user.role is UserRole.SHELTER:
        return redirect(url_for("shelter.dashboard"))
    if current_user.role is UserRole.VET:
        return redirect(url_for("vet_workspace.dashboard"))
    if current_user.role is UserRole.ADOPTER:
        return redirect(url_for("adopter.dashboard"))

    # Admin.
    return redirect(url_for("admin.dashboard"))


# ---------------------------------------------------------------------------
# Email verification (6-digit code)
# ---------------------------------------------------------------------------
class VerifyForm(FlaskForm):
    code = StringField("Code", validators=[DataRequired(), Length(min=6, max=6)])


def _pending_verification_user() -> User | None:
    from flask import session

    uid = session.get("pending_verification_user_id")
    if uid is None and current_user.is_authenticated:
        uid = current_user.id
    return db.session.get(User, uid) if uid else None


@auth_bp.route("/verify", methods=["GET", "POST"])
def verify_email():
    user = _pending_verification_user()
    if user is None:
        flash("Start by creating an account or logging in.", "info")
        return redirect(url_for("auth.login"))
    if user.is_verified:
        flash("Your email is already verified.", "info")
        return redirect(url_for("auth.dashboard") if current_user.is_authenticated else url_for("auth.login"))

    form = VerifyForm()
    if form.validate_on_submit():
        submitted = form.code.data.strip()
        if not user.verification_is_fresh():
            flash("That code has expired. We've sent a new one.", "warning")
            _send_verification_code(user)
            return render_template("auth/verify.html", form=form, email=user.email)
        if submitted != user.verification_code:
            flash("That code didn't match. Please try again.", "danger")
            return render_template("auth/verify.html", form=form, email=user.email)

        user.is_verified = True
        user.verification_code = None
        public_id = _assign_public_id(user)
        db.session.commit()
        session.pop("pending_verification_user_id", None)
        flash(
            f"Your email is verified. Your PetShip user ID is {public_id}. "
            "Log in using this ID and your password.",
            "success",
        )
        if current_user.is_authenticated:
            return redirect(url_for("auth.dashboard"))
        return redirect(url_for("auth.login"))

    return render_template("auth/verify.html", form=form, email=user.email)


@auth_bp.route("/verify/resend", methods=["POST"])
def resend_code():
    user = _pending_verification_user()
    if user is None:
        return redirect(url_for("auth.login"))
    _send_verification_code(user)
    flash("A new code is on its way.", "info")
    return redirect(url_for("auth.verify_email"))


# ---------------------------------------------------------------------------
# Password reset
# ---------------------------------------------------------------------------
class ForgotForm(FlaskForm):
    email = StringField("Email address", validators=[DataRequired(), Email()])


class ResetForm(FlaskForm):
    password = PasswordField(
        "New password",
        validators=[DataRequired(), Length(min=8, message="At least 8 characters")],
    )
    confirm = PasswordField(
        "Confirm password",
        validators=[DataRequired(), EqualTo("password", message="Passwords must match")],
    )


class ResetCodeForm(FlaskForm):
    code = StringField(
        "6-digit code",
        validators=[DataRequired(), Length(min=6, max=6)],
    )


class ResetCredentialsForm(FlaskForm):
    public_id = StringField("User ID", validators=[DataRequired(), Length(max=24)])
    password = PasswordField(
        "New password",
        validators=[DataRequired(), Length(min=8, message="At least 8 characters")],
    )
    confirm = PasswordField(
        "Re-enter new password",
        validators=[DataRequired(), EqualTo("password", message="Passwords must match")],
    )


@auth_bp.route("/forgot-password", methods=["GET", "POST"])
def forgot_password():
    form = ForgotForm()
    if form.validate_on_submit():
        user = db.session.scalar(
            db.select(User).filter_by(email=form.email.data.lower().strip())
        )
        if user is not None:
            code = generate_code()
            user.start_reset(code)
            db.session.commit()
            delivery = send_email(
                to=user.email,
                subject="Your PetShip password reset code",
                body=(
                    f"Hi {user.first_name or 'there'},\n\n"
                    f"Your 6-digit password reset code is {code}. "
                    "It is valid for 15 minutes.\n\n"
                    "If you didn't request this, you can ignore this email."
                ),
            )
            session["password_reset_user_id"] = user.id
            session.pop("password_reset_verified_user_id", None)
            if delivery == "console":
                flash(
                    f"No email was sent because email delivery is unavailable. "
                    f"Your reset code is: {code}",
                    "info",
                )
        # Always show the same message to avoid leaking which emails exist.
        flash("If that email is registered, a 6-digit reset code is on its way.", "info")
        return render_template(
            "auth/forgot.html",
            form=form,
            reset_code_form=ResetCodeForm(),
            sent=True,
            email=form.email.data.lower().strip(),
        )

    return render_template(
        "auth/forgot.html",
        form=form,
        reset_code_form=ResetCodeForm(),
        sent=False,
    )


@auth_bp.route("/reset-password/code", methods=["POST"])
def verify_reset_code():
    form = ResetCodeForm()
    user_id = session.get("password_reset_user_id")
    user = db.session.get(User, user_id) if user_id else None
    if user is None:
        flash("Request a password reset code first.", "warning")
        return redirect(url_for("auth.forgot_password"))
    if form.validate_on_submit():
        if (
            not user.reset_is_fresh(timedelta(minutes=15))
            or form.code.data.strip() != user.reset_token
        ):
            flash("That code is invalid or has expired. Request a new one.", "danger")
            return redirect(url_for("auth.forgot_password"))
        session["password_reset_verified_user_id"] = user.id
        return redirect(url_for("auth.reset_password_by_code"))
    flash("Enter the 6-digit code.", "warning")
    return redirect(url_for("auth.forgot_password"))


@auth_bp.route("/reset-password", methods=["GET", "POST"])
def reset_password_by_code():
    user_id = session.get("password_reset_verified_user_id")
    user = db.session.get(User, user_id) if user_id else None
    if user is None or not user.reset_is_fresh(timedelta(minutes=15)):
        session.pop("password_reset_verified_user_id", None)
        flash("Verify your reset code before choosing a new password.", "warning")
        return redirect(url_for("auth.forgot_password"))

    form = ResetCredentialsForm()
    if form.validate_on_submit():
        if form.public_id.data.strip().upper() != (user.public_id or ""):
            flash("That user ID does not match the verified email.", "danger")
            return render_template("auth/reset.html", form=form, code_verified=True)
        user.set_password(form.password.data)
        user.force_password_reset = False
        user.clear_reset()
        db.session.commit()
        session.pop("password_reset_user_id", None)
        session.pop("password_reset_verified_user_id", None)
        flash("Your password has been updated. Log in with your user ID and new password.", "success")
        return redirect(url_for("auth.login"))
    return render_template("auth/reset.html", form=form, code_verified=True)


@auth_bp.route("/reset-password/<token>", methods=["GET", "POST"])
def reset_password(token: str):
    user = db.session.scalar(db.select(User).filter_by(reset_token=token))
    if user is None or not user.reset_is_fresh():
        flash("That reset link is invalid or has expired.", "danger")
        return redirect(url_for("auth.forgot_password"))

    form = ResetForm()
    if form.validate_on_submit():
        user.set_password(form.password.data)
        user.force_password_reset = False
        user.clear_reset()
        db.session.commit()
        flash("Your password has been updated. Please log in.", "success")
        return redirect(url_for("auth.login"))

    return render_template("auth/reset.html", form=form, token=token)


@auth_bp.route("/google")
def google_login():
    """Begin Google OAuth. Disabled gracefully when unconfigured."""
    from ..services.oauth import google_enabled, oauth

    if not google_enabled():
        flash("Google sign-in isn't configured on this server.", "info")
        return redirect(url_for("auth.login"))
    redirect_uri = url_for("auth.google_callback", _external=True)
    return oauth.google.authorize_redirect(redirect_uri)


@auth_bp.route("/google/callback")
def google_callback():
    from ..services.oauth import google_enabled, oauth

    if not google_enabled():
        return redirect(url_for("auth.login"))

    token = oauth.google.authorize_access_token()
    info = token.get("userinfo") or {}
    email = (info.get("email") or "").lower().strip()
    sub = info.get("sub")
    if not email:
        flash("Google didn't return an email address.", "danger")
        return redirect(url_for("auth.login"))

    user = db.session.scalar(db.select(User).filter_by(email=email))
    if user is None:
        # First-time Google sign-in creates a verified adopter account.
        user = User(
            email=email,
            first_name=info.get("given_name"),
            last_name=info.get("family_name"),
            role=UserRole.ADOPTER,
            is_verified=True,
            oauth_provider="google",
            oauth_sub=sub,
        )
        db.session.add(user)
        db.session.flush()
        _assign_public_id(user)
    else:
        user.oauth_provider = "google"
        user.oauth_sub = sub
        user.is_verified = True
        _assign_public_id(user)
    db.session.commit()

    if not user.is_active:
        flash("This account has been suspended. Contact support.", "warning")
        return redirect(url_for("auth.login"))

    login_user(user, remember=True)
    flash(f"Welcome, {user.first_name or 'friend'}!", "success")
    return redirect(url_for("auth.dashboard"))
