"""
Article enrichment service.
Runs after content extraction to ensure every article has:
1. Substantial content (≥300 chars) — via web search fallback + LLM synthesis
2. A relevant image — via source extraction → Unsplash → Gemini generation
3. A content_quality score for feed ranking

Enrichment stages (each attempt tries the next available stage):
  Content: trafilatura (already done) → Tavily web search → LLM synthesis → LLM expansion
  Images:  source page → Unsplash search + GPT selection → Gemini image generation
"""
import asyncio
import logging

from app.services.image_extraction import fetch_best_source_image

logger = logging.getLogger(__name__)

# Thresholds
MIN_CONTENT_LENGTH = 300  # chars — below this, content needs enrichment
GOOD_CONTENT_LENGTH = 500  # chars — above this, content is considered good

# Batch config
ENRICHMENT_BATCH_SIZE = 25
ENRICHMENT_CONCURRENCY = 6
MAX_ENRICHMENT_ATTEMPTS = 5


def compute_content_quality(content: str | None, image_url: str | None, web_searched: bool = False) -> float:
    """
    Compute a 0-1 quality score based on content length and image presence.

    1.0 = content >= 500 chars + has image + original source
    0.8 = content >= 500 chars + has image + web-search-sourced
    0.6 = content >= 300 chars + has image
    0.4 = content >= 300 chars + no image
    0.2 = content < 300 chars (thin)
    0.0 = no content
    """
    content_len = len((content or "").strip())
    has_image = bool(image_url)

    if content_len == 0:
        return 0.0
    if content_len < MIN_CONTENT_LENGTH:
        return 0.2
    if content_len < GOOD_CONTENT_LENGTH:
        return 0.6 if has_image else 0.4
    # content >= 500
    if not has_image:
        return 0.4
    if web_searched:
        return 0.8
    return 1.0


async def enrich_articles(conn) -> dict:
    """
    Find articles that have been content-extracted but not yet enriched,
    and enrich them (expand thin content, recover/generate images).

    Returns dict with counts.
    """
    from app.services.openai_service import get_openai_service
    from app.services.web_search_service import get_web_search_service
    from app.services.image_generation_service import get_image_generation_service

    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT id, url, title, summary, content, image_url,
                   enrichment_attempts, category
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
        return {"content_enriched": 0, "images_found": 0, "images_generated": 0}

    openai_svc = get_openai_service()
    search_svc = get_web_search_service()
    image_gen_svc = get_image_generation_service()
    semaphore = asyncio.Semaphore(ENRICHMENT_CONCURRENCY)
    stats = {"content_enriched": 0, "images_found": 0, "images_generated": 0}

    async def _enrich_one(row):
        async with semaphore:
            updates = {}
            web_searched = False

            title = row.get("title", "")
            summary = row.get("summary", "")
            content = (row.get("content") or "").strip()
            category = row.get("category", "")

            # ── CONTENT ENRICHMENT ──────────────────────────────────────
            if len(content) < MIN_CONTENT_LENGTH:
                search_result = None

                # Stage 1: Tavily web search for full content from alternative source
                if search_svc.available:
                    search_result = await search_svc.search_article_content(title, summary)
                    if search_result and len(search_result["content"]) >= MIN_CONTENT_LENGTH:
                        updates["content"] = search_result["content"]
                        web_searched = True
                        stats["content_enriched"] += 1
                        logger.info(
                            "Enriched content via Tavily for: %s (from %s)",
                            title[:50], search_result.get("source_name", "?"),
                        )

                # Stage 2: LLM synthesis from Tavily snippets + original content
                if not updates.get("content") and search_result and search_result["content"]:
                    synthesized = await openai_svc.generate_expanded_summary(
                        title=title,
                        summary=summary,
                        content=search_result["content"][:2000],
                    )
                    if synthesized and len(synthesized) >= MIN_CONTENT_LENGTH:
                        updates["content"] = synthesized
                        web_searched = True
                        stats["content_enriched"] += 1

                # Stage 3: LLM expansion from whatever we have (existing fallback)
                if not updates.get("content"):
                    expanded = await openai_svc.generate_expanded_summary(
                        title=title,
                        summary=summary,
                        content=content,
                    )
                    if expanded and len(expanded) > len(content):
                        updates["content"] = expanded
                        stats["content_enriched"] += 1

            # ── IMAGE ENRICHMENT ────────────────────────────────────────
            if not row.get("image_url"):
                image_url = None

                # Stage 1: Source page extraction (existing)
                article_url = row.get("url", "")
                if article_url:
                    image_url = await fetch_best_source_image(article_url, timeout=5.0)
                    if image_url:
                        stats["images_found"] += 1

                # Stage 2: Unsplash search + GPT selection
                if not image_url:
                    search_query = f"{title} {category}".strip()
                    candidates = await openai_svc.search_unsplash_images(search_query, per_page=10)
                    if candidates:
                        article_dict = {"title": title, "summary": summary}
                        best = await openai_svc.select_best_image(article_dict, candidates)
                        if best and best.get("url"):
                            image_url = best["url"]
                            stats["images_found"] += 1
                            logger.info("Found Unsplash image for: %s", title[:50])

                # Stage 3: Gemini image generation
                if not image_url and image_gen_svc.available:
                    image_url = await image_gen_svc.generate_article_image(title, category)
                    if image_url:
                        stats["images_generated"] += 1
                        logger.info("Generated image via Gemini for: %s", title[:50])

                if image_url:
                    updates["image_url"] = image_url

            # ── QUALITY SCORE ───────────────────────────────────────────
            final_content = updates.get("content") or content
            final_image = updates.get("image_url") or row.get("image_url")
            quality = compute_content_quality(final_content, final_image, web_searched)
            updates["content_quality"] = quality

            # ── COMPLETION ──────────────────────────────────────────────
            attempts = (row.get("enrichment_attempts") or 0) + 1
            has_image = bool(final_image)
            has_content = len((final_content or "").strip()) >= MIN_CONTENT_LENGTH
            completed = (has_image and has_content) or attempts >= MAX_ENRICHMENT_ATTEMPTS

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

            if "content_quality" in updates:
                set_clauses.append("content_quality = %s")
                params.append(updates["content_quality"])

            params.append(article_id)
            cur.execute(
                f"UPDATE public.articles SET {', '.join(set_clauses)} WHERE id = %s",
                params,
            )
    except Exception:
        logger.exception("Error applying enrichment for article %s", article_id)
