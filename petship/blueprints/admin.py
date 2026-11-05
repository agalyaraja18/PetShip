"""Admin console: dashboard, user management, verification, analytics
(Tasks 34, 35, 37). Moderation queues live in admin_moderation.py (Task 36)."""
from __future__ import annotations

import csv
import io
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from flask import (
    Blueprint,
    current_app,
    Response,
    abort,
    flash,
    redirect,
    render_template,
    request,
    url_for,
)
from flask_login import current_user

from ..extensions import db
from ..models.application import Application, ApplicationStage
from ..models.pet import Pet, PetStatus, Species
from ..models.report import AbuseReport, AbuseStatus
from ..models.shelter import Shelter
from ..models.content import ContactMessage
from ..models.platform import PlatformFeedback, PlatformMetricEvent
from ..models.lostfound import LostFoundReport, ReportKind, ReportStatus
from ..models.reminder import Notification
from ..models.user import User, UserRole
from ..models.vet import VetProfile
from ..services.mail import send_email
from ..security import role_required

admin_bp = Blueprint("admin", __name__, url_prefix="/admin")


def _shelter_visit_utc(shelter: Shelter, admin_timezone: ZoneInfo) -> datetime | None:
    visit_at = shelter.verification_visit_at
    if visit_at is None:
        return None
    if shelter.verification_visit_time_is_utc:
        if visit_at.tzinfo is None:
            visit_at = visit_at.replace(tzinfo=timezone.utc)
    else:
        visit_at = visit_at.replace(tzinfo=admin_timezone)
    return visit_at.astimezone(timezone.utc)


def _count(model, **filters) -> int:
    q = db.select(db.func.count()).select_from(model)
    if filters:
        q = q.filter_by(**filters)
    return db.session.scalar(q) or 0


# ---- Dashboard (Task 34) ----
@admin_bp.route("/")
@role_required(UserRole.ADMIN)
def dashboard():
    stats = {
        "users": _count(User),
        "shelters": _count(Shelter),
        "vets": _count(VetProfile),
        "adoptions": _count(Application, stage=ApplicationStage.COMPLETE),
        "reports": _count(AbuseReport, status=AbuseStatus.OPEN),
    }
    pending_shelters = db.session.scalar(
        db.select(db.func.count())
        .select_from(Shelter)
        .where(
            Shelter.is_verified.is_(False),
            Shelter.owner_id.is_not(None),
            Shelter.owner.has(User.registration_status == "pending"),
        )
    ) or 0
    pending_vets = db.session.scalar(
        db.select(db.func.count())
        .select_from(VetProfile)
        .join(User, VetProfile.user_id == User.id)
        .where(
            VetProfile.is_verified.is_(False),
            User.registration_status == "pending",
        )
    ) or 0

    # Verification queue preview (mix of shelters and vets awaiting review).
    queue = []
    for s in db.session.scalars(
        db.select(Shelter)
        .where(
            Shelter.is_verified.is_(False),
            Shelter.owner_id.is_not(None),
            Shelter.owner.has(User.registration_status == "pending"),
        )
        .order_by(Shelter.created_at, Shelter.id)
        .limit(3)
    ).all():
        queue.append({"type": "shelter", "id": s.id, "name": s.name})
    for v in db.session.scalars(
        db.select(VetProfile)
        .join(User, VetProfile.user_id == User.id)
        .where(
            VetProfile.is_verified.is_(False),
            User.registration_status == "pending",
        )
        .order_by(VetProfile.created_at, VetProfile.id)
        .limit(3)
    ).all():
        queue.append({"type": "vet", "id": v.id, "name": v.display_name})

    return render_template(
        "admin/dashboard.html",
        stats=stats,
        pending_shelters=pending_shelters,
        pending_vets=pending_vets,
        queue=queue,
        active_nav="overview",
    )


