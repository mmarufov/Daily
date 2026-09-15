"""Authoritative article-content contract for Daily.

The legacy ``articles.content`` column is useful to ranking/chat code, but it is
not a safe reader contract: historically it mixed publisher feed bodies,
same-URL extraction, and cross-publisher search text.  This module gives those
concepts explicit ownership:

* immutable canonical article metadata stays on ``articles``;
* every acquired body/context is a versioned artifact with provenance;
* source policy is default-deny for native full-text display;
* extraction work is claimed with a lease and completed with a version CAS;
* the presentation decision is materialized on ``articles`` for cheap reads;
* final job outcomes are separate from per-rung extractor telemetry.

All schema changes are additive so an older application image can coexist
during a rolling deployment.  The explicit historical backfill lives in
``backend/scripts/backfill_s2_content.py`` and is deliberately not run during
startup.
"""
from __future__ import annotations

import hashlib
import ipaddress
import logging
import os
import re
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Any, Iterator, Mapping, Sequence
from urllib.parse import urlsplit, urlunsplit

logger = logging.getLogger(__name__)

PRESENTATION_MODES = frozenset({"native_full_text", "source_web", "unavailable"})
BODY_STATES = frozenset({"verified_full", "partial", "none"})
JOB_STATES = frozenset(
    {"pending", "leased", "ready", "retryable_failure", "terminal_failure"}
)
BODY_ARTIFACT_KINDS = frozenset({"licensed_api", "publisher_feed", "origin_extract"})
ARTIFACT_KINDS = BODY_ARTIFACT_KINDS | frozenset(
    {"analysis_text", "legacy_unverified"}
)
COMPLETENESS_STATES = frozenset({"complete", "partial", "unknown", "invalid"})
DISPLAY_POLICIES = frozenset({"source_only", "native_full_text"})
FINAL_OUTCOMES = frozenset(
    {
        "publisher_feed",
        "verified_full",
        "source_web",
        "unavailable",
        "retryable_failure",
        "stale_discarded",
        "revoked",
    }
)
IMAGE_ORIGINS = frozenset(
    {
        "publisher_feed",
        "publisher_page",
        "licensed_api",
        "aggregator_api",
        "stock",
        "generated",
        "legacy_unknown",
    }
)
LEGACY_SAFE_IMAGE_ORIGINS = frozenset(
    {"publisher_feed", "publisher_page", "licensed_api", "aggregator_api"}
)
NON_EXPLICIT_RIGHTS_BASES = frozenset(
    {
        "false",
        "n_a",
        "no_rights",
        "none",
        "not_applicable",
        "pending",
        "revoked",
        "unknown",
        "unreviewed",
        "unspecified",
        "unverified",
    }
)

MAX_ARTIFACT_CHARS = 250_000
BODY_EXCERPT_CHARS = 500
MAX_JOB_ATTEMPTS = 3
DEFAULT_LEASE_SECONDS = 120
EXTRACTOR_VERSION = 4
# Transaction-scoped lock serializing additive DDL across Uvicorn workers and
# machines during a rolling deployment. The fixed key is unique to S2 schema
# installation and is released automatically on commit/rollback or disconnect.
S2_SCHEMA_ADVISORY_LOCK_KEY = 731_202_004

_RETRY_DELAYS_SECONDS = (300, 1_800, 7_200)
_TERMINAL_FAILURES = frozenset(
    {
        "access_denied",
        "consent_required",
        "credentials_not_allowed",
        "error_page_detected",
        "host_not_allowed",
        "identity_mismatch",
        "invalid_url",
        "login_required",
        "missing_host",
        "not_found",
        "paywall_detected",
        "port_not_allowed",
        "redirect_limit",
        "redirect_loop",
        "redirect_missing_location",
        "unsupported_content_type",
        "unsupported_content_encoding",
        "unsafe_address",
        "unsafe_redirect",
        "unsafe_scheme",
        "response_too_large",
    }
)


class _StaleCompletion(RuntimeError):
    """Roll back a completion whose final compare-and-set lost its lease."""


@contextmanager
def article_content_transaction(conn) -> Iterator[None]:
    """Open a real transaction even when the pooled connection autocommits.

    Psycopg turns nested calls into savepoints, so ingestion can use this around
    the article upsert while the lower-level artifact/job functions retain
    their own crash-consistency boundary. Small unit-test doubles without a
    transaction API retain their previous behavior.
    """
    transaction = getattr(conn, "transaction", None)
    if callable(transaction):
        with transaction():
            yield
    else:
        yield


