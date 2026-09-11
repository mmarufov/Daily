"""Regression test for a real bug found deploying to production for the first
time in 5 months (2026-09-11): `_security_headers` called
`response.headers.pop("Server", None)`, but Starlette's `MutableHeaders` has
no `.pop` (it only implements `__delitem__`/`__contains__`, inherited from
`Mapping` rather than `MutableMapping`). Every single request 500'd,
including `/healthz`, because the middleware runs on every response.

Every other test in this suite calls route handler functions directly
(`main.build_feed(...)`) or stubs `fastapi` out entirely via
`tests/_app_stubs.py` for speed -- none of them ever sends a request through
the actual ASGI app, so none of them exercise `@app.middleware("http")`
functions at all. That gap is exactly how this shipped past 1,884 passing
tests and was only caught by deploying. This file intentionally uses the
real `fastapi`/`starlette` (not the stub) and a real `TestClient` request,
so a break in any middleware that runs on every response fails here first.
"""
import os
import sys

os.environ.setdefault("OPENAI_API_KEY", "test-key-not-used")

# tests/conftest.py unconditionally imports tests._app_stubs before any test
# module is collected, and that installs a minimal fake `fastapi` (no
# TestClient, no real Starlette) into sys.modules for the whole session so
# other tests can skip the heavy dependency. This file needs the real thing,
# and whether it's already faked depends on collection order, so evict any
# stub and anything built on top of it, then import fresh.
for _name in list(sys.modules):
    if _name == "fastapi" or _name.startswith("fastapi.") \
            or _name == "app" or _name.startswith("app.") \
            or _name == "services" or _name.startswith("services."):
        del sys.modules[_name]

import fastapi  # noqa: E402  (forces a real import from site-packages)

assert fastapi.__file__ and "site-packages" in fastapi.__file__, (
    "fastapi resolved to something other than the real installed package "
    f"({fastapi.__file__!r}) -- the stub eviction above didn't work"
)

from fastapi.testclient import TestClient  # noqa: E402

from app import main  # noqa: E402

# TestClient only runs `main.lifespan` (which opens a real DB pool) when used
# as a context manager. Used directly, requests go straight through the ASGI
# app and its middleware without startup/shutdown -- exactly what a
# middleware-only smoke test needs, with no database required.
client = TestClient(main.app)


def test_healthz_returns_200_through_the_real_middleware_stack():
    """The one endpoint that must survive every middleware, always.

    Fly's health check hits this path; if any `@app.middleware("http")`
    function raises on every response (as `_security_headers` did), this
    goes from 200 to a 500 loop and the app never becomes ready.
    """
    response = client.get("/healthz")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert "git_sha" in body


def test_security_headers_applied_and_server_header_stripped():
    """Locks down the exact fix: MutableHeaders has no .pop(), only
    __delitem__/__contains__. `del headers[k]` after an `in` check is the
    correct pattern here, not dict's `.pop(k, default)`.
    """
    response = client.get("/healthz")
    assert response.status_code == 200
    assert "server" not in response.headers
    assert response.headers["strict-transport-security"] == (
        "max-age=31536000; includeSubDomains"
    )
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["x-frame-options"] == "DENY"
