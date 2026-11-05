"""Tests for the media storage wrapper (Firebase + local fallback)."""
from __future__ import annotations

import io

from werkzeug.datastructures import FileStorage

from petship.services import storage


def _png_file(name="photo.png"):
    # Minimal 1x1 PNG bytes.
    data = (
        b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
        b"\x08\x06\x00\x00\x00\x1f\x15\xc4\x89\x00\x00\x00\nIDATx\x9cc\x00"
        b"\x01\x00\x00\x05\x00\x01\r\n-\xb4\x00\x00\x00\x00IEND\xaeB`\x82"
    )
    return FileStorage(stream=io.BytesIO(data), filename=name, content_type="image/png")


def test_backend_is_local_without_firebase(app):
    with app.app_context():
        assert storage.storage_backend() == "local"


def test_backend_is_firebase_when_configured(app):
    with app.app_context():
        app.config["FIREBASE_CREDENTIALS_FILE"] = "/fake/path.json"
        app.config["FIREBASE_STORAGE_BUCKET"] = "demo.appspot.com"
        assert storage.storage_backend() == "firebase"


def test_save_image_local_returns_static_url(app):
    with app.test_request_context():
        url = storage.save_image(_png_file(), folder="avatars")
    assert url is not None
    assert "/static/uploads/avatars/" in url
    assert url.endswith(".png")


def test_rejects_disallowed_extension(app):
    with app.test_request_context():
        bad = FileStorage(stream=io.BytesIO(b"nope"), filename="malware.exe")
        assert storage.save_image(bad) is None


def test_rejects_empty_file(app):
    with app.test_request_context():
        empty = FileStorage(stream=io.BytesIO(b""), filename="")
        assert storage.save_image(empty) is None


def test_firebase_failure_falls_back_to_local(app, monkeypatch):
    with app.test_request_context():
        app.config["FIREBASE_CREDENTIALS_FILE"] = "/fake/path.json"
        app.config["FIREBASE_STORAGE_BUCKET"] = "demo.appspot.com"

        def boom(*args, **kwargs):
            raise RuntimeError("firebase down")

        monkeypatch.setattr(storage, "_save_firebase", boom)
        url = storage.save_image(_png_file(), folder="avatars")
    # Despite Firebase being "configured", the upload degrades to local.
    assert url is not None
    assert "/static/uploads/avatars/" in url
