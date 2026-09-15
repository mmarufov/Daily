"""Transactional S5 authority. Lock order: user, reader, operation, derivatives.

Connections use psycopg dict rows. Every mutation and publication owns an explicit
transaction, including when the application pool uses autocommit. No provider work
may happen inside these transaction contexts. This module never deletes sources.
"""
from __future__ import annotations

import json
import uuid
from contextlib import contextmanager
from pathlib import Path

from psycopg.types.json import Jsonb

from app.services.reader_contract import ReaderMutation, apply_patch, canonical_hash, intent_semantic_hash
from app.services.reader_compiler import import_legacy, legacy_patch, projections


class ReaderConflict(ValueError):
    def __init__(self, code: str, current: dict | None = None):
        self.code, self.current = code, current
        super().__init__(code)


class ReaderNotFound(ValueError):
    pass


def install_schema(conn):
    with conn.transaction():
        conn.execute("SELECT pg_advisory_xact_lock(73405303)")
        conn.execute(Path(__file__).with_name("reader_schema.sql").read_text())


def _snapshot(row: dict) -> dict:
    return {"profile": row["profile"], "revision": row["revision"],
            "learning_revision": row["learning_revision"], "generation": row["generation"],
            "migration_status": row["migration_status"],
            "capabilities": {"typed_patch": True, "reset_learning": True,
                             "reviewed_proposals": True, "undo": False},
            # Canonical/lexical readiness is known here; vector readiness belongs
            # to the compatible-space worker and cannot be inferred from a save.
            "derived_work": "lexical_ready" if row["migration_status"] == "ready" else "needs_review"}


def _user_guard(conn, user_id):
    user = conn.execute("SELECT id FROM public.users WHERE id=%s AND NOT COALESCE(is_deleted,false) FOR SHARE", (user_id,)).fetchone()
    if not user:
        raise ReaderNotFound("reader account does not exist")


def _load_locked(conn, user_id: str, create: bool) -> dict | None:
    _user_guard(conn, user_id)
    if create:
        existing = conn.execute("SELECT user_id FROM public.reader_profiles WHERE user_id=%s", (user_id,)).fetchone()
        if not existing:
            legacy = conn.execute("SELECT interests,ai_profile,user_profile_v2,source_selection_brief FROM public.user_preferences WHERE user_id=%s", (user_id,)).fetchone()
            profile, status, evidence = import_legacy(user_id, legacy)
            conn.execute("""INSERT INTO public.reader_profiles(user_id,profile,projections,migration_status,migration_evidence)
                VALUES(%s,%s,%s,%s,%s) ON CONFLICT(user_id) DO NOTHING""",
                (user_id, Jsonb(profile), Jsonb(projections(profile)), status, Jsonb(evidence)))
    return conn.execute("SELECT * FROM public.reader_profiles WHERE user_id=%s FOR UPDATE", (user_id,)).fetchone()


def load_reader(conn, user_id: str, create: bool = True) -> dict | None:
    with conn.transaction():
        row = _load_locked(conn, user_id, create)
        return _snapshot(row) if row else None


def _receipt(conn, user_id, operation_id):
    return conn.execute("SELECT request_hash,result FROM public.reader_operations WHERE user_id=%s AND operation_id=%s", (user_id, operation_id)).fetchone()


def get_operation(conn, user_id: str, operation_id: str) -> dict | None:
    operation_id = str(uuid.UUID(operation_id))
    with conn.transaction():
        row = _load_locked(conn, user_id, False)
        if not row:
            return None
        receipt = _receipt(conn, user_id, operation_id)
        return {**receipt["result"], "replayed": True, "current": _snapshot(row)} if receipt else None


def _begin_operation(conn, user_id, request, kind):
    command = ReaderMutation.model_validate(request)
    row = _load_locked(conn, user_id, True)
    # Hash the exact supplied JSON representation (canonical key order), not its
    # coerced/default-expanded model: reusing an ID with changed bytes is rejected.
    digest = canonical_hash({"kind": kind, "request": request})
    receipt = _receipt(conn, user_id, command.operation_id)
    if receipt:
        if receipt["request_hash"] != digest:
            raise ReaderConflict("operation_id_reused", _snapshot(row))
        return command, row, digest, {**receipt["result"], "replayed": True, "current": _snapshot(row)}
    if command.base_generation != row["generation"] or command.base_revision != row["revision"]:
        raise ReaderConflict("reader_changed", _snapshot(row))
    return command, row, digest, None


def _save_receipt(conn, user_id, command, digest, kind, row):
    conn.execute("DELETE FROM public.reader_operations WHERE user_id=%s AND created_at < now()-interval '7 days'", (user_id,))
    result = {**_snapshot(row), "operation_id": command.operation_id, "replayed": False}
    conn.execute("""INSERT INTO public.reader_operations(user_id,operation_id,request_hash,kind,result)
        VALUES(%s,%s,%s,%s,%s)""", (user_id, command.operation_id, digest, kind, Jsonb(result)))
    return result


def _invalidate(conn, user_id):
    conn.execute("DELETE FROM public.user_feed_cache WHERE user_id=%s", (user_id,))
    # These tables differ across old installations. Check existence with a bound
    # regclass, then use only this static allowlist; no dynamic user SQL identifiers.
    for table in ("briefing_cache",):
        exists = conn.execute("SELECT to_regclass(%s) AS relation", ("public." + table,)).fetchone()
        if exists and exists["relation"]:
            conn.execute("DELETE FROM public." + table + " WHERE user_id=%s", (user_id,))
    # S7 is an optional additive installation. Invalidate build fences and immutable
    # results within the same reader mutation/reset transaction, never refund spend.
    ranking = conn.execute("SELECT to_regclass(%s) AS relation", ("public.ranking_builds",)).fetchone()
    if ranking and ranking["relation"]:
        from .ranking_repository import invalidate
        invalidate(conn, user_id)


