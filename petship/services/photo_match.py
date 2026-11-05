"""Perceptual-hash photo similarity for lost & found (Task 29).

Uses ImageHash (pHash) over Pillow images. This suggests *possible* matches
between lost and found reports based on visual similarity — it is a ranking
aid, not reliable pet identification. OpenAI/Gemini is not required.

Design notes:
* ``hash_image`` returns a stable hex pHash string for an image file/bytes.
* ``similarity`` converts Hamming distance into a 0-100 score.
* ``rank_matches`` scores a target hash against candidate (id, hash) pairs and
  returns the most similar above a threshold.
"""
from __future__ import annotations

import io

# pHash is 64 bits, so the maximum Hamming distance is 64.
_HASH_BITS = 64
# Candidates below this score are unlikely to be the same photo/pet.
DEFAULT_THRESHOLD = 55


def hash_image(source) -> str | None:
    """Return a hex perceptual hash for an image.

    ``source`` may be a file path, a bytes object, or a file-like object
    (e.g. a Werkzeug FileStorage ``.stream``). Returns None if the image can't
    be read.
    """
    try:
        import imagehash
        from PIL import Image

        if isinstance(source, (bytes, bytearray)):
            img = Image.open(io.BytesIO(source))
        elif hasattr(source, "read"):
            # Rewind file-like objects so re-reads work.
            try:
                source.seek(0)
            except Exception:
                pass
            img = Image.open(source)
        else:
            img = Image.open(source)
        return str(imagehash.phash(img))
    except Exception:
        return None


def _hamming(a: str, b: str) -> int:
    """Hamming distance between two hex pHash strings."""
    ia = int(a, 16)
    ib = int(b, 16)
    return bin(ia ^ ib).count("1")


def similarity(hash_a: str | None, hash_b: str | None) -> int:
    """0-100 similarity score (100 = identical hash)."""
    if not hash_a or not hash_b:
        return 0
    try:
        distance = _hamming(hash_a, hash_b)
    except ValueError:
        return 0
    return round(100 * (1 - distance / _HASH_BITS))


def rank_matches(target_hash, candidates, threshold: int = DEFAULT_THRESHOLD,
                 limit: int = 5):
    """Rank candidate (object, hash) pairs by similarity to ``target_hash``.

    ``candidates`` is an iterable of ``(obj, hash_str)`` tuples. Returns a list
    of ``(obj, score)`` sorted by score desc, keeping only those at/above the
    threshold.
    """
    if not target_hash:
        return []
    scored = []
    for obj, h in candidates:
        score = similarity(target_hash, h)
        if score >= threshold:
            scored.append((obj, score))
    scored.sort(key=lambda t: t[1], reverse=True)
    return scored[:limit]


def find_report_matches(report, threshold: int = DEFAULT_THRESHOLD, limit: int = 5):
    """Suggest possible matches for a lost/found report.

    Compares the report's photo hash against active reports of the opposite
    kind (lost<->found) and returns ``(report, score)`` pairs, best first.
    """
    from ..extensions import db
    from ..models.lostfound import LostFoundReport, ReportStatus

    if not report.photo_hash:
        return []

    candidates_q = db.session.scalars(
        db.select(LostFoundReport).filter(
            LostFoundReport.kind == report.opposite_kind,
            LostFoundReport.status == ReportStatus.ACTIVE,
            LostFoundReport.id != report.id,
            LostFoundReport.photo_hash.isnot(None),
        )
    ).all()
    pairs = [(r, r.photo_hash) for r in candidates_q]
    return rank_matches(report.photo_hash, pairs, threshold=threshold, limit=limit)
