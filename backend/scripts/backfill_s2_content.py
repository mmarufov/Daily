#!/usr/bin/env python3
"""Resumable migration of legacy Daily articles into the S2 content contract.

Dry-run is the default and performs no schema or data writes.  ``--apply``:

* installs the additive S2 schema;
* preserves ambiguous legacy ``articles.content`` as non-display
  ``legacy_unverified`` analysis context;
* creates the durable origin-extraction job without treating that text as a
  publisher-owned full body;
* quarantines pre-provenance images as ``legacy_unknown`` when the deployed
  schema has the image provenance columns.

Each batch is one transaction and rows are claimed with ``FOR UPDATE SKIP
LOCKED``.  Successful rows stop matching the selection query, making reruns
idempotent and safe after an interruption.  Database credentials are accepted
only through an environment variable, never a command-line argument.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import psycopg
from psycopg.rows import dict_row

from app.services.article_content import (
    EXTRACTOR_VERSION,
    ensure_article_content_schema,
    record_content_artifact,
    register_ingested_article,
)


CONSTRAINTS_TO_VALIDATE = (
    ("articles", "articles_presentation_mode_check"),
    ("articles", "articles_body_state_check"),
    ("articles", "articles_reader_pointer_consistency_check"),
    ("articles", "articles_display_artifact_fk"),
    ("articles", "articles_analysis_artifact_fk"),
    ("articles", "articles_display_artifact_owner_fk_v1"),
    ("articles", "articles_analysis_artifact_owner_fk_v1"),
    ("article_content_artifacts", "article_content_artifact_displayable_v3_check"),
    ("article_content_artifacts", "article_content_artifact_version_check"),
    ("article_content_jobs", "article_content_jobs_lease_check"),
    ("article_content_jobs", "article_content_jobs_outcome_v2_check"),
    ("article_content_jobs", "article_content_job_counters_check"),
    ("article_source_policies", "article_source_policy_allowed_kinds_check"),
    ("article_source_policies", "article_source_policy_version_check"),
    ("article_source_policies", "article_source_policy_rights_v1_check"),
    ("article_source_policies", "article_source_policy_feed_scope_v1_check"),
    ("articles", "articles_image_origin_check"),
)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--database-env",
        default="DATABASE_URL",
        help="environment variable containing the PostgreSQL URL (default: DATABASE_URL)",
    )
    parser.add_argument("--batch-size", type=int, default=250)
    parser.add_argument(
        "--max-rows",
        type=int,
        help="stop after this many rows (useful for a production canary)",
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="perform the migration; omission is a strictly read-only dry run",
    )
    parser.add_argument(
        "--validate-constraints",
        action="store_true",
        help="after backfill, validate S2 NOT VALID constraints (may take locks)",
    )
    return parser


def _columns(conn) -> set[str]:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT column_name
            FROM information_schema.columns
            WHERE table_schema = 'public' AND table_name = 'articles'
            """
        )
        return {row["column_name"] for row in cur.fetchall()}


def _table_exists(conn, name: str) -> bool:
    with conn.cursor() as cur:
        cur.execute("SELECT to_regclass(%s) IS NOT NULL AS present", (f"public.{name}",))
        return bool(cur.fetchone()["present"])


def _dry_run_counts(conn) -> dict[str, int | bool]:
    columns = _columns(conn)
    jobs_exist = _table_exists(conn, "article_content_jobs")
    artifacts_exist = _table_exists(conn, "article_content_artifacts")
    has_display_pointer = "display_content_artifact_id" in columns
    has_image_origin = "image_origin" in columns

    with conn.cursor() as cur:
        if "content" in columns:
            display_clause = (
                "AND display_content_artifact_id IS NULL" if has_display_pointer else ""
            )
            cur.execute(
                f"SELECT count(*) AS count FROM public.articles "
                f"WHERE NULLIF(btrim(content), '') IS NOT NULL {display_clause}"
            )
            legacy_content = int(cur.fetchone()["count"])
        else:
            legacy_content = 0

        if "image_url" in columns:
            image_clause = (
                "AND image_origin IS NULL" if has_image_origin else ""
            )
            cur.execute(
                f"SELECT count(*) AS count FROM public.articles "
                f"WHERE NULLIF(btrim(image_url), '') IS NOT NULL {image_clause}"
            )
            legacy_images = int(cur.fetchone()["count"])
        else:
            legacy_images = 0

        if jobs_exist:
            cur.execute(
                "SELECT count(*) AS count FROM public.articles a "
                "LEFT JOIN public.article_content_jobs j ON j.article_id = a.id "
                "WHERE j.article_id IS NULL"
            )
            missing_jobs = int(cur.fetchone()["count"])
        else:
            cur.execute("SELECT count(*) AS count FROM public.articles")
            missing_jobs = int(cur.fetchone()["count"])

        if artifacts_exist and has_display_pointer:
            cur.execute(
                "SELECT count(DISTINCT a.id) AS count "
                "FROM public.articles a "
                "JOIN public.article_content_artifacts ca ON ca.article_id = a.id "
                "WHERE ca.kind = 'origin_extract' AND ca.is_current = true "
                "AND ca.extractor_version < %s",
                (EXTRACTOR_VERSION,),
            )
            outdated_origin = int(cur.fetchone()["count"])
        else:
            outdated_origin = 0

    return {
        "article_content_schema_present": jobs_exist and artifacts_exist,
        "legacy_content_rows": legacy_content,
        "legacy_image_rows": legacy_images,
        "missing_job_rows": missing_jobs,
        "outdated_origin_rows": outdated_origin,
    }


