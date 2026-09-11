"""Transactionally attributed explicit feedback. Passive telemetry never rewrites S5 taste."""
from __future__ import annotations

import hashlib
import json
import logging
import math
import uuid
from datetime import datetime, timezone
from pathlib import Path

from .reader_contract import active, intent_semantic_hash
from . import reward as _reward

logger = logging.getLogger(__name__)

# S10 C: the shared reward definition with the legacy path (feedback_signals.py).
DELTAS = _reward.DELTAS


def _valid_content_hash(value):
    return (isinstance(value, str) and len(value) == 64
            and all(character in "0123456789abcdef" for character in value))


def _intent_semantics(snapshot, now):
    return {i["id"]: intent_semantic_hash(i) for i in snapshot["profile"]["intents"] if active(i, now)}


def install_schema(conn):
    with conn.transaction():
        conn.execute("SELECT pg_advisory_xact_lock(811505)")
        conn.execute(Path(__file__).with_name("reader_feedback_schema.sql").read_text())


def record_delivery(conn, user_id, request_id, snapshot, articles):
    """Record final server delivery, not exposure or an intermediate ranking opportunity.

    Legacy callers retain exact-article receipts but cannot manufacture confirmed S7
    intent attribution. Ranking callers supply a recipe and current evidence stamp;
    only their confirmed `_reader_intent_ids` receive semantic proof.
    """
    semantics = _intent_semantics(snapshot, datetime.now(timezone.utc))
    if len({str(a["id"]) for a in articles}) != len(articles):
        raise ValueError("Final delivery contains duplicate articles")
    prepared = []
    for position, article in enumerate(articles):
        position = article.get("delivery_position", position)
        if type(position) is not int or not 0 <= position <= 10000:
            raise ValueError("Invalid immutable delivery position")
        recipe = article.get("_ranking_recipe")
        evidence = article.get("_ranking_evidence_stamp")
        if recipe is not None and (not isinstance(recipe, str) or not recipe or len(recipe) > 256):
            raise ValueError("Invalid ranking receipt recipe")
        encoded_evidence = json.dumps(evidence, sort_keys=True, allow_nan=False)
        if len(encoded_evidence.encode()) > 16384:
            raise ValueError("Ranking receipt evidence stamp is too large")
        ids = article.get("_reader_intent_ids", [])
        if not isinstance(ids, list) or any(not isinstance(i, str) or i not in semantics for i in ids):
            raise ValueError("Receipt contains an unknown confirmed intent")
        ids = sorted(set(ids))
        hashes = {i: semantics[i] for i in ids} if recipe and evidence is not None else {}
        assembly_recipe = article.get("_assembly_recipe")
        coverage = article.get("_assembly_coverage_unit")
        novelty = article.get("_assembly_novelty_key")
        content_hash = article.get("_assembly_content_hash")
        if assembly_recipe is not None:
            if (not isinstance(assembly_recipe, str) or not 1 <= len(assembly_recipe) <= 256
                    or not isinstance(coverage, str) or not 1 <= len(coverage) <= 512
                    or novelty is not None and (not _valid_content_hash(novelty) or not _valid_content_hash(content_hash))
                    or content_hash is not None and not _valid_content_hash(content_hash)):
                raise ValueError("Invalid assembly receipt proof")
        elif coverage is not None or novelty is not None or content_hash is not None:
            raise ValueError("Assembly receipt proof requires a recipe")
        prepared.append((article, position, recipe, encoded_evidence, ids, hashes,
                         assembly_recipe, coverage, novelty, content_hash))
    if len({row[1] for row in prepared}) != len(prepared):
        raise ValueError("Final delivery contains duplicate positions")
    for article, position, recipe, evidence, ids, hashes, assembly_recipe, coverage, novelty, content_hash in prepared:
        # Disabled S8 retains compatibility with the existing S5/S7 schema.
        extra_columns = ",assembly_recipe,coverage_key,novelty_key,assembly_content_hash" if assembly_recipe else ""
        extra_values = ",%s,%s,%s,%s" if assembly_recipe else ""
        conn.execute("""INSERT INTO public.reader_delivery_receipts
          (user_id,feed_request_id,article_id,generation,revision,article_revision,intent_ids,
           learning_revision,ranking_recipe,final_position,evidence_stamp,intent_semantic_hashes"""
          + extra_columns + ") VALUES (%s,%s,%s,%s,%s,%s,%s::jsonb,%s,%s,%s,%s::jsonb,%s::jsonb"
          + extra_values + ")\n" + """
          ON CONFLICT DO NOTHING""",
          (user_id, request_id, article["id"], snapshot["generation"], snapshot["revision"],
           str(article.get("understanding_revision") or article.get("content_version") or "unknown"),
           json.dumps(ids), snapshot["learning_revision"], recipe, position, evidence, json.dumps(hashes))
          + ((assembly_recipe, coverage, novelty, content_hash) if assembly_recipe else ()))
    # Per-user cleanup is bounded by that user's receipt volume, not a global request-path scan.
    conn.execute("DELETE FROM public.reader_delivery_receipts WHERE user_id=%s AND created_at < now()-interval '30 days'", (user_id,))


