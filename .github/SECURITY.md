# Security Policy

## Reporting a vulnerability

Please do not open a public issue for a security problem.

Use GitHub's private reporting — **Security → Advisories → Report a vulnerability**
on this repository — or email the maintainer listed in the commit history. Include
what you found, how to reproduce it, and what an attacker could reach with it. You
will get an acknowledgement within a few days.

## What is and is not a secret in this repository

Daily is a public repository that talks to a private backend. The boundary matters:

| In the repository | Status |
|---|---|
| `Daily/GoogleService-Info.plist` | **Not a secret.** It holds only the public OAuth client identifier, which ships inside every copy of the app binary. |
| `backend/.env.example` | **Not a secret.** Variable names and safe defaults only. |
| `backend/.env` | Never committed — it is gitignored. |
| Model/database credentials | Live in Fly.io secrets, set with `fly secrets set`. |
| `backend/evals/.cache/` | Cached model *responses* over public news articles. No credentials, no user data. |

If you find a real credential in the history, report it privately rather than filing
an issue, so it can be rotated first.

## Security properties the backend tries to hold

These are the invariants worth testing against. A breach of any of them is a valid
report:

- **Outbound fetching is bounded.** `backend/app/services/safe_http.py` constrains
  redirects, DNS resolution, response size, and content type for every outbound
  request, so a hostile feed cannot turn the ingester into an SSRF probe.
- **Article bodies are provenance-bound.** A publisher defaults to `source_only`.
  Native full text requires a reviewed, append-only source policy plus an
  identity-matched artifact; text found elsewhere on the web is never served as a
  publisher body.
- **Auth verifies upstream.** Apple and Google ID tokens are checked against the
  provider JWKS before any session token is issued.
- **Admin surfaces are keyed.** `/admin/*` requires `ADMIN_API_KEY`.
- **Migrations are dry-run by default.** The `backend/scripts/manage_*.py` tools read
  the database URL only from the environment and change nothing without `--apply`.

## Supported versions

This is an actively developed single-branch project. Only `main` receives fixes.