def _ensure_article_content_schema(conn) -> None:
    """Implementation for :func:`ensure_article_content_schema`."""
    with conn.cursor() as cur:
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS public.article_source_policies (
                source_domain text PRIMARY KEY,
                display_policy text NOT NULL DEFAULT 'source_only'
                    CHECK (display_policy IN ('source_only', 'native_full_text')),
                allowed_artifact_kinds text[] NOT NULL DEFAULT ARRAY[]::text[],
                allowed_feed_urls text[] NOT NULL DEFAULT ARRAY[]::text[],
                publisher_feed_full_text boolean NOT NULL DEFAULT false,
                rights_basis text NOT NULL DEFAULT 'unknown',
                access_hint text NOT NULL DEFAULT 'unknown',
                version bigint NOT NULL DEFAULT 1,
                reviewed_at timestamptz,
                reviewed_by text,
                updated_at timestamptz NOT NULL DEFAULT now()
            )
            """
        )
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS public.article_content_artifacts (
                id bigserial PRIMARY KEY,
                article_id uuid NOT NULL REFERENCES public.articles(id) ON DELETE CASCADE,
                kind text NOT NULL CHECK (
                    kind IN ('licensed_api', 'publisher_feed', 'origin_extract',
                             'analysis_text', 'legacy_unverified')
                ),
                text text NOT NULL,
                origin_url text NOT NULL,
                origin_domain text NOT NULL,
                origin_source_id uuid,
                method text NOT NULL,
                rights_basis text NOT NULL DEFAULT 'unknown',
                completeness text NOT NULL DEFAULT 'unknown'
                    CHECK (completeness IN ('complete', 'partial', 'unknown', 'invalid')),
                confidence double precision NOT NULL DEFAULT 0.0
                    CHECK (confidence >= 0.0 AND confidence <= 1.0),
                content_hash text NOT NULL,
                fetched_at timestamptz NOT NULL DEFAULT now(),
                extractor_version integer NOT NULL DEFAULT 1,
                displayable boolean NOT NULL DEFAULT false,
                is_current boolean NOT NULL DEFAULT true,
                version bigint NOT NULL,
                created_at timestamptz NOT NULL DEFAULT now(),
                UNIQUE (article_id, version)
            )
            """
        )
        # Early S2 builds used a history-wide hash uniqueness constraint. It
        # made A -> B -> A impossible: the last A could neither become current
        # nor receive a new monotonic version. Idempotence belongs to the
        # current artifact only; historical reacquisition is a new event.
        cur.execute(
            """
            ALTER TABLE public.article_content_artifacts
            DROP CONSTRAINT IF EXISTS article_content_artifacts_article_id_kind_content_hash_key
            """
        )
        cur.execute(
            """
            CREATE UNIQUE INDEX IF NOT EXISTS idx_article_content_current_kind
            ON public.article_content_artifacts (article_id, kind)
            WHERE is_current
            """
        )
        cur.execute(
            """
            CREATE UNIQUE INDEX IF NOT EXISTS idx_article_content_artifact_owner
            ON public.article_content_artifacts (id, article_id)
            """
        )
        cur.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_article_content_display
            ON public.article_content_artifacts (article_id, displayable, version DESC)
            """
        )
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS public.article_content_jobs (
                article_id uuid PRIMARY KEY REFERENCES public.articles(id) ON DELETE CASCADE,
                state text NOT NULL DEFAULT 'pending'
                    CHECK (state IN ('pending', 'leased', 'ready',
                                     'retryable_failure', 'terminal_failure')),
                failure_class text,
                failure_reason text,
                attempt_count integer NOT NULL DEFAULT 0,
                next_retry_at timestamptz,
                lease_owner text,
                lease_expires_at timestamptz,
                version bigint NOT NULL DEFAULT 0,
                final_outcome text,
                created_at timestamptz NOT NULL DEFAULT now(),
                updated_at timestamptz NOT NULL DEFAULT now(),
                completed_at timestamptz
            )
            """
        )
        cur.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_article_content_jobs_ready
            ON public.article_content_jobs (state, next_retry_at, updated_at)
            """
        )
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS public.article_content_outcomes (
                id bigserial PRIMARY KEY,
                article_id uuid NOT NULL REFERENCES public.articles(id) ON DELETE CASCADE,
                job_version bigint NOT NULL,
                outcome text NOT NULL,
                method text,
                char_count integer NOT NULL DEFAULT 0,
                failure_class text,
                duration_ms integer,
                created_at timestamptz NOT NULL DEFAULT now(),
                UNIQUE (article_id, job_version)
            )
            """
        )
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS public.article_source_policy_events (
                id bigserial PRIMARY KEY,
                source_domain text NOT NULL,
                action text NOT NULL CHECK (action IN ('grant', 'update', 'revoke')),
                policy_version bigint NOT NULL,
                display_policy text NOT NULL,
                allowed_artifact_kinds text[] NOT NULL DEFAULT ARRAY[]::text[],
                allowed_feed_urls text[] NOT NULL DEFAULT ARRAY[]::text[],
                publisher_feed_full_text boolean NOT NULL DEFAULT false,
                rights_basis text NOT NULL,
                access_hint text NOT NULL,
                reviewed_by text NOT NULL,
                created_at timestamptz NOT NULL DEFAULT now(),
                UNIQUE (source_domain, policy_version)
            )
            """
        )

        # Rolling upgrades may encounter the table created by an earlier S2
        # image. Keep additions idempotent before any code reads them.
        cur.execute(
            "ALTER TABLE public.article_source_policies ADD COLUMN IF NOT EXISTS publisher_feed_full_text boolean NOT NULL DEFAULT false"
        )
        cur.execute(
            "ALTER TABLE public.article_source_policies ADD COLUMN IF NOT EXISTS allowed_feed_urls text[] NOT NULL DEFAULT ARRAY[]::text[]"
        )
        cur.execute(
            "ALTER TABLE public.article_source_policies ADD COLUMN IF NOT EXISTS version bigint NOT NULL DEFAULT 1"
        )
        cur.execute("ALTER TABLE public.article_source_policies ADD COLUMN IF NOT EXISTS "
                    "offline_cache_seconds integer NOT NULL DEFAULT 0 "
                    "CHECK(offline_cache_seconds BETWEEN 0 AND 86400)")
        cur.execute("ALTER TABLE public.article_source_policy_events ADD COLUMN IF NOT EXISTS "
                    "offline_cache_seconds integer NOT NULL DEFAULT 0 "
                    "CHECK(offline_cache_seconds BETWEEN 0 AND 86400)")
        cur.execute(
            "ALTER TABLE public.article_source_policy_events ADD COLUMN IF NOT EXISTS allowed_feed_urls text[] NOT NULL DEFAULT ARRAY[]::text[]"
        )

        # Materialized reader/analysis pointers keep feed reads to one cheap PK
        # join instead of re-running policy selection for every card.
        cur.execute(
            "ALTER TABLE public.articles ADD COLUMN IF NOT EXISTS canonical_source_domain text"
        )
        cur.execute(
            "ALTER TABLE public.articles ADD COLUMN IF NOT EXISTS presentation_mode text NOT NULL DEFAULT 'source_web'"
        )
        cur.execute(
            "ALTER TABLE public.articles ADD COLUMN IF NOT EXISTS presentation_reason text NOT NULL DEFAULT 'source_policy_default_deny'"
        )
        cur.execute(
            "ALTER TABLE public.articles ADD COLUMN IF NOT EXISTS body_state text NOT NULL DEFAULT 'none'"
        )
        cur.execute(
            "ALTER TABLE public.articles ADD COLUMN IF NOT EXISTS content_access_hint text NOT NULL DEFAULT 'unknown'"
        )
        cur.execute(
            "ALTER TABLE public.articles ADD COLUMN IF NOT EXISTS display_content_artifact_id bigint"
        )
        cur.execute(
            "ALTER TABLE public.articles ADD COLUMN IF NOT EXISTS analysis_content_artifact_id bigint"
        )
        cur.execute(
            "ALTER TABLE public.articles ADD COLUMN IF NOT EXISTS display_body_excerpt text"
        )
        cur.execute(
            "ALTER TABLE public.articles ADD COLUMN IF NOT EXISTS display_rights_basis text"
        )
        cur.execute(
            "ALTER TABLE public.articles ADD COLUMN IF NOT EXISTS display_effective_completeness text"
        )
        cur.execute(
            "ALTER TABLE public.articles ADD COLUMN IF NOT EXISTS display_policy_version bigint"
        )
        cur.execute(
            "ALTER TABLE public.articles ADD COLUMN IF NOT EXISTS content_version bigint NOT NULL DEFAULT 0"
        )
        cur.execute(
            "ALTER TABLE public.articles ADD COLUMN IF NOT EXISTS analysis_text text"
        )
        cur.execute(
            "ALTER TABLE public.articles ADD COLUMN IF NOT EXISTS analysis_content_version bigint"
        )
        cur.execute(
            "ALTER TABLE public.articles ADD COLUMN IF NOT EXISTS embedding_content_version bigint"
        )
        cur.execute(
            "ALTER TABLE public.articles ADD COLUMN IF NOT EXISTS content_quality double precision"
        )
        cur.execute(
            "ALTER TABLE public.articles ADD COLUMN IF NOT EXISTS content_quality_content_version bigint"
        )
        cur.execute(
            "ALTER TABLE public.articles ADD COLUMN IF NOT EXISTS enrichment_completed boolean NOT NULL DEFAULT false"
        )
        cur.execute(
            "ALTER TABLE public.articles ADD COLUMN IF NOT EXISTS enrichment_attempts integer NOT NULL DEFAULT 0"
        )
        cur.execute(
            "ALTER TABLE public.articles ADD COLUMN IF NOT EXISTS image_origin text"
        )
        cur.execute(
            "ALTER TABLE public.articles ADD COLUMN IF NOT EXISTS image_source_url text"
        )
        cur.execute(
            "ALTER TABLE public.articles ADD COLUMN IF NOT EXISTS image_attribution text"
        )
        cur.execute(
            "ALTER TABLE public.articles ADD COLUMN IF NOT EXISTS image_is_illustrative boolean NOT NULL DEFAULT false"
        )
        cur.execute(
            "CREATE INDEX IF NOT EXISTS idx_articles_presentation_mode ON public.articles (presentation_mode)"
        )
        cur.execute(
            "CREATE INDEX IF NOT EXISTS idx_articles_canonical_source_domain ON public.articles (canonical_source_domain)"
        )

        # NOT VALID keeps startup bounded on a large pre-existing table while
        # enforcing each invariant for all new writes. The explicit backfill
        # validates these after historical rows are normalized.
        cur.execute(
            """
            DO $$
            BEGIN
                IF NOT EXISTS (
                    SELECT 1 FROM pg_constraint
                    WHERE conname = 'articles_presentation_mode_check'
                ) THEN
                    ALTER TABLE public.articles ADD CONSTRAINT articles_presentation_mode_check
                    CHECK (presentation_mode IN ('native_full_text', 'source_web', 'unavailable'))
                    NOT VALID;
                END IF;
                IF NOT EXISTS (
                    SELECT 1 FROM pg_constraint
                    WHERE conname = 'articles_body_state_check'
                ) THEN
                    ALTER TABLE public.articles ADD CONSTRAINT articles_body_state_check
                    CHECK (body_state IN ('verified_full', 'partial', 'none')) NOT VALID;
                END IF;
                IF NOT EXISTS (
                    SELECT 1 FROM pg_constraint
                    WHERE conname = 'articles_reader_pointer_consistency_check'
                ) THEN
                    ALTER TABLE public.articles ADD CONSTRAINT articles_reader_pointer_consistency_check
                    CHECK (
                        (presentation_mode = 'native_full_text'
                         AND body_state = 'verified_full'
                         AND display_content_artifact_id IS NOT NULL)
                        OR
                        (presentation_mode <> 'native_full_text'
                         AND body_state <> 'verified_full'
                         AND display_content_artifact_id IS NULL)
                    ) NOT VALID;
                END IF;
                IF NOT EXISTS (
                    SELECT 1 FROM pg_constraint
                    WHERE conname = 'articles_display_artifact_fk'
                ) THEN
                    ALTER TABLE public.articles ADD CONSTRAINT articles_display_artifact_fk
                    FOREIGN KEY (display_content_artifact_id)
                    REFERENCES public.article_content_artifacts(id) ON DELETE SET NULL NOT VALID;
                END IF;
                IF NOT EXISTS (
                    SELECT 1 FROM pg_constraint
                    WHERE conname = 'articles_analysis_artifact_fk'
                ) THEN
                    ALTER TABLE public.articles ADD CONSTRAINT articles_analysis_artifact_fk
                    FOREIGN KEY (analysis_content_artifact_id)
                    REFERENCES public.article_content_artifacts(id) ON DELETE SET NULL NOT VALID;
                END IF;
                IF NOT EXISTS (
                    SELECT 1 FROM pg_constraint
                    WHERE conname = 'articles_display_artifact_owner_fk_v1'
                ) THEN
                    ALTER TABLE public.articles
                    ADD CONSTRAINT articles_display_artifact_owner_fk_v1
                    FOREIGN KEY (display_content_artifact_id, id)
                    REFERENCES public.article_content_artifacts(id, article_id)
                    DEFERRABLE INITIALLY DEFERRED NOT VALID;
                END IF;
                IF NOT EXISTS (
                    SELECT 1 FROM pg_constraint
                    WHERE conname = 'articles_analysis_artifact_owner_fk_v1'
                ) THEN
                    ALTER TABLE public.articles
                    ADD CONSTRAINT articles_analysis_artifact_owner_fk_v1
                    FOREIGN KEY (analysis_content_artifact_id, id)
                    REFERENCES public.article_content_artifacts(id, article_id)
                    DEFERRABLE INITIALLY DEFERRED NOT VALID;
                END IF;
                IF NOT EXISTS (
                    SELECT 1 FROM pg_constraint
                    WHERE conname = 'article_content_artifact_displayable_v3_check'
                ) THEN
                    ALTER TABLE public.article_content_artifacts
                    ADD CONSTRAINT article_content_artifact_displayable_v3_check
                    CHECK (
                        NOT displayable OR (
                            is_current
                            AND kind IN ('licensed_api', 'publisher_feed', 'origin_extract')
                            AND (kind <> 'origin_extract' OR extractor_version >= 4)
                            AND (
                                completeness = 'complete'
                                OR (kind = 'publisher_feed' AND completeness = 'unknown')
                            )
                        )
                    ) NOT VALID;
                END IF;
                IF NOT EXISTS (
                    SELECT 1 FROM pg_constraint
                    WHERE conname = 'article_content_jobs_lease_check'
                ) THEN
                    ALTER TABLE public.article_content_jobs
                    ADD CONSTRAINT article_content_jobs_lease_check
                    CHECK (
                        (state = 'leased' AND lease_owner IS NOT NULL AND lease_expires_at IS NOT NULL)
                        OR (state <> 'leased' AND lease_owner IS NULL AND lease_expires_at IS NULL)
                    ) NOT VALID;
                END IF;
                IF NOT EXISTS (
                    SELECT 1 FROM pg_constraint
                    WHERE conname = 'article_content_jobs_outcome_v2_check'
                ) THEN
                    ALTER TABLE public.article_content_jobs
                    ADD CONSTRAINT article_content_jobs_outcome_v2_check
                    CHECK (
                        final_outcome IS NULL OR final_outcome IN (
                            'publisher_feed', 'verified_full', 'source_web',
                            'unavailable', 'retryable_failure',
                            'stale_discarded', 'revoked'
                        )
                    ) NOT VALID;
                END IF;
                IF NOT EXISTS (
                    SELECT 1 FROM pg_constraint
                    WHERE conname = 'article_source_policy_allowed_kinds_check'
                ) THEN
                    ALTER TABLE public.article_source_policies
                    ADD CONSTRAINT article_source_policy_allowed_kinds_check
                    CHECK (
                        allowed_artifact_kinds <@ ARRAY[
                            'licensed_api', 'publisher_feed', 'origin_extract'
                        ]::text[]
                    ) NOT VALID;
                END IF;
                IF NOT EXISTS (
                    SELECT 1 FROM pg_constraint
                    WHERE conname = 'article_source_policy_version_check'
                ) THEN
                    ALTER TABLE public.article_source_policies
                    ADD CONSTRAINT article_source_policy_version_check
                    CHECK (version >= 1) NOT VALID;
                END IF;
                IF NOT EXISTS (
                    SELECT 1 FROM pg_constraint
                    WHERE conname = 'article_source_policy_rights_v1_check'
                ) THEN
                    ALTER TABLE public.article_source_policies
                    ADD CONSTRAINT article_source_policy_rights_v1_check
                    CHECK (
                        rights_basis = lower(btrim(rights_basis))
                        AND rights_basis ~ '^[a-z0-9][a-z0-9._:-]{0,199}$'
                        AND (
                            display_policy <> 'native_full_text'
                            OR rights_basis NOT IN (
                                'false', 'n_a', 'no_rights', 'none',
                                'not_applicable', 'pending', 'revoked', 'unknown',
                                'unreviewed', 'unspecified', 'unverified'
                            )
                        )
                    ) NOT VALID;
                END IF;
                IF NOT EXISTS (
                    SELECT 1 FROM pg_constraint
                    WHERE conname = 'article_source_policy_feed_scope_v1_check'
                ) THEN
                    ALTER TABLE public.article_source_policies
                    ADD CONSTRAINT article_source_policy_feed_scope_v1_check
                    CHECK (
                        (
                            display_policy = 'source_only'
                            AND cardinality(allowed_artifact_kinds) = 0
                            AND cardinality(allowed_feed_urls) = 0
                            AND publisher_feed_full_text = false
                        )
                        OR (
                            display_policy = 'native_full_text'
                            AND (
                                publisher_feed_full_text = false
                                OR (
                                    'publisher_feed' = ANY(allowed_artifact_kinds)
                                    AND cardinality(allowed_feed_urls) > 0
                                )
                            )
                        )
                    ) NOT VALID;
                END IF;
                IF NOT EXISTS (
                    SELECT 1 FROM pg_constraint
                    WHERE conname = 'article_content_artifact_version_check'
                ) THEN
                    ALTER TABLE public.article_content_artifacts
                    ADD CONSTRAINT article_content_artifact_version_check
                    CHECK (version >= 1 AND extractor_version >= 1) NOT VALID;
                END IF;
                IF NOT EXISTS (
                    SELECT 1 FROM pg_constraint
                    WHERE conname = 'article_content_job_counters_check'
                ) THEN
                    ALTER TABLE public.article_content_jobs
                    ADD CONSTRAINT article_content_job_counters_check
                    CHECK (attempt_count >= 0 AND version >= 0) NOT VALID;
                END IF;
                IF NOT EXISTS (
                    SELECT 1 FROM pg_constraint
                    WHERE conname = 'articles_image_origin_check'
                ) THEN
                    ALTER TABLE public.articles
                    ADD CONSTRAINT articles_image_origin_check
                    CHECK (
                        image_origin IS NULL OR image_origin IN (
                            'publisher_feed', 'publisher_page', 'licensed_api',
                            'aggregator_api', 'stock', 'generated', 'legacy_unknown'
                        )
                    ) NOT VALID;
                END IF;
            END $$
            """
        )
        cur.execute(
            """
            ALTER TABLE public.article_content_artifacts
            DROP CONSTRAINT IF EXISTS article_content_artifact_displayable_check
            """
        )
        cur.execute(
            """
            ALTER TABLE public.article_content_artifacts
            DROP CONSTRAINT IF EXISTS article_content_artifact_displayable_v2_check
            """
        )
        cur.execute(
            """
            ALTER TABLE public.article_content_jobs
            DROP CONSTRAINT IF EXISTS article_content_jobs_outcome_check
            """
        )


def ensure_article_content_schema(conn) -> None:
    """Create the additive S2 schema atomically, serially, and idempotently."""
    with article_content_transaction(conn):
        with conn.cursor() as cur:
            # ``IF NOT EXISTS`` alone does not prevent PostgreSQL catalog
            # uniqueness races when two first-start workers create a table.
            cur.execute(
                "SELECT pg_advisory_xact_lock(%s)",
                (S2_SCHEMA_ADVISORY_LOCK_KEY,),
            )
        _ensure_article_content_schema(conn)


def normalized_domain(url: str | None) -> str:
    """Return a stable lowercase hostname (``www.`` is not an identity)."""
    if not isinstance(url, str):
        return ""
    try:
        parsed = urlsplit(url.strip())
    except ValueError:
        return ""
    if parsed.scheme.lower() not in {"http", "https"} or not parsed.hostname:
        return ""
    host = parsed.hostname.rstrip(".").lower()
    return host[4:] if host.startswith("www.") else host


def normalize_source_domain(value: str | None) -> str:
    """Normalize either a URL or a bare source hostname."""
    if not isinstance(value, str) or not value.strip():
        return ""
    raw = value.strip()
    if "://" in raw:
        host = normalized_domain(raw)
        return host if _structurally_public_host(host) else ""
    if any(character in raw for character in "/?#@"):
        return ""
    try:
        parsed = urlsplit(f"https://{raw}")
    except ValueError:
        return ""
    if not parsed.hostname or parsed.port is not None:
        return ""
    host = parsed.hostname.rstrip(".").lower()
    host = host[4:] if host.startswith("www.") else host
    return host if _structurally_public_host(host) else ""


_NON_PUBLIC_HOST_SUFFIXES = (
    ".local",
    ".localhost",
    ".internal",
    ".test",
    ".invalid",
    ".example",
    ".home",
    ".lan",
)
_HOST_LABEL = re.compile(r"^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$", re.I)


def _structurally_public_host(host: str) -> bool:
    """Reject local/special host syntax without doing DNS on a read path."""
    candidate = host.rstrip(".").lower()
    if not candidate or candidate in {"localhost", "localhost.localdomain"}:
        return False
    try:
        literal = ipaddress.ip_address(candidate.split("%", 1)[0])
    except ValueError:
        try:
            ascii_host = candidate.encode("idna").decode("ascii")
        except UnicodeError:
            return False
        if (
            len(ascii_host) > 253
            or "." not in ascii_host
            or ascii_host.endswith(_NON_PUBLIC_HOST_SUFFIXES)
        ):
            return False
        return all(_HOST_LABEL.fullmatch(label) for label in ascii_host.split("."))
    return literal.is_global


def valid_original_url(url: str | None) -> bool:
    """Validate a URL before exposing it as a one-tap reader destination.

    This is deliberately DNS-free on the feed hot path. Ingestion performs the
    network-level public-address check; registered-source trust and Safari's
    process isolation are the remaining defense for hostnames that later
    rebind. Literal private addresses, local names, userinfo, and unusual ports
    are rejected here without I/O.
    """
    if not isinstance(url, str) or not url.strip() or len(url) > 4096:
        return False
    try:
        parsed = urlsplit(url.strip())
        port = parsed.port
    except (TypeError, ValueError):
        return False
    if parsed.scheme.lower() not in {"http", "https"} or not parsed.hostname:
        return False
    if parsed.username is not None or parsed.password is not None:
        return False
    if port is not None and port not in {80, 443}:
        return False
    return _structurally_public_host(parsed.hostname)


_RIGHTS_BASIS_TOKEN = re.compile(r"^[a-z0-9][a-z0-9._:-]{0,199}$")


def normalize_rights_basis(value: str | None) -> str:
    """Return the canonical audited token, or an empty string if malformed."""
    token = str(value or "").strip().casefold()
    return token if _RIGHTS_BASIS_TOKEN.fullmatch(token) else ""


def rights_basis_is_explicit(value: str | None) -> bool:
    """Fail closed for placeholders, revocations, and malformed rights claims."""
    token = normalize_rights_basis(value)
    return bool(token and token not in NON_EXPLICIT_RIGHTS_BASES)


def normalize_feed_url(value: str | None) -> str:
    """Canonicalize an exact HTTPS feed identity used by reviewed policies.

    A feed URL is an acquisition principal, not just transport metadata. Exact
    matching prevents an aggregator or user-submitted feed from borrowing the
    article publisher's domain-level display permission.
    """
    if not valid_original_url(value):
        return ""
    try:
        parsed = urlsplit(str(value).strip())
        port = parsed.port
    except (TypeError, ValueError):
        return ""
    if parsed.scheme.casefold() != "https" or port not in {None, 443}:
        return ""
    host = (parsed.hostname or "").rstrip(".").casefold()
    try:
        ipaddress.ip_address(host.split("%", 1)[0])
    except ValueError:
        try:
            host = host.encode("idna").decode("ascii")
        except UnicodeError:
            return ""
    else:
        return ""
    netloc = host
    path = parsed.path or "/"
    return urlunsplit(("https", netloc, path, parsed.query, ""))


def same_origin(left: str | None, right: str | None) -> bool:
    """Strict publisher identity boundary used by display-body artifacts."""
    if not valid_original_url(left) or not valid_original_url(right):
        return False
    left_domain = normalized_domain(left)
    return bool(left_domain and left_domain == normalized_domain(right))


def _normalize_text(text: str | None) -> str:
    if not isinstance(text, str):
        return ""
    return re.sub(r"[\t\r\f\v ]+", " ", text).strip()


def _excerpt(text: str | None, limit: int = BODY_EXCERPT_CHARS) -> str | None:
    clean = _normalize_text(text)
    if not clean:
        return None
    if len(clean) <= limit:
        return clean
    candidate = clean[:limit].rsplit(" ", 1)[0].rstrip(" ,;:-")
    return (candidate or clean[:limit]).rstrip() + "…"


def _iso(value: Any) -> str | None:
    if isinstance(value, datetime):
        value = value if value.tzinfo else value.replace(tzinfo=timezone.utc)
        return value.isoformat()
    if isinstance(value, str) and value:
        return value
    return None


def serialize_article(row: Mapping[str, Any], *, include_body: bool) -> dict[str, Any]:
    """Serialize both fresh/cache/detail rows with identical reader semantics.

    ``content`` remains additive for one client transition, but is populated
    only with a complete native body on detail responses. A clipped preview is
    never labeled as content.
    """
    original_url = row.get("url") if valid_original_url(row.get("url")) else None
    requested_mode = row.get("presentation_mode")
    mode = requested_mode if requested_mode in PRESENTATION_MODES else "source_web"
    selected_id = row.get("display_content_artifact_id")
    body = _normalize_text(row.get("display_body")) if include_body else ""
    try:
        content_version = int(row.get("content_version") or 0)
        policy_version = int(row.get("display_policy_version") or 0)
        artifact_confidence = float(row.get("artifact_confidence") or 0.0)
        artifact_extractor_version = int(row.get("artifact_extractor_version") or 0)
    except (TypeError, ValueError, OverflowError):
        content_version = 0
        policy_version = 0
        artifact_confidence = 0.0
        artifact_extractor_version = 0

    native_contract_is_trusted = bool(
        selected_id
        and row.get("body_state") == "verified_full"
        and row.get("artifact_kind") in BODY_ARTIFACT_KINDS
        and (
            row.get("artifact_kind") != "origin_extract"
            or artifact_extractor_version >= EXTRACTOR_VERSION
        )
        and (row.get("display_effective_completeness") or row.get("artifact_completeness"))
        == "complete"
        and rights_basis_is_explicit(row.get("display_rights_basis"))
        and content_version > 0
        and policy_version > 0
        and valid_original_url(row.get("artifact_origin_url"))
        and artifact_confidence >= 0.8
    )
    if mode == "native_full_text" and not native_contract_is_trusted:
        mode = "source_web" if original_url else "unavailable"
    if mode == "native_full_text" and include_body and not body:
        mode = "source_web" if original_url else "unavailable"
    if mode == "source_web" and not original_url:
        mode = "unavailable"

    body_state = row.get("body_state")
    if mode == "native_full_text":
        body_state = "verified_full"
    elif body_state not in BODY_STATES or body_state == "verified_full":
        body_state = "partial" if row.get("body_state") == "partial" else "none"

    reason = row.get("presentation_reason") or "source_policy_default_deny"
    if mode == "unavailable":
        reason = "invalid_or_missing_original_url"

    source_name = row.get("source_name") or row.get("source")
    provenance = None
    if selected_id and mode == "native_full_text":
        provenance = {
            "kind": row.get("artifact_kind"),
            "method": row.get("artifact_method"),
            "source_url": row.get("artifact_origin_url"),
            "source_name": source_name,
            "fetched_at": _iso(row.get("artifact_fetched_at")),
            "content_hash": row.get("artifact_content_hash"),
            "extractor_version": row.get("artifact_extractor_version"),
            # These are the current reviewed decision values. The immutable
            # acquisition-time values remain on the artifact for audit, but a
            # later grant must not claim "unknown" rights in the app, and a
            # revocation clears the selected artifact entirely.
            "rights_policy": row.get("display_rights_basis"),
            "completeness": (
                row.get("display_effective_completeness")
                or row.get("artifact_completeness")
            ),
            "confidence": row.get("artifact_confidence"),
            "content_version": content_version,
            "policy_version": policy_version,
        }

    image = None
    image_url = row.get("image_url")
    image_origin = row.get("image_origin")
    if (
        valid_original_url(image_url)
        and image_origin in IMAGE_ORIGINS
        and image_origin != "legacy_unknown"
    ):
        image_source_url = row.get("image_source_url")
        image = {
            "url": image_url,
            "origin": image_origin,
            "source_url": (
                image_source_url if valid_original_url(image_source_url) else None
            ),
            "attribution": row.get("image_attribution"),
            "illustrative": bool(row.get("image_is_illustrative")),
        }
    legacy_image_url = (
        image_url
        if image is not None and image_origin in LEGACY_SAFE_IMAGE_ORIGINS
        else None
    )

    full_native_body = body if mode == "native_full_text" and include_body else None
    result = {
        "id": str(row["id"]),
        "title": row.get("title", ""),
        "summary": row.get("summary"),
        "description": row.get("summary"),
        "body_excerpt": row.get("display_body_excerpt") if mode == "native_full_text" else None,
        "content": full_native_body,
        "author": row.get("author"),
        "source": source_name,
        "publisher": {"name": source_name, "canonical_url": original_url},
        "image": image,
        # Compatibility for older clients. Illustration/unknown provenance is
        # intentionally omitted so it cannot be mistaken for publisher media.
        "image_url": legacy_image_url,
        "url": original_url,
        "published_at": _iso(row.get("published_at")),
        "category": row.get("category"),
        "presentation": {
            "mode": mode,
            "original_url": original_url,
            "body": full_native_body,
            "body_state": body_state,
            "access_hint": row.get("content_access_hint") or "unknown",
            "reason": reason,
            "provenance": provenance,
        },
    }
    return result


def enqueue_content_job(conn, article_id: Any) -> None:
    """Create a pending job once; repeated feed refreshes do not reset failures."""
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO public.article_content_jobs (article_id, state)
            VALUES (%s, 'pending')
            ON CONFLICT (article_id) DO NOTHING
            """,
            (article_id,),
        )


