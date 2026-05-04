"""
Phase 1 telemetry: persist per-extraction outcome and per-attempt history.

The static cascade in `content_extractor.extract_article_content` returns
`extraction_method`, `domain`, and `attempts` alongside the content. This
helper writes those into:
  * `articles.extraction_method | extraction_attempt_count | extraction_domain`
  * `extraction_attempts` history rows
"""
from __future__ import annotations

import logging
from typing import Any, Iterable, Mapping

logger = logging.getLogger(__name__)


def record_extraction(
    conn,
    article_id: Any,
    url: str,
    extracted: Mapping[str, Any],
) -> None:
    """Persist extraction telemetry for a single attempt cycle.

    Best-effort: any error here is logged and swallowed so a telemetry
    failure can never break the extraction path.
    """
    try:
        domain = extracted.get("domain") or ""
        method = extracted.get("extraction_method")
        attempts: Iterable[Mapping[str, Any]] = extracted.get("attempts") or []

        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE public.articles
                SET extraction_method = %s,
                    extraction_attempt_count = COALESCE(extraction_attempt_count, 0) + 1,
                    extraction_domain = COALESCE(NULLIF(%s, ''), extraction_domain)
                WHERE id = %s
                """,
                (method, domain, article_id),
            )
            for a in attempts:
                cur.execute(
                    """
                    INSERT INTO public.extraction_attempts
                        (article_id, domain, method, char_count, duration_ms, error)
                    VALUES (%s, %s, %s, %s, %s, %s)
                    """,
                    (
                        article_id,
                        domain or "",
                        a.get("method") or "unknown",
                        int(a.get("char_count") or 0),
                        a.get("duration_ms"),
                        (a.get("error") or None),
                    ),
                )
    except Exception:
        logger.exception("extraction_telemetry: failed to record %s", url[:100])
