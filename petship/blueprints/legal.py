"""Legal pages: Privacy Policy and Terms & Conditions (Task 4).

Content is defined once and shared between the HTML section-nav pages and the
ReportLab PDF export for the Terms.
"""
from __future__ import annotations

from flask import Blueprint, Response, render_template

from ..services.pdf import render_document

legal_bp = Blueprint("legal", __name__)

TERMS_EFFECTIVE = "Effective 1 October 2026"
PRIVACY_UPDATED = "Last updated 1 October 2026"

# (anchor, heading, body) for each section.
TERMS_SECTIONS = [
    (
        "using-petship",
        "1. Using Petship",
        "By creating an account, you agree to use PetShip to support responsible "
        "adoption and pet care. Shelters and veterinarians must complete "
        "verification before offering services.",
    ),
    (
        "accounts-roles",
        "2. Accounts & roles",
        "Each account holds one role: adopter, shelter, or veterinarian. You're "
        "responsible for keeping your login details secure.",
    ),
    (
        "adoption-rules",
        "3. Adoption rules",
        "PetShip is for adoption only. Commercial selling of animals is "
        "prohibited. Applications and listings must be accurate and truthful.",
    ),
    (
        "vet-services",
        "4. Vet services",
        "Veterinary information on PetShip supports but does not replace in-person "
        "professional care. Always consult a licensed vet for medical decisions.",
    ),
    (
        "community-conduct",
        "5. Community conduct",
        "Respect people and animals in every interaction. Harassment, fraud, and "
        "abusive content are not tolerated and may lead to account removal.",
    ),
    (
        "liability",
        "6. Liability",
        "PetShip connects adopters, shelters, and vets but is not party to the "
        "adoption agreement itself. Use the platform responsibly.",
    ),
    (
        "changes",
        "7. Changes",
        "We may update these terms. Material changes will be communicated, and "
        "continued use constitutes acceptance of the updated terms.",
    ),
]

PRIVACY_SECTIONS = [
    (
        "summary",
        "1. Summary",
        "PetShip respects your privacy and the welfare of every animal on our "
        "platform. This policy explains what information we collect, why, and how "
        "you stay in control. In short: we collect only what we need to match pets "
        "with families and support their care. We never sell your data.",
    ),
    (
        "data-we-collect",
        "2. Data we collect",
        "Account details such as name, email, and city; adoption applications and "
        "household information; pet profiles, medical records, and reminders; and "
        "messages with shelters and vets.",
    ),
    (
        "how-we-use-it",
        "3. How we use it",
        "To run adoption workflows, power AI matching, schedule care reminders, and "
        "keep you informed about your applications, pets, and appointments.",
    ),
    (
        "pet-health-data",
        "4. Pet health data",
        "Medical records and vaccination history are shared only with you and the "
        "veterinarians you choose. You control who can view your pet's records.",
    ),
    (
        "sharing",
        "5. Sharing",
        "We share information only as needed to complete adoptions and appointments "
        "(for example, with a shelter you apply to). We never sell personal data.",
    ),
    (
        "your-rights",
        "6. Your rights",
        "You can view, edit, export, or delete your data from account settings at "
        "any time.",
    ),
    (
        "contact",
        "7. Contact",
        "Questions about privacy? Reach us at hello@petship.com.",
    ),
]


@legal_bp.route("/privacy")
def privacy():
    return render_template(
        "legal/privacy.html",
        sections=PRIVACY_SECTIONS,
        updated=PRIVACY_UPDATED,
        active_nav="",
    )


@legal_bp.route("/terms")
def terms():
    return render_template(
        "legal/terms.html",
        sections=TERMS_SECTIONS,
        effective=TERMS_EFFECTIVE,
        active_nav="",
    )


@legal_bp.route("/terms.pdf")
def terms_pdf():
    pdf_bytes = render_document(
        "Terms & Conditions",
        TERMS_EFFECTIVE,
        [(heading, body) for _, heading, body in TERMS_SECTIONS],
    )
    return Response(
        pdf_bytes,
        mimetype="application/pdf",
        headers={
            "Content-Disposition": "attachment; filename=petship-terms.pdf"
        },
    )
