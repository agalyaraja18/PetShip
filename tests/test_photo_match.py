"""Task 29 tests: perceptual-hash photo matching for lost & found."""
from __future__ import annotations

import io

from petship.extensions import db
from petship.models.lostfound import (
    LostFoundReport,
    ReportKind,
    ReportStatus,
)
from petship.models.user import User, UserRole
from petship.services import photo_match


def _image_bytes(kind: str) -> bytes:
    """Generate a deterministic test image. `kind` controls the content so we
    can make visually-similar vs. clearly-different images."""
    from PIL import Image, ImageDraw

    img = Image.new("RGB", (128, 128), "white")
    draw = ImageDraw.Draw(img)
    if kind == "circles":
        for r in range(10, 60, 10):
            draw.ellipse([64 - r, 64 - r, 64 + r, 64 + r], outline="black", width=3)
    elif kind == "circles2":
        # Same pattern, tiny perturbation -> should hash very similarly.
        for r in range(10, 60, 10):
            draw.ellipse([65 - r, 64 - r, 65 + r, 64 + r], outline="black", width=3)
    else:  # "stripes" -> clearly different structure
        for x in range(0, 128, 12):
            draw.line([(x, 0), (x, 128)], fill="black", width=4)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


# ---- Hashing ----
def test_hash_is_stable():
    data = _image_bytes("circles")
    h1 = photo_match.hash_image(data)
    h2 = photo_match.hash_image(data)
    assert h1 is not None
    assert h1 == h2  # deterministic


def test_hash_invalid_returns_none():
    assert photo_match.hash_image(b"not an image") is None


def test_hash_accepts_file_like():
    data = _image_bytes("circles")
    assert photo_match.hash_image(io.BytesIO(data)) is not None


# ---- Similarity ----
def test_similar_images_score_high():
    a = photo_match.hash_image(_image_bytes("circles"))
    b = photo_match.hash_image(_image_bytes("circles2"))
    # A 1px perturbation of the same pattern stays clearly similar.
    assert photo_match.similarity(a, b) >= 70


def test_different_images_score_lower():
    a = photo_match.hash_image(_image_bytes("circles"))
    c = photo_match.hash_image(_image_bytes("stripes"))
    similar = photo_match.similarity(
        a, photo_match.hash_image(_image_bytes("circles2"))
    )
    different = photo_match.similarity(a, c)
    assert different < similar


def test_similarity_handles_missing():
    assert photo_match.similarity(None, "abc") == 0
    assert photo_match.similarity("abc", None) == 0


# ---- Ranking ----
def test_rank_matches_orders_by_score():
    target = photo_match.hash_image(_image_bytes("circles"))
    near = photo_match.hash_image(_image_bytes("circles2"))
    far = photo_match.hash_image(_image_bytes("stripes"))
    candidates = [("far", far), ("near", near)]
    ranked = photo_match.rank_matches(target, candidates, threshold=0)
    assert ranked[0][0] == "near"  # most similar first


def test_rank_matches_threshold_filters():
    target = photo_match.hash_image(_image_bytes("circles"))
    far = photo_match.hash_image(_image_bytes("stripes"))
    ranked = photo_match.rank_matches(target, [("far", far)], threshold=95)
    assert ranked == []


# ---- DB-backed report matching ----
def _report(app, kind, img_kind, status=ReportStatus.ACTIVE):
    user = db.session.scalar(db.select(User))
    if user is None:
        user = User(email="r@example.com", first_name="R", role=UserRole.ADOPTER)
        user.set_password("x")
        user.is_active = True
        db.session.add(user)
        db.session.commit()
    r = LostFoundReport(
        reporter_id=user.id, kind=kind, status=status,
        photo_hash=photo_match.hash_image(_image_bytes(img_kind)),
    )
    db.session.add(r)
    db.session.commit()
    return r


def test_find_report_matches_suggests_opposite_kind(app):
    lost = _report(app, ReportKind.LOST, "circles")
    found_similar = _report(app, ReportKind.FOUND, "circles2")
    found_different = _report(app, ReportKind.FOUND, "stripes")

    matches = photo_match.find_report_matches(lost, threshold=0)
    ids = [r.id for r, _ in matches]
    # The visually-similar found report ranks first.
    assert ids[0] == found_similar.id
    assert found_different.id in ids  # present but lower (threshold=0)


def test_find_report_matches_ignores_same_kind(app):
    lost = _report(app, ReportKind.LOST, "circles")
    _report(app, ReportKind.LOST, "circles2")  # another LOST, should be ignored
    matches = photo_match.find_report_matches(lost, threshold=0)
    assert matches == []  # no FOUND reports to match against


def test_find_report_matches_no_hash(app):
    user = db.session.scalar(db.select(User)) or None
    if user is None:
        user = User(email="r@example.com", first_name="R", role=UserRole.ADOPTER)
        user.set_password("x"); user.is_active = True
        db.session.add(user); db.session.commit()
    r = LostFoundReport(reporter_id=user.id, kind=ReportKind.LOST, photo_hash=None)
    db.session.add(r); db.session.commit()
    assert photo_match.find_report_matches(r) == []
