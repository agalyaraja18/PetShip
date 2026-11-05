#!/usr/bin/env bash
# Container entrypoint: wait for the database to be reachable, apply
# migrations, then exec the given command (gunicorn by default).
set -euo pipefail

if [ -z "${DATABASE_URL:-}" ]; then
    echo "[entrypoint] ERROR: DATABASE_URL is not set." >&2
    echo "[entrypoint] On Render, copy your PostgreSQL 'Internal Database URL'" >&2
    echo "[entrypoint] into the web service's DATABASE_URL environment variable." >&2
    exit 1
fi

# Wait for the database host to accept connections. Render's database may take
# a few seconds to become resolvable/ready after the service starts.
echo "[entrypoint] Waiting for the database to become reachable..."
python - <<'PY'
import os
import sys
import time
from urllib.parse import urlsplit

from sqlalchemy import create_engine, text

# Normalise the scheme the same way the app config does.
url = os.environ["DATABASE_URL"]
if url.startswith("postgres://"):
    url = url.replace("postgres://", "postgresql+psycopg://", 1)
elif url.startswith("postgresql://"):
    url = url.replace("postgresql://", "postgresql+psycopg://", 1)

# Print the host/port we're about to connect to, with credentials masked, so
# deploy logs reveal exactly what DNS name is being resolved.
try:
    parts = urlsplit(url)
    print(
        f"[entrypoint] Connecting to host={parts.hostname!r} "
        f"port={parts.port!r} db={parts.path.lstrip('/')!r} "
        f"user={parts.username!r}"
    )
except Exception as _exc:  # noqa: BLE001
    print(f"[entrypoint] Could not parse DATABASE_URL: {_exc}")

last_err = None
for attempt in range(1, 31):  # up to ~60s
    try:
        engine = create_engine(url, pool_pre_ping=True)
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        print(f"[entrypoint] Database reachable (attempt {attempt}).")
        sys.exit(0)
    except Exception as exc:  # noqa: BLE001
        last_err = exc
        print(f"[entrypoint] DB not ready (attempt {attempt}/30): {exc}")
        time.sleep(2)

print(f"[entrypoint] Database never became reachable. Last error:\n{last_err}")
sys.exit(1)
PY

echo "[entrypoint] Applying database migrations..."
flask --app wsgi db upgrade || {
    echo "[entrypoint] Migration failed." >&2
    exit 1
}

echo "[entrypoint] Starting: $*"
exec "$@"