# ---- User management (Task 34) ----
@admin_bp.route("/users")
@role_required(UserRole.ADMIN)
def users():
    role = request.args.get("role")
    q = (request.args.get("q") or "").strip().lower()
    query = db.select(User).order_by(User.created_at.desc())
    if role and role in {r.value for r in UserRole}:
        query = query.filter_by(role=UserRole(role))
    users = db.session.scalars(query).all()
    if q:
        users = [
            u for u in users
            if q in u.email.lower() or q in (u.full_name or "").lower()
        ]
    return render_template(
        "admin/users.html",
        users=users,
        roles=list(UserRole),
        active_role=role or "all",
        q=q,
        active_nav="users",
    )


@admin_bp.route("/users/<int:user_id>/suspend", methods=["POST"])
@role_required(UserRole.ADMIN)
def toggle_suspend(user_id: int):
    user = db.session.get(User, user_id)
    if user is None:
        abort(404)
    if user.id == current_user.id:
        flash("You can't suspend your own account.", "warning")
        return redirect(url_for("admin.users"))
    user.is_active = not user.is_active
    db.session.commit()
    flash(f"{user.full_name} {'restored' if user.is_active else 'suspended'}.", "info")
    return redirect(url_for("admin.users"))


@admin_bp.route("/users.csv")
@role_required(UserRole.ADMIN)
def users_csv():
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(["id", "email", "name", "role", "active", "verified", "joined"])
    for u in db.session.scalars(db.select(User).order_by(User.id)).all():
        writer.writerow([
            u.id, u.email, u.full_name, u.role.value,
            u.is_active, u.is_verified, u.created_at.strftime("%Y-%m-%d"),
        ])
    return Response(
        buf.getvalue(),
        mimetype="text/csv",
        headers={"Content-Disposition": "attachment; filename=petship-users.csv"},
    )


@admin_bp.route("/feedback")
@role_required(UserRole.ADMIN)
def feedback():
    items = db.session.scalars(
        db.select(PlatformFeedback)
        .order_by(PlatformFeedback.created_at.desc())
        .limit(200)
    ).all()
    average_rating = round(
        sum(item.rating for item in items) / len(items), 1
    ) if items else 0
    return render_template(
        "admin/feedback.html",
        feedback_items=items,
        average_rating=average_rating,
        active_nav="feedback",
    )


@admin_bp.route("/feedback/<int:feedback_id>/action", methods=["POST"])
@role_required(UserRole.ADMIN)
def feedback_action(feedback_id: int):
    item = db.session.get(PlatformFeedback, feedback_id)
    if item is None:
        abort(404)
    action = request.form.get("action")
    if action not in {"handled", "unhandled"}:
        abort(400)
    item.handled = action == "handled"
    db.session.commit()
    flash("Feedback status updated.", "success")
    return redirect(url_for("admin.feedback"))


@admin_bp.route("/messages")
@role_required(UserRole.ADMIN)
def messages():
    items = db.session.scalars(
        db.select(ContactMessage).order_by(
            ContactMessage.handled.asc(), ContactMessage.created_at.desc()
        ).limit(200)
    ).all()
    return render_template(
        "admin/messages.html",
        messages=items,
        active_nav="messages",
    )


@admin_bp.route("/messages/<int:message_id>/action", methods=["POST"])
@role_required(UserRole.ADMIN)
def message_action(message_id: int):
    item = db.session.get(ContactMessage, message_id)
    if item is None:
        abort(404)
    action = request.form.get("action")
    if action not in {"handled", "unhandled"}:
        abort(400)
    item.handled = action == "handled"
    db.session.commit()
    flash("Contact message status updated.", "success")
    return redirect(url_for("admin.messages"))


