"""S8 evidence and acknowledged-history store; no provider work or implicit schema install.

hydrate() reads a coherent snapshot. validate() MUST run inside S6's publication
guard, after its sorted union article locks; those locks also fence absent S3
memberships because every S3 membership writer locks its parent article first.
Reader/history writers share the canonical user -> reader lock. Never acquire
the S3 clustering advisory lock from delivery, or infer serializability from RR.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

from psycopg.types.json import Jsonb

from .reader_contract import canonical_hash


class AssemblyStoreError(ValueError):
    pass


def install_schema(conn):
    with conn.transaction():
        conn.execute("SELECT pg_advisory_xact_lock(73405801)")
        conn.execute(Path(__file__).with_name("assembly_schema.sql").read_text())


def available(conn):
    row = conn.execute("SELECT to_regclass('public.assembly_control') AS relation").fetchone()
    return bool(row and row["relation"])


def control(conn, *, lock=False):
    if not available(conn):
        return None
    return conn.execute("SELECT * FROM public.assembly_control WHERE singleton"
                        + (" FOR SHARE" if lock else "")).fetchone()


def configure(conn, recipe, *, approved=False, serving=False):
    from .assembly_contract import validate_recipe
    if type(approved) is not bool or type(serving) is not bool:
        raise AssemblyStoreError("invalid_assembly_flag")
    recipe = validate_recipe(recipe)
    if serving and not approved:
        raise AssemblyStoreError("assembly_not_approved")
    with conn.transaction():
        conn.execute("SET LOCAL lock_timeout = '100ms'")
        return conn.execute("""UPDATE public.assembly_control SET epoch=epoch+1,
          recipe=%s,recipe_hash=%s,approved=%s,serving=%s,updated_at=clock_timestamp()
          WHERE singleton RETURNING *""",
          (Jsonb(recipe), canonical_hash(recipe), approved, serving)).fetchone()


def _state(conn, recipe, *, lock=False):
    from .assembly_contract import validate_recipe
    recipe = validate_recipe(recipe)
    row = control(conn, lock=lock)
    if not row or not row["approved"] or not row["serving"]:
        raise AssemblyStoreError("assembly_unavailable")
    if row["recipe_hash"] != canonical_hash(recipe) or row["recipe"] != recipe:
        raise AssemblyStoreError("assembly_recipe_changed")
    return {"epoch": row["epoch"], "recipe_hash": row["recipe_hash"], "recipe": recipe}


def _json(value):
    """Driver UUID/datetime values are explicit, not permissively stringified JSON."""
    from uuid import UUID
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, dict):
        return {key: _json(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json(item) for item in value]
    return value


def candidate_evidence(current, *, membership=None, cluster=None, membership_enabled=False):
    """Project only current supported identity/aboutness and exact content proof.

    This returns potential analysis-content proof, not proof of a viewed body.
    The adapter must match it to the actual S2 native presentation; receipt-backed
    reads must additionally report that displayed content hash. Image, clock and
    membership-version changes never produce a new-content claim.
    """
    from .reader_integration import host
    article = current.get("article") or {}
    article_id = str(current.get("article_id") or article.get("id"))
    unit = "article:" + article_id
    verified = False
    validated = current.get("membership")
    if (membership_enabled and current.get("state") == "ready" and validated and membership
            and cluster and str(validated["cluster_id"]) == str(cluster["id"])
            and validated == membership and cluster["recipe_id"] == current.get("recipe_id")):
        unit = "s3:" + str(current["recipe_id"]) + ":" + str(cluster["id"])
        verified = True
    bundle = current.get("evidence") or {}
    manifest = bundle.get("manifest") or {}
    artifact = manifest.get("artifact") or {}
    novelty = None
    if (bundle.get("sufficient") is True and bundle.get("evidence_tier") == "original_body"
            and manifest.get("analysis_allowed") is True and manifest.get("truncated") is False
            and artifact.get("completeness") == "complete" and artifact.get("text_hash")):
        novelty = canonical_hash({"version": "s8-exact-content-v1", "coverage_key": unit,
                                  "fields": manifest["field_hashes"]})
    return {"coverage_key": unit if verified else None, "identity_verified": verified,
            "publisher_id": host(article.get("url")) or None,
            "topic_ids": (current.get("policy_evidence") or {}).get("topic_ids"),
            "analysis_content_hash": artifact.get("content_hash") if novelty else None,
            "novelty_key": novelty, "known_read": False,
            "membership_stamp": _json({"membership": membership if membership_enabled else None,
                "cluster": {key: cluster[key] for key in ("id", "recipe_id", "version")}
                    if membership_enabled and cluster else None,
                "current_input_hash": current.get("input_hash"),
                "current_recipe": current.get("recipe_id"), "state": current.get("state")})}


def _hydrate(conn, user_id, snapshot, article_ids, recipe, *, as_of, lock=False):
    from .reader_retrieval import _s6_recipe, _s6_hydrate
    from .understanding_repository import load_current_batch
    if as_of.tzinfo is None:
        raise AssemblyStoreError("assembly_time_requires_timezone")
    identifiers = sorted(set(str(value) for value in article_ids))
    if len(identifiers) > 600:
        raise AssemblyStoreError("assembly_article_limit")
    membership_enabled = recipe["s3_membership_enabled"]
    s3_recipe = _s6_recipe(conn)
    recipe_id = s3_recipe["id"] if s3_recipe else None
    current, memberships, clusters = {}, {}, {}
    for start in range(0, len(identifiers), 300):
        chunk = identifiers[start:start + 300]
        if recipe_id:
            current.update(load_current_batch(conn, chunk, recipe_id,
                                             include_membership=membership_enabled))
        else:
            # Ordinary display stays possible without an installed/approved S3.
            # No source-only metadata is upgraded into complete-content proof.
            current.update({identity: {"article_id": identity, "article": row["article"],
                "state": "disabled", "policy_evidence": row["policy"]}
                for identity, row in _s6_hydrate(conn, chunk, None).items()})
    if membership_enabled and recipe_id and identifiers:
        rows = conn.execute("""SELECT * FROM public.story_memberships
          WHERE article_id=ANY(%s::uuid[]) AND recipe_id=%s ORDER BY article_id"""
          + (" FOR SHARE" if lock else ""), (identifiers, recipe_id)).fetchall()
        memberships = {str(row["article_id"]): row for row in rows}
        cluster_ids = sorted({str(row["cluster_id"]) for row in rows})
        if cluster_ids:
            rows = conn.execute("""SELECT id,recipe_id,version FROM public.story_clusters
              WHERE id=ANY(%s::uuid[]) ORDER BY id""" + (" FOR SHARE" if lock else ""),
              (cluster_ids,)).fetchall()
            clusters = {str(row["id"]): row for row in rows}
    candidates = {}
    for identity in identifiers:
        row = current.get(identity)
        if not row or not row.get("article"):
            raise AssemblyStoreError("assembly_article_missing")
        membership = memberships.get(identity)
        candidates[identity] = candidate_evidence(row, membership=membership,
            cluster=clusters.get(str(membership["cluster_id"])) if membership else None,
            membership_enabled=membership_enabled)
    # A missing state row is revision zero. Publication's reader row lock fences
    # insertion as well as updates; every acknowledge writer takes that guard.
    history = conn.execute("""SELECT revision FROM public.reader_edition_state
      WHERE user_id=%s AND generation=%s""" + (" FOR SHARE" if lock else ""),
      (user_id, snapshot["generation"])).fetchone()
    keys = sorted({row["novelty_key"] for row in candidates.values() if row["novelty_key"]})
    known = set()
    if keys:
        cutoff = as_of - timedelta(days=recipe["history_retention_days"])
        rows = conn.execute("""SELECT novelty_key FROM public.reader_edition_reads
          WHERE user_id=%s AND generation=%s AND novelty_key=ANY(%s::text[])
            AND acknowledged_at >= %s AND acknowledged_at <= %s""",
          (user_id, snapshot["generation"], keys, cutoff, as_of)).fetchall()
        known = {row["novelty_key"] for row in rows}
    for candidate in candidates.values():
        candidate["known_read"] = candidate["novelty_key"] in known
    return {"user_id": str(user_id), "generation": snapshot["generation"],
            "history_revision": history["revision"] if history else 0,
            "control": _state(conn, recipe, lock=lock), "as_of": as_of.isoformat(),
            "candidates": candidates}


def hydrate(conn, user_id, snapshot, article_ids, recipe, *, as_of=None):
    """Read-only snapshot; caller must supply an idle exclusively owned connection."""
    from .assembly_contract import validate_recipe
    recipe = validate_recipe(recipe)
    if hasattr(conn, "info"):
        from psycopg.pq import TransactionStatus
        if conn.info.transaction_status != TransactionStatus.IDLE:
            raise AssemblyStoreError("assembly_hydration_requires_idle_connection")
    with conn.transaction():
        conn.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
        conn.execute("SET LOCAL statement_timeout = '2000ms'")
        return _hydrate(conn, user_id, snapshot, article_ids, recipe,
                        as_of=as_of or datetime.now(timezone.utc))


def validate(conn, user_id, snapshot, expected):
    """Compare all selection dependencies under the caller's S6 publication fence."""
    from .assembly_contract import validate_recipe
    recipe = validate_recipe(expected["control"]["recipe"])
    if hasattr(conn, "info"):
        from psycopg.pq import TransactionStatus
        if conn.info.transaction_status != TransactionStatus.INTRANS:
            raise AssemblyStoreError("assembly_validation_requires_publication_transaction")
    fresh = _hydrate(conn, user_id, snapshot, expected["candidates"], recipe,
                     as_of=datetime.fromisoformat(expected["as_of"]), lock=True)
    if fresh != expected:
        raise AssemblyStoreError("assembly_dependencies_changed")
    return fresh


