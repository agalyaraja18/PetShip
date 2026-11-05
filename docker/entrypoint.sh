#!/usr/bin/env bash
# Container entrypoint: wait for the database, apply migrations, then exec the
# given command (gunicorn by default).
set -euo pipefail

echo "[entrypoint] Applying database migrations..."
# `flask db upgrade` is idempotent; safe to run on every boot.
flask --app wsgi db upgrade || {
    echo "[entrypoint] Migration failed." >&2
    exit 1
}

echo "[entrypoint] Starting: $*"
exec "$@"