@admin_bp.route("/lost-found")
@role_required(UserRole.ADMIN)
def lost_found():
    selected_view = request.args.get("view", "recent")
    if selected_view not in {"recent", "lost", "reunited"}:
        selected_view = "recent"
    query = db.select(LostFoundReport)
    if selected_view == "lost":
        query = query.filter(
            LostFoundReport.kind == ReportKind.LOST,
            LostFoundReport.status != ReportStatus.REUNITED,
        )
    elif selected_view == "reunited":
        query = query.filter(
            db.or_(
                LostFoundReport.kind == ReportKind.FOUND,
                LostFoundReport.status == ReportStatus.REUNITED,
            )
        )
    reports = db.session.scalars(
        query
        .order_by(LostFoundReport.created_at.desc())
        .limit(500)
    ).all()
    total_reports = _count(LostFoundReport)
    reunited_condition = db.or_(
        LostFoundReport.kind == ReportKind.FOUND,
        LostFoundReport.status == ReportStatus.REUNITED,
    )
    counts = {
        "recent": total_reports,
        "lost": db.session.scalar(
            db.select(db.func.count()).select_from(LostFoundReport).filter(
                LostFoundReport.kind == ReportKind.LOST,
                LostFoundReport.status != ReportStatus.REUNITED,
            )
        ) or 0,
        "reunited": db.session.scalar(
            db.select(db.func.count()).select_from(LostFoundReport).filter(
                reunited_condition
            )
        ) or 0,
    }
    return render_template(
        "admin/lostfound.html",
        reports=reports,
        counts=counts,
        selected_view=selected_view,
        active_nav="lostfound",
    )


# ---- Verification queues (Task 35) ----
@admin_bp.route("/verify/shelters")
@role_required(UserRole.ADMIN)
def verify_shelters():
    selected_view = request.args.get("view", "all")
    if selected_view not in {"all", "visit", "approved"}:
        selected_view = "all"
    pending_registration = Shelter.owner.has(
        User.registration_status == "pending"
    )
    if selected_view == "visit":
        status_filter = db.and_(
            Shelter.is_verified.is_(False),
            Shelter.owner_id.is_not(None),
            pending_registration,
            Shelter.verification_visit_at.is_not(None),
        )
    elif selected_view == "approved":
        status_filter = db.and_(
            Shelter.is_verified.is_(True),
            Shelter.owner_id.is_not(None),
        )
    else:
        status_filter = db.or_(
            db.and_(
                Shelter.is_verified.is_(True),
                Shelter.owner_id.is_not(None),
            ),
            db.and_(
                Shelter.is_verified.is_(False),
                Shelter.owner_id.is_not(None),
                pending_registration,
            ),
        )
    candidates = db.session.scalars(
        db.select(Shelter)
        .where(status_filter)
        .order_by(Shelter.created_at, Shelter.id)
    ).all()
    pending = []
    seen = set()
    for shelter in candidates:
        key = (shelter.name.strip().casefold(), (shelter.address or "").strip().casefold())
        if key not in seen:
            seen.add(key)
            pending.append(shelter)
    return render_template(
        "admin/verify_shelters.html",
        pending=pending,
        selected_view=selected_view,
        active_nav="shelterverify",
    )


