"""Task 4 tests: branded error pages and legal pages (+ Terms PDF)."""
from __future__ import annotations

from petship import create_app


def test_404_is_branded(client):
    resp = client.get("/no-such-page")
    assert resp.status_code == 404
    assert b"404" in resp.data
    assert b"This page wandered off" in resp.data


def test_403_is_branded(client):
    # `/_forbidden` is registered by the factory under the testing config.
    resp = client.get("/_forbidden")
    assert resp.status_code == 403
    assert b"403" in resp.data
    assert b"Members only" in resp.data


def test_500_is_branded():
    # Build a fresh testing app with exception propagation off so the custom
    # 500 handler runs instead of re-raising.
    app = create_app("testing")
    app.config["PROPAGATE_EXCEPTIONS"] = False
    client = app.test_client()
    resp = client.get("/_boom")
    assert resp.status_code == 500
    assert b"500" in resp.data
    assert b"chewed the cables" in resp.data
    assert b"PS-500-" in resp.data


def test_privacy_page_renders(client):
    resp = client.get("/privacy")
    assert resp.status_code == 200
    assert b"Privacy Policy" in resp.data
    assert b"Data we collect" in resp.data


def test_terms_page_renders(client):
    resp = client.get("/terms")
    assert resp.status_code == 200
    assert b"Terms &amp; Conditions" in resp.data or b"Terms & Conditions" in resp.data
    assert b"Using Petship" in resp.data


def test_terms_pdf_downloads(client):
    resp = client.get("/terms.pdf")
    assert resp.status_code == 200
    assert resp.mimetype == "application/pdf"
    assert resp.data[:4] == b"%PDF"
    assert "attachment" in resp.headers.get("Content-Disposition", "")
