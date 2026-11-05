"""Media storage wrapper (fallback-first).

Uploads go to Firebase Cloud Storage when Firebase is configured; otherwise
they are saved to the local ``static/uploads`` folder so the app works with no
external account in development. Both paths return a public URL usable in an
``<img src>``.

Firebase configuration (any of):
* ``FIREBASE_CREDENTIALS_FILE`` - path to a service-account JSON file, or
* ``FIREBASE_CREDENTIALS``      - the service-account JSON as a string.
Plus ``FIREBASE_STORAGE_BUCKET`` - the bucket name (e.g. my-app.appspot.com).
"""
from __future__ import annotations

import json
import os
import secrets
import threading
from pathlib import Path

from flask import current_app, url_for
from werkzeug.datastructures import FileStorage
from werkzeug.utils import secure_filename

ALLOWED_IMAGE_EXTENSIONS = {"png", "jpg", "jpeg", "gif", "webp"}

# Guards one-time Firebase Admin initialization across threads.
_firebase_lock = threading.Lock()
_firebase_app = None


def _ext_ok(filename: str) -> bool:
    return (
        "." in filename
        and filename.rsplit(".", 1)[1].lower() in ALLOWED_IMAGE_EXTENSIONS
    )


def _firebase_configured() -> bool:
    cfg = current_app.config
    has_creds = bool(
        cfg.get("FIREBASE_CREDENTIALS_FILE") or cfg.get("FIREBASE_CREDENTIALS")
    )
    return has_creds and bool(cfg.get("FIREBASE_STORAGE_BUCKET"))


def storage_backend() -> str:
    return "firebase" if _firebase_configured() else "local"


def save_image(file: FileStorage, folder: str = "avatars") -> str | None:
    """Persist an uploaded image and return its public URL, or None if invalid."""
    if file is None or not getattr(file, "filename", ""):
        return None
    if not _ext_ok(file.filename):
        return None

    if _firebase_configured():
        try:
            return _save_firebase(file, folder)
        except Exception:  # pragma: no cover - fall back on any provider error
            current_app.logger.exception(
                "Firebase upload failed; falling back to local storage."
            )

    return _save_local(file, folder)


def _get_firebase_bucket():
    """Return the configured Firebase Storage bucket, initializing the Admin
    SDK once per process (thread-safe, idempotent)."""
    global _firebase_app

    import firebase_admin
    from firebase_admin import credentials, storage

    cfg = current_app.config
    bucket_name = cfg["FIREBASE_STORAGE_BUCKET"]

    if _firebase_app is None:
        with _firebase_lock:
            if _firebase_app is None:
                cred = _build_credentials(cfg)
                # Reuse an existing default app if one was already created.
                try:
                    _firebase_app = firebase_admin.get_app()
                except ValueError:
                    _firebase_app = firebase_admin.initialize_app(
                        cred, {"storageBucket": bucket_name}
                    )

    return storage.bucket(bucket_name, app=_firebase_app)


def _build_credentials(cfg):
    from firebase_admin import credentials

    cred_file = cfg.get("FIREBASE_CREDENTIALS_FILE")
    if cred_file:
        return credentials.Certificate(cred_file)
    # Inline JSON string.
    data = json.loads(cfg["FIREBASE_CREDENTIALS"])
    return credentials.Certificate(data)


def _save_firebase(file: FileStorage, folder: str) -> str:
    bucket = _get_firebase_bucket()

    original = secure_filename(file.filename) or "upload.png"
    ext = original.rsplit(".", 1)[1].lower()
    blob_path = f"petship/{folder}/{secrets.token_hex(8)}.{ext}"

    blob = bucket.blob(blob_path)
    file.stream.seek(0)
    blob.upload_from_file(file.stream, content_type=file.mimetype)
    # Make the object publicly readable and return its stable public URL.
    blob.make_public()
    return blob.public_url


def _save_local(file: FileStorage, folder: str) -> str:
    base = Path(current_app.config["UPLOAD_FOLDER"]) / folder
    base.mkdir(parents=True, exist_ok=True)

    original = secure_filename(file.filename) or "upload.png"
    ext = original.rsplit(".", 1)[1].lower()
    name = f"{secrets.token_hex(8)}.{ext}"
    path = base / name
    file.stream.seek(0)
    file.save(os.fspath(path))

    # Served from the static folder: static/uploads/<folder>/<name>
    return url_for("static", filename=f"uploads/{folder}/{name}")