@admin_bp.route("/verify/shelters/<int:shelter_id>", methods=["POST"])
@role_required(UserRole.ADMIN)
def verify_shelter(shelter_id: int):
    shelter = db.session.get(Shelter, shelter_id)
    if shelter is None:
        abort(404)
    decision = request.form.get("decision")
    if decision == "schedule_visit":
        try:
            visit_value = (
                request.form.get("scheduled_for_utc")
                or request.form.get("scheduled_for", "")
            )
            visit_at = datetime.fromisoformat(visit_value)
        except ValueError:
            flash("Choose a valid date and time for the shelter visit.", "warning")
            return redirect(url_for("admin.verify_shelters"))
        if visit_at.tzinfo is None:
            visit_at = visit_at.replace(tzinfo=timezone.utc)
        else:
            visit_at = visit_at.astimezone(timezone.utc)
        if visit_at <= datetime.now(timezone.utc):
            flash("Choose a future date and time for the shelter visit.", "warning")
            return redirect(url_for("admin.verify_shelters"))
        shelter.verification_visit_at = visit_at
        shelter.verification_visit_time_is_utc = True
        if shelter.owner:
            Notification.push(
                shelter.owner.id,
                "Shelter verification visit scheduled",
                f"Your in-person verification visit is scheduled for "
                f"{visit_at.strftime('%d %b %Y at %I:%M %p UTC')}.",
                category="general",
                link=url_for("auth.login", role="shelter"),
            )
        db.session.commit()
        if shelter.owner:
            delivery = send_email(
                to=shelter.owner.email,
                subject="PetShip shelter verification visit scheduled",
                body=(
                    f"Your in-person shelter verification visit is scheduled for "
                    f"{visit_at.strftime('%d %b %Y at %I:%M %p UTC')}."
                ),
            )
            if delivery == "console":
                flash(
                    "Visit time was saved, but email is not configured; notify "
                    "the shelter outside PetShip.",
                    "warning",
                )
        flash(f"Verification visit scheduled for {shelter.name}.", "success")
    elif decision == "visit_completed":
        try:
            admin_timezone = ZoneInfo(request.form.get("browser_timezone") or "UTC")
        except ZoneInfoNotFoundError:
            flash("Could not determine your time zone. Please reload and try again.", "warning")
            return redirect(url_for("admin.verify_shelters"))
        visit_at = _shelter_visit_utc(shelter, admin_timezone)
        if visit_at is None or visit_at > datetime.now(timezone.utc):
            flash("The scheduled visit must have taken place before it can be verified.", "warning")
            return redirect(url_for("admin.verify_shelters"))
        shelter.verification_visit_at = visit_at
        shelter.verification_visit_time_is_utc = True
        shelter.verification_visit_completed_at = datetime.now(timezone.utc)
        if shelter.owner:
            Notification.push(
                shelter.owner.id,
                "Shelter verification visit completed",
                "Your in-person visit is complete. PetShip will notify you after the final review.",
                category="general",
                link=url_for("auth.login", role="shelter"),
            )
        db.session.commit()
        flash(f"In-person verification recorded for {shelter.name}.", "success")
    elif decision == "approve":
        if shelter.owner and shelter.owner.registration_status == "pending":
            try:
                admin_timezone = ZoneInfo(request.form.get("browser_timezone") or "UTC")
            except ZoneInfoNotFoundError:
                flash("Could not determine your time zone. Please reload and try again.", "warning")
                return redirect(url_for("admin.verify_shelters"))
            visit_at = _shelter_visit_utc(shelter, admin_timezone)
            now = datetime.now(timezone.utc)
            if visit_at is None:
                flash("Schedule the in-person shelter visit before approving.", "warning")
                return redirect(url_for("admin.verify_shelters"))
            if visit_at > now:
                flash("The scheduled visit has not taken place yet.", "warning")
                return redirect(url_for("admin.verify_shelters"))
            shelter.verification_visit_at = visit_at
            shelter.verification_visit_time_is_utc = True
            if shelter.verification_visit_completed_at is None:
                shelter.verification_visit_completed_at = now
                Notification.push(
                    shelter.owner.id,
                    "Shelter verification visit completed",
                    "The admin recorded your in-person visit as complete and approved your registration.",
                    category="general",
                    link=url_for("auth.login", role="shelter"),
                )
        shelter.is_verified = True
        if shelter.owner and shelter.owner.registration_status == "pending":
            _approve_registration(shelter.owner)
            Notification.push(
                shelter.owner.id,
                "Shelter registration approved",
                "Your registration is approved. Use Registration Status with your access code to see your user ID and create a password.",
                category="general",
                link=url_for("auth.login", role="shelter"),
            )
            delivery = send_email(
                to=shelter.owner.email,
                subject="Your PetShip shelter registration is approved",
                body=_approval_credentials(shelter.owner, shelter.name),
            )
            if delivery == "console":
                flash(
                    "Approval was saved, but no email was sent. Configure email "
                    "delivery to send the shelter's login credentials.",
                    "warning",
                )
        flash(f"{shelter.name} approved.", "success")
    elif decision == "reject":
        if shelter.owner and shelter.owner.registration_status == "pending":
            shelter.owner.registration_status = "rejected"
            shelter.owner.is_active = False
            Notification.push(
                shelter.owner_id,
                "Shelter registration update",
                "Your registration request was not approved. Contact PetShip support for assistance.",
                category="general",
                link=url_for("auth.login", role="shelter"),
            )
            delivery = send_email(
                to=shelter.owner.email,
                subject="PetShip shelter registration update",
                body="We’re unable to approve your shelter registration at this time. Contact PetShip support for assistance.",
            )
            if delivery == "console":
                flash(
                    "Rejection was saved, but no email was sent because email "
                    "delivery is not configured.",
                    "warning",
                )
        flash(f"{shelter.name} rejected.", "info")
    db.session.commit()
    return redirect(url_for("admin.verify_shelters"))