def decayed(weight, updated_at, now):
    seconds = max(0.0, (now - updated_at).total_seconds())
    return weight * 0.5 ** (seconds / (30 * 86400))


def load_learned_weights(conn, user_id, snapshot, *, as_of=None):
    """Return bounded, decayed weights only for the current meaning of each
    intent, folded with two passive (non-explicit) S10 D signals for
    currently active intents -- a repeated-impression discount and a net
    qualified-read/quick-back engagement term -- either of which can apply
    even to an intent with no explicit-feedback row at all. This is the
    single seam both S5 direct-serve (adjust_candidates) and S7
    (ranking_service) read, so passive signals reach both consumers without
    ever writing to reader_learned_signals itself (see this module's
    docstring: passive telemetry never rewrites S5 taste)."""
    rows = conn.execute("""SELECT intent_id,semantic_hash,weight,updated_at FROM public.reader_learned_signals
      WHERE user_id=%s AND generation=%s""", (user_id, snapshot["generation"])).fetchall()
    now = as_of or datetime.now(timezone.utc)
    semantics = _intent_semantics(snapshot, now)
    weights = {}
    for row in rows:
        identity = str(row["intent_id"])
        weight = row["weight"]
        if not row.get("semantic_hash") or row["semantic_hash"] != semantics.get(identity):
            continue
        if isinstance(weight, bool) or not isinstance(weight, (int, float)) or not math.isfinite(weight):
            continue
        weights[identity] = decayed(max(-1.0, min(0.8, weight)), row["updated_at"], now)
    exposure = load_topic_exposure(conn, user_id)
    engagement = load_topic_engagement(conn, user_id)
    for identity in semantics:
        passive = engagement.get(identity, 0.0) - _reward.impression_discount(exposure.get(identity, 0))
        if passive:
            weights[identity] = weights.get(identity, 0.0) + passive
    return weights


def adjust_candidates(conn, user_id, snapshot, articles):
    weights = load_learned_weights(conn, user_id, snapshot)
    # The retrieval budget and interleaving stay intact. Stable reordering within the first
    # attributed intent changes preference while preserving cross-interest opportunities.
    groups = {}
    order = []
    for a in articles:
        key = next(iter(a.get("_reader_intent_ids", [])), "general")
        if key not in groups:
            groups[key] = []
            order.append(key)
        ids = a.get("_reader_intent_ids", [])
        delta = sum(weights.get(i, 0) for i in ids) / max(1, len(ids))
        a["_reader_score"] = float(a.get("_reader_score", 0.5)) + max(-0.5, min(0.25, delta))
        groups[key].append(a)
    for values in groups.values():
        values.sort(key=lambda a: -a["_reader_score"])
    out = []
    # One opportunity per nonempty interest first, then weighted fair scheduling.
    # Learning changes later allocation, never removes an explicit interest's floor.
    priorities = {i["id"]: i["priority"] for i in snapshot["profile"]["intents"]}
    effective = {key: max(0.1, priorities.get(key, 1) * (1 + weights.get(key, 0))) for key in order}
    served = {key: 0 for key in order}
    for key in order:
        if groups[key]:
            out.append(groups[key].pop(0))
            served[key] += 1
    while any(groups.values()):
        key = min((k for k in order if groups[k]), key=lambda k: (served[k] / effective[k], order.index(k)))
        out.append(groups[key].pop(0))
        served[key] += 1
    return out