def claim_content_jobs(
    conn,
    worker_id: str,
    *,
    limit: int = 20,
    lease_seconds: int = DEFAULT_LEASE_SECONDS,
) -> list[dict[str, Any]]:
    """Atomically lease ready work with SKIP LOCKED.

    ``version`` is incremented on every lease and is the completion token. An
    expired worker can finish its network call, but its CAS will be rejected.
    """
    if not worker_id or len(worker_id) > 200:
        raise ValueError("worker_id must be 1...200 characters")
    safe_limit = max(1, min(int(limit), 100))
    safe_lease = max(30, min(int(lease_seconds), 900))
    safe_reap_limit = min(max(safe_limit * 5, 25), 500)
    exhausted: list[dict[str, Any]] = []
    claimed: list[dict[str, Any]] = []
    with article_content_transaction(conn):
        # A worker that dies on its final permitted attempt must not leave an
        # unreclaimable ``leased`` row forever. Reap all due exhausted states
        # before claiming fresh work, using the same transaction/row locks.
        with conn.cursor() as cur:
            cur.execute(
                """
                WITH exhausted AS (
                    SELECT j.article_id
                    FROM public.article_content_jobs j
                    WHERE j.attempt_count >= %s
                      AND (
                          j.state = 'pending'
                          OR (
                              j.state = 'retryable_failure'
                              AND (j.next_retry_at IS NULL OR j.next_retry_at <= now())
                          )
                          OR (
                              j.state = 'leased'
                              AND j.lease_expires_at <= now()
                          )
                      )
                    ORDER BY j.updated_at, j.article_id
                    FOR UPDATE OF j SKIP LOCKED
                    LIMIT %s
                )
                UPDATE public.article_content_jobs j
                SET state = 'terminal_failure',
                    failure_class = COALESCE(j.failure_class, 'attempts_exhausted'),
                    failure_reason = COALESCE(
                        j.failure_reason,
                        'worker lease expired after the final extraction attempt'
                    ),
                    next_retry_at = NULL,
                    lease_owner = NULL,
                    lease_expires_at = NULL,
                    version = j.version + 1,
                    final_outcome = 'source_web',
                    updated_at = now(),
                    completed_at = now()
                FROM exhausted e
                WHERE j.article_id = e.article_id
                RETURNING j.article_id, j.version AS job_version,
                          j.failure_class
                """,
                (MAX_JOB_ATTEMPTS, safe_reap_limit),
            )
            exhausted = [dict(row) for row in cur.fetchall()]

        for row in exhausted:
            _record_final_outcome(
                conn,
                article_id=row["article_id"],
                job_version=int(row["job_version"]),
                outcome="source_web",
                extracted={"extraction_method": "lease_reaper"},
                failure_class=row.get("failure_class") or "attempts_exhausted",
                duration_ms=None,
            )

        with conn.cursor() as cur:
            cur.execute(
                """
                WITH claimable AS (
                    SELECT j.article_id
                    FROM public.article_content_jobs j
                    JOIN public.articles a ON a.id = j.article_id
                    WHERE a.url IS NOT NULL
                      AND j.attempt_count < %s
                      AND (
                          j.state = 'pending'
                          OR (
                              j.state = 'retryable_failure'
                              AND (j.next_retry_at IS NULL OR j.next_retry_at <= now())
                          )
                          OR (
                              j.state = 'leased'
                              AND j.lease_expires_at <= now()
                          )
                      )
                    ORDER BY COALESCE(j.next_retry_at, j.created_at), j.article_id
                    FOR UPDATE OF j SKIP LOCKED
                    LIMIT %s
                )
                UPDATE public.article_content_jobs j
                SET state = 'leased',
                    attempt_count = j.attempt_count + 1,
                    lease_owner = %s,
                    lease_expires_at = now() + (%s * interval '1 second'),
                    version = j.version + 1,
                    failure_class = NULL,
                    failure_reason = NULL,
                    final_outcome = NULL,
                    updated_at = now(),
                    completed_at = NULL
                FROM claimable c, public.articles a
                WHERE j.article_id = c.article_id AND a.id = j.article_id
                RETURNING j.article_id, j.version AS job_version, j.attempt_count,
                          a.url, a.title, a.source_name,
                          COALESCE(a.canonical_source_domain, '') AS source_domain
                """,
                (MAX_JOB_ATTEMPTS, safe_limit, worker_id, safe_lease),
            )
            claimed = [dict(row) for row in cur.fetchall()]
    return claimed


