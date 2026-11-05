"""Core blueprint: health check and a minimal landing placeholder.

This blueprint is intentionally tiny and dependency-free so the application
has a working, testable surface from Task 1 onward. Richer public pages are
added in later tasks (Phase 2) and will supersede the placeholder index.
"""
from __future__ import annotations

from flask import Blueprint, jsonify

core_bp = Blueprint("core", __name__)


@core_bp.route("/healthz")
def healthz():
    """Liveness/readiness probe used by tests and container orchestration."""
    return jsonify(status="ok", service="petship"), 200
