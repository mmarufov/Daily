"""In-memory stand-in for the production Postgres connection.

`feed_service.get_personalized_feed` talks to the database through a handful of
SQL statements. `SnapshotConn` answers each of them from a frozen snapshot pool
so the *real* production code path runs unchanged, offline, against a corpus
that never moves. Anything it does not recognise is recorded and raised: several
production loaders swallow exceptions, so an unhandled query would otherwise
silently degrade into "no signals" and the runner would measure the wrong thing.
"""
from __future__ import annotations

import json
import re
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

EVAL_NS = uuid.UUID("2c7f4a1e-5b3d-4e8f-9a6c-1d2e3f4a5b6c")

_INTERVAL = re.compile(r"interval '(\d+) hours'")
_LIMIT = re.compile(r"LIMIT (\d+)")


def eval_uuid(article_id: str) -> uuid.UUID:
    """Deterministic UUID for a snapshot article id ("a00042")."""
    return uuid.uuid5(EVAL_NS, f"article:{article_id}")


def persona_uuid(key: str) -> uuid.UUID:
    return uuid.uuid5(EVAL_NS, f"persona:{key}")


def _parse_dt(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    if isinstance(value, str) and value:
        try:
            dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    return None


class SnapshotCursor:
    def __init__(self, conn: "SnapshotConn"):
        self.conn = conn
        self._rows: list[dict] = []

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def execute(self, query: str, params: Any = None) -> None:
        q = " ".join(str(query).split())
        self.conn.store["executed"].append((q[:120], params))
        self._rows = self.conn.dispatch(q, params)

    def fetchone(self):
        return self._rows[0] if self._rows else None

    def fetchall(self):
        return list(self._rows)


class SnapshotConn:
    """Serves one persona + one pool. `datetime_cls` lets a runner hand back
    instances of its frozen datetime subclass so `isinstance(x, datetime)`
    checks inside `feed_service` keep passing after `datetime` is patched."""

    def __init__(self, persona: dict, pool: list[dict], frozen_now: datetime,
                 datetime_cls: type = datetime, content_quality: float = 0.7):
        self.persona = persona
        self.pool = pool
        self.frozen_now = frozen_now if frozen_now.tzinfo else frozen_now.replace(tzinfo=timezone.utc)
        self.datetime_cls = datetime_cls
        self.content_quality = content_quality
        self.store: dict[str, Any] = {"executed": [], "cache_inserts": {}, "unhandled": [], "served_ids": set()}
        self._rows: list[dict] | None = None
        # S10 F: in-memory stand-in for user_feedback_signals/reading_events,
        # written by the REAL app.services.feedback_signals.apply_feedback
        # against this same connection (see evals/learning_replay.py) so a
        # persona's next build reflects actual feedback instead of the
        # unconditional `[]` this harness previously always returned for
        # these tables -- the S0 gap docs/stages/s10-learning-audit.md names as the
        # most important one: nothing could previously prove learning works.
        self.feedback_signals: dict[tuple[str, str, str], dict] = {}
        self.suppressed_article_ids: set[str] = set()

    def cursor(self) -> SnapshotCursor:
        return SnapshotCursor(self)

    def suppress(self, article_id: str) -> None:
        """S10 F: record that this user rejected an article, exactly what
        load_suppressed_article_ids checks for (not_relevant/less_like_this/
        already_knew/hide_source in reading_events). Direct rather than a
        scripted INSERT round-trip: that write path is already covered by
        test_feedback_signals.py's TestSuppression; what this harness proves
        is that the unchanged production get_personalized_feed responds
        correctly once the signal exists, not that the insert SQL is right."""
        self.suppressed_article_ids.add(str(eval_uuid(article_id)))

    # -- helpers ---------------------------------------------------------------
    def _dt(self, value: Any) -> Any:
        dt = _parse_dt(value)
        if dt is None:
            return None
        return self.datetime_cls(dt.year, dt.month, dt.day, dt.hour, dt.minute, dt.second,
                                 dt.microsecond, tzinfo=dt.tzinfo)

    def _all_rows(self) -> list[dict]:
        if self._rows is None:
            rows = []
            for a in self.pool:
                pub = _parse_dt(a.get("published_at")) or self.frozen_now
                rows.append({
                    "_sort": pub, "_sid": a["id"],
                    "id": eval_uuid(a["id"]), "url": a.get("url"), "title": a.get("title", ""),
                    "summary": a.get("summary") or "", "content": a.get("content") or "",
                    "author": a.get("author"), "source_name": a.get("source"),
                    "image_url": a.get("image_url"),
                    "published_at": self._dt(a.get("published_at")),
                    "ingested_at": self._dt(self.frozen_now),
                    "category": a.get("category") or a.get("feed_vertical"),
                    "content_quality": a.get("content_quality", self.content_quality),
                    "coverage_role": None, "selection_reason": None,
                    "matched_topics": [], "matched_entities": [],
                    "precision_score": 0.0, "breadth_score": 0.0,
                })
            rows.sort(key=lambda r: r["_sort"], reverse=True)
            self._rows = rows
        return self._rows

    def _candidate_rows(self, q: str) -> list[dict]:
        m_int, m_lim = _INTERVAL.search(q), _LIMIT.search(q)
        hours = int(m_int.group(1)) if m_int else 24 * 14
        limit = int(m_lim.group(1)) if m_lim else 10_000
        cutoff = self.frozen_now - timedelta(hours=hours)
        out = []
        for r in self._all_rows():
            if r["_sort"] <= cutoff:
                continue
            if not (r["content_quality"] >= 0.4):
                continue
            out.append({k: v for k, v in r.items() if not k.startswith("_")})
            self.store["served_ids"].add(r["_sid"])
            if len(out) >= limit:
                break
        return out

    def _prefs_row(self) -> dict:
        p = self.persona
        v2 = p.get("user_profile_v2") or {}
        brief = v2.get("source_selection_brief") or p.get("source_selection_brief") or {}
        return {
            "ai_profile": p.get("ai_profile") or "",
            "interests": json.dumps(p.get("interests") or {}),
            "user_profile_v2": json.dumps(v2),
            "source_selection_brief": json.dumps(brief),
            "updated_at": self.frozen_now - timedelta(days=1),
        }

    # -- dispatch ------------------------------------------------------------------
    def dispatch(self, q: str, params: Any) -> list[dict]:
        if "SELECT behavior_cache FROM public.user_preferences" in q:
            return []
        if "FROM public.user_preferences WHERE user_id = %s AND completed" in q:
            return [self._prefs_row()]
        if "SELECT 1 FROM public.user_sources" in q:
            return [{"?column?": 1}]
        if "FROM public.user_feed_cache ufc" in q:
            return []
        if ("FROM public.articles a JOIN public.article_source_links" in q
                or "FROM public.articles a LEFT JOIN public.article_content_artifacts artifact" in q
                or "FROM public.articles WHERE COALESCE(published_at" in q):
            return self._candidate_rows(q)
        if "FROM public.entity_pins" in q or "FROM public.source_quality" in q:
            return []
        # S10 F: real signals instead of an unconditional []. `_attributions`
        # (the SELECT with the LEFT JOIN) reads the article's source/category
        # from the pool and its matched_profile_signals from whatever a prior
        # INSERT INTO user_feed_cache recorded, exactly like production.
        if "FROM public.articles a" in q and "LEFT JOIN public.user_feed_cache ufc" in q:
            article_id = str(params[1]) if params and len(params) > 1 else None
            row = next((r for r in self._all_rows() if str(r["id"]) == article_id), None)
            if row is None:
                return []
            cached = self.store["cache_inserts"].get(article_id, {})
            return [{"source_name": row["source_name"], "category": row["category"],
                     "matched_profile_signals": cached.get("matched_profile_signals")}]
        if q.startswith("INSERT INTO public.user_feedback_signals"):
            user_id, kind, value, delta = str(params[0]), params[1], params[2], params[3]
            floor, ceiling = params[4], params[5]
            key = (user_id, kind, value)
            existing = self.feedback_signals.get(key)
            # Replay applies at a single frozen instant: no wall-clock time
            # passes between builds, so the real UPSERT's decay term is ~1
            # and is correctly omitted here rather than reimplementing SQL's
            # extract(epoch FROM ...) in Python for a case that never fires.
            base = existing["weight"] if existing else 0.0
            self.feedback_signals[key] = {
                "weight": max(floor, min(ceiling, base + delta)),
                "events": (existing["events"] + 1) if existing else 1,
                "updated_at": self.frozen_now,
            }
            return []
        if "FROM public.user_feedback_signals" in q:
            user_id = str(params[0]) if params else None
            return [{"kind": k, "value": v, "weight": data["weight"], "updated_at": data["updated_at"]}
                    for (uid, k, v), data in self.feedback_signals.items() if uid == user_id]
        if "FROM public.reading_events" in q:
            return [{"article_id": aid} for aid in self.suppressed_article_ids]
        if q.startswith("DELETE FROM public.user_feed_cache"):
            return []
        if q.startswith("INSERT INTO public.user_feed_cache"):
            if params and len(params) > 3:
                self.store["cache_inserts"][str(params[1])] = {
                    "score": params[2], "relevant": params[3],
                    "reason": params[4] if len(params) > 4 else None,
                    # S10 F: index 8 in the 12-param shape _save_feed_cache
                    # writes (S10 A1 added feed_request_id at the end).
                    "matched_profile_signals": json.loads(params[8]) if len(params) > 8 and params[8] else None,
                }
            return []
        if q.startswith("UPDATE public.articles") or q.startswith("INSERT INTO public.feed_build_log"):
            return []
        self.store["unhandled"].append(q[:200])
        raise AssertionError(f"SnapshotConn: unhandled SQL: {q[:160]}")
