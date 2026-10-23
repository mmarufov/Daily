"""Replay the 2026-09-30 quota switch through the real embedding step and /llmz.

Each scenario gets a disposable PostgreSQL database with the application's own
schema. The clock is frozen and advanced in 3-minute ticks. Every tick inserts
10 eligible articles, runs `embed_pending` (the ingestion loop's embedding
step) through `OpenAIService.generate_embedding` and the real `openai` SDK over
an `httpx.MockTransport`, flushes the traces, and asks the real `/llmz`
handler for its status. From the switch onward the transport answers every
request with HTTP 429 and OpenAI's `insufficient_quota` error body.

Expected results are pre-registered in PREREGISTRATION.md.

    python -m evals.llm_observability.replay --database-url postgresql:///postgres --write
"""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import platform
import secrets
import subprocess
import sys
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Iterator

os.environ.setdefault("OPENAI_API_KEY", "replay-not-used")

import httpx
import psycopg
from psycopg import sql
from psycopg.conninfo import conninfo_to_dict, make_conninfo
from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool

from app import main as app_main
from app.services import llm_trace
from app.services.article_embeddings import embed_pending
from app.services.openai_service import OpenAIService



def _real_openai():
    """The real SDK, even when a test module registered a stub under `openai`
    first. The stub is put back for the modules that expect it."""
    registered = sys.modules.get("openai")
    if hasattr(registered, "RateLimitError"):
        return registered
    sys.modules.pop("openai", None)
    try:
        import openai as real
    finally:
        if registered is not None:
            sys.modules["openai"] = registered
    return real


openai = _real_openai()

BACKEND = Path(__file__).resolve().parents[2]
RESULTS = BACKEND / "evals" / "results" / "llm-observability.json"

UTC = timezone.utc
START = datetime(2026, 9, 30, 18, 40, tzinfo=UTC)
SWITCH = datetime(2026, 9, 30, 19, 40, tzinfo=UTC)
END = datetime(2026, 9, 30, 21, 30, tzinfo=UTC)
TICK = timedelta(minutes=3)
ARTICLES_PER_TICK = 10
EXTRA_CHECKPOINTS = (datetime(2026, 9, 30, 19, 39, tzinfo=UTC), datetime(2026, 9, 30, 20, 10, tzinfo=UTC))

SCENARIOS = {
    "incident": {"switch": True, "tagging": True, "limit": 50},
    "tagging_removed": {"switch": True, "tagging": False, "limit": 50},
    "no_switch": {"switch": False, "tagging": True, "limit": 50},
    "few_calls": {"switch": True, "tagging": True, "limit": 1},
}

QUOTA_BODY = {"error": {
    "message": "You exceeded your current quota, please check your plan and billing details.",
    "type": "insufficient_quota", "param": None, "code": "insufficient_quota"}}


def quota_transport(state: dict, *, switch: bool) -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        if switch and state["now"] >= SWITCH:
            return httpx.Response(429, json=QUOTA_BODY)
        text = json.loads(request.content)["input"]
        tokens = max(1, len(text) // 4)
        return httpx.Response(200, json={
            "object": "list", "model": "text-embedding-3-small",
            "data": [{"object": "embedding", "index": 0, "embedding": [0.001] * 1536}],
            "usage": {"prompt_tokens": tokens, "total_tokens": tokens}})
    return httpx.MockTransport(handler)


@contextmanager
def disposable_database(base_url: str) -> Iterator[str]:
    name = f"daily_llmobs_{os.getpid()}_{secrets.token_hex(4)}"
    with psycopg.connect(base_url, autocommit=True) as admin:
        admin.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(name)))
    parameters = conninfo_to_dict(base_url)
    parameters["dbname"] = name
    try:
        yield make_conninfo(**parameters)
    finally:
        with psycopg.connect(base_url, autocommit=True) as admin:
            admin.execute(sql.SQL("DROP DATABASE IF EXISTS {} WITH (FORCE)").format(sql.Identifier(name)))