def submit_feedback(conn, user_id, payload):
    from .reader_repository import load_reader, publication_guard, mutate_reader, _invalidate
    from .reader_integration import host
    article_id = str(uuid.UUID(str(payload.get("article_id"))))
    event_id = str(uuid.UUID(str(payload.get("event_id") or payload.get("operation_id"))))
    generation = payload.get("base_generation", payload.get("reader_generation"))
    if type(generation) is not int:
        raise ValueError("reader_generation and stable event_id are required")
    action = payload.get("action")
    if action not in {*DELTAS, "already_knew", "hide_source"}:
        raise ValueError("Unsupported feedback action")
    digest = hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    snapshot = load_reader(conn, user_id)
    with publication_guard(conn, user_id, snapshot):
        conn.execute("DELETE FROM public.reader_feedback_events WHERE user_id=%s AND created_at < now()-interval '30 days'", (user_id,))
        old = conn.execute("SELECT * FROM public.reader_feedback_events WHERE user_id=%s AND event_id=%s",
                           (user_id, event_id)).fetchone()
        if old:
            if old["request_hash"] != digest:
                raise ValueError("event_id was already used for another request")
            return old["result"]
        if snapshot["generation"] != generation:
            from .reader_repository import ReaderConflict
            raise ReaderConflict("reader_reset", snapshot)
        article = conn.execute("SELECT id,url FROM public.articles WHERE id=%s", (article_id,)).fetchone()
        if not article:
            raise ValueError("Article not found")
        receipt = None
        if payload.get("feed_request_id"):
            receipt = conn.execute("""SELECT intent_ids,intent_semantic_hashes FROM public.reader_delivery_receipts
              WHERE user_id=%s AND feed_request_id=%s AND article_id=%s AND generation=%s
                AND created_at > now()-interval '30 days'""",
              (user_id, str(uuid.UUID(payload["feed_request_id"])), article_id, generation)).fetchone()
        semantics = _intent_semantics(snapshot, datetime.now(timezone.utc))
        proof = receipt.get("intent_semantic_hashes", {}) if receipt else {}
        receipt_ids = receipt.get("intent_ids", []) if receipt else []
        ids = sorted({i for i in receipt_ids if isinstance(i, str) and i in semantics
                      and isinstance(proof, dict) and proof.get(i) == semantics[i]})
        # S10 C: route through the shared reward() rather than a bare dict
        # lookup -- currently equivalent for these six actions (reward()'s own
        # DELTAS.get(action, 0.0) already returns 0 for already_knew/hide_source,
        # same as the prior DELTAS.get(action, 0)), but this is now the one
        # call site any future implicit term also flows through.
        delta = _reward.reward(action) / max(1, len(ids))
        # Article/source controls without a taste delta do not rewrite learned signals.
        learned_ids = ids if delta else []
        recipe_hash = _reward.reward_recipe_hash()
        for intent_id in learned_ids:
            conn.execute("""INSERT INTO public.reader_learned_signals
              (user_id,intent_id,generation,weight,semantic_hash,reward_recipe_hash) VALUES (%s,%s,%s,%s,%s,%s)
              ON CONFLICT(user_id,intent_id) DO UPDATE SET weight=GREATEST(-1,LEAST(0.8,
                CASE WHEN reader_learned_signals.generation=EXCLUDED.generation
                  AND reader_learned_signals.semantic_hash=EXCLUDED.semantic_hash
                THEN reader_learned_signals.weight * power(0.5,
                  GREATEST(0,extract(epoch FROM (now()-reader_learned_signals.updated_at)))/(30*86400))
                ELSE 0 END + EXCLUDED.weight)), generation=EXCLUDED.generation,
                semantic_hash=EXCLUDED.semantic_hash,reward_recipe_hash=EXCLUDED.reward_recipe_hash,updated_at=now()""",
              (user_id, intent_id, generation, delta, semantics[intent_id], recipe_hash))
        if action in {"not_relevant", "already_knew", "hide_source"}:
            policies = list(snapshot["profile"]["policies"])
            kind = "publisher" if action == "hide_source" else "article"
            value = host(article["url"]) if kind == "publisher" else article_id
            if not value:
                raise ValueError("Publisher identity unavailable; cannot claim the source was blocked")
            if not any(p["kind"] == kind and p["value"] == value for p in policies):
                policies.append({"id": str(uuid.uuid5(uuid.UUID(event_id), "policy")), "kind": kind, "value": value})
                mutate_reader(conn, user_id, {"operation_id": event_id,
                    "base_generation": snapshot["generation"], "base_revision": snapshot["revision"],
                    "patch": {"policies": policies}})
        conn.execute("UPDATE public.reader_profiles SET learning_revision=learning_revision+1 WHERE user_id=%s", (user_id,))
        _invalidate(conn, user_id)
        result = {"status": "ok", "action": action, "signals_adjusted": len(learned_ids), "attributed": receipt is not None}
        conn.execute("""INSERT INTO public.reader_feedback_events(user_id,event_id,generation,request_hash,result)
          VALUES (%s,%s,%s,%s,%s::jsonb)""", (user_id, event_id, generation, digest, json.dumps(result)))
        return result