def _write_projection(conn, user_id, profile):
    compiled = projections(profile)
    conn.execute("""INSERT INTO public.user_preferences(user_id,interests,ai_profile,user_profile_v2,source_selection_brief,completed,completed_at)
        VALUES(%s,%s,%s,%s,%s,true,now()) ON CONFLICT(user_id) DO UPDATE SET
        interests=EXCLUDED.interests,ai_profile=EXCLUDED.ai_profile,user_profile_v2=EXCLUDED.user_profile_v2,
        source_selection_brief=EXCLUDED.source_selection_brief,completed=true,
        completed_at=COALESCE(user_preferences.completed_at,now()),updated_at=now()""",
        (user_id, json.dumps(compiled["interests"], ensure_ascii=False), compiled["ai_profile"],
         json.dumps(compiled["user_profile_v2"], ensure_ascii=False), json.dumps(compiled["source_selection_brief"], ensure_ascii=False)))
    return compiled


def _queue(conn, user_id, row, kind):
    conn.execute("""INSERT INTO public.reader_jobs(user_id,generation,revision,kind,payload)
        VALUES(%s,%s,%s,%s,%s) ON CONFLICT(user_id,generation,revision,kind) DO NOTHING""",
        (user_id, row["generation"], row["revision"], kind, Jsonb({})))


def mutate_reader(conn, user_id: str, request: dict) -> dict:
    with conn.transaction():
        command, row, digest, replay = _begin_operation(conn, user_id, request, "patch")
        if replay is not None:
            return replay
        if row["migration_status"] == "needs_review" and not command.confirm_migration:
            raise ReaderConflict("migration_review_required", _snapshot(row))
        profile = apply_patch(row["profile"], command.patch)
        status = "ready" if command.confirm_migration else row["migration_status"]
        if profile != row["profile"] or status != row["migration_status"]:
            before = row["profile"]
            compiled = _write_projection(conn, user_id, profile)
            row = {**row, "profile": profile, "revision": row["revision"] + 1, "migration_status": status}
            conn.execute("""UPDATE public.reader_profiles SET profile=%s,projections=%s,revision=%s,
                migration_status=%s,migration_evidence=CASE WHEN %s='ready' THEN '{}'::jsonb ELSE migration_evidence END,
                updated_at=now() WHERE user_id=%s""", (Jsonb(profile), Jsonb(compiled), row["revision"], status, status, user_id))
            _invalidate(conn, user_id)
            before_queries = {i["id"]: intent_semantic_hash(i) for i in before["intents"]}
            after_queries = {i["id"]: intent_semantic_hash(i) for i in profile["intents"]}
            if before_queries != after_queries:
                _queue(conn, user_id, row, "embeddings")
                _queue(conn, user_id, row, "source_reconcile")
            elif before["policies"] != profile["policies"] or before["languages"] != profile["languages"]:
                _queue(conn, user_id, row, "source_reconcile")
        return _save_receipt(conn, user_id, command, digest, "patch", row)


def reset_learning(conn, user_id: str, request: dict, *, cleanup=None) -> dict:
    with conn.transaction():
        command, row, digest, replay = _begin_operation(conn, user_id, request, "reset_learning")
        if replay is not None:
            return replay
        if command.patch or command.confirm_migration:
            raise ValueError("reset-learning does not accept a profile patch")
        for table in ("user_feedback_signals", "reading_events", "interest_suggestions"):
            exists = conn.execute("SELECT to_regclass(%s) AS relation", ("public." + table,)).fetchone()
            if exists and exists["relation"]:
                # Cast the COLUMN to text rather than the parameter to uuid:
                # correct whether user_id is uuid (reading_events,
                # interest_suggestions, and user_feedback_signals on a
                # migrated database) or still the pre-S10-A3 bare text column
                # (an unmigrated user_feedback_signals with orphaned rows).
                # One cast strategy for all three tables, no per-table branch.
                conn.execute("DELETE FROM public." + table + " WHERE user_id::text=%s", (str(user_id),))
        conn.execute("UPDATE public.user_preferences SET behavior_cache=NULL WHERE user_id=%s", (user_id,))
        conn.execute("DELETE FROM public.reader_jobs WHERE user_id=%s", (user_id,))
        if cleanup:
            cleanup(conn, user_id)
        row = {**row, "generation": row["generation"] + 1, "learning_revision": row["learning_revision"] + 1}
        conn.execute("""UPDATE public.reader_profiles SET generation=%s,learning_revision=%s,updated_at=now()
            WHERE user_id=%s""", (row["generation"], row["learning_revision"], user_id))
        _invalidate(conn, user_id)
        _queue(conn, user_id, row, "embeddings")
        return _save_receipt(conn, user_id, command, digest, "reset_learning", row)


@contextmanager
def publication_guard(conn, user_id: str, snapshot: dict):
    """Hold the mutation lock through the caller's writes. Never await inside."""
    with conn.transaction():
        row = _load_locked(conn, user_id, False)
        if not row or not all(row[key] == snapshot[key] for key in ("generation", "revision", "learning_revision")):
            raise ReaderConflict("reader_changed", _snapshot(row) if row else None)
        yield _snapshot(row)