@contextmanager
def patched(state: dict, url: str, *, tagging: bool) -> Iterator[None]:
    saved = (llm_trace.clock, app_main.pool, llm_trace.Scope.fallback)
    llm_trace.clock = lambda: state["now"]
    app_main.pool = ConnectionPool(url, min_size=1, max_size=2, open=True,
                                   kwargs={"row_factory": dict_row, "autocommit": True})
    if not tagging:
        llm_trace.Scope.fallback = lambda self, exc=None, *, outcome=None: None
    llm_trace.drain()
    try:
        yield
    finally:
        app_main.pool.close()
        llm_trace.clock, app_main.pool, llm_trace.Scope.fallback = saved
        llm_trace.drain()


def _status(response) -> tuple[int, dict]:
    body = getattr(response, "body", None)
    # tests/_app_stubs.py swaps in a JSONResponse that keeps `content` unencoded.
    return response.status_code, json.loads(body) if body is not None else response.content


def _observation(at: datetime, code: int, body: dict) -> dict:
    ingestion = body.get("fallback", {}).get("jobs", {}).get("ingestion")
    return {"at": at.strftime("%H:%M"), "status": code, "tripped": body.get("tripped", []),
            "ingestion": ingestion, "coverage": body.get("embedding_coverage")}


def run_scenario(base_url: str, name: str) -> dict:
    spec = SCENARIOS[name]
    state = {"now": START}
    timeline = []
    attempted = 0
    flushed: list = []
    with disposable_database(base_url) as url, patched(state, url, tagging=spec["tagging"]):
        with psycopg.connect(url, autocommit=True, row_factory=dict_row) as conn:
            app_main._ensure_tables(conn, force=True)
            service = OpenAIService()
            service.client = llm_trace.TracedOpenAI(openai.OpenAI(
                api_key="replay", max_retries=0,
                http_client=httpx.Client(transport=quota_transport(state, switch=spec["switch"]))))
            llm_trace.set_job("ingestion")

            ticks = []
            t = START
            while t <= END:
                ticks.append(t)
                t += TICK
            events = sorted({*ticks, *EXTRA_CHECKPOINTS})
            for at in events:
                state["now"] = at
                if at in ticks:
                    with conn.cursor() as cur:
                        for i in range(ARTICLES_PER_TICK):
                            cur.execute(
                                "INSERT INTO public.articles (url, title, summary, ingested_at, "
                                "analysis_text, analysis_content_version) VALUES (%s, %s, %s, %s, %s, 1)",
                                (f"https://replay.example/{at:%H%M}/{i}", f"Story {at:%H:%M} {i}",
                                 "Summary.", at, "Body text of the article. " * 20))
                    attempted += asyncio.run(embed_pending(conn, service, limit=spec["limit"]))["attempted"]
                    batch = llm_trace.drain()
                    llm_trace._enqueue(batch)
                    llm_trace.flush(conn)
                    flushed.extend(batch)
                code, body = _status(asyncio.run(app_main.llmz()))
                timeline.append(_observation(at, code, body))

            def traced() -> int:
                return conn.execute("SELECT count(*) AS n FROM public.llm_calls").fetchone()["n"]

            traced_once = traced()
            # Every record again, as a flush retried after a failure would send it.
            llm_trace._enqueue(flushed)
            llm_trace.flush(conn)
            return {"timeline": timeline, "attempted": attempted,
                    "traced": traced_once, "traced_after_reflush": traced()}


def run_unevaluable(base_url: str) -> dict:
    state = {"now": SWITCH}
    with disposable_database(base_url) as url, patched(state, url, tagging=True):
        with psycopg.connect(url, autocommit=True, row_factory=dict_row) as conn:
            app_main._ensure_tables(conn, force=True)
            conn.execute("DROP TABLE public.llm_calls")
        code, body = _status(asyncio.run(app_main.llmz()))
    return {"status": code, "body_status": body["status"], "reason": body.get("reason")}


def _at(timeline: list[dict], hhmm: str) -> dict:
    return next(o for o in timeline if o["at"] == hhmm)


def _first(timeline: list[dict], predicate) -> str | None:
    return next((o["at"] for o in timeline if predicate(o)), None)