def _load_policy(cur, canonical_url: str) -> dict[str, Any]:
    domain = normalized_domain(canonical_url)
    if not domain:
        return {
            "source_domain": "",
            "display_policy": "source_only",
            "allowed_artifact_kinds": [],
            "allowed_feed_urls": [],
            "publisher_feed_full_text": False,
            "rights_basis": "unknown",
            "access_hint": "unknown",
            "version": 0,
        }
    cur.execute(
        """
        SELECT source_domain, display_policy, allowed_artifact_kinds,
               allowed_feed_urls, publisher_feed_full_text, rights_basis,
               access_hint, version, offline_cache_seconds
        FROM public.article_source_policies
        WHERE source_domain = %s
        """,
        (domain,),
    )
    row = cur.fetchone()
    if row:
        return dict(row)
    # Default deny is a pure read decision. Do not create a policy row as a
    # side effect of ingestion; explicit reviewed mutations own that table.
    return {
        "source_domain": domain,
        "display_policy": "source_only",
        "allowed_artifact_kinds": [],
        "allowed_feed_urls": [],
        "publisher_feed_full_text": False,
        "rights_basis": "unknown",
        "access_hint": "unknown",
        "version": 0,
    }


def _validate_policy_input(
    *,
    source_domain: str,
    display_policy: str,
    allowed_artifact_kinds: Sequence[str],
    allowed_feed_urls: Sequence[str],
    publisher_feed_full_text: bool,
    rights_basis: str,
    access_hint: str,
    reviewed_by: str,
) -> tuple[str, list[str], list[str], str, str, str]:
    domain = normalize_source_domain(source_domain)
    if not domain:
        raise ValueError("source_domain must be a public DNS hostname")
    try:
        ipaddress.ip_address(domain)
    except ValueError:
        pass
    else:
        raise ValueError("source_domain must be a publisher hostname, not an IP address")
    if display_policy not in DISPLAY_POLICIES:
        raise ValueError(f"unsupported display_policy: {display_policy}")
    kinds = sorted({str(kind).strip() for kind in allowed_artifact_kinds})
    if any(kind not in BODY_ARTIFACT_KINDS for kind in kinds):
        raise ValueError("allowed_artifact_kinds contains a non-body artifact kind")
    raw_rights = str(rights_basis or "").strip()
    rights = normalize_rights_basis(raw_rights)
    if raw_rights and not rights:
        raise ValueError("rights_basis must be a stable lowercase-compatible token")
    feed_urls = sorted(
        {
            normalized
            for value in allowed_feed_urls
            if (normalized := normalize_feed_url(str(value)))
        }
    )
    if len(feed_urls) != len({str(value).strip() for value in allowed_feed_urls}):
        raise ValueError("allowed_feed_urls must contain unique public HTTPS feed URLs")
    hint = str(access_hint or "unknown").strip()[:100]
    reviewer = str(reviewed_by or "").strip()[:200]
    if not reviewer:
        raise ValueError("reviewed_by is required for an auditable policy change")
    if not rights:
        raise ValueError("rights_basis is required")
    if not hint or not re.fullmatch(r"[a-z0-9][a-z0-9_-]{0,99}", hint):
        raise ValueError("access_hint must be a stable lowercase token")
    if display_policy == "native_full_text":
        if not rights_basis_is_explicit(rights):
            raise ValueError("native_full_text requires an explicit rights_basis")
        if not kinds:
            raise ValueError("native_full_text requires at least one approved artifact kind")
    elif kinds or feed_urls or publisher_feed_full_text:
        raise ValueError("source_only cannot approve native artifact kinds")
    if "publisher_feed" in kinds and not publisher_feed_full_text:
        raise ValueError(
            "publisher_feed requires an explicit publisher_feed_full_text assertion"
        )
    if publisher_feed_full_text and (
        "publisher_feed" not in kinds or not feed_urls
    ):
        raise ValueError(
            "publisher_feed_full_text requires publisher_feed and an approved feed URL"
        )
    if feed_urls and not publisher_feed_full_text:
        raise ValueError("allowed_feed_urls require publisher_feed_full_text")
    return domain, kinds, feed_urls, rights, hint, reviewer


