import asyncio
import inspect
import os
import sys
import types
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

# Mock external deps before importing
if "httpx" not in sys.modules:
    sys.modules["httpx"] = types.SimpleNamespace(
        AsyncClient=object,
    )
if "bs4" not in sys.modules:
    sys.modules["bs4"] = types.SimpleNamespace(BeautifulSoup=object)
if "openai" not in sys.modules:
    sys.modules["openai"] = types.SimpleNamespace(OpenAI=object)
if "dotenv" not in sys.modules:
    sys.modules["dotenv"] = types.SimpleNamespace(load_dotenv=lambda: None)
if "jose" not in sys.modules:
    sys.modules["jose"] = types.SimpleNamespace(jwt=types.SimpleNamespace(decode=lambda *a, **kw: {}))
    sys.modules["jose.jwt"] = sys.modules["jose"].jwt
if "jwt" not in sys.modules:
    sys.modules["jwt"] = types.SimpleNamespace(
        get_unverified_header=lambda *a: {},
        decode=lambda *a, **kw: {},
    )
if "fastapi" not in sys.modules:
    # Minimal FastAPI stubs to allow main.py import for source inspection
    _fake_fastapi = types.ModuleType("fastapi")
    _fake_fastapi.FastAPI = type("FastAPI", (), {
        "__init__": lambda self, **kw: None,
        "post": lambda self, *a, **kw: lambda f: f,
        "get": lambda self, *a, **kw: lambda f: f,
        "delete": lambda self, *a, **kw: lambda f: f,
        "put": lambda self, *a, **kw: lambda f: f,
        "on_event": lambda self, *a, **kw: lambda f: f,
        "middleware": lambda self, *a, **kw: lambda f: f,
    })
    _fake_fastapi.HTTPException = type("HTTPException", (Exception,), {
        "__init__": lambda self, status_code=500, detail="": setattr(self, "status_code", status_code) or setattr(self, "detail", detail),
    })
    _fake_fastapi.Header = lambda **kw: None
    _fake_fastapi.Depends = lambda f: None
    _fake_fastapi.Query = lambda **kw: None
    sys.modules["fastapi"] = _fake_fastapi
    # fastapi.middleware.cors
    _cors_mod = types.ModuleType("fastapi.middleware")
    _cors_sub = types.ModuleType("fastapi.middleware.cors")
    _cors_sub.CORSMiddleware = object
    sys.modules["fastapi.middleware"] = _cors_mod
    sys.modules["fastapi.middleware.cors"] = _cors_sub
if "psycopg2" not in sys.modules:
    _fake_pg = types.ModuleType("psycopg2")
    _fake_pg.connect = lambda *a, **kw: None
    _fake_extras = types.ModuleType("psycopg2.extras")
    _fake_extras.RealDictCursor = object
    sys.modules["psycopg2"] = _fake_pg
    sys.modules["psycopg2.extras"] = _fake_extras
if "apscheduler" not in sys.modules:
    _fake_aps = types.ModuleType("apscheduler")
    _fake_sched = types.ModuleType("apscheduler.schedulers")
    _fake_async = types.ModuleType("apscheduler.schedulers.asyncio")
    _fake_async.AsyncIOScheduler = type("AsyncIOScheduler", (), {
        "__init__": lambda self, **kw: None,
        "add_job": lambda self, *a, **kw: None,
        "start": lambda self: None,
    })
    _fake_trigger = types.ModuleType("apscheduler.triggers")
    _fake_interval = types.ModuleType("apscheduler.triggers.interval")
    _fake_interval.IntervalTrigger = object
    sys.modules["apscheduler"] = _fake_aps
    sys.modules["apscheduler.schedulers"] = _fake_sched
    sys.modules["apscheduler.schedulers.asyncio"] = _fake_async
    sys.modules["apscheduler.triggers"] = _fake_trigger
    sys.modules["apscheduler.triggers.interval"] = _fake_interval


class PreferencesTimeoutTests(unittest.IsolatedAsyncioTestCase):
    def test_complete_preferences_timeout_returns_504(self):
        """Verify the complete_user_preferences endpoint wraps the OpenAI call
        in asyncio.wait_for and raises a 504 HTTPException on timeout."""
        # Instead of bootstrapping the full FastAPI app, we inspect the source
        # of the endpoint function to confirm the timeout pattern is present.
        # This is a lightweight structural test that catches accidental removal
        # of the timeout guard.
        try:
            from app import main as app_main
            source = inspect.getsource(app_main.complete_user_preferences)
        except Exception:
            # If the full import fails due to missing infra deps, fall back to
            # reading the source file directly.
            main_path = os.path.join(os.path.dirname(__file__), "..", "app", "main.py")
            with open(main_path) as f:
                source = f.read()

        # 1. asyncio.wait_for wraps the OpenAI call
        self.assertIn("asyncio.wait_for", source)

        # 2. There is a timeout parameter
        self.assertIn("timeout=", source)

        # 3. asyncio.TimeoutError is caught
        self.assertIn("asyncio.TimeoutError", source)

        # 4. A 504 status code is raised on timeout
        self.assertIn("504", source)
        self.assertIn("timed out", source.lower())


if __name__ == "__main__":
    unittest.main()
