"""Adoption agreement sharing, signatures, and secured downloads."""
from __future__ import annotations

from io import BytesIO

from pypdf import PdfReader, PdfWriter

from petship.extensions import db
from petship.models.application import AdoptionAgreement, Application, ApplicationStage
from petship.models.health import OwnedPet
from petship.models.pet import Pet
from petship.models.user import User
from petship.seed import seed_data


def _blank_pdf() -> bytes:
    writer = PdfWriter()
    writer.add_blank_page(width=612, height=792)
    result = BytesIO()
    writer.write(result)
    return result.getvalue()


def _application(client):
    seed_data()
    adopter = db.session.scalar(
        db.select(User).filter_by(email="agalya@demo.petship")
    )
    pet = db.session.scalar(db.select(Pet).filter_by(name="Bruno"))
    application = Application(
        reference="PS-93421",
        applicant_id=adopter.id,
        pet_id=pet.id,
        stage=ApplicationStage.AGREEMENT,
        answers={},
    )
    db.session.add(application)
    db.session.commit()
    return application, adopter


def test_shelter_shares_and_adopter_signs_downloadable_agreement(
    client, app, monkeypatch, tmp_path
):
    application, adopter = _application(client)
    monkeypatch.setattr(app, "instance_path", str(tmp_path))

    client.post(
        "/auth/login",
        data={"role": "shelter", "email": "kavya@demo.petship", "password": "password123"},
    )
    response = client.post(
        f"/shelter/requests/{application.id}/agreement",
        data={
            "signature": "Kavya S",
            "agreement": (BytesIO(_blank_pdf()), "Petship Adoption.pdf"),
        },
        content_type="multipart/form-data",
    )
    assert response.status_code == 302
    db.session.refresh(application)
    agreement = application.agreement
    assert agreement is not None
    assert agreement.original_filename == "Petship_Adoption.pdf"
    assert agreement.shelter_signature == "Kavya S"
    assert application.stage is ApplicationStage.AGREEMENT

    client.get("/auth/logout")
    client.post(
        "/auth/login",
        data={"role": "adopter", "email": "agalya@demo.petship", "password": "password123"},
    )
    unsigned = client.get(
        f"/adopt/application/{application.id}/agreement/download"
    )
    assert unsigned.status_code == 200
    assert unsigned.mimetype == "application/pdf"
    assert len(PdfReader(BytesIO(unsigned.data)).pages) == 1
    preview = client.get(
        f"/adopt/application/{application.id}/agreement/download?view=1"
    )
    assert preview.status_code == 200
    assert preview.headers["Content-Disposition"].startswith("inline")

    signed = client.post(
        f"/adopt/application/{application.id}/agreement/sign",
        data={"signature": adopter.full_name},
    )
    assert signed.status_code == 302
    db.session.refresh(agreement)
    assert agreement.adopter_signature == adopter.full_name

    downloaded = client.get(
        f"/adopt/application/{application.id}/agreement/download"
    )
    assert downloaded.status_code == 200
    pages = PdfReader(BytesIO(downloaded.data)).pages
    assert len(pages) == 2
    assert b"PetShip" in pages[1].extract_text().encode()

    owned_pet = OwnedPet(
        owner_id=adopter.id,
        application_id=application.id,
        name=application.pet.name,
    )
    db.session.add(owned_pet)
    db.session.commit()
    documents = client.get(f"/me/pets/{owned_pet.id}?tab=documents")
    assert documents.status_code == 302
    assert documents.headers["Location"].endswith(f"/me/pets/{owned_pet.id}")
    tracking = client.get(f"/adopt/application/{application.id}")
    assert b"View agreement" in tracking.data
    assert b"Download agreement" in tracking.data


def test_shelter_rejects_non_pdf_agreement(client, app):
    application, _ = _application(client)
    client.post(
        "/auth/login",
        data={"role": "shelter", "email": "kavya@demo.petship", "password": "password123"},
    )
    response = client.post(
        f"/shelter/requests/{application.id}/agreement",
        data={
            "signature": "Kavya S",
            "agreement": (BytesIO(b"not a pdf"), "agreement.pdf"),
        },
        content_type="multipart/form-data",
    )
    assert response.status_code == 302
    assert db.session.scalar(db.select(AdoptionAgreement)) is None


def test_other_users_cannot_download_agreement(client, app, monkeypatch, tmp_path):
    application, adopter = _application(client)
    monkeypatch.setattr(app, "instance_path", str(tmp_path))
    agreement_dir = tmp_path / "agreements"
    agreement_dir.mkdir()
    (agreement_dir / "private.pdf").write_bytes(_blank_pdf())
    db.session.add(AdoptionAgreement(
        application_id=application.id,
        file_name="private.pdf",
        original_filename="agreement.pdf",
        shelter_signature="Kavya S",
    ))
    db.session.commit()
    other = User(email="other@example.com", first_name="Other")
    other.set_password("password123")
    other.is_active = True
    db.session.add(other)
    db.session.commit()
    client.post(
        "/auth/login",
        data={"role": "adopter", "email": "other@example.com", "password": "password123"},
    )
    assert client.get(
        f"/adopt/application/{application.id}/agreement/download"
    ).status_code == 404
