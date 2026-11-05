"""Task 3 tests: design system styleguide and all four role shells render."""
from __future__ import annotations

import pytest


def test_styleguide_renders(client):
    resp = client.get("/styleguide")
    assert resp.status_code == 200
    body = resp.data
    # Core design-system markers are present.
    assert b"PetShip Styleguide" in body
    assert b"Colour palette" in body
    assert b"base.css" in body
    assert b"components.css" in body
    assert b"shells.css" in body
    # Vendored libs are wired.
    assert b"htmx.min.js" in body
    assert b"alpine.min.js" in body
    # CSRF token meta is injected for htmx.
    assert b'name="csrf-token"' in body


@pytest.mark.parametrize(
    "shell,marker",
    [
        ("public", b"PetShip Styleguide"),
        ("adopter", b"Good morning, Agalya"),
        ("vet", b"Today's schedule"),
        ("shelter", b"Shelter overview"),
        ("admin", b"Platform overview"),
    ],
)
def test_shell_previews_render(client, shell, marker):
    resp = client.get(f"/styleguide/shell/{shell}")
    assert resp.status_code == 200
    assert marker in resp.data


def test_dark_shells_use_dark_class(client):
    for shell in ("shelter", "admin"):
        resp = client.get(f"/styleguide/shell/{shell}")
        assert b"shell-dark" in resp.data
    for shell in ("adopter", "vet"):
        resp = client.get(f"/styleguide/shell/{shell}")
        assert b"shell-light" in resp.data


def test_unknown_shell_404(client):
    resp = client.get("/styleguide/shell/nope")
    assert resp.status_code == 404