def _confirmed_intent_ids(delivered: dict) -> list[str]:
    """The receipt's confirmed intent_ids, defensively filtered. Shared by
    every S10 D passive-signal call site so they all trust the same shape."""
    intent_ids = delivered.get("intent_ids")
    if not isinstance(intent_ids, list):
        return []
    return [i for i in intent_ids[:24] if isinstance(i, str)]


def ingest_events(conn, user_id, payload):
    """Validated acknowledged batches. Invalid events cannot poison the transaction."""
    events = payload.get("events")
    if not isinstance(events, list) or not 1 <= len(events) <= 100:
        raise ValueError("Events must be 1–100 items")
    accepted, rejected, inserted = [], [], 0
    # Explicit controls have their own attributed, idempotent route. Do not create
    # a second non-equivalent learning writer through telemetry.
    allowed = {"impression", "tap", "read", "skip"}
    with conn.transaction():
        from . import assembly_repository
        potential_read = any(isinstance(event, dict) and event.get("type") == "read"
                             and event.get("feed_request_id") and event.get("event_id")
                             and event.get("position") is not None
                             and _valid_content_hash(event.get("read_content_hash")) for event in events)
        assembly_available = potential_read and assembly_repository.available(conn)
        reader = None
        if assembly_available:
            # Same lock as publication/reset, acquired BEFORE any article/FK
            # writes. Revision increments therefore serialize in commit order.
            from .reader_repository import _load_locked
            reader = _load_locked(conn, user_id, False)
        for index, event in enumerate(events):
            try:
                if not isinstance(event, dict) or event.get("type") not in allowed:
                    raise ValueError("invalid type")
                article_id = str(uuid.UUID(str(event.get("article_id"))))
                client_id = str(uuid.UUID(str(event["event_id"]))) if event.get("event_id") else None
                receipt = str(uuid.UUID(str(event["feed_request_id"]))) if event.get("feed_request_id") else None
                duration, position = event.get("duration_seconds"), event.get("position")
                if duration is not None and (type(duration) is not int or not 0 <= duration <= 86400):
                    raise ValueError("invalid duration")
                if position is not None and (type(position) is not int or not 0 <= position <= 10000):
                    raise ValueError("invalid position")
            except (ValueError, TypeError, KeyError):
                rejected.append(index)
                continue
            delivered = None
            if receipt:
                # S10 D: intent_ids is fetched unconditionally (not gated on
                # assembly_available) so a genuine impression can bump the
                # per-topic exposure counter even when S8 assembly is off.
                extra = ",intent_ids"
                extra += ",generation,assembly_recipe,coverage_key,novelty_key,assembly_content_hash" if assembly_available else ""
                delivered = conn.execute("SELECT final_position" + extra + """ FROM public.reader_delivery_receipts
                  WHERE user_id=%s AND feed_request_id=%s AND article_id=%s
                    AND created_at > now()-interval '30 days'""", (user_id, receipt, article_id)).fetchone()
                if not delivered or (position is not None and delivered.get("final_position") is not None
                                     and position != delivered["final_position"]):
                    rejected.append(index)
                    continue
            # INSERT SELECT avoids an FK error for expired/unknown article IDs.
            row = conn.execute("""INSERT INTO public.reading_events
              (user_id,article_id,event_type,duration_seconds,feed_request_id,position_in_feed,client_event_id)
              SELECT %s,a.id,%s,%s,%s,%s,%s FROM public.articles a WHERE a.id=%s
                AND (%s::uuid IS NULL OR EXISTS (SELECT 1 FROM public.reader_delivery_receipts r
                  WHERE r.user_id=%s AND r.feed_request_id=%s AND r.article_id=a.id
                    AND r.created_at > now()-interval '30 days'))
              ON CONFLICT DO NOTHING RETURNING id""",
              (user_id, event["type"], duration, receipt, position, client_id, article_id,
               receipt, user_id, receipt)).fetchone()
            inserted += int(row is not None)
            if (row is not None and event["type"] == "read" and reader and delivered
                    and position is not None and position == delivered.get("final_position")
                    and _valid_content_hash(event.get("read_content_hash"))
                    and event["read_content_hash"] == delivered.get("assembly_content_hash")):
                assembly_repository.acknowledge_read(conn, user_id, reader["generation"], receipt,
                    article_id, client_id, delivered)
            # S10 D: a genuine, newly-inserted impression bumps the exposure
            # counter for every intent this article was confirmed against.
            # Only ever a discount downstream (reward.impression_discount),
            # never a positive term -- an impression is not engagement.
            if row is not None and event["type"] == "impression" and delivered:
                for intent_id in _confirmed_intent_ids(delivered):
                    _bump_topic_exposure(conn, user_id, intent_id)
            # S10 D: passive engagement, folded only at read time into
            # load_learned_weights -- never a write to reader_learned_signals
            # itself (see this module's docstring). A qualified read (the
            # client only sends "read" past its own dwell floor, and only
            # sets read_content_hash for a verified native-body view) nudges
            # this topic up a little; a quick-back (opened, abandoned within
            # seconds, reported as "skip") nudges it down a little.
            if row is not None and delivered:
                if event["type"] == "read" and _valid_content_hash(event.get("read_content_hash")):
                    delta = _reward.reward(None, qualified_read=True)
                elif event["type"] == "skip":
                    delta = _reward.reward(None, quick_back=True)
                else:
                    delta = 0.0
                if delta:
                    for intent_id in _confirmed_intent_ids(delivered):
                        bump_topic_engagement(conn, user_id, intent_id, delta)
            accepted.append(client_id if client_id else index)
    return {"inserted": inserted, "acknowledged": accepted, "rejected_indices": rejected}