@admin_bp.route("/verify/vets")
@role_required(UserRole.ADMIN)
def verify_vets():
    selected_view = request.args.get("view", "all")
    if selected_view not in {"all", "visit", "approved"}:
        selected_view = "all"
    pending_registration = db.and_(
        VetProfile.is_verified.is_(False),
        User.registration_status == "pending",
    )
    approved_registration = db.and_(
        VetProfile.is_verified.is_(True),
        User.registration_status == "approved",
    )
    if selected_view == "visit":
        status_filter = pending_registration
    elif selected_view == "approved":
        status_filter = approved_registration
    else:
        status_filter = db.or_(pending_registration, approved_registration)
    candidates = db.session.scalars(
        db.select(VetProfile)
        .join(User, VetProfile.user_id == User.id)
        .where(status_filter)
        .order_by(VetProfile.created_at, VetProfile.id)
    ).all()
    pending = []
    seen = set()
    for vet in candidates:
        key = (
            vet.display_name.strip().casefold(),
            (vet.clinic_name or "").strip().casefold(),
            (vet.clinic_address or "").strip().casefold(),
        )
        if key not in seen:
            seen.add(key)
            pending.append(vet)
    return render_template(
        "admin/verify_vets.html",
        pending=pending,
        selected_view=selected_view,
        active_nav="vetverify",
    )


@admin_bp.route("/verify/vets/<int:vet_id>", methods=["POST"])
@role_required(UserRole.ADMIN)
def verify_vet(vet_id: int):
    vet = db.session.get(VetProfile, vet_id)
    if vet is None:
        abort(404)
    decision = request.form.get("decision")
    if decision == "approve":
        vet.is_verified = True
        if vet.user.registration_status == "pending":
            _approve_registration(vet.user)
            Notification.push(
                vet.user_id,
                "Veterinarian registration approved",
                "Your registration is approved. Use Registration Status with your access code to see your user ID and create a password.",
                category="general",
                link=url_for("auth.login", role="vet"),
            )
            delivery = send_email(
                to=vet.user.email,
                subject="Your PetShip veterinarian registration is approved",
                body=_approval_credentials(vet.user, vet.display_name),
            )
            if delivery == "console":
                flash(
                    "Approval was saved, but no email was sent. Configure email "
                    "delivery to send the veterinarian's login credentials.",
                    "warning",
                )
        flash(f"{vet.display_name} approved.", "success")
    elif decision == "reject":
        vet.user.registration_status = "rejected"
        vet.user.is_active = False
        Notification.push(
            vet.user_id,
            "Veterinarian registration update",
            "Your registration request was not approved. Contact PetShip support for assistance.",
            category="general",
            link=url_for("auth.login", role="vet"),
        )
        delivery = send_email(
            to=vet.user.email,
            subject="PetShip veterinarian registration update",
            body="We’re unable to approve your veterinarian registration at this time. Contact PetShip support for assistance.",
        )
        if delivery == "console":
            flash(
            "Rejection was saved, but no email was sent because email "
            "delivery is not configured.",
            "warning",
            )
        flash(f"{vet.display_name} rejected.", "info")
    db.session.commit()
    return redirect(url_for("admin.verify_vets"))


def _approve_registration(user: User) -> None:
    prefixes = {
        UserRole.ADOPTER: "ADP",
        UserRole.SHELTER: "SHL",
        UserRole.VET: "VET",
        UserRole.ADMIN: "ADM",
    }
    if not user.public_id:
        user.public_id = f"{prefixes[user.role]}-{user.id:08d}"
    user.registration_status = "approved"
    user.is_active = True
    user.is_verified = True
    user.force_password_reset = True


def _approval_credentials(user: User, display_name: str) -> str:
    user.force_password_reset = True
    return (
        f"Hello {display_name},\n\n"
        "Your PetShip registration has been approved.\n"
        f"User ID: {user.public_id}\n\n"
        "For account security, your password is not sent or displayed. Open "
        "PetShip's Registration Status page, choose your registration type, and "
        "enter your registered email and the access code shown when you applied "
        "to create your login password."
    )


