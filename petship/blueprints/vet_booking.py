"""Vet appointment booking wizard + confirmation (Task 19).

A single-page booking form (pet, service, date, time) with a live price
summary driven by Alpine, submitting to create an Appointment. Slot
availability prevents double-booking the same vet at the same time.
"""
from __future__ import annotations

import secrets
from datetime import date, datetime, time, timedelta, timezone

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

from ..extensions import db
from ..models.appointment import Appointment, AppointmentKind, AppointmentStatus
from ..models.reminder import Notification
from ..models.vet import VetProfile

vet_booking_bp = Blueprint("vet_booking", __name__, url_prefix="/book")

# Services and their base prices (₹). "video" uses the vet's video fee.
SERVICES = [
    ("general", "General check-up"),
    ("vaccination", "Vaccination"),
    ("dental", "Dental"),
    ("grooming", "Grooming"),
    ("video", "Video consult"),
]
TIME_SLOTS = ["09:30", "10:30", "11:00", "14:00", "16:30"]


def _service_price(vet: VetProfile, service: str) -> float:
    base = float(vet.consult_fee or 500)
    if service == "video":
        return float(vet.video_fee or base)
    if service == "vaccination":
        return base + 750
    if service == "dental":
        return base + 1500
    if service == "grooming":
        return base + 400
    return base


@vet_booking_bp.route("/<slug>", methods=["GET", "POST"])
@login_required
def book(slug: str):
    vet = db.session.scalar(db.select(VetProfile).filter_by(slug=slug))
    if vet is None:
        abort(404)

    # Date options: next 7 days.
    today = date.today()
    date_options = [today + timedelta(days=i) for i in range(7)]
    prices = {key: _service_price(vet, key) for key, _ in SERVICES}

    if request.method == "POST":
        service = request.form.get("service", "general")
        date_str = request.form.get("date")
        slot = request.form.get("slot")
        pet_name = (request.form.get("pet_name") or "").strip() or "My pet"

        if not date_str or not slot:
            flash("Please choose a date and time.", "warning")
            return render_template(
                "vet/booking.html", vet=vet, services=SERVICES, slots=TIME_SLOTS,
                date_options=date_options, prices=prices,
                selected={
                    "service": service,
                    "date": date_str or "",
                    "pet_name": pet_name,
                },
                active_nav="vets",
            )

        try:
            appt_dt = datetime.combine(
                date.fromisoformat(date_str),
                time.fromisoformat(slot if len(slot) > 5 else slot + ":00"),
                tzinfo=timezone.utc,
            )
        except ValueError:
            abort(400)

        # Slot availability: reject if this vet already has an appointment then.
        clash = db.session.scalar(
            db.select(Appointment).filter(
                Appointment.vet_id == vet.user_id,
                Appointment.scheduled_for == appt_dt,
                Appointment.status != AppointmentStatus.CANCELLED,
            )
        )
        if clash:
            flash("That slot was just taken. Please pick another time.", "warning")
            return render_template(
                "vet/booking.html", vet=vet, services=SERVICES, slots=TIME_SLOTS,
                date_options=date_options, prices=prices,
                selected={
                    "service": service,
                    "date": date_str,
                    "pet_name": pet_name,
                },
                active_nav="vets",
            )

        price = _service_price(vet, service)
        appt = Appointment(
            kind=AppointmentKind.VET_VISIT,
            status=AppointmentStatus.CONFIRMED,
            scheduled_for=appt_dt,
            vet_id=vet.user_id,
            user_id=current_user.id,
            service=dict(SERVICES).get(service, service),
            location=vet.clinic_name,
            note=pet_name,
            price=price,
            reference="VB-" + str(secrets.randbelow(90000) + 10000),
        )
        db.session.add(appt)
        if vet.user.prefs.get("vet_appointments", True):
            Notification.push(
                vet.user_id,
                "New vet appointment booked",
                f"{current_user.full_name} booked {appt.service} for {pet_name} on "
                f"{appt_dt.strftime('%d %b %Y at %I:%M %p UTC')}.",
                category="appointments",
                link=url_for("vet_workspace.appointments"),
            )
        db.session.commit()
        return redirect(url_for("vet_booking.confirmation", appt_id=appt.id))

    return render_template(
        "vet/booking.html",
        vet=vet,
        services=SERVICES,
        slots=TIME_SLOTS,
        date_options=date_options,
        prices=prices,
        selected={
            "service": request.args.get("service", "general"),
            "date": request.args.get("date", ""),
            "pet_name": request.args.get("pet_name", ""),
        },
        active_nav="vets",
    )


@vet_booking_bp.route("/confirmation/<int:appt_id>")
@login_required
def confirmation(appt_id: int):
    appt = db.session.get(Appointment, appt_id)
    if appt is None or appt.user_id != current_user.id:
        abort(404)
    return render_template("vet/booking_confirm.html", appt=appt, active_nav="vets")