def _select_batch(conn, limit: int, *, image_provenance: bool) -> list[dict]:
    legacy_image_predicate = (
        "OR (NULLIF(btrim(a.image_url), '') IS NOT NULL AND a.image_origin IS NULL)"
        if image_provenance
        else ""
    )
    with conn.cursor() as cur:
        cur.execute(
            f"""
            SELECT a.id, a.url,
                   CASE
                     WHEN a.display_content_artifact_id IS NULL
                      AND NULLIF(btrim(a.content), '') IS NOT NULL
                      AND NOT EXISTS (
                          SELECT 1 FROM public.article_content_artifacts ca
                          WHERE ca.article_id = a.id
                            AND ca.kind = 'legacy_unverified'
                            AND ca.is_current = true
                      )
                     THEN a.content
                     ELSE NULL
                   END AS legacy_content,
                   NULLIF(btrim(a.image_url), '') AS legacy_image_url,
                   EXISTS (
                       SELECT 1 FROM public.article_content_artifacts old_origin
                       WHERE old_origin.article_id = a.id
                         AND old_origin.kind = 'origin_extract'
                         AND old_origin.is_current = true
                         AND old_origin.extractor_version < %s
                   ) AS outdated_origin
            FROM public.articles a
            LEFT JOIN public.article_content_jobs j ON j.article_id = a.id
            WHERE j.article_id IS NULL
               OR (
                   a.display_content_artifact_id IS NULL
                   AND NULLIF(btrim(a.content), '') IS NOT NULL
                   AND NOT EXISTS (
                       SELECT 1 FROM public.article_content_artifacts ca
                       WHERE ca.article_id = a.id
                         AND ca.kind = 'legacy_unverified'
                         AND ca.is_current = true
                   )
               )
               {legacy_image_predicate}
               OR EXISTS (
                   SELECT 1 FROM public.article_content_artifacts old_origin
                   WHERE old_origin.article_id = a.id
                     AND old_origin.kind = 'origin_extract'
                     AND old_origin.is_current = true
                     AND old_origin.extractor_version < %s
               )
            ORDER BY a.id
            FOR UPDATE OF a SKIP LOCKED
            LIMIT %s
            """,
            (EXTRACTOR_VERSION, EXTRACTOR_VERSION, limit),
        )
        return [dict(row) for row in cur.fetchall()]


def _empty_migration_counts() -> dict[str, int]:
    """Return the complete, stable counter schema used by batches and totals."""
    return {
        "rows": 0,
        "legacy_content": 0,
        "jobs": 0,
        "legacy_images": 0,
        "outdated_origins": 0,
    }


def _accumulate_counts(total: dict[str, int], batch: dict[str, int]) -> None:
    """Merge a committed batch without letting a new counter crash the runner."""
    for key, value in batch.items():
        total[key] = total.get(key, 0) + value


