"""Security headers applied to every response (Task 39).

A conservative Content-Security-Policy is applied. Because the app self-hosts
all JS/CSS/fonts (htmx, Alpine, Leaflet, Chart.js, Socket.IO client) the policy
can stay tight: scripts/styles from 'self' only, plus inline allowances for the
small per-page <script>/<style> blocks the templates use, and OpenStreetMap
tile images.
"""
from __future__ import annotations

from flask import Flask

# Note on 'unsafe-eval': Alpine.js evaluates its directive expressions (x-data,
# :class, @click, x-show) via the Function constructor, which CSP blocks unless
# 'unsafe-eval' is allowed for scripts. Without it, all Alpine interactivity
# silently fails. Images allow https/data for self-hosted + remote pet photos;
# OpenStreetMap tiles are served from *.tile.openstreetmap.org.
CSP = (
    "default-src 'self'; "
    "img-src 'self' data: https: blob:; "
    "script-src 'self' 'unsafe-inline' 'unsafe-eval'; "
    "style-src 'self' 'unsafe-inline'; "
    "font-src 'self'; "
    "connect-src 'self' ws: wss:; "
    "frame-ancestors 'none'; "
    "base-uri 'self'"
)


def register_security_headers(app: Flask) -> None:
    @app.after_request
    def _set_headers(resp):
        resp.headers.setdefault("X-Content-Type-Options", "nosniff")
        resp.headers.setdefault("X-Frame-Options", "DENY")
        resp.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
        resp.headers.setdefault(
            "Permissions-Policy", "geolocation=(self), microphone=(), camera=()"
        )
        resp.headers.setdefault("Content-Security-Policy", CSP)
        # HSTS only over HTTPS in production.
        if app.config.get("PREFERRED_URL_SCHEME") == "https":
            resp.headers.setdefault(
                "Strict-Transport-Security", "max-age=31536000; includeSubDomains"
            )
        return resp
