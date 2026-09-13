#!/usr/bin/env bash
#
# Post-deploy verification for staging (Phase 7.3). Run on its own, or as the
# last step of provision_staging.sh.
#
# Every check here corresponds to something that actually broke, or would have:
#
#   /healthz 200            -- returned 404 for five months and nobody noticed
#   git_sha matches HEAD    -- proves the deploy is the code you think it is
#   /readyz 200             -- the only check that touches the database, so the
#                              only one that proves _ensure_tables' ~100 DDL
#                              statements completed against a fresh schema
#   a request that isn't
#   /healthz                -- `_security_headers` called MutableHeaders.pop(),
#                              which does not exist, and 500'd *every* request;
#                              /healthz alone would not have caught it because
#                              the bug was in middleware common to all of them
#   security headers        -- set by that same middleware
#
# Usage: ./scripts/smoke_staging.sh [app-name]
set -euo pipefail

cd "$(dirname "$0")/.."

APP="${1:-${STAGING_APP:-daily-backend-staging}}"
BASE="https://${APP}.fly.dev"
EXPECTED_SHA="$(git rev-parse --short HEAD 2>/dev/null || echo '')"

pass() { printf '  \033[32mok\033[0m  %s\n' "$1"; }
fail() { printf '  \033[31mFAIL\033[0m %s\n' "$1"; FAILURES=$((FAILURES + 1)); }
FAILURES=0

printf '\n\033[1mSmoke-testing %s\033[0m\n\n' "$BASE"

# auto_start_machines wakes a stopped machine on the first request, which can
# take a few seconds. Retry rather than reporting a cold start as an outage.
health=""
for attempt in 1 2 3 4 5 6 7 8 9 10; do
  health="$(curl -fsS --max-time 20 "$BASE/healthz" 2>/dev/null || true)"
  [ -n "$health" ] && break
  sleep 3
done

if [ -n "$health" ]; then
  pass "/healthz responded"
else
  fail "/healthz did not respond after ~30s"
  echo; echo "Recent logs:"; fly logs --app "$APP" --no-tail 2>/dev/null | tail -30
  exit 1
fi

sha="$(printf '%s' "$health" | python3 -c 'import json,sys; print(json.load(sys.stdin).get("git_sha",""))' 2>/dev/null || echo '')"
if [ -z "$EXPECTED_SHA" ]; then
  pass "git_sha=$sha (no local git checkout to compare against)"
elif [ "$sha" = "$EXPECTED_SHA" ]; then
  pass "git_sha=$sha matches HEAD"
else
  fail "git_sha=$sha but HEAD is $EXPECTED_SHA -- staging is running different code"
fi

# The database check. A machine can be healthy and still have failed to migrate.
ready_code="$(curl -s -o /tmp/staging_readyz -w '%{http_code}' --max-time 30 "$BASE/readyz" || echo 000)"
if [ "$ready_code" = "200" ]; then
  pass "/readyz 200 -- schema migrated and reachable"
else
  fail "/readyz $ready_code -- $(cat /tmp/staging_readyz 2>/dev/null | head -c 200)"
fi

# An authenticated route without a token. 401 is the right answer and proves
# the request got through routing and middleware to a real handler.
me_code="$(curl -s -o /dev/null -w '%{http_code}' --max-time 20 "$BASE/me" || echo 000)"
if [ "$me_code" = "401" ]; then
  pass "/me 401 without a token -- middleware and routing are intact"
else
  fail "/me returned $me_code, expected 401"
fi

headers="$(curl -fsS -D - -o /dev/null --max-time 20 "$BASE/healthz" 2>/dev/null || true)"
for header in "x-content-type-options" "x-frame-options" "strict-transport-security"; do
  if printf '%s' "$headers" | tr 'A-Z' 'a-z' | grep -q "^$header:"; then
    pass "$header present"
  else
    fail "$header missing"
  fi
done

# Deletion and revocation are the newest surface (Phase 7.1) and the one whose
# absence is hardest to notice: nothing in the app calls them on a happy path.
for route in "/auth/session" "/user/account"; do
  code="$(curl -s -o /dev/null -w '%{http_code}' -X DELETE --max-time 20 "$BASE$route" || echo 000)"
  if [ "$code" = "401" ]; then
    pass "DELETE $route 401 without a token -- route is registered"
  else
    fail "DELETE $route returned $code, expected 401"
  fi
done

printf '\n'
if [ "$FAILURES" -eq 0 ]; then
  printf '\033[32mStaging looks healthy.\033[0m Production deploy is now a rehearsed change.\n\n'
else
  printf '\033[31m%d check(s) failed.\033[0m Do not promote this build.\n\n' "$FAILURES"
  echo "Recent logs:"; fly logs --app "$APP" --no-tail 2>/dev/null | tail -40
  exit 1
fi
