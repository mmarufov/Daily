"""Ingest and summarise iOS crash/hang reports (Phase 7.2).

The client side is MetricKit, not a vendor SDK -- see
`Daily/Services/DiagnosticsService.swift` for why. That leaves the server with
a small job: accept the payloads, keep them for a bounded window, and make them
readable without a database client. All three matter; a crash table nobody can
read is not crash reporting.

Validation is hand-rolled to match the rest of `main.py` (no Pydantic models
exist in this app). Everything about a report is attacker-controllable except
the account it arrives on, so every field is length-bounded and the payload is
stored as opaque text rather than parsed: MetricKit's schema is Apple's to
change, and this table is a record of what the device said, not a model of it.
"""
from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

MAX_REPORTS_PER_REQUEST = 5
MAX_PAYLOAD_CHARS = 600_000
MAX_LABEL_CHARS = 64
#: Long enough to see whether a fix in the last release actually worked;
#: short enough that this never becomes a data-retention question of its own.
RETENTION_DAYS = 30

KNOWN_KINDS = frozenset({"crash", "hang", "cpu_exception", "disk_write_exception", "unknown"})


class DiagnosticsRejected(ValueError):
    """A malformed batch. Surfaced as 422, never as a 500."""


def _label(value, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise DiagnosticsRejected(f"{field} is required")
    if len(value) > MAX_LABEL_CHARS:
        raise DiagnosticsRejected(f"{field} is too long")
    return value.strip()


def _parse(report) -> dict:
    if not isinstance(report, dict):
        raise DiagnosticsRejected("each report must be an object")
    try:
        report_id = uuid.UUID(str(report.get("report_id")))
    except (TypeError, ValueError):
        raise DiagnosticsRejected("report_id must be a uuid") from None

    kinds = report.get("kinds")
    if not isinstance(kinds, list) or not 1 <= len(kinds) <= 8:
        raise DiagnosticsRejected("kinds must be a list of 1-8 entries")
    # Unknown kinds are kept rather than rejected: a future OS may report
    # something this build has never heard of, and losing that report would be
    # worse than storing a label we don't recognise. They're bucketed as
    # "unknown" for counting and the original survives in the payload.
    normalised = sorted({k if k in KNOWN_KINDS else "unknown"
                         for k in (_label(kind, "kind") for kind in kinds)})

    payload = report.get("payload")
    if not isinstance(payload, str) or not payload:
        raise DiagnosticsRejected("payload must be a non-empty string")
    if len(payload) > MAX_PAYLOAD_CHARS:
        raise DiagnosticsRejected("payload is too large")

    captured_at = report.get("captured_at")
    try:
        captured = datetime.fromisoformat(str(captured_at).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        raise DiagnosticsRejected("captured_at must be an ISO 8601 timestamp") from None
    if captured.tzinfo is None:
        captured = captured.replace(tzinfo=timezone.utc)
    # A device clock can be wrong in either direction. Clamp rather than reject:
    # a crash report with a bad timestamp is still a crash report.
    now = datetime.now(timezone.utc)
    if captured > now:
        captured = now

    return {
        "report_id": report_id,
        "captured_at": captured,
        "app_version": _label(report.get("app_version"), "app_version"),
        "build_number": _label(report.get("build_number"), "build_number"),
        "os_version": _label(report.get("os_version"), "os_version"),
        "kinds": normalised,
        "payload": payload,
        "truncated": bool(report.get("truncated")),
    }


def ingest(conn, user_id: str, body) -> dict:
    """Store a batch. Idempotent: `report_id` is client-minted and unique.

    A client that uploads, loses the response, and retries on the next launch
    must not double-count a crash -- which is exactly what the retry path in
    `DiagnosticsService.flush` does when the network drops mid-request.
    """
    reports = body.get("reports") if isinstance(body, dict) else None
    if not isinstance(reports, list) or not 1 <= len(reports) <= MAX_REPORTS_PER_REQUEST:
        raise DiagnosticsRejected(f"reports must be a list of 1-{MAX_REPORTS_PER_REQUEST} items")

    parsed = [_parse(report) for report in reports]
    stored = 0
    with conn.transaction():
        for report in parsed:
            row = conn.execute(
                """INSERT INTO public.client_diagnostics
                     (report_id, user_id, captured_at, app_version, build_number, os_version,
                      kinds, payload, truncated)
                   VALUES (%s,%s,%s,%s,%s,%s,%s::jsonb,%s,%s)
                   ON CONFLICT (report_id) DO NOTHING
                   RETURNING report_id""",
                (report["report_id"], uuid.UUID(str(user_id)), report["captured_at"],
                 report["app_version"], report["build_number"], report["os_version"],
                 json.dumps(report["kinds"]), report["payload"], report["truncated"]),
            ).fetchone()
            stored += int(row is not None)
    if stored:
        logger.info("Client diagnostics stored count=%d kinds=%s builds=%s", stored,
                    sorted({k for r in parsed for k in r["kinds"]}),
                    sorted({r["build_number"] for r in parsed}))
    return {"accepted": len(parsed), "stored": stored}


def summary(conn, *, days: int = 7, limit: int = 50) -> dict:
    """What broke, in which build, how often -- the only view anyone needs.

    Payload bodies are deliberately not returned: they are megabytes of address
    tables that only mean anything alongside the matching dSYM, and this is a
    read-through-curl endpoint, not a symbolication service.
    """
    days = max(1, min(int(days), RETENTION_DAYS))
    limit = max(1, min(int(limit), 200))
    rows = conn.execute(
        """SELECT build_number, app_version, kind, count(*) AS reports,
                  max(captured_at) AS last_seen
             FROM public.client_diagnostics, jsonb_array_elements_text(kinds) AS kind
            WHERE received_at > now() - make_interval(days => %s)
            GROUP BY build_number, app_version, kind
            ORDER BY reports DESC, last_seen DESC
            LIMIT %s""",
        (days, limit),
    ).fetchall()
    return {
        "window_days": days,
        "groups": [
            {
                "app_version": row["app_version"],
                "build_number": row["build_number"],
                "kind": row["kind"],
                "reports": int(row["reports"]),
                "last_seen": row["last_seen"].isoformat() if row["last_seen"] else None,
            }
            for row in rows
        ],
    }


def purge_expired(conn) -> int:
    with conn.cursor() as cur:
        cur.execute(
            "DELETE FROM public.client_diagnostics "
            "WHERE received_at < now() - make_interval(days => %s)",
            (RETENTION_DAYS,),
        )
        return cur.rowcount
