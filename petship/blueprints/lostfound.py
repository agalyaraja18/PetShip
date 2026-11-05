"""Lost & Found pets (Task 33). Integrates the Task 29 photo matcher."""
from __future__ import annotations

from flask import (
    Blueprint,
    abort,
    flash,
    jsonify,
    redirect,
    render_template,
    request,
    url_for,
)
from flask_login import current_user, login_required

from ..extensions import db
from ..models.lostfound import LostFoundReport, ReportKind, ReportStatus
from ..models.lostfound import FoundPetTip
from ..models.user import UserRole
from ..services.photo_match import find_report_matches, hash_image
from ..services.storage import save_image

lostfound_bp = Blueprint("lostfound", __name__, url_prefix="/lost-found")


@lostfound_bp.route("/")
def index():
    status_filter = request.args.get("filter", "all")
    query = db.select(LostFoundReport)
    if status_filter == "lost":
        query = query.filter_by(kind=ReportKind.LOST, status=ReportStatus.ACTIVE)
    elif status_filter == "found":
        query = query.filter_by(kind=ReportKind.FOUND, status=ReportStatus.ACTIVE)
    elif status_filter == "reunited":
        query = query.filter_by(status=ReportStatus.REUNITED)
    reports = db.session.scalars(query.order_by(LostFoundReport.created_at.desc())).all()
    return render_template(
        "community/lostfound.html",
        reports=reports,
        status_filter=status_filter,
        ReportKind=ReportKind,
        active_nav="lostfound",
    )


@lostfound_bp.route("/reports.json")
def reports_json():
    reports = db.session.scalars(
        db.select(LostFoundReport).filter(
            LostFoundReport.status == ReportStatus.ACTIVE,
            LostFoundReport.lat.isnot(None),
        )
    ).all()
    return jsonify([
        {"id": r.id, "name": r.pet_name or "Pet", "kind": r.kind.value,
         "lat": r.lat, "lng": r.lng, "location": r.location}
        for r in reports
    ])


@lostfound_bp.route("/report", methods=["GET", "POST"])
@login_required
def new_report():
    if current_user.role != UserRole.ADOPTER:
        abort(403)
    if request.method == "POST":
        kind = request.form.get("kind", "lost")
        if kind not in {member.value for member in ReportKind}:
            flash("Choose whether the pet is lost or found.", "warning")
            return redirect(url_for("lostfound.new_report"))
        pet_name = (request.form.get("pet_name") or "").strip()
        species = (request.form.get("species") or "").strip()
        location = (request.form.get("location") or "").strip()
        description = (request.form.get("description") or "").strip()
        photo = request.files.get("photo")
        if (
            not species
            or len(species) > 40
            or not location
            or len(location) > 200
            or len(pet_name) > 120
            or len(description) > 5000
        ):
            flash(
                "Enter a valid pet species, location, name, and description within the field limits.",
                "warning",
            )
            return redirect(url_for("lostfound.new_report"))
        if kind == ReportKind.LOST.value and (not photo or not photo.filename):
            flash("Add a photo of the lost pet so others can identify them.", "warning")
            return redirect(url_for("lostfound.new_report"))

        photo_hash = None
        photo_url = None
        if photo and photo.filename:
            photo_hash = hash_image(photo.stream)
            if photo_hash is None:
                flash("Upload a valid pet photo in PNG, JPG, GIF, or WebP format.", "warning")
                return redirect(url_for("lostfound.new_report"))
            photo_url = save_image(photo, folder="lostfound")
            if photo_url is None:
                flash("The pet photo could not be saved. Please try another image.", "warning")
                return redirect(url_for("lostfound.new_report"))

        report = LostFoundReport(
            reporter_id=current_user.id,
            kind=ReportKind(kind),
            pet_name=pet_name or None,
            species=species,
            description=description or None,
            location=location,
            lat=request.form.get("lat", type=float),
            lng=request.form.get("lng", type=float),
            photo_hash=photo_hash,
            photo_url=photo_url,
        )
        db.session.add(report)
        db.session.commit()
        flash("Your alert is live. We'll suggest possible matches.", "success")
        return redirect(url_for("lostfound.detail", report_id=report.id))
    return render_template("community/lostfound_form.html", ReportKind=ReportKind,
                           active_nav="lostfound")


@lostfound_bp.route("/<int:report_id>")
def detail(report_id: int):
    report = db.session.get(LostFoundReport, report_id)
    if report is None:
        abort(404)
    matches = find_report_matches(report, threshold=45, limit=5)
    owner_tips = (
        db.session.scalars(
            db.select(FoundPetTip)
            .filter_by(report_id=report.id)
            .order_by(FoundPetTip.created_at.desc())
        ).all()
        if current_user.is_authenticated and current_user.id == report.reporter_id
        else []
    )
    return render_template(
        "community/lostfound_detail.html",
        report=report,
        matches=matches,
        owner_tips=owner_tips,
        active_nav="lostfound",
    )


@lostfound_bp.route("/<int:report_id>/found-tip", methods=["POST"])
@login_required
def found_tip(report_id: int):
    report = db.session.get(LostFoundReport, report_id)
    if report is None or report.kind != ReportKind.LOST or report.status != ReportStatus.ACTIVE:
        abort(404)
    if report.reporter_id == current_user.id:
        flash("You cannot send a found-pet tip to your own post.", "warning")
        return redirect(url_for("lostfound.detail", report_id=report.id))

    contact = (request.form.get("contact") or "").strip()
    message = (request.form.get("message") or "").strip()
    if not contact or not message:
        flash("Add a way for the pet owner to contact you and describe what you found.", "warning")
        return redirect(url_for("lostfound.detail", report_id=report.id))
    if len(contact) > 200 or len(message) > 2000:
        flash("Contact details or message are too long.", "warning")
        return redirect(url_for("lostfound.detail", report_id=report.id))

    tip = FoundPetTip(
        report_id=report.id,
        reporter_id=current_user.id,
        name=current_user.full_name,
        contact=contact,
        message=message,
    )
    db.session.add(tip)
    db.session.commit()
    if report.reporter:
        from ..services.notify import notify

        notify(
            report.reporter,
            title=f"Someone may have found {report.pet_name or 'your pet'}",
            body=f"{current_user.full_name} sent you a tip on your lost-pet post.",
            category="general",
            link=url_for("lostfound.detail", report_id=report.id),
        )
        db.session.commit()
    flash("Your tip has been sent privately to the pet's owner.", "success")
    return redirect(url_for("lostfound.detail", report_id=report.id))


@lostfound_bp.route("/<int:report_id>/reunite", methods=["POST"])
@login_required
def reunite(report_id: int):
    report = db.session.get(LostFoundReport, report_id)
    if report is None or report.reporter_id != current_user.id:
        abort(404)
    report.status = ReportStatus.REUNITED
    db.session.commit()
    flash("Marked as reunited. We're so happy! 🐾", "success")
    return redirect(url_for("lostfound.detail", report_id=report_id))