def _rematerialize_source_policy(cur, domain: str) -> list[Any]:
    """Apply a policy decision to every already-normalized article from it."""
    # Every path that needs both records locks article -> job. Ingestion already
    # owns the article row after its URL upsert, so reversing this order creates
    # a real deadlock with extraction completion.
    cur.execute(
        """
        SELECT id, url
        FROM public.articles
        WHERE canonical_source_domain = %s
        ORDER BY id
        FOR UPDATE
        """,
        (domain,),
    )
    articles = [dict(row) for row in cur.fetchall()]
    cur.execute(
        """
        SELECT j.article_id
        FROM public.article_content_jobs j
        JOIN public.articles a ON a.id = j.article_id
        WHERE a.canonical_source_domain = %s
        ORDER BY j.article_id
        FOR UPDATE OF j
        """,
        (domain,),
    )
    cur.fetchall()
    for article in articles:
        _resolve_materialized_content(cur, article["id"], article.get("url") or "")
    return [article["id"] for article in articles]


def set_source_policy(
    conn,
    *,
    source_domain: str,
    display_policy: str,
    allowed_artifact_kinds: Sequence[str],
    publisher_feed_full_text: bool,
    rights_basis: str,
    access_hint: str,
    reviewed_by: str,
    allowed_feed_urls: Sequence[str] = (),
    action: str = "update",
    offline_cache_seconds: int = 0,
) -> dict[str, Any]:
    """Grant/update a reviewed source policy and rematerialize atomically.

    Policy mutation is intentionally an explicit operational action, never a
    side effect of ingestion. The append-only event records who made every
    decision and a monotonically increasing version fences cached readers.
    """
    if action not in {"grant", "update", "revoke"}:
        raise ValueError("action must be grant, update, or revoke")
    if (type(offline_cache_seconds) is not int or not 0 <= offline_cache_seconds <= 86400
            or (offline_cache_seconds and display_policy != 'native_full_text')):
        raise ValueError("offline cache requires explicit native permission and 0..86400 seconds")
    if action == "revoke" and (
        display_policy != "source_only"
        or allowed_artifact_kinds
        or publisher_feed_full_text
    ):
        raise ValueError("revoke must remove every native full-text permission")
    domain, kinds, feed_urls, rights, hint, reviewer = _validate_policy_input(
        source_domain=source_domain,
        display_policy=display_policy,
        allowed_artifact_kinds=allowed_artifact_kinds,
        allowed_feed_urls=allowed_feed_urls,
        publisher_feed_full_text=bool(publisher_feed_full_text),
        rights_basis=rights_basis,
        access_hint=access_hint,
        reviewed_by=reviewed_by,
    )
    with article_content_transaction(conn):
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO public.article_source_policies (
                    source_domain, display_policy, allowed_artifact_kinds,
                    allowed_feed_urls, publisher_feed_full_text, rights_basis,
                    access_hint, version, reviewed_at, reviewed_by, updated_at, offline_cache_seconds
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, 1, now(), %s, now(), %s)
                ON CONFLICT (source_domain) DO UPDATE
                SET display_policy = EXCLUDED.display_policy,
                    allowed_artifact_kinds = EXCLUDED.allowed_artifact_kinds,
                    allowed_feed_urls = EXCLUDED.allowed_feed_urls,
                    publisher_feed_full_text = EXCLUDED.publisher_feed_full_text,
                    rights_basis = EXCLUDED.rights_basis,
                    access_hint = EXCLUDED.access_hint,
                    offline_cache_seconds = EXCLUDED.offline_cache_seconds,
                    version = article_source_policies.version + 1,
                    reviewed_at = now(),
                    reviewed_by = EXCLUDED.reviewed_by,
                    updated_at = now()
                RETURNING source_domain, display_policy,
                          allowed_artifact_kinds, allowed_feed_urls,
                          publisher_feed_full_text, rights_basis, access_hint,
                          version, reviewed_at, reviewed_by, offline_cache_seconds
                """,
                (
                    domain,
                    display_policy,
                    kinds,
                    feed_urls,
                    bool(publisher_feed_full_text),
                    rights,
                    hint,
                    reviewer,
                    offline_cache_seconds,
                ),
            )
            policy = dict(cur.fetchone())
            cur.execute(
                """
                INSERT INTO public.article_source_policy_events (
                    source_domain, action, policy_version, display_policy,
                    allowed_artifact_kinds, allowed_feed_urls,
                    publisher_feed_full_text, rights_basis, access_hint,
                    reviewed_by, offline_cache_seconds
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    domain,
                    action,
                    policy["version"],
                    display_policy,
                    kinds,
                    feed_urls,
                    bool(publisher_feed_full_text),
                    rights,
                    hint,
                    reviewer,
                    offline_cache_seconds,
                ),
            )
            article_ids = _rematerialize_source_policy(cur, domain)
            # A grant can make an existing reviewed artifact displayable without
            # reacquisition. Revocation fences active workers. A later native
            # policy that no longer accepts the previously-ready artifact must
            # requeue the job instead of leaving it permanently wedged at ready.
            if article_ids and action == "revoke":
                cur.execute(
                    """
                    UPDATE public.article_content_jobs j
                    SET state = CASE WHEN j.state = 'leased' THEN 'pending' ELSE j.state END,
                        lease_owner = NULL,
                        lease_expires_at = NULL,
                        version = j.version + 1,
                        final_outcome = 'revoked',
                        updated_at = now(),
                        completed_at = CASE WHEN j.state = 'leased' THEN NULL
                                            ELSE j.completed_at END
                    FROM public.articles a
                    WHERE j.article_id = a.id
                      AND a.canonical_source_domain = %s
                    """,
                    (domain,),
                )
            elif article_ids and display_policy == "native_full_text":
                cur.execute(
                    """
                    UPDATE public.article_content_jobs j
                    SET state = 'ready', failure_class = NULL,
                        failure_reason = NULL, next_retry_at = NULL,
                        lease_owner = NULL, lease_expires_at = NULL,
                        version = j.version + 1,
                        final_outcome = CASE a.body_state
                            WHEN 'verified_full' THEN
                                CASE ca.kind WHEN 'publisher_feed'
                                    THEN 'publisher_feed' ELSE 'verified_full' END
                            ELSE j.final_outcome
                        END,
                        updated_at = now(), completed_at = now()
                    FROM public.articles a
                    JOIN public.article_content_artifacts ca
                      ON ca.id = a.display_content_artifact_id
                    WHERE j.article_id = a.id
                      AND a.canonical_source_domain = %s
                      AND a.presentation_mode = 'native_full_text'
                    """,
                    (domain,),
                )
                cur.execute(
                    """
                    UPDATE public.article_content_jobs j
                    SET state = 'pending', failure_class = NULL,
                        failure_reason = NULL, next_retry_at = NULL,
                        attempt_count = 0,
                        lease_owner = NULL, lease_expires_at = NULL,
                        version = j.version + 1, final_outcome = NULL,
                        updated_at = now(), completed_at = NULL
                    FROM public.articles a
                    WHERE j.article_id = a.id
                      AND a.canonical_source_domain = %s
                      AND a.presentation_mode <> 'native_full_text'
                      AND j.state IN ('ready', 'leased')
                    """,
                    (domain,),
                )
            policy["rematerialized_articles"] = len(article_ids)
            return policy


def revoke_source_policy(
    conn,
    *,
    source_domain: str,
    reviewed_by: str,
    access_hint: str = "unknown",
) -> dict[str, Any]:
    """Immediately revoke native display while retaining immutable evidence."""
    policy = set_source_policy(
        conn,
        source_domain=source_domain,
        display_policy="source_only",
        allowed_artifact_kinds=[],
        publisher_feed_full_text=False,
        rights_basis="revoked",
        access_hint=access_hint,
        reviewed_by=reviewed_by,
        action="revoke",
    )
    return policy


