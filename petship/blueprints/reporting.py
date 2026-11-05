"""Adopter reports about potentially fraudulent shelters and veterinarians."""
from __future__ import annotations

from flask import Blueprint, abort, flash, redirect, request, url_for
from flask_login import current_user, login_required

from ..extensions import db
from ..models.report import AbuseReport, AbuseStatus, ReportTargetType
from ..models.shelter import Shelter
from ..models.user import UserRole
from ..models.vet import VetProfile

reporting_bp = Blueprint("reporting", __name__, url_prefix="/reports")

REPORT_REASONS = (
    "Fake identity or credentials",
    "Fraud or payment scam",
    "Irresponsible or unsafe conduct",
    "Misleading information",
    "Other safety concern",
)


@reporting_bp.route("/provider/<target_type>/<int:target_id>", methods=["POST"])
@login_required
def report_provider(target_type: str, target_id: int):
    if current_user.role != UserRole.ADOPTER:
        abort(403)
    try:
        report_type = ReportTargetType(target_type)
    except ValueError:
        abort(404)
    if report_type not in {ReportTargetType.SHELTER, ReportTargetType.VET}:
        abort(404)

    if report_type == ReportTargetType.SHELTER:
        target = db.session.get(Shelter, target_id)
        target_name = target.name if target else None
    else:
        target = db.session.get(VetProfile, target_id)
        target_name = target.display_name if target else None
    if target is None:
        abort(404)

    reason = (request.form.get("reason") or "").strip()
    details = (request.form.get("details") or "").strip()
    if reason not in REPORT_REASONS:
        flash("Choose a reason for your report.", "warning")
    elif len(details) > 2000:
        flash("Additional details must be 2,000 characters or fewer.", "warning")
    else:
        duplicate = db.session.scalar(
            db.select(AbuseReport).filter_by(
                reporter_id=current_user.id,
                target_type=report_type,
                target_id=target_id,
                status=AbuseStatus.OPEN,
            )
        )
        if duplicate:
            flash("You already have an open report for this provider.", "info")
        else:
            db.session.add(
                AbuseReport(
                    reporter_id=current_user.id,
                    target_type=report_type,
                    target_id=target_id,
                    target_label=target_name,
                    reason=reason,
                    details=details or None,
                    priority="high",
                )
            )
            db.session.commit()
            flash("Your report has been sent to the PetShip admin team for review.", "success")
    if report_type == ReportTargetType.SHELTER:
        return redirect(url_for("shelter.public", slug=target.slug))
    return redirect(url_for("vet.detail", slug=target.slug))
