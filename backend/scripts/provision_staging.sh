#!/usr/bin/env bash
#
# Provision, deploy and smoke-test the staging app (Phase 7.3).
#
# Staging exists for one reason: production went five months without a deploy,
# and when it finally happened two bugs that no test could have caught went
# live at once (`MutableHeaders.pop`, and a text-vs-uuid comparison in the
# per-user refresh loop -- see commits 8460dcf and a7ac86c). Both would have
# surfaced in sixty seconds against a real deployed instance. This script is
# how that instance gets made, and remade.
#
# Idempotent: safe to re-run. Creating an app that exists, or setting a secret
# to the value it already has, is a no-op.
#
# Usage:
#   STAGING_DATABASE_URL='postgresql://...' ./scripts/provision_staging.sh
#
# Optional:
#   STAGING_APP=daily-backend-staging   # app name, must match fly.staging.toml
#   OPENAI_API_KEY=sk-...               # otherwise read from backend/.env
#   SKIP_DEPLOY=1                       # provision + secrets only
#
# The staging database must be its own server or project -- never production,
# never a schema inside it. `_ensure_tables` runs ~100 DDL statements against
# whatever it is pointed at, on every boot.
set -euo pipefail

cd "$(dirname "$0")/.."

APP="${STAGING_APP:-daily-backend-staging}"
CONFIG="fly.staging.toml"
REGION="$(awk -F'"' '/^primary_region/ {print $2}' "$CONFIG")"

die() { printf '\n\033[31m%s\033[0m\n' "$*" >&2; exit 1; }
step() { printf '\n\033[1m==> %s\033[0m\n' "$*"; }

command -v fly >/dev/null || die "flyctl is not installed: https://fly.io/docs/flyctl/install/"
fly auth whoami >/dev/null 2>&1 || die "Not signed in to Fly. Run: fly auth login"
[ -f "$CONFIG" ] || die "$CONFIG not found; run this from backend/ or via its own path"

# The app name in the config is the one Fly deploys to; a mismatch would
# silently deploy staging code somewhere else -- including, in the worst case,
# over production.
CONFIG_APP="$(awk -F'"' '/^app =/ {print $2}' "$CONFIG")"
[ "$CONFIG_APP" = "$APP" ] || die "$CONFIG declares app '$CONFIG_APP' but STAGING_APP is '$APP'"
[ "$APP" != "daily-backend" ] || die "Refusing to run: '$APP' is production"

: "${STAGING_DATABASE_URL:?Set STAGING_DATABASE_URL to a separate, disposable Postgres 16 + pgvector database}"
case "$STAGING_DATABASE_URL" in
  *nvxcwxdllwcyvsskauww*)
    die "STAGING_DATABASE_URL points at the production Supabase project. Use a separate one."
    ;;
esac

OPENAI_KEY="${OPENAI_API_KEY:-$(grep -E '^OPENAI_API_KEY=' .env 2>/dev/null | cut -d= -f2- || true)}"
[ -n "$OPENAI_KEY" ] || die "Set OPENAI_API_KEY (or put it in backend/.env)"

step "Checking the staging database"
# Prefer the project venv: the system python3 has no psycopg on a typical dev
# machine, and a pre-flight that silently skips itself is worse than none --
# the whole point is to fail here rather than in a boot loop on Fly.
PYTHON=""
if [ -x venv/bin/python ] && venv/bin/python -c "import psycopg" 2>/dev/null; then
  PYTHON="venv/bin/python"
elif python3 -c "import psycopg" 2>/dev/null; then
  PYTHON="python3"
else
  printf '\033[33m%s\033[0m\n' \
    "No psycopg available, skipping the pre-flight. The app still fails loudly at boot if" \
    "the database is wrong; pip install -r requirements.txt into ./venv to check it here."
fi

if [ -n "$PYTHON" ]; then
"$PYTHON" - <<'PYEOF' || die "Staging database is not usable; see the error above"
import os
import sys

import psycopg

url = os.environ["STAGING_DATABASE_URL"]
with psycopg.connect(url, autocommit=True, connect_timeout=15) as conn:
    version = conn.execute("SHOW server_version").fetchone()[0]
    major = int(version.split(".")[0])
    if major < 16:
        sys.exit(f"Postgres {version}: CI pins pg16, staging must not be older")
    # Without this, startup aborts: _ensure_tables does
    # `CREATE EXTENSION IF NOT EXISTS vector` and re-raises on failure.
    conn.execute("CREATE EXTENSION IF NOT EXISTS vector")
    vector = conn.execute(
        "SELECT extversion FROM pg_extension WHERE extname = 'vector'").fetchone()[0]
    tables = conn.execute(
        "SELECT count(*) FROM information_schema.tables WHERE table_schema = 'public'"
    ).fetchone()[0]
    print(f"Postgres {version}, pgvector {vector}, {tables} existing public tables")
    if tables > 50:
        print("\033[33mWarning: this database already has a large schema. "
              "Staging is meant to be disposable -- is this the right one?\033[0m")
PYEOF
fi

step "Creating the app if it does not exist"
# Capture first, then match. `fly apps list | grep -q` looks right and is not:
# grep -q exits on the first match, fly gets SIGPIPE, and under `set -o
# pipefail` the pipeline reports failure even though the app was found -- so
# the script would try to re-create an app that already exists, and die.
APP_LIST="$(fly apps list 2>/dev/null || true)"
if printf '%s\n' "$APP_LIST" | grep -qE "^[[:space:]]*$APP[[:space:]]"; then
  echo "$APP already exists"
else
  fly apps create "$APP" --org personal
fi

step "Setting secrets"
# --stage so the values are written without triggering a deploy each time; the
# deploy below picks them all up at once.
fly secrets set --app "$APP" --stage \
  DATABASE_URL="$STAGING_DATABASE_URL" \
  OPENAI_API_KEY="$OPENAI_KEY" >/dev/null
echo "DATABASE_URL, OPENAI_API_KEY staged"
echo "Everything else (TAVILY_API_KEY, GEMINI_API_KEY, NEWS_API_KEY, ADMIN_API_KEY,"
echo "CORS_ORIGINS) degrades gracefully when unset; add them only if staging needs them."

if [ "${SKIP_DEPLOY:-}" = "1" ]; then
  step "SKIP_DEPLOY=1 -- stopping before deploy"
  exit 0
fi

SHA="$(git rev-parse --short HEAD)"
step "Deploying $SHA to $APP ($REGION)"
# Same GIT_SHA discipline as production: /healthz reports it, so "did my change
# actually deploy" is a question with an answer.
fly deploy --config "$CONFIG" --app "$APP" --build-arg "GIT_SHA=$SHA" --strategy rolling

step "Smoke test"
exec ./scripts/smoke_staging.sh
