"""
Article enrichment service.
Runs after content extraction to:
1. Expand thin article content using OpenAI
2. Recover source-authentic images for articles without images

Supports retry: articles without images are retried up to MAX_ENRICHMENT_ATTEMPTS
times. Content expansion is skipped on retry if content is already adequate.
"""
import asyncio
import logging

from app.services.image_extraction import fetch_best_source_image

logger = logging.getLogger(__name__)

# Articles with content shorter than this get AI-expanded summaries
MIN_CONTENT_LENGTH = 200

# Max articles to enrich per cycle
ENRICHMENT_BATCH_SIZE = 25
ENRICHMENT_CONCURRENCY = 6

# Max retry attempts for image enrichment
MAX_ENRICHMENT_ATTEMPTS = 3


async def enrich_articles(conn) -> dict:
    """
    Find articles that have been content-extracted but not yet enriched,
    and enrich them (expand thin content, recover missing source images).

    Returns dict with counts: {"content_enriched": int, "images_found": int}
    """
    from app.services.openai_service import get_openai_service

    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT id, url, title, summary, content, image_url, enrichment_attempts
            FROM public.articles
            WHERE content_extracted = true
              AND enrichment_completed = false
              AND enrichment_attempts < %s
            ORDER BY ingested_at DESC
            LIMIT %s
            """,
            (MAX_ENRICHMENT_ATTEMPTS, ENRICHMENT_BATCH_SIZE),
        )
        pending = cur.fetchall()

    if not pending:
        return {"content_enriched": 0, "images_found": 0}

    openai_service = get_openai_service()
    semaphore = asyncio.Semaphore(ENRICHMENT_CONCURRENCY)
    stats = {"content_enriched": 0, "images_found": 0}

    async def _enrich_one(row):
        async with semaphore:
            updates = {}

            # 1. Content enrichment: only if content is thin AND not already expanded
            content = row.get("content") or ""
            if len(content.strip()) < MIN_CONTENT_LENGTH:
                expanded = await openai_service.generate_expanded_summary(
                    title=row.get("title", ""),
                    summary=row.get("summary", ""),
                    content=content,
                )
                if expanded:
                    updates["content"] = expanded
                    stats["content_enriched"] += 1

            # 2. Image enrichment: if no image_url
            if not row.get("image_url"):
                image_url = await fetch_best_source_image(row.get("url", ""), timeout=5.0)
                if image_url:
                    updates["image_url"] = image_url
                    stats["images_found"] += 1

            # 3. Determine completion: completed if image found/present or attempts exhausted
            attempts = (row.get("enrichment_attempts") or 0) + 1
            has_image = bool(row.get("image_url") or updates.get("image_url"))
            completed = has_image or attempts >= MAX_ENRICHMENT_ATTEMPTS

            _apply_enrichment(conn, row["id"], updates, completed, attempts)

    await asyncio.gather(
        *[_enrich_one(row) for row in pending],
        return_exceptions=True,
    )

    return stats


def _apply_enrichment(conn, article_id, updates: dict, completed: bool, attempts: int):
    """Apply enrichment updates, increment attempts, and optionally mark completed."""
    try:
        with conn.cursor() as cur:
            set_clauses = ["enrichment_attempts = %s"]
            params = [attempts]

            if completed:
                set_clauses.append("enrichment_completed = true")

            if updates.get("content"):
                set_clauses.append("content = %s")
                params.append(updates["content"])

            if updates.get("image_url"):
                set_clauses.append("image_url = %s")
                params.append(updates["image_url"])

            params.append(article_id)
            cur.execute(
                f"UPDATE public.articles SET {', '.join(set_clauses)} WHERE id = %s",
                params,
            )
    except Exception:
        logger.exception("Error applying enrichment for article %s", article_id)
