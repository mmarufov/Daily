"""Non-authoritative article enrichment.

This service may improve images and a ranking hint. It must never replace a
publisher body: display text is owned by ``article_content`` and cross-source
Tavily material, when explicitly enabled, is stored only as non-display
analysis context.
"""
import asyncio
import logging
import os

from app.services.image_extraction import fetch_best_source_image

logger = logging.getLogger(__name__)

# Thresholds
MIN_CONTENT_LENGTH = 200  # chars — below this, content needs enrichment
GOOD_CONTENT_LENGTH = 500  # chars — above this, content is considered good
# A summary at least this long carries a real story, so the article stays
# rankable even when we never recovered its body.
USABLE_SUMMARY_LENGTH = 120

# Batch config
ENRICHMENT_BATCH_SIZE = 25
ENRICHMENT_CONCURRENCY = 6
# Cap retries low: even source-page image recovery is outbound work, and the
# optional analysis/illustration stages can add paid calls when enabled.
MAX_ENRICHMENT_ATTEMPTS = 3


def _env_enabled(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


# Illustrative imagery is integrity-sensitive and must be explicitly enabled.
# Source-authentic publisher images are the production default.
ENRICH_GENERATED_IMAGES = _env_enabled("ENRICH_GENERATED_IMAGES", default=False)
ENRICH_STOCK_IMAGES = _env_enabled("ENRICH_STOCK_IMAGES", default=False)
# Cross-source text is off by default and, if enabled for ranking experiments,
# can only enter the analysis artifact kind—not articles.content/display body.
ENRICH_CROSS_SOURCE_ANALYSIS = _env_enabled(
    "ENRICH_CROSS_SOURCE_ANALYSIS", default=False
)


def compute_content_quality(
    content: str | None,
    image_url: str | None,
    web_searched: bool = False,
    summary: str | None = None,
) -> float:
    """
    Compute a 0-1 quality score for feed ranking.

    1.0 = content >= 500 chars + has image + original source
    0.8 = content >= 500 chars + has image + web-search-sourced
    0.6 = content >= 300 chars + has image
    0.4 = content >= 300 chars + no image
    0.2 = content < 300 chars (thin)

    A story we couldn't extract is not a bad story — it is a story the reader
    opens at the source. So a real headline plus a substantive summary still
    scores as showable rather than collapsing to 0.0, which would drop it from
    the candidate pool entirely.
    """
    content_len = len((content or "").strip())
    summary_len = len((summary or "").strip())
    has_image = bool(image_url)

    if content_len == 0:
        if summary_len >= USABLE_SUMMARY_LENGTH:
            return 0.5 if has_image else 0.4
        return 0.2 if summary_len else 0.0
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
    Find articles not yet enriched and improve non-authoritative ranking context
    and image metadata. Display eligibility remains owned by article_content.

    Returns dict with counts.
    """
    from app.services.openai_service import get_openai_service
    from app.services.article_content import record_analysis_context

    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT id, url, title, summary, content, analysis_text, source_name, image_url,
                   image_origin, image_source_url, image_attribution,
                   image_is_illustrative, enrichment_attempts, category,
                   analysis_content_version
            FROM public.articles
            WHERE (
                    enrichment_completed = false
                    OR enrichment_completed IS NULL
                    OR content_quality_content_version
                       IS DISTINCT FROM analysis_content_version
                  )
              AND COALESCE(enrichment_attempts, 0) < %s
            ORDER BY ingested_at DESC
            LIMIT %s
            """,
            (MAX_ENRICHMENT_ATTEMPTS, ENRICHMENT_BATCH_SIZE),
        )
        pending = cur.fetchall()

    if not pending:
        return {"content_enriched": 0, "images_found": 0, "images_generated": 0}

    openai_svc = get_openai_service() if ENRICH_STOCK_IMAGES else None
    search_svc = None
    if ENRICH_CROSS_SOURCE_ANALYSIS:
        from app.services.web_search_service import get_web_search_service
        search_svc = get_web_search_service()
    image_gen_svc = None
    if ENRICH_GENERATED_IMAGES:
        from app.services.image_generation_service import get_image_generation_service
        image_gen_svc = get_image_generation_service()
    semaphore = asyncio.Semaphore(ENRICHMENT_CONCURRENCY)
    stats = {"content_enriched": 0, "images_found": 0, "images_generated": 0}

    async def _enrich_one(row):
        async with semaphore:
            updates = {}
            web_searched = False
            analysis_artifact = None
            images_found = 0
            images_generated = 0

            title = row.get("title", "")
            summary = row.get("summary", "")
            analysis_text = (row.get("analysis_text") or row.get("content") or "").strip()
            category = row.get("category", "")

            # ── OPTIONAL ANALYSIS CONTEXT ───────────────────────────────
            # Never assign this result to updates["content"]. Search may find
            # another outlet or aggregate snippets from several documents.
            if (
                ENRICH_CROSS_SOURCE_ANALYSIS
                and len(analysis_text) < MIN_CONTENT_LENGTH
                and getattr(search_svc, "available", False)
            ):
                try:
                    search_result = await search_svc.search_article_content(title, summary)
                except Exception:
                    logger.exception("Tavily search failed for %s", title[:50])
                    search_result = None
                if search_result and len(search_result.get("content", "")) >= MIN_CONTENT_LENGTH:
                    analysis_artifact = {
                        "text": search_result["content"],
                        "source_url": search_result.get("source_url") or "",
                    }
                    analysis_text = search_result["content"].strip()
                    web_searched = True

            # ── IMAGE ENRICHMENT ────────────────────────────────────────
            if not row.get("image_url") or row.get("image_origin") in (None, "legacy_unknown"):
                image_url = None
                image_provenance = None

                # Stage 1: Source page extraction (existing)
                article_url = row.get("url", "")
                if article_url:
                    try:
                        image_url = await fetch_best_source_image(article_url, timeout=5.0)
                    except Exception:
                        logger.exception("Source-image fetch failed for %s", title[:50])
                        image_url = None
                    if image_url:
                        image_provenance = {
                            "image_origin": "publisher_page",
                            "image_source_url": article_url,
                            "image_attribution": row.get("source_name"),
                            "image_is_illustrative": False,
                        }
                        images_found += 1

                # Stage 2: Unsplash search + GPT selection
                if ENRICH_STOCK_IMAGES and not image_url and openai_svc is not None:
                    try:
                        search_query = f"{title} {category}".strip()
                        candidates = await openai_svc.search_unsplash_images(search_query, per_page=10)
                        if candidates:
                            article_dict = {"title": title, "summary": summary}
                            best = await openai_svc.select_best_image(article_dict, candidates)
                            if best and best.get("url"):
                                image_url = best["url"]
                                image_provenance = {
                                    "image_origin": "stock",
                                    "image_source_url": best.get("source_url") or "https://unsplash.com",
                                    "image_attribution": best.get("attribution") or "Unsplash",
                                    "image_is_illustrative": True,
                                }
                                images_found += 1
                                logger.info("Found Unsplash image for: %s", title[:50])
                    except Exception:
                        logger.exception("Unsplash stage failed for %s", title[:50])

                # Stage 3: Gemini image generation
                if (
                    ENRICH_GENERATED_IMAGES
                    and not image_url
                    and getattr(image_gen_svc, "available", False)
                ):
                    try:
                        image_url = await image_gen_svc.generate_article_image(title, category)
                        if image_url:
                            image_provenance = {
                                "image_origin": "generated",
                                "image_source_url": None,
                                "image_attribution": "AI-generated illustration",
                                "image_is_illustrative": True,
                            }
                            images_generated += 1
                            logger.info("Generated image via Gemini for: %s", title[:50])
                    except Exception:
                        logger.exception("Image generation failed for %s", title[:50])

                if image_url:
                    updates["image_url"] = image_url
                    updates.update(image_provenance or {})

            # ── QUALITY SCORE ───────────────────────────────────────────
            final_content = analysis_text
            final_image = updates.get("image_url") or row.get("image_url")
            quality = compute_content_quality(
                final_content, final_image, web_searched, summary=summary,
            )
            updates["content_quality"] = quality

            # ── COMPLETION ──────────────────────────────────────────────
            attempts = (row.get("enrichment_attempts") or 0) + 1
            final_image_origin = updates.get("image_origin") or row.get("image_origin")
            has_image = bool(final_image) and final_image_origin not in (None, "legacy_unknown")
            has_content = len((final_content or "").strip()) >= MIN_CONTENT_LENGTH
            completed = (has_image and has_content) or attempts >= MAX_ENRICHMENT_ATTEMPTS

            return {
                "article_id": row["id"],
                "title": title,
                "updates": updates,
                "completed": completed,
                "attempts": attempts,
                "analysis_artifact": analysis_artifact,
                "analysis_content_version": row.get("analysis_content_version"),
                "images_found": images_found,
                "images_generated": images_generated,
            }

    results = await asyncio.gather(
        *[_enrich_one(row) for row in pending],
        return_exceptions=True,
    )
    # Psycopg operations on one shared connection are applied serially after
    # concurrent network work. This prevents one task's transaction/savepoint
    # from interleaving with another article's write lifecycle.
    for row, result in zip(pending, results):
        if isinstance(result, BaseException):
            logger.error(
                "Unhandled enrichment failure for article %s",
                row.get("id"),
                exc_info=(type(result), result, result.__traceback__),
            )
            continue
        analysis_artifact = result.get("analysis_artifact")
        if analysis_artifact:
            try:
                record_analysis_context(
                    conn,
                    result["article_id"],
                    text=analysis_artifact["text"],
                    source_url=analysis_artifact["source_url"],
                )
                stats["content_enriched"] += 1
                logger.info(
                    "Stored non-display analysis context for: %s",
                    result["title"][:50],
                )
            except Exception:
                logger.exception(
                    "Failed to store analysis context for article %s",
                    result["article_id"],
                )
        applied = _apply_enrichment(
            conn,
            result["article_id"],
            result["updates"],
            result["completed"],
            result["attempts"],
            result["analysis_content_version"],
        )
        if applied:
            stats["images_found"] += result["images_found"]
            stats["images_generated"] += result["images_generated"]

    return stats