# ---- Platform analytics (Task 37) ----
@admin_bp.route("/analytics")
@role_required(UserRole.ADMIN)
def analytics():
    from ..models.appointment import Appointment, AppointmentKind

    periods = {"7d": 7, "30d": 30, "90d": 90, "1y": 365}
    period = request.args.get("period", "30d")
    if period not in periods:
        period = "30d"
    today = datetime.now(timezone.utc).date()
    interval = "week" if period == "90d" else "month" if period == "1y" else "day"
    if interval == "month":
        start_date = today.replace(day=1)
        for _ in range(11):
            start_date = (start_date.replace(day=1) - timedelta(days=1)).replace(day=1)
        bucket_count = 12
    else:
        bucket_count = 13 if interval == "week" else periods[period]
        start_date = today - timedelta(days=(bucket_count * (7 if interval == "week" else 1)) - 1)
    start = datetime.combine(start_date, datetime.min.time(), tzinfo=timezone.utc)

    def bucket_index(value: datetime) -> int | None:
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        value_date = value.astimezone(timezone.utc).date()
        days = (value_date - start_date).days
        index = (
            (value_date.year - start_date.year) * 12 + value_date.month - start_date.month
            if interval == "month"
            else days // 7 if interval == "week"
            else days
        )
        return index if 0 <= index < bucket_count else None

    if interval == "month":
        labels = []
        cursor = start_date
        for _ in range(bucket_count):
            labels.append(cursor.strftime("%b %Y"))
            cursor = (cursor.replace(day=28) + timedelta(days=4)).replace(day=1)
    elif interval == "week":
        labels = [
            (start_date + timedelta(days=7 * index)).strftime("%d %b")
            for index in range(bucket_count)
        ]
    else:
        labels = [
            (start_date + timedelta(days=index)).strftime("%d %b")
            for index in range(bucket_count)
        ]

    series = {
        "adopters": [0] * bucket_count,
        "shelters": [0] * bucket_count,
        "vets": [0] * bucket_count,
        "adoptions": [0] * bucket_count,
        "vet_bookings": [0] * bucket_count,
        "ai_matches": [0] * bucket_count,
        "pet_returns": [0] * bucket_count,
    }

    users = db.session.execute(
        db.select(User.role, User.created_at)
        .filter(User.role.in_([UserRole.ADOPTER, UserRole.VET]))
        .filter(User.created_at >= start)
    ).all()
    for role, created_at in users:
        index = bucket_index(created_at)
        if index is not None:
            series["adopters" if role == UserRole.ADOPTER else "vets"][index] += 1

    shelter_dates = db.session.scalars(
        db.select(Shelter.created_at).filter(Shelter.created_at >= start)
    ).all()
    for created_at in shelter_dates:
        index = bucket_index(created_at)
        if index is not None:
            series["shelters"][index] += 1

    applications = db.session.execute(
        db.select(Application.stage, Application.adopted_at, Application.updated_at)
        .filter(Application.stage != ApplicationStage.DRAFT)
    ).all()
    for stage, adopted_at, updated_at in applications:
        if stage == ApplicationStage.COMPLETE:
            index = bucket_index(adopted_at or updated_at)
            if index is not None:
                series["adoptions"][index] += 1
    adoptions = sum(series["adoptions"])

    vet_bookings = db.session.scalars(
        db.select(Appointment.created_at).filter(
            Appointment.kind == AppointmentKind.VET_VISIT,
            Appointment.created_at >= start,
        )
    ).all()
    for created_at in vet_bookings:
        index = bucket_index(created_at)
        if index is not None:
            series["vet_bookings"][index] += 1

    metric_events = db.session.execute(
        db.select(PlatformMetricEvent.event_type, PlatformMetricEvent.created_at)
        .filter(PlatformMetricEvent.created_at >= start)
    ).all()
    for event_type, created_at in metric_events:
        index = bucket_index(created_at)
        if index is None:
            continue
        if event_type == "ai_match":
            series["ai_matches"][index] += 1

    returned_applications = db.session.execute(
        db.select(Application.returned_at)
        .filter(Application.returned_at.is_not(None), Application.returned_at >= start)
    ).scalars().all()
    for returned_at in returned_applications:
        index = bucket_index(returned_at)
        if index is not None:
            series["pet_returns"][index] += 1

    lost_found_reports = db.session.scalars(
        db.select(LostFoundReport).filter(LostFoundReport.created_at >= start)
    ).all()
    lost_count = sum(
        report.kind == ReportKind.LOST and report.status != ReportStatus.REUNITED
        for report in lost_found_reports
    )
    reunited_count = sum(
        report.kind == ReportKind.FOUND or report.status == ReportStatus.REUNITED
        for report in lost_found_reports
    )
    lost_found_total = lost_count + reunited_count
    lost_found_rates = {
        "lost": round(100 * lost_count / lost_found_total, 1)
        if lost_found_total else 0,
        "reunited": round(100 * reunited_count / lost_found_total, 1)
        if lost_found_total else 0,
        "lost_count": lost_count,
        "reunited_count": reunited_count,
        "total": lost_found_total,
    }
    lost_found_map = [
        {
            "id": report.id,
            "name": report.pet_name or report.species or "Pet",
            "kind": (
                "reunited"
                if report.kind == ReportKind.FOUND or report.status == ReportStatus.REUNITED
                else "lost"
            ),
            "status": report.status.value,
            "location": report.location or "",
            "lat": report.lat,
            "lng": report.lng,
        }
        for report in lost_found_reports
        if report.lat is not None and report.lng is not None
        and -90 <= report.lat <= 90 and -180 <= report.lng <= 180
    ]

    all_applications = db.session.scalars(
        db.select(Application).filter(Application.stage != ApplicationStage.DRAFT)
    ).all()
    completed_applications = [
        application for application in all_applications
        if application.stage == ApplicationStage.COMPLETE
    ]
    adoption_rate = (
        round(100 * len(completed_applications) / len(all_applications), 1)
        if all_applications else 0
    )
    return_rate = (
        round(100 * sum(application.returned_at is not None for application in completed_applications)
              / len(completed_applications), 1)
        if completed_applications else 0
    )
    stats = {
        "adopters": sum(series["adopters"]),
        "shelters": sum(series["shelters"]),
        "vets": sum(series["vets"]),
        "adoptions": adoptions,
        "adoption_rate": adoption_rate,
        "vet_bookings": sum(series["vet_bookings"]),
        "ai_matches": sum(series["ai_matches"]),
        "pet_returns": sum(series["pet_returns"]),
        "pet_return_rate": return_rate,
    }
    species_counts = {species.label: 0 for species in Species}
    for application in completed_applications:
        if application.pet:
            label = application.pet.species.label
            species_counts[label] = species_counts.get(label, 0) + 1
    funnel = {
        "Applied": len(all_applications),
        "In review": sum(
            application.stage == ApplicationStage.REVIEW
            for application in all_applications
        ),
        "Home visit": sum(
            application.stage == ApplicationStage.HOME_VISIT
            for application in all_applications
        ),
        "Adopted": len(completed_applications),
    }
    chart_series = [
        {"label": "Adopter registrations", "data": series["adopters"], "color": "#a85d43"},
        {"label": "Shelter registrations", "data": series["shelters"], "color": "#e6a23c"},
        {"label": "Vet registrations", "data": series["vets"], "color": "#4b8f8c"},
        {"label": "Completed adoptions", "data": series["adoptions"], "color": "#6a7fc1"},
        {"label": "Vet bookings", "data": series["vet_bookings"], "color": "#3b82a0"},
        {"label": "AI match usage", "data": series["ai_matches"], "color": "#8b6bb5"},
        {"label": "Returned pets", "data": series["pet_returns"], "color": "#c75d5d"},
    ]
    return render_template(
        "admin/analytics.html",
        period=period,
        stats=stats,
        labels=labels,
        chart_series=chart_series,
        species_counts=species_counts,
        funnel=funnel,
        lost_found_rates=lost_found_rates,
        lost_found_map=lost_found_map,
        active_nav="analytics",
    )