def summarize(timeline: list[dict]) -> dict:
    return {
        "status_19_39": _at(timeline, "19:39")["status"],
        "first_503": _first(timeline, lambda o: o["status"] == 503),
        "status_20_10": _at(timeline, "20:10")["status"],
        "ingestion_rate_20_10": (_at(timeline, "20:10")["ingestion"] or {}).get("rate"),
        "ingestion_state_20_10": (_at(timeline, "20:10")["ingestion"] or {}).get("state"),
        "coverage_first_trip": _first(timeline, lambda o: "embedding_coverage" in o["tripped"]),
        "max_ingestion_calls_in_window": max((o["ingestion"] or {}).get("calls", 0) for o in timeline),
    }


def expectations(summaries: dict, unevaluable: dict) -> dict:
    """The pre-registered expectations, evaluated. Every value must be True."""
    inc = summaries["incident"]
    ctl = summaries["tagging_removed"]
    clean = summaries["no_switch"]
    few = summaries["few_calls"]
    return {
        "incident: 200 at 19:39": inc["status_19_39"] == 200,
        "incident: first 503 between 19:40 and 19:50": inc["first_503"] is not None
            and "19:40" <= inc["first_503"] <= "19:50",
        "incident: 503 at 20:10 with ingestion fallback rate 1.0": inc["status_20_10"] == 503
            and inc["ingestion_rate_20_10"] == 1.0,
        "incident: coverage first trips between 20:40 and 21:10": inc["coverage_first_trip"] is not None
            and "20:40" <= inc["coverage_first_trip"] <= "21:10",
        "control tagging removed: 200 at 20:10": ctl["status_20_10"] == 200,
        "control no switch: never 503": clean["first_503"] is None and clean["coverage_first_trip"] is None,
        "control few calls: fallback reports insufficient data at 20:10":
            few["ingestion_state_20_10"] == "insufficient_data",
        "control unevaluable: 503": unevaluable["status"] == 503 and unevaluable["body_status"] == "unevaluable",
    }


def run_all(base_url: str) -> dict:
    runs = {name: run_scenario(base_url, name) for name in SCENARIOS}
    summaries = {}
    for name, run in runs.items():
        summaries[name] = summarize(run["timeline"])
        summaries[name].update(attempted=run["attempted"], traced=run["traced"],
                               traced_after_reflush=run["traced_after_reflush"])
    unevaluable = run_unevaluable(base_url)
    return {"summaries": summaries, "unevaluable": unevaluable,
            "expectations": expectations(summaries, unevaluable),
            "timelines": {name: run["timeline"] for name, run in runs.items()}}


def _git(*args: str) -> str:
    return subprocess.run(["git", *args], cwd=BACKEND, capture_output=True, text=True).stdout.strip()


def provenance(base_url: str) -> dict:
    with psycopg.connect(base_url) as conn:
        server = conn.execute("SHOW server_version").fetchone()[0]
    return {
        "command": "python -m evals.llm_observability.replay --database-url <disposable server> --write",
        "git_sha": _git("rev-parse", "HEAD"),
        "git_dirty": bool(_git("status", "--porcelain", "--", "app", "evals/llm_observability")),
        "ran_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "machine": f"{platform.system()} {platform.release()} {platform.machine()}",
        "python": platform.python_version(),
        "postgres": server,
        "openai_sdk": openai.__version__,
        "policy_sha256": hashlib.sha256(llm_trace.POLICY_PATH.read_bytes()).hexdigest(),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--database-url", required=True)
    parser.add_argument("--write", action="store_true")
    args = parser.parse_args(argv)
    result = run_all(args.database_url)
    print(json.dumps({"summaries": result["summaries"], "unevaluable": result["unevaluable"],
                      "expectations": result["expectations"]}, indent=2))
    if args.write:
        existing = json.loads(RESULTS.read_text()) if RESULTS.exists() else {}
        existing["replay"] = {"provenance": provenance(args.database_url), **result}
        RESULTS.write_text(json.dumps(existing, indent=2, sort_keys=False) + "\n")
        print(f"wrote {RESULTS.relative_to(BACKEND)}")
    return 0 if all(result["expectations"].values()) else 1


if __name__ == "__main__":
    sys.exit(main())
