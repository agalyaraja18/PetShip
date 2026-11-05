"""Token/code generation helpers for verification and password reset."""
from __future__ import annotations

import secrets


def generate_code(digits: int = 6) -> str:
    """A zero-padded numeric code, e.g. '048213'."""
    upper = 10**digits
    return str(secrets.randbelow(upper)).zfill(digits)


def generate_reset_token() -> str:
    """A URL-safe, high-entropy password reset token."""
    return secrets.token_urlsafe(32)