def _apply_enrichment(
    conn,
    article_id,
    updates: dict,
    completed: bool,
    attempts: int,
    analysis_content_version,
) -> bool:
    """Apply enrichment updates, increment attempts, and optionally mark completed."""
    try:
        with conn.cursor() as cur:
            set_clauses = ["enrichment_attempts = %s"]
            params = [attempts]

            if completed:
                set_clauses.append("enrichment_completed = true")

            if updates.get("image_url"):
                # Replace only an empty/quarantined legacy image. Never let a
                # later enrichment race overwrite trusted publisher metadata.
                set_clauses.extend(
                    [
                        "image_url = CASE WHEN image_url IS NULL OR image_origin IS NULL OR image_origin = 'legacy_unknown' THEN %s ELSE image_url END",
                        "image_origin = CASE WHEN image_url IS NULL OR image_origin IS NULL OR image_origin = 'legacy_unknown' THEN %s ELSE image_origin END",
                        "image_source_url = CASE WHEN image_url IS NULL OR image_origin IS NULL OR image_origin = 'legacy_unknown' THEN %s ELSE image_source_url END",
                        "image_attribution = CASE WHEN image_url IS NULL OR image_origin IS NULL OR image_origin = 'legacy_unknown' THEN %s ELSE image_attribution END",
                        "image_is_illustrative = CASE WHEN image_url IS NULL OR image_origin IS NULL OR image_origin = 'legacy_unknown' THEN %s ELSE image_is_illustrative END",
                    ]
                )
                params.extend(
                    [
                        updates["image_url"],
                        updates.get("image_origin"),
                        updates.get("image_source_url"),
                        updates.get("image_attribution"),
                        bool(updates.get("image_is_illustrative", False)),
                    ]
                )

            if "content_quality" in updates:
                set_clauses.extend(
                    [
                        "content_quality = %s",
                        "content_quality_content_version = %s",
                    ]
                )
                params.extend(
                    [updates["content_quality"], analysis_content_version]
                )

            params.extend([article_id, analysis_content_version])
            cur.execute(
                f"UPDATE public.articles SET {', '.join(set_clauses)} "
                "WHERE id = %s "
                "AND analysis_content_version IS NOT DISTINCT FROM %s",
                params,
            )
            # Lightweight unit-test cursors may not expose rowcount; the real
            # psycopg cursor does, and a missing target row is the only false.
            return getattr(cur, "rowcount", 1) != 0
    except Exception:
        logger.exception("Error applying enrichment for article %s", article_id)
        return False