def _resolve_materialized_content(cur, article_id: Any, canonical_url: str) -> None:
    """Re-evaluate policy, then materialize display and analysis pointers."""
    policy = _load_policy(cur, canonical_url)
    allowed_kinds = set(policy.get("allowed_artifact_kinds") or [])
    allowed_feed_urls = {
        normalized
        for value in (policy.get("allowed_feed_urls") or [])
        if (normalized := normalize_feed_url(value))
    }
    policy_allows = (
        policy.get("display_policy") == "native_full_text"
        and rights_basis_is_explicit(policy.get("rights_basis"))
    )

    cur.execute(
        """
        SELECT id, kind, text, version, completeness, confidence,
               origin_url, origin_domain, method, fetched_at, extractor_version
        FROM public.article_content_artifacts
        WHERE article_id = %s AND is_current = true
        ORDER BY CASE kind
                   WHEN 'licensed_api' THEN 400
                   WHEN 'publisher_feed' THEN 300
                   WHEN 'origin_extract' THEN 200
                   WHEN 'legacy_unverified' THEN 50
                   WHEN 'analysis_text' THEN 10
                   ELSE 0
                 END DESC,
                 version DESC
        """,
        (article_id,),
    )
    artifacts = [dict(row) for row in cur.fetchall()]

    display = None
    for artifact in artifacts:
        publisher_feed_is_complete = (
            artifact["kind"] == "publisher_feed"
            and bool(policy.get("publisher_feed_full_text"))
            and normalize_feed_url(artifact.get("origin_url")) in allowed_feed_urls
        )
        effectively_complete = (
            artifact.get("completeness") == "complete"
            or (
                publisher_feed_is_complete
                and artifact.get("completeness") == "unknown"
            )
        )
        eligible = (
            policy_allows
            and artifact["kind"] in allowed_kinds
            and artifact["kind"] in BODY_ARTIFACT_KINDS
            and effectively_complete
            and (artifact["kind"] != "publisher_feed" or publisher_feed_is_complete)
            and float(artifact.get("confidence") or 0.0) >= 0.8
            and (
                artifact["kind"] != "origin_extract"
                or int(artifact.get("extractor_version") or 0) >= EXTRACTOR_VERSION
            )
            and (
                publisher_feed_is_complete
                if artifact["kind"] == "publisher_feed"
                else same_origin(canonical_url, artifact.get("origin_url"))
            )
        )
        cur.execute(
            "UPDATE public.article_content_artifacts SET displayable = %s WHERE id = %s",
            (eligible, artifact["id"]),
        )
        if eligible and display is None:
            display = artifact

    # Analysis can use explicitly separated cross-source context, but it never
    # becomes display text or the legacy body. Prefer publisher/origin bodies.
    analysis = next(
        (a for a in artifacts if a["kind"] in BODY_ARTIFACT_KINDS and a.get("completeness") != "invalid"),
        None,
    ) or next(
        (a for a in artifacts if a["kind"] in {"analysis_text", "legacy_unverified"}),
        None,
    )

    original_is_valid = valid_original_url(canonical_url)
    if display:
        mode = "native_full_text"
        reason = "verified_body_permitted"
        body_state = "verified_full"
        display_id = display["id"]
        excerpt = _excerpt(display["text"])
        display_rights_basis = policy.get("rights_basis")
        display_effective_completeness = "complete"
        display_policy_version = policy.get("version")
    else:
        mode = "source_web" if original_is_valid else "unavailable"
        if not original_is_valid:
            reason = "invalid_or_missing_original_url"
        elif policy.get("display_policy") != "native_full_text":
            reason = "source_policy_default_deny"
        elif not allowed_kinds:
            reason = "no_approved_artifact_kind"
        elif any(a.get("completeness") == "partial" for a in artifacts):
            reason = "body_not_verified_full"
        else:
            reason = "body_unavailable"
        body_state = (
            "partial"
            if any(a.get("completeness") == "partial" for a in artifacts)
            else "none"
        )
        display_id = None
        excerpt = None
        display_rights_basis = None
        display_effective_completeness = None
        display_policy_version = None

    analysis_id = analysis["id"] if analysis else None
    analysis_version = analysis["version"] if analysis else None
    analysis_text = analysis["text"] if analysis else None
    # The ambiguous legacy field is display-owned, not analysis-owned. Older
    # clients may receive a body only when the same policy/artifact contract
    # would permit the native reader. Ranking/chat use ``analysis_text``.
    legacy_content = display["text"] if display else None
    cur.execute(
        """
        UPDATE public.articles
        SET canonical_source_domain = %s,
            presentation_mode = %s,
            presentation_reason = %s,
            body_state = %s,
            content_access_hint = %s,
            display_content_artifact_id = %s,
            display_body_excerpt = %s,
            display_rights_basis = %s,
            display_effective_completeness = %s,
            display_policy_version = %s,
            analysis_content_artifact_id = %s,
            analysis_text = %s,
            analysis_content_version = %s,
            content = %s,
            content_extracted = %s,
            embedding = CASE
                WHEN analysis_content_artifact_id IS DISTINCT FROM %s THEN NULL
                ELSE embedding
            END,
            embedding_content_version = CASE
                WHEN analysis_content_artifact_id IS DISTINCT FROM %s THEN NULL
                ELSE embedding_content_version
            END,
            content_quality = CASE
                WHEN analysis_content_artifact_id IS DISTINCT FROM %s THEN NULL
                ELSE content_quality
            END,
            content_quality_content_version = CASE
                WHEN analysis_content_artifact_id IS DISTINCT FROM %s THEN NULL
                ELSE content_quality_content_version
            END,
            enrichment_completed = CASE
                WHEN analysis_content_artifact_id IS DISTINCT FROM %s THEN false
                ELSE enrichment_completed
            END,
            enrichment_attempts = CASE
                WHEN analysis_content_artifact_id IS DISTINCT FROM %s THEN 0
                ELSE enrichment_attempts
            END
        WHERE id = %s
        """,
        (
            normalized_domain(canonical_url),
            mode,
            reason,
            body_state,
            policy.get("access_hint") or "unknown",
            display_id,
            excerpt,
            display_rights_basis,
            display_effective_completeness,
            display_policy_version,
            analysis_id,
            analysis_text,
            analysis_version,
            legacy_content,
            bool(legacy_content),
            analysis_id,
            analysis_id,
            analysis_id,
            analysis_id,
            analysis_id,
            analysis_id,
            article_id,
        ),
    )


def _record_content_artifact(
    conn,
    article_id: Any,
    *,
    kind: str,
    text: str,
    origin_url: str,
    method: str,
    completeness: str,
    confidence: float,
    extractor_version: int = EXTRACTOR_VERSION,
    fetched_at: datetime | None = None,
) -> int | None:
    """Append an artifact version and re-resolve the materialized contract.

    Origin extracts are rejected unless their origin matches the immutable
    canonical article URL. Publisher-feed artifacts retain the exact feed URL
    that supplied them and only become displayable when that URL appears in an
    audited policy allowlist. ``analysis_text`` is never displayable.
    """
    if kind not in ARTIFACT_KINDS:
        raise ValueError(f"unsupported artifact kind: {kind}")
    if completeness not in COMPLETENESS_STATES:
        raise ValueError(f"unsupported completeness: {completeness}")
    clean = _normalize_text(text)
    if not clean:
        return None
    if len(clean) > MAX_ARTIFACT_CHARS:
        clean = clean[:MAX_ARTIFACT_CHARS]
        completeness = "partial"
    confidence = max(0.0, min(float(confidence), 1.0))
    content_hash = hashlib.sha256(clean.encode("utf-8")).hexdigest()
    fetched_at = fetched_at or datetime.now(timezone.utc)

    with conn.cursor() as cur:
        # This lock serializes version allocation and artifact selection for an
        # article. Job callers already lock job -> article in the same order.
        cur.execute(
            "SELECT url, content_version FROM public.articles WHERE id = %s FOR UPDATE",
            (article_id,),
        )
        article = cur.fetchone()
        if not article:
            return None
        canonical_url = article.get("url")
        body_origin_is_valid = (
            normalize_feed_url(origin_url) != ""
            if kind == "publisher_feed"
            else same_origin(canonical_url, origin_url)
        )
        if kind in BODY_ARTIFACT_KINDS and not body_origin_is_valid:
            logger.warning(
                "Rejected cross-origin %s artifact for article %s (%s -> %s)",
                kind,
                article_id,
                normalized_domain(canonical_url),
                normalized_domain(origin_url),
            )
            return None

        policy = _load_policy(cur, canonical_url)
        cur.execute(
            """
            SELECT id, origin_url, method, rights_basis, completeness,
                   confidence, extractor_version
            FROM public.article_content_artifacts
            WHERE article_id = %s AND kind = %s AND content_hash = %s
              AND is_current = true
            """,
            (article_id, kind, content_hash),
        )
        duplicate = cur.fetchone()
        rights_basis = policy.get("rights_basis") or "unknown"
        if duplicate and (
            duplicate.get("origin_url") == origin_url
            and duplicate.get("method") == method
            and duplicate.get("rights_basis") == rights_basis
            and duplicate.get("completeness") == completeness
            and float(duplicate.get("confidence") or 0.0) == confidence
            and int(duplicate.get("extractor_version") or 0) == int(extractor_version)
        ):
            _resolve_materialized_content(cur, article_id, canonical_url)
            return int(duplicate["id"])

        version = int(article.get("content_version") or 0) + 1
        cur.execute(
            """
            UPDATE public.article_content_artifacts
            SET is_current = false, displayable = false
            WHERE article_id = %s AND kind = %s AND is_current = true
            """,
            (article_id, kind),
        )
        cur.execute(
            """
            INSERT INTO public.article_content_artifacts (
                article_id, kind, text, origin_url, origin_domain, method,
                rights_basis, completeness, confidence, content_hash,
                fetched_at, extractor_version, displayable, version
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, false, %s)
            RETURNING id
            """,
            (
                article_id,
                kind,
                clean,
                origin_url,
                normalized_domain(origin_url),
                method,
                rights_basis,
                completeness,
                confidence,
                content_hash,
                fetched_at,
                int(extractor_version),
                version,
            ),
        )
        artifact_id = int(cur.fetchone()["id"])
        cur.execute(
            "UPDATE public.articles SET content_version = %s WHERE id = %s",
            (version, article_id),
        )
        _resolve_materialized_content(cur, article_id, canonical_url)
        return artifact_id


def record_content_artifact(
    conn,
    article_id: Any,
    *,
    kind: str,
    text: str,
    origin_url: str,
    method: str,
    completeness: str,
    confidence: float,
    extractor_version: int = EXTRACTOR_VERSION,
    fetched_at: datetime | None = None,
) -> int | None:
    """Crash-consistent public wrapper around artifact materialization."""
    with article_content_transaction(conn):
        return _record_content_artifact(
            conn,
            article_id,
            kind=kind,
            text=text,
            origin_url=origin_url,
            method=method,
            completeness=completeness,
            confidence=confidence,
            extractor_version=extractor_version,
            fetched_at=fetched_at,
        )