def acknowledge_read(conn, user_id, generation, receipt, article_id, event_id, delivered):
    """Called only after a new reading_events insert under the canonical reader guard."""
    if (not event_id or delivered.get("generation") != generation
            or not delivered.get("assembly_recipe") or not delivered.get("novelty_key")
            or not delivered.get("coverage_key")):
        return False
    # Bounded per-account cleanup, never a global request-path history scan.
    conn.execute("""DELETE FROM public.reader_edition_reads WHERE ctid IN (
      SELECT ctid FROM public.reader_edition_reads WHERE user_id=%s
      AND acknowledged_at < clock_timestamp()-interval '30 days'
      ORDER BY acknowledged_at LIMIT 1000)""", (user_id,))
    inserted = conn.execute("""INSERT INTO public.reader_edition_reads
      (user_id,generation,novelty_key,feed_request_id,article_id,client_event_id)
      VALUES(%s,%s,%s,%s,%s,%s) ON CONFLICT DO NOTHING RETURNING novelty_key""",
      (user_id, generation, delivered["novelty_key"], receipt, article_id, event_id)).fetchone()
    if inserted:
        conn.execute("""INSERT INTO public.reader_edition_state(user_id,generation,revision)
          VALUES(%s,%s,1) ON CONFLICT(user_id,generation) DO UPDATE
          SET revision=reader_edition_state.revision+1""", (user_id, generation))
    return inserted is not None