def _bump_topic_exposure(conn, user_id, topic_key: str) -> None:
    """Bounded per-(user, topic) impression counter, evolving 14-day window.
    Best-effort: never raise for a missing table (pre-migration database) and
    never fail the caller's impression insert over a discount side effect."""
    try:
        conn.execute("""
            INSERT INTO public.reader_topic_exposure (user_id, topic_key, count, window_start, updated_at)
            VALUES (%s, %s, 1, now(), now())
            ON CONFLICT (user_id, topic_key) DO UPDATE SET
                count = CASE WHEN reader_topic_exposure.window_start < now() - interval '14 days'
                             THEN 1 ELSE reader_topic_exposure.count + 1 END,
                window_start = CASE WHEN reader_topic_exposure.window_start < now() - interval '14 days'
                                    THEN now() ELSE reader_topic_exposure.window_start END,
                updated_at = now()
            """, (user_id, topic_key))
    except Exception:
        logger.exception("Failed to bump topic exposure for user %s topic %s", user_id, topic_key)


def load_topic_exposure(conn, user_id) -> dict[str, int]:
    """This reader's current per-topic impression counts, keyed by intent_id.
    Best-effort: an unmigrated database (table absent) yields no discount,
    never an error -- exposure discounting is an optimization, not a
    correctness requirement of learning."""
    try:
        rows = conn.execute(
            "SELECT topic_key, count FROM public.reader_topic_exposure WHERE user_id=%s", (user_id,)
        ).fetchall()
    except Exception:
        logger.exception("Failed to load topic exposure for user %s", user_id)
        return {}
    return {str(row["topic_key"]): int(row["count"]) for row in rows
            if isinstance(row.get("count"), int) and row["count"] >= 0}


def bump_topic_engagement(conn, user_id, topic_key: str, delta: float) -> None:
    """Passive (non-explicit) engagement, decayed before accumulation exactly
    like the explicit reader_learned_signals UPSERT, but into a SEPARATE
    table -- this must never become a second writer to reader_learned_signals
    itself (see this module's docstring). Best-effort and a no-op for delta=0."""
    if not delta or not math.isfinite(delta):
        return
    try:
        conn.execute("""
            INSERT INTO public.reader_topic_engagement (user_id, topic_key, net_reward, updated_at)
            VALUES (%s, %s, %s, now())
            ON CONFLICT (user_id, topic_key) DO UPDATE SET
                net_reward = GREATEST(%s, LEAST(%s,
                    reader_topic_engagement.net_reward * power(0.5,
                        GREATEST(0, extract(epoch FROM (now() - reader_topic_engagement.updated_at))) / (30*86400))
                    + EXCLUDED.net_reward)),
                updated_at = now()
            """, (user_id, topic_key, delta, _reward.ADJUSTMENT_FLOOR, _reward.ADJUSTMENT_CEILING))
    except Exception:
        logger.exception("Failed to bump topic engagement for user %s topic %s", user_id, topic_key)


def load_topic_engagement(conn, user_id) -> dict[str, float]:
    """This reader's current passive net engagement per topic, keyed by
    intent_id, already decayed at read time. Best-effort: an unmigrated
    database yields no adjustment, never an error."""
    try:
        rows = conn.execute(
            "SELECT topic_key, net_reward, updated_at FROM public.reader_topic_engagement WHERE user_id=%s",
            (user_id,),
        ).fetchall()
    except Exception:
        logger.exception("Failed to load topic engagement for user %s", user_id)
        return {}
    now = datetime.now(timezone.utc)
    out = {}
    for row in rows:
        value = row.get("net_reward")
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
            continue
        try:
            out[str(row["topic_key"])] = decayed(value, row.get("updated_at"), now)
        except TypeError:
            continue
    return out