def register_ingested_article(
    conn,
    article_id: Any,
    *,
    canonical_url: str,
    feed_content: str | None,
    feed_url: str | None = None,
) -> None:
    """Attach publisher-feed provenance or enqueue origin extraction.

    Only a reviewed full-text feed invalidates an in-flight lower-precedence
    extraction lease. An unreviewed long feed entry is retained as analysis
    context while origin extraction remains pending.
    """
    clean_feed = _normalize_text(feed_content)
    feed_origin_url = normalize_feed_url(feed_url)
    with article_content_transaction(conn):
        # The surrounding ingestion upsert may already own this article row.
        # Lock it first everywhere, then the job, to prevent article/job cycles.
        with conn.cursor() as cur:
            cur.execute(
                "SELECT url FROM public.articles WHERE id = %s FOR UPDATE",
                (article_id,),
            )
            article = cur.fetchone()
            if not article:
                raise ValueError(f"unknown article_id: {article_id}")
            cur.execute(
                """
                INSERT INTO public.article_content_jobs (article_id, state)
                VALUES (%s, 'pending')
                ON CONFLICT (article_id) DO NOTHING
                """,
                (article_id,),
            )
            cur.execute(
                """
                SELECT state, version, final_outcome
                FROM public.article_content_jobs
                WHERE article_id = %s
                FOR UPDATE
                """,
                (article_id,),
            )
            job = cur.fetchone()
            if not job:
                raise ValueError(f"unknown article_id: {article_id}")
            stored_url = article.get("url") or canonical_url

            if not valid_original_url(stored_url):
                if not (
                    job.get("state") == "terminal_failure"
                    and job.get("final_outcome") == "unavailable"
                ):
                    previous_version = int(job.get("version") or 0)
                    cur.execute(
                        """
                        UPDATE public.article_content_jobs
                        SET state = 'terminal_failure', failure_class = 'invalid_url',
                            failure_reason = 'invalid_or_missing_original_url',
                            next_retry_at = NULL, lease_owner = NULL,
                            lease_expires_at = NULL, version = version + 1,
                            final_outcome = 'unavailable', updated_at = now(),
                            completed_at = now()
                        WHERE article_id = %s AND version = %s
                        """,
                        (article_id, previous_version),
                    )
                    if cur.rowcount != 1:
                        raise _StaleCompletion("ingestion job CAS failed")
                _resolve_materialized_content(cur, article_id, stored_url)
                return

            policy = _load_policy(cur, stored_url)
            if not clean_feed:
                _resolve_materialized_content(cur, article_id, stored_url)
                if (
                    job.get("state") == "ready"
                    and policy.get("display_policy") == "native_full_text"
                    and "origin_extract" in set(policy.get("allowed_artifact_kinds") or [])
                ):
                    cur.execute(
                        "SELECT display_content_artifact_id FROM public.articles WHERE id = %s",
                        (article_id,),
                    )
                    resolved = cur.fetchone()
                    if resolved and resolved.get("display_content_artifact_id") is None:
                        cur.execute(
                            """
                            UPDATE public.article_content_jobs
                            SET state = 'pending', failure_class = NULL,
                                failure_reason = NULL, next_retry_at = NULL,
                                attempt_count = 0, lease_owner = NULL,
                                lease_expires_at = NULL, version = version + 1,
                                final_outcome = NULL, updated_at = now(),
                                completed_at = NULL
                            WHERE article_id = %s AND state = 'ready'
                            """,
                            (article_id,),
                        )
                return

            # A body without its acquisition principal cannot safely inherit a
            # publisher's rights policy. Preserve it for ranking/audit only.
            if not feed_origin_url:
                record_content_artifact(
                    conn,
                    article_id,
                    kind="legacy_unverified",
                    text=clean_feed,
                    origin_url=stored_url,
                    method="publisher_feed_missing_origin",
                    completeness="unknown",
                    confidence=0.0,
                    extractor_version=EXTRACTOR_VERSION,
                )
                logger.warning(
                    "Quarantined feed text without an HTTPS feed identity for article %s",
                    article_id,
                )
                return

            approved_feed_urls = {
                normalized
                for value in (policy.get("allowed_feed_urls") or [])
                if (normalized := normalize_feed_url(value))
            }
            publisher_feed_is_full = bool(
                policy.get("display_policy") == "native_full_text"
                and rights_basis_is_explicit(policy.get("rights_basis"))
                and policy.get("publisher_feed_full_text")
                and "publisher_feed" in set(policy.get("allowed_artifact_kinds") or [])
                and feed_origin_url in approved_feed_urls
            )

            feed_completeness = (
                "complete" if publisher_feed_is_full else "unknown"
            )
            cur.execute(
                """
                SELECT id, content_hash, completeness, rights_basis,
                       confidence, extractor_version, method, origin_url
                FROM public.article_content_artifacts
                WHERE article_id = %s AND kind = 'publisher_feed'
                  AND is_current = true
                """,
                (article_id,),
            )
            existing = cur.fetchone()
            feed_hash = hashlib.sha256(clean_feed.encode("utf-8")).hexdigest()
            unchanged = bool(
                existing
                and existing.get("content_hash") == feed_hash
                and existing.get("completeness") == feed_completeness
                and existing.get("rights_basis") == (policy.get("rights_basis") or "unknown")
                and float(existing.get("confidence") or 0.0) == 1.0
                and int(existing.get("extractor_version") or 0) == EXTRACTOR_VERSION
                and existing.get("method") == "publisher_feed"
                and existing.get("origin_url") == feed_origin_url
            )
            if (
                unchanged
                and publisher_feed_is_full
                and job.get("state") == "ready"
                and job.get("final_outcome") == "publisher_feed"
            ):
                _resolve_materialized_content(cur, article_id, stored_url)
                return

        artifact_id = record_content_artifact(
            conn,
            article_id,
            kind="publisher_feed",
            text=clean_feed,
            origin_url=feed_origin_url,
            method="publisher_feed",
            completeness=feed_completeness,
            confidence=1.0,
            extractor_version=EXTRACTOR_VERSION,
        )
        if artifact_id is None:
            raise ValueError("publisher feed artifact failed source validation")

        # A substantial feed entry is still only analysis text until a human-
        # reviewed source policy declares that this publisher's feed carries
        # the complete article. Keep the origin job/lease alive in that case.
        if not publisher_feed_is_full:
            return

        with conn.cursor() as cur:
            previous_version = int(job.get("version") or 0)
            cur.execute(
                """
                UPDATE public.article_content_jobs
                SET state = 'ready', failure_class = NULL, failure_reason = NULL,
                    next_retry_at = NULL, lease_owner = NULL,
                    lease_expires_at = NULL, version = version + 1,
                    final_outcome = 'publisher_feed', updated_at = now(),
                    completed_at = now()
                WHERE article_id = %s AND version = %s
                RETURNING version
                """,
                (article_id, previous_version),
            )
            if cur.rowcount != 1:
                raise _StaleCompletion("publisher feed job CAS failed")
            updated = cur.fetchone()
            outcome_version = int(updated["version"])
        _record_final_outcome(
            conn,
            article_id=article_id,
            job_version=outcome_version,
            outcome="publisher_feed",
            extracted={
                "content": clean_feed,
                "extraction_method": "publisher_feed",
            },
            failure_class=None,
            duration_ms=None,
        )


def classify_failure(extracted: Mapping[str, Any]) -> str:
    """Return one stable terminal/retry taxonomy code.

    Extractor ``error`` codes are more specific than broad transport classes,
    so they take precedence. Older workers are normalized conservatively.
    """
    error = str(extracted.get("error") or "").strip().lower().replace(" ", "_")
    aliases = {
        "paywall": "paywall_detected",
        "paywalled": "paywall_detected",
        "subscription_required": "paywall_detected",
        "login_wall": "login_required",
        "private_address": "unsafe_address",
        "unsafe_url": "unsafe_address",
        "title_mismatch": "origin_mismatch",
        "canonical_domain_mismatch": "origin_mismatch",
        "redirected_domain_mismatch": "origin_mismatch",
        "identity_mismatch": "origin_mismatch",
        "invalid_document": "identity_unverified",
    }
    if error:
        normalized = aliases.get(error, error)
        known_prefixes = (
            "invalid_", "unsafe_", "redirect_", "dns_", "network_",
            "unsupported_", "response_", "partial_", "empty_",
            "identity_", "origin_", "paywall", "login_", "consent_",
            "error_page", "article_too_", "timeout", "rate_",
        )
        if normalized == "http_status":
            pass
        elif normalized.startswith(known_prefixes):
            return normalized[:80]

    status = extracted.get("http_status")
    try:
        status = int(status) if status is not None else None
    except (TypeError, ValueError):
        status = None
    if status in {401, 403, 451}:
        return "access_denied"
    if status in {404, 410}:
        return "not_found"
    if status == 429:
        return "rate_limited"
    if status in {408, 425}:
        return "timeout"
    if status is not None and 500 <= status <= 599:
        return "server_error"
    if status is not None and 400 <= status <= 499:
        return "http_client_error"

    state = str(extracted.get("content_state") or "").strip().lower()
    state_codes = {
        "paywalled": "paywall_detected",
        "login_required": "login_required",
        "consent_required": "consent_required",
        "identity_mismatch": "origin_mismatch",
        "partial": "partial_document",
        "empty": "empty_document",
    }
    if state in state_codes:
        return state_codes[state]

    explicit = str(extracted.get("failure_class") or "").strip().lower()
    explicit_codes = {
        "identity": "identity_unverified",
        "origin_mismatch": "origin_mismatch",
        "identity_unverified": "identity_unverified",
        "network": "network_error",
        "http": "http_error",
        "access": "access_denied",
        "quality": "partial_document",
        "unsupported": "unsupported_content_type",
        "security": "unsafe_address",
        "internal": "extractor_internal_error",
    }
    return explicit_codes.get(explicit, explicit[:80] or "extraction_failed")


def failure_is_terminal(extracted: Mapping[str, Any], failure_class: str) -> bool:
    """Classify permanent handoffs separately from safe background retries."""
    if failure_class in _TERMINAL_FAILURES or failure_class in {
        "identity_unverified",
        "origin_mismatch",
        "http_client_error",
        "article_too_long",
    }:
        return True
    status = extracted.get("http_status")
    try:
        status = int(status) if status is not None else None
    except (TypeError, ValueError):
        status = None
    if status in {401, 403, 404, 410, 451}:
        return True
    if status is not None and 400 <= status <= 499 and status not in {408, 425, 429}:
        return True
    return False


