"""Import `app.main` in a test process without its heavy third-party deps.

`app.main` pulls in FastAPI, psycopg, the OpenAI SDK and more at import time.
Tests that only need its pure logic (leader election, schema guard, helpers)
install these stubs first. Importing this module has the side effect of
registering the stubs; import it before `from app import main`.

Only modules that are genuinely absent are stubbed, so a real dependency is
always preferred when the environment has it.
"""
import os
import sys
import types

# `app.main` builds a ChatService at import time, which constructs an
# OpenAIService, which refuses to exist without a key. Nothing in these tests
# makes a request; this only gets past the constructor.
os.environ.setdefault("OPENAI_API_KEY", "test-key-not-used")


def _stub(name: str, module) -> None:
    if name not in sys.modules:
        sys.modules[name] = module


class _FakeOpenAI:
    """Accepts the constructor kwargs the real client does; does nothing."""

    def __init__(self, *a, **kw):
        self.chat = types.SimpleNamespace(completions=types.SimpleNamespace(create=None))
        self.embeddings = types.SimpleNamespace(create=None)


# S8 tests can import the consumer graph before provider test modules. Prefer
# the installed transport, not merely an already-imported transport; otherwise
# exception classification captures a permanent incomplete stub at import time.
try:
    import httpx
except ImportError:
    _stub("httpx", types.SimpleNamespace(AsyncClient=object))
_stub("bs4", types.SimpleNamespace(BeautifulSoup=object))
_stub("openai", types.SimpleNamespace(OpenAI=_FakeOpenAI))
_stub("dotenv", types.SimpleNamespace(load_dotenv=lambda *a, **kw: None))

# Another test module may have registered a bare `OpenAI = object` stub first,
# which explodes on `OpenAI(api_key=...)`. Upgrade it, but never touch the real SDK.
_openai = sys.modules.get("openai")
if getattr(_openai, "OpenAI", None) is object:
    _openai.OpenAI = _FakeOpenAI

# `openai_service` does `from openai import OpenAI` at import time, so if it was
# already imported under a bare stub the name is bound there and fixing
# sys.modules alone is too late. Rebind it, then pre-seed the singleton so
# importing `app.main` (which constructs a ChatService at module scope) never
# runs the real constructor at all. Test modules stub `openai` in several
# different ways and import order varies, so this must not depend on who ran first.
# pytest can end up with the same file loaded under more than one module name
# (`app.services.openai_service` and `services.openai_service`), so patching a
# single instance is not enough — rebind the name everywhere it is bound to the
# bare `object` sentinel another test module installed.
for _name, _mod in list(sys.modules.items()):
    if _mod is not None and getattr(_mod, "OpenAI", None) is object:
        try:
            _mod.OpenAI = _FakeOpenAI
        except Exception:  # pragma: no cover - immutable module, nothing to do
            pass

try:
    import app.services.openai_service as _svc

    if getattr(_svc, "_openai_service", None) is None:
        _stub_service = _svc.OpenAIService.__new__(_svc.OpenAIService)
        _stub_service.client = _FakeOpenAI()
        _stub_service.model = "test-model"
        _stub_service.scoring_model = "test-model"
        _svc._openai_service = _stub_service
except Exception as exc:  # pragma: no cover
    SEED_ERROR = exc

_stub("jose", types.SimpleNamespace(jwt=types.SimpleNamespace(decode=lambda *a, **kw: {})))
_stub("jose.jwt", sys.modules["jose"].jwt)
_stub("jwt", types.SimpleNamespace(
    get_unverified_header=lambda *a: {},
    decode=lambda *a, **kw: {},
))

def _fastapi_is_incomplete() -> bool:
    """True when no fastapi is registered, or a thinner stub from another test
    module is. Never true for the real package, which has all of these."""
    mod = sys.modules.get("fastapi")
    if mod is None:
        return True
    return not all(hasattr(mod, a) for a in
                   ("FastAPI", "HTTPException", "Header", "Depends", "Query", "Request", "Body"))


if _fastapi_is_incomplete():
    fastapi = types.ModuleType("fastapi")
    fastapi.FastAPI = type("FastAPI", (), {
        "__init__": lambda self, **kw: None,
        "post": lambda self, *a, **kw: lambda f: f,
        "get": lambda self, *a, **kw: lambda f: f,
        "delete": lambda self, *a, **kw: lambda f: f,
        "put": lambda self, *a, **kw: lambda f: f,
        "on_event": lambda self, *a, **kw: lambda f: f,
        "middleware": lambda self, *a, **kw: lambda f: f,
        "add_middleware": lambda self, *a, **kw: None,
        "exception_handler": lambda self, *a, **kw: lambda f: f,
        "include_router": lambda self, *a, **kw: None,
        "patch": lambda self, *a, **kw: lambda f: f,
    })
    fastapi.HTTPException = type("HTTPException", (Exception,), {
        "__init__": lambda self, status_code=500, detail="":
            (setattr(self, "status_code", status_code), setattr(self, "detail", detail))[0],
    })
    fastapi.APIRouter = fastapi.FastAPI
    fastapi.Header = lambda **kw: None
    fastapi.Depends = lambda f: None
    fastapi.Query = lambda **kw: None
    fastapi.Request = object
    fastapi.Body = lambda **kw: None
    sys.modules["fastapi"] = fastapi

    middleware = types.ModuleType("fastapi.middleware")
    cors = types.ModuleType("fastapi.middleware.cors")
    cors.CORSMiddleware = object
    sys.modules["fastapi.middleware"] = middleware
    sys.modules["fastapi.middleware.cors"] = cors

    responses = types.ModuleType("fastapi.responses")
    class JSONResponse:
        def __init__(self, *, status_code=200, content=None, **_kwargs):
            self.status_code = status_code
            self.content = content

    responses.JSONResponse = JSONResponse
    responses.StreamingResponse = object
    sys.modules["fastapi.responses"] = responses

if "psycopg2" not in sys.modules:
    pg = types.ModuleType("psycopg2")
    pg.connect = lambda *a, **kw: None
    extras = types.ModuleType("psycopg2.extras")
    extras.RealDictCursor = object
    sys.modules["psycopg2"] = pg
    sys.modules["psycopg2.extras"] = extras

if "apscheduler" not in sys.modules:
    aps = types.ModuleType("apscheduler")
    sched = types.ModuleType("apscheduler.schedulers")
    aio = types.ModuleType("apscheduler.schedulers.asyncio")
    aio.AsyncIOScheduler = type("AsyncIOScheduler", (), {
        "__init__": lambda self, **kw: None,
        "add_job": lambda self, *a, **kw: None,
        "start": lambda self: None,
    })
    triggers = types.ModuleType("apscheduler.triggers")
    interval = types.ModuleType("apscheduler.triggers.interval")
    interval.IntervalTrigger = object
    sys.modules["apscheduler"] = aps
    sys.modules["apscheduler.schedulers"] = sched
    sys.modules["apscheduler.schedulers.asyncio"] = aio
    sys.modules["apscheduler.triggers"] = triggers
    sys.modules["apscheduler.triggers.interval"] = interval
