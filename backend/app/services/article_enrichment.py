"""
Article enrichment service.
Runs after content extraction to:
1. Expand thin article content using OpenAI
2. Find images for articles without images using Unsplash
"""
import asyncio
import logging

logger = logging.getLogger(__name__)

# Articles with content shorter than this get AI-expanded summaries
MIN_CONTENT_LENGTH = 200

# Max articles to enrich per cycle
ENRICHMENT_BATCH_SIZE = 10
ENRICHMENT_CONCURRENCY = 3


async def enrich_articles(conn) -> dict:
    """
    Find articles that have been content-extracted but not yet enriched,
    and enrich them (expand thin content, find missing images).

    Returns dict with counts: {"content_enriched": int, "images_found": int}
    """
    from app.services.openai_service import get_openai_service

    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT id, url, title, summary, content, image_url
            FROM public.articles
            WHERE content_extracted = true
              AND enrichment_completed = false
            ORDER BY ingested_at DESC
            LIMIT %s
            """,
            (ENRICHMENT_BATCH_SIZE,),
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

            # 1. Content enrichment: if content is thin
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
                search_query = row.get("title", "")[:80]
                candidates = await openai_service.search_unsplash_images(
                    query=search_query, per_page=5
                )
                if candidates:
                    best = await openai_service.select_best_image(
                        article={
                            "title": row.get("title"),
                            "summary": row.get("summary"),
                        },
                        image_candidates=candidates,
                    )
                    if best and best.get("url"):
                        updates["image_url"] = best["url"]
                        stats["images_found"] += 1

            # 3. Mark enrichment as completed (even if nothing was enriched)
            _apply_enrichment(conn, row["id"], updates)

    await asyncio.gather(
        *[_enrich_one(row) for row in pending],
        return_exceptions=True,
    )

    return stats


def _apply_enrichment(conn, article_id, updates: dict):
    """Apply enrichment updates and mark the article as enrichment_completed."""
    try:
        with conn.cursor() as cur:
            if updates.get("content") and updates.get("image_url"):
                cur.execute(
                    """
                    UPDATE public.articles
                    SET content = %s, image_url = %s, enrichment_completed = true
                    WHERE id = %s
                    """,
                    (updates["content"], updates["image_url"], article_id),
                )
            elif updates.get("content"):
                cur.execute(
                    """
                    UPDATE public.articles
                    SET content = %s, enrichment_completed = true
                    WHERE id = %s
                    """,
                    (updates["content"], article_id),
                )
            elif updates.get("image_url"):
                cur.execute(
                    """
                    UPDATE public.articles
                    SET image_url = %s, enrichment_completed = true
                    WHERE id = %s
                    """,
                    (updates["image_url"], article_id),
                )
            else:
                cur.execute(
                    "UPDATE public.articles SET enrichment_completed = true WHERE id = %s",
                    (article_id,),
                )
    except Exception:
        logger.exception("Error applying enrichment for article %s", article_id)