def retry_delay_seconds(
    attempt_count: int,
    *,
    retry_after_seconds: Any = None,
    jitter_key: str = "",
) -> int:
    """Exponential retry delay honoring Retry-After plus stable positive jitter."""
    index = min(max(int(attempt_count) - 1, 0), len(_RETRY_DELAYS_SECONDS) - 1)
    base = _RETRY_DELAYS_SECONDS[index]
    try:
        retry_after = int(retry_after_seconds)
    except (TypeError, ValueError, OverflowError):
        retry_after = 0
    retry_after = max(0, min(retry_after, 86_400))
    base = max(base, retry_after)
    jitter_ceiling = min(max(5, base // 5), 900)
    digest = hashlib.sha256(
        f"{jitter_key}:{attempt_count}:{base}".encode("utf-8")
    ).digest()
    jitter = int.from_bytes(digest[:4], "big") % (jitter_ceiling + 1)
    return min(86_400, base + jitter)


def _record_final_outcome(
    conn,
    *,
    article_id: Any,
    job_version: int,
    outcome: str,
    extracted: Mapping[str, Any],
    failure_class: str | None,
    duration_ms: int | None,
) -> None:
    """Best-effort article-level outcome; never controls retry state."""
    def _insert() -> None:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO public.article_content_outcomes (
                    article_id, job_version, outcome, method, char_count,
                    failure_class, duration_ms
                ) VALUES (%s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (article_id, job_version) DO NOTHING
                """,
                (
                    article_id,
                    job_version,
                    outcome,
                    extracted.get("extraction_method"),
                    len(_normalize_text(
                        extracted.get("content") or extracted.get("partial_content")
                    )),
                    failure_class,
                    duration_ms,
                ),
            )

    try:
        # psycopg nests this as a savepoint, so a telemetry failure does not
        # poison or roll back the authoritative state transaction.
        transaction = getattr(conn, "transaction", None)
        if transaction:
            with transaction():
                _insert()
        else:  # small test doubles
            _insert()
    except Exception:
        logger.exception("Failed to record final content outcome for %s", article_id)


def complete_content_job(
    conn,
    *,
    article_id: Any,
    worker_id: str,
    job_version: int,
    extracted: Mapping[str, Any],
    duration_ms: int | None = None,
) -> bool:
    """Complete a leased job iff its owner/version still match.

    Returns ``False`` for a stale worker. No artifact or canonical metadata is
    changed in that case.
    """
    stale = False
    try:
        with article_content_transaction(conn):
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT url FROM public.articles WHERE id = %s FOR UPDATE",
                    (article_id,),
                )
                article = cur.fetchone()
                canonical_url = article.get("url") if article else ""
                cur.execute(
                    """
                    SELECT state, lease_owner, version, attempt_count,
                           (lease_expires_at > now()) AS lease_is_live
                    FROM public.article_content_jobs
                    WHERE article_id = %s
                    FOR UPDATE
                    """,
                    (article_id,),
                )
                job = cur.fetchone()
                if (
                    not job
                    or job.get("state") != "leased"
                    or job.get("lease_owner") != worker_id
                    or int(job.get("version") or -1) != int(job_version)
                    or job.get("lease_is_live") is not True
                ):
                    raise _StaleCompletion("lease owner/version no longer current")

            if not article or not valid_original_url(canonical_url):
                failure_class = "invalid_url"
            else:
                content = _normalize_text(extracted.get("content"))
                partial = _normalize_text(extracted.get("partial_content"))
                completeness = extracted.get("completeness")
                identity_valid = extracted.get("identity_valid") is True
                content_state = extracted.get("content_state")
                try:
                    confidence = float(extracted.get("confidence") or 0.0)
                except (TypeError, ValueError, OverflowError):
                    confidence = 0.0
                try:
                    reported_extractor_version = int(
                        extracted.get("extractor_version") or 0
                    )
                except (TypeError, ValueError, OverflowError):
                    reported_extractor_version = 0
                origin_url = str(
                    extracted.get("canonical_url")
                    or extracted.get("final_url")
                    or canonical_url
                )
                verified = (
                    bool(content)
                    and content_state == "complete"
                    and completeness == "complete"
                    and identity_valid
                    and confidence >= 0.8
                    and reported_extractor_version >= EXTRACTOR_VERSION
                    and same_origin(canonical_url, origin_url)
                )

                if verified:
                    artifact_id = record_content_artifact(
                        conn,
                        article_id,
                        kind="origin_extract",
                        text=content,
                        origin_url=origin_url,
                        method=str(extracted.get("extraction_method") or "origin_extract"),
                        completeness="complete",
                        confidence=confidence,
                        extractor_version=reported_extractor_version,
                    )
                    if artifact_id is None:
                        raise _StaleCompletion("verified artifact was rejected")
                    with conn.cursor() as cur:
                        cur.execute(
                            """
                            UPDATE public.article_content_jobs
                            SET state = 'ready', failure_class = NULL,
                                failure_reason = NULL, next_retry_at = NULL,
                                lease_owner = NULL, lease_expires_at = NULL,
                                final_outcome = 'verified_full', updated_at = now(),
                                completed_at = now()
                            WHERE article_id = %s AND state = 'leased'
                              AND lease_owner = %s AND version = %s
                              AND lease_expires_at > now()
                            """,
                            (article_id, worker_id, job_version),
                        )
                        if cur.rowcount != 1:
                            raise _StaleCompletion("completion CAS failed")
                    _record_final_outcome(
                        conn,
                        article_id=article_id,
                        job_version=job_version,
                        outcome="verified_full",
                        extracted=extracted,
                        failure_class=None,
                        duration_ms=duration_ms,
                    )
                    return True

                classified = classify_failure(extracted)
                otherwise_verified_but_outdated = bool(
                    content
                    and content_state == "complete"
                    and completeness == "complete"
                    and identity_valid
                    and confidence >= 0.8
                    and same_origin(canonical_url, origin_url)
                    and reported_extractor_version < EXTRACTOR_VERSION
                )
                identity_independent_failures = _TERMINAL_FAILURES | {
                    "network_error", "dns_failure", "timeout", "rate_limited",
                    "server_error", "http_error", "extractor_internal_error",
                }
                if otherwise_verified_but_outdated:
                    failure_class = "extractor_outdated"
                elif classified in identity_independent_failures:
                    failure_class = classified
                elif not identity_valid and (content or partial):
                    failure_class = (
                        classified
                        if classified in {"origin_mismatch", "identity_unverified"}
                        else "identity_unverified"
                    )
                elif not same_origin(canonical_url, origin_url):
                    failure_class = "origin_mismatch"
                elif completeness == "invalid":
                    failure_class = "identity_unverified"
                elif content_state == "complete" and confidence < 0.8:
                    failure_class = "identity_unverified"
                else:
                    failure_class = classified

                # A same-origin, identity-validated partial may help ranking and
                # diagnostics, but it is never a ready/native body.
                if (
                    partial
                    and identity_valid
                    and same_origin(canonical_url, origin_url)
                    and completeness == "partial"
                ):
                    record_content_artifact(
                        conn,
                        article_id,
                        kind="origin_extract",
                        text=partial,
                        origin_url=origin_url,
                        method=str(extracted.get("extraction_method") or "origin_extract"),
                        completeness="partial",
                        confidence=confidence,
                        extractor_version=max(reported_extractor_version, 1),
                    )

            attempt_count = int(job.get("attempt_count") or 0)
            terminal = failure_is_terminal(extracted, failure_class) or attempt_count >= MAX_JOB_ATTEMPTS
            state = "terminal_failure" if terminal else "retryable_failure"
            outcome = (
                "unavailable"
                if terminal and not valid_original_url(canonical_url)
                else "source_web" if terminal
                else "retryable_failure"
            )
            delay = retry_delay_seconds(
                attempt_count,
                retry_after_seconds=extracted.get("retry_after_seconds"),
                jitter_key=f"{article_id}:{job_version}",
            )
            reason = str(
                extracted.get("error_reason")
                or extracted.get("error")
                or failure_class
            )[:500]
            with conn.cursor() as cur:
                cur.execute(
                    """
                    UPDATE public.article_content_jobs
                    SET state = %s, failure_class = %s, failure_reason = %s,
                        next_retry_at = CASE WHEN %s THEN NULL
                                             ELSE now() + (%s * interval '1 second') END,
                        lease_owner = NULL, lease_expires_at = NULL,
                        final_outcome = %s, updated_at = now(),
                        completed_at = CASE WHEN %s THEN now() ELSE NULL END
                    WHERE article_id = %s AND state = 'leased'
                      AND lease_owner = %s AND version = %s
                      AND lease_expires_at > now()
                    """,
                    (
                        state,
                        failure_class,
                        reason,
                        terminal,
                        delay,
                        outcome,
                        terminal,
                        article_id,
                        worker_id,
                        job_version,
                    ),
                )
                if cur.rowcount != 1:
                    raise _StaleCompletion("failure CAS failed")
                access_hints = {
                    "paywall_detected": (
                        "subscription_may_be_required",
                        "publisher_access_control",
                    ),
                    "login_required": (
                        "publisher_sign_in_required",
                        "publisher_access_control",
                    ),
                    "consent_required": (
                        "publisher_consent_required",
                        "publisher_access_control",
                    ),
                }
                if terminal and failure_class in access_hints:
                    access_hint, presentation_reason = access_hints[failure_class]
                    cur.execute(
                        """
                        UPDATE public.articles
                        SET content_access_hint = %s,
                            presentation_reason = CASE
                                WHEN display_content_artifact_id IS NULL THEN %s
                                ELSE presentation_reason
                            END
                        WHERE id = %s
                        """,
                        (access_hint, presentation_reason, article_id),
                    )
            _record_final_outcome(
                conn,
                article_id=article_id,
                job_version=job_version,
                outcome=outcome,
                extracted=extracted,
                failure_class=failure_class,
                duration_ms=duration_ms,
            )
            return True
    except _StaleCompletion:
        stale = True

    if stale:
        _record_final_outcome(
            conn,
            article_id=article_id,
            job_version=job_version,
            outcome="stale_discarded",
            extracted=extracted,
            failure_class="stale_lease",
            duration_ms=duration_ms,
        )
        return False
    return True


def record_analysis_context(
    conn,
    article_id: Any,
    *,
    text: str,
    source_url: str,
    method: str = "tavily_related_coverage",
) -> int | None:
    """Store optional non-display analysis without touching publisher bodies."""
    return record_content_artifact(
        conn,
        article_id,
        kind="analysis_text",
        text=text,
        origin_url=source_url,
        method=method,
        completeness="unknown",
        confidence=0.0,
    )


def worker_identity() -> str:
    return f"{os.getenv('GIT_SHA', 'unknown')}:{os.getpid()}"