def _apply_batch(conn, limit: int, *, image_provenance: bool) -> dict[str, int]:
    counts = _empty_migration_counts()
    with conn.transaction():
        rows = _select_batch(conn, limit, image_provenance=image_provenance)
        for row in rows:
            counts["rows"] += 1
            if row.get("outdated_origin"):
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        UPDATE public.article_content_artifacts
                        SET is_current = false, displayable = false
                        WHERE article_id = %s AND kind = 'origin_extract'
                          AND is_current = true AND extractor_version < %s
                        """,
                        (row["id"], EXTRACTOR_VERSION),
                    )
                    if cur.rowcount:
                        cur.execute(
                            "UPDATE public.articles "
                            "SET content_version = content_version + 1 WHERE id = %s",
                            (row["id"],),
                        )
                        counts["outdated_origins"] += 1
            if row["legacy_content"]:
                artifact_id = record_content_artifact(
                    conn,
                    row["id"],
                    kind="legacy_unverified",
                    text=row["legacy_content"],
                    origin_url=row["url"] or "urn:daily:legacy",
                    method="s2_legacy_backfill",
                    completeness="unknown",
                    confidence=0.0,
                )
                if artifact_id is None:
                    raise RuntimeError(f"failed to preserve legacy content for {row['id']}")
                counts["legacy_content"] += 1

            # Idempotent ON CONFLICT semantics live in the authoritative API.
            register_ingested_article(
                conn,
                row["id"],
                canonical_url=row["url"] or "",
                feed_content=None,
            )
            counts["jobs"] += 1

            if image_provenance and row["legacy_image_url"]:
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        UPDATE public.articles
                        SET image_origin = 'legacy_unknown',
                            image_source_url = NULL,
                            image_attribution = NULL,
                            image_is_illustrative = true,
                            enrichment_completed = false,
                            enrichment_attempts = 0
                        WHERE id = %s AND image_origin IS NULL
                        """,
                        (row["id"],),
                    )
                    counts["legacy_images"] += cur.rowcount
        return counts


def _validate_constraints(conn) -> None:
    with conn.transaction():
        with conn.cursor() as cur:
            for table, constraint in CONSTRAINTS_TO_VALIDATE:
                cur.execute(
                    "SELECT convalidated FROM pg_constraint "
                    "WHERE conname = %s AND conrelid = %s::regclass",
                    (constraint, f"public.{table}"),
                )
                row = cur.fetchone()
                if row and not row["convalidated"]:
                    # Names are constants controlled by this file.
                    cur.execute(
                        f'ALTER TABLE public."{table}" '
                        f'VALIDATE CONSTRAINT "{constraint}"'
                    )


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if args.batch_size < 1 or args.batch_size > 5_000:
        print("error: --batch-size must be between 1 and 5000", file=sys.stderr)
        return 2
    if args.max_rows is not None and args.max_rows < 1:
        print("error: --max-rows must be positive", file=sys.stderr)
        return 2
    if args.validate_constraints and not args.apply:
        print("error: --validate-constraints requires --apply", file=sys.stderr)
        return 2
    database_url = os.getenv(args.database_env)
    if not database_url:
        print(f"error: {args.database_env} is not set", file=sys.stderr)
        return 2

    try:
        with psycopg.connect(database_url, autocommit=True, row_factory=dict_row) as conn:
            if not _table_exists(conn, "articles"):
                raise RuntimeError("public.articles does not exist")
            before = _dry_run_counts(conn)
            print(json.dumps({"dry_run": not args.apply, "before": before}, indent=2))
            if not args.apply:
                print("No changes made. Re-run with --apply after reviewing these counts.")
                return 0

            ensure_article_content_schema(conn)
            columns = _columns(conn)
            image_provenance = {
                "image_origin",
                "image_source_url",
                "image_attribution",
                "image_is_illustrative",
            }.issubset(columns)
            total = _empty_migration_counts()
            while args.max_rows is None or total["rows"] < args.max_rows:
                batch_limit = args.batch_size
                if args.max_rows is not None:
                    batch_limit = min(batch_limit, args.max_rows - total["rows"])
                batch = _apply_batch(
                    conn, batch_limit, image_provenance=image_provenance
                )
                _accumulate_counts(total, batch)
                print(json.dumps({"batch": batch, "cumulative": total}))
                if batch["rows"] == 0:
                    break

            if args.validate_constraints:
                _validate_constraints(conn)
            after = _dry_run_counts(conn)
            print(
                json.dumps(
                    {
                        "applied": True,
                        "migrated": total,
                        "after": after,
                        "constraints_validated": args.validate_constraints,
                    },
                    indent=2,
                )
            )
            return 0
    except Exception as exc:
        print(
            "backfill failed; previously completed batches may already be committed. "
            f"The operation is idempotent and can be rerun safely: {exc}",
            file=sys.stderr,
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
