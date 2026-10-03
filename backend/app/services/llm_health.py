"""Online scorers behind `/llmz`.

Two signals, thresholds from `llm_health_policy.json` (pre-registered in
`evals/llm_observability/PREREGISTRATION.md`):

- fallback: per job, the share of traced calls answered by a fallback in the
  last window. Below `min_calls` a job is reported as insufficient data.
- embedding coverage: eligible articles past the grace period with no current
  vector. Read from `articles`, not from traces, so it sees a failure that no
  traced call reports.

`decide` is pure; `evaluate` runs the two queries and calls it.
"""
from __future__ import annotations

from datetime import datetime, timedelta

from app.services import llm_trace

POLICY = llm_trace.POLICY

_FALLBACK_SQL = """
    SELECT job,
           count(*) AS calls,
           count(*) FILTER (WHERE fallback) AS fallbacks
    FROM public.llm_calls
    WHERE ts > %s AND ts <= %s
    GROUP BY job
    ORDER BY job
"""

_COVERAGE_SQL = """
    SELECT count(*) AS eligible,
           count(*) FILTER (
               WHERE embedding IS NULL
                  OR embedding_content_version IS DISTINCT FROM analysis_content_version
           ) AS missing
    FROM public.articles
    WHERE analysis_text IS NOT NULL
      AND ingested_at > %s
      AND ingested_at <= %s
"""


def decide(fallback_rows: list[dict], coverage: dict, policy: dict = POLICY) -> dict:
    fb = policy["fallback"]
    jobs = {}
    for row in fallback_rows:
        calls, fallbacks = int(row["calls"]), int(row["fallbacks"])
        rate = fallbacks / calls if calls else 0.0
        if calls < fb["min_calls"]:
            state = "insufficient_data"
        elif rate > fb["max_rate"]:
            state = "tripped"
        else:
            state = "ok"
        jobs[row["job"]] = {"calls": calls, "fallbacks": fallbacks,
                            "rate": round(rate, 4), "state": state}

    cv = policy["embedding_coverage"]
    eligible, missing = int(coverage["eligible"]), int(coverage["missing"])
    share = missing / eligible if eligible else 0.0
    coverage_state = ("tripped" if missing >= cv["min_missing"] and share > cv["max_missing_share"]
                      else "ok")

    tripped = sorted(f"fallback:{job}" for job, v in jobs.items() if v["state"] == "tripped")
    if coverage_state == "tripped":
        tripped.append("embedding_coverage")
    return {
        "status": "tripped" if tripped else "ok",
        "tripped": tripped,
        "fallback": {"window_minutes": fb["window_minutes"], "jobs": jobs},
        "embedding_coverage": {"eligible": eligible, "missing": missing,
                               "missing_share": round(share, 4), "state": coverage_state},
    }


def evaluate(conn, *, at: datetime | None = None, policy: dict = POLICY) -> dict:
    from psycopg.rows import dict_row

    at = at or llm_trace.clock()
    fb, cv = policy["fallback"], policy["embedding_coverage"]
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(_FALLBACK_SQL, (at - timedelta(minutes=fb["window_minutes"]), at))
        fallback_rows = cur.fetchall()
        cur.execute(_COVERAGE_SQL, (at - timedelta(hours=cv["window_hours"]),
                                    at - timedelta(minutes=cv["grace_minutes"])))
        coverage = cur.fetchone()
    report = decide(fallback_rows, coverage, policy)
    report["evaluated_at"] = at.isoformat(timespec="seconds")
    return report


def unevaluable(reason: str) -> dict:
    """A monitor that cannot look must not report healthy."""
    return {"status": "unevaluable", "tripped": ["unevaluable"], "reason": reason}
