"""
Feed service: pre-filter articles from shared pool, batch-score with AI, cache results.
"""
import asyncio
import json
import logging
import uuid as _uuid
from datetime import datetime, timezone, timedelta

from app.services.openai_service import get_openai_service
from app.services.content_extractor import extract_article_content

logger = logging.getLogger(__name__)


FEED_CACHE_TTL_MINUTES = 15
MIN_READY_CANDIDATES = 30
CANDIDATE_LOOKBACK_HOURS = 72
CANDIDATE_QUERY_LIMIT = 150
MAX_CANDIDATES_TO_SCORE = 80
BACKFILL_EXTRACTION_LIMIT = 15
BACKFILL_CONCURRENCY = 4
GENERAL_SECTION_THRESHOLD = 0.4
MIN_IMMEDIATE_CANDIDATES = 10
MIN_CANDIDATE_TEXT_LENGTH = 40


async def get_personalized_feed(
    user_id: str,
    conn,
    limit: int = 20,
    force_refresh: bool = False,
    category: str | None = None,
    section: str | None = None,
) -> list[dict]:
    """
    Return a personalized news feed for the given user.

    1. Check cache (user_feed_cache) — return if fresh and not force_refresh
    2. Load user's ai_profile + structured interests from user_preferences
    3. Load a large recent article pool, hydrating it on-demand if needed
    4. Batch-score the best candidates with AI in a single call
    5. Cache and return top `limit` articles

    Optional filters:
    - section="general": return only high-scored articles (score >= 0.6)
    - section="all": return full scored feed (default behavior)
    - category: filter articles by category (case-insensitive)
    """
    user_uuid = _uuid.UUID(user_id)

    # 1. Check cache
    if not force_refresh:
        cached = _load_cached_feed(conn, user_uuid)
        if cached is not None:
            filtered = _apply_filters(cached, category=category, section=section)
            return filtered[:limit]

    # 2. Load user preferences
    ai_profile = None
    interests = None
    with conn.cursor() as cur:
        cur.execute(
            "SELECT ai_profile, interests FROM public.user_preferences WHERE user_id = %s AND completed = true",
            (user_uuid,),
        )
        row = cur.fetchone()
        if row:
            ai_profile = row.get("ai_profile")
            interests = _parse_interests(row.get("interests"))

    logger.info(
        "Feed scoring prefs loaded for user %s: ai_profile=%s interests=%s",
        user_id,
        bool(ai_profile),
        bool(interests),
    )

    # 3. Query a large recent candidate pool. If the pool is too thin,
    # hydrate it on-demand before asking the LLM to score anything.
    candidates = await _load_ready_candidates(conn)

    if not candidates:
        return []

    if len(candidates) > MAX_CANDIDATES_TO_SCORE:
        candidates = candidates[:MAX_CANDIDATES_TO_SCORE]

    # 4. AI scoring
    if ai_profile or interests:
        openai_service = get_openai_service()
        scores = await openai_service.score_articles_batch(
            candidates,
            ai_profile or "",
            interests=interests,
        )
        # Attach scores
        for i, candidate in enumerate(candidates):
            candidate["_score"] = scores[i] if i < len(scores) else 0.5
        _log_score_distribution(scores, threshold=GENERAL_SECTION_THRESHOLD, context=f"user_id={user_id}")
    else:
        # No profile yet — just use recency (all articles get equal score)
        for candidate in candidates:
            candidate["_score"] = 0.5
        logger.info(
            "Feed scoring skipped for user %s: no profile or interests, using neutral scores",
            user_id,
        )

    # Sort by score descending
    candidates.sort(key=lambda x: x.get("_score", 0), reverse=True)

    # 5. Cache results (cache ALL scored articles, not just the filtered subset)
    _save_feed_cache(conn, user_uuid, candidates)

    # Move _score to relevance_score for the response
    for article in candidates:
        article["relevance_score"] = article.pop("_score", 0.5)

    # Apply section/category filters
    filtered = _apply_filters(candidates, category=category, section=section)

    return filtered[:limit]


def _apply_filters(
    articles: list[dict],
    category: str | None = None,
    section: str | None = None,
) -> list[dict]:
    """Apply section and category filters to a list of scored articles."""
    result = articles

    # Filter by category (case-insensitive)
    if category:
        result = [
            a for a in result
            if a.get("category", "").lower() == category.lower()
        ]

    # Filter by section
    if section == "general":
        # General: only high-relevance articles
        result = [
            a for a in result
            if a.get("relevance_score", 0.5) >= GENERAL_SECTION_THRESHOLD
        ]
    # "all" or None: no additional filtering

    return result


async def _load_ready_candidates(conn) -> list[dict]:
    """Load recent candidates, topping up ingestion/content when the pool is too small."""
    rows = _query_candidate_rows(conn)
    candidates = _rows_to_candidates(rows)

    if len(candidates) >= MIN_READY_CANDIDATES:
        return candidates

    if len(candidates) >= MIN_IMMEDIATE_CANDIDATES:
        logger.info(
            "Returning %d ready candidates immediately; below target pool size of %d",
            len(candidates),
            MIN_READY_CANDIDATES,
        )
        return candidates

    from app.services.news_ingestion import fetch_rss_feeds

    new_count = await fetch_rss_feeds(conn)
    if new_count:
        rows = _query_candidate_rows(conn)
        candidates = _rows_to_candidates(rows)

    if candidates:
        logger.info(
            "Returning %d candidates after RSS ingest (new_count=%d)",
            len(candidates),
            new_count,
        )
        return candidates

    await _backfill_candidate_content(conn, limit=BACKFILL_EXTRACTION_LIMIT)
    rows = _query_candidate_rows(conn)
    candidates = _rows_to_candidates(rows)

    if candidates:
        logger.info("Returning %d candidates after content backfill", len(candidates))
    else:
        logger.warning("No feed candidates available after ingest and backfill")

    return candidates


def _query_candidate_rows(conn) -> list[dict]:
    with conn.cursor() as cur:
        cur.execute(
            f"""
            SELECT id, url, title, summary, content, author, source_name, image_url,
                   published_at, ingested_at, category
            FROM public.articles
            WHERE COALESCE(published_at, ingested_at) > now() - interval '{CANDIDATE_LOOKBACK_HOURS} hours'
            ORDER BY COALESCE(published_at, ingested_at) DESC
            LIMIT {CANDIDATE_QUERY_LIMIT}
            """,
        )
        return cur.fetchall()


def _rows_to_candidates(rows: list[dict]) -> list[dict]:
    candidates = []

    for row in rows:
        published_at = row.get("published_at")
        if isinstance(published_at, datetime):
            published_at_str = published_at.replace(tzinfo=timezone.utc).isoformat()
        else:
            published_at_str = None

        summary = row.get("summary") or _derive_summary(row.get("content"))
        text_blob = f"{row.get('title', '')} {summary or ''}".strip()

        if len(text_blob) < MIN_CANDIDATE_TEXT_LENGTH:
            continue

        candidates.append({
            "id": str(row["id"]),
            "title": row.get("title", ""),
            "summary": summary,
            "content": (row.get("content") or "")[:500],
            "author": row.get("author"),
            "source": row.get("source_name"),
            "image_url": row.get("image_url"),
            "url": row.get("url"),
            "published_at": published_at_str,
            "category": row.get("category"),
        })

    return candidates


async def _backfill_candidate_content(conn, limit: int) -> None:
    """Extract content/images for the newest incomplete articles before scoring."""
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT id, url
            FROM public.articles
            WHERE url IS NOT NULL
              AND (content_extracted = false OR image_url IS NULL OR content IS NULL)
            ORDER BY ingested_at DESC
            LIMIT %s
            """,
            (limit,),
        )
        pending = cur.fetchall()

    semaphore = asyncio.Semaphore(BACKFILL_CONCURRENCY)

    async def _extract(row: dict) -> tuple[_uuid.UUID, dict] | None:
        async with semaphore:
            try:
                return row["id"], await extract_article_content(row["url"])
            except Exception:
                logger.exception("Feed backfill error extracting %s", row["url"])
                return None

    results = await asyncio.gather(
        *[_extract(row) for row in pending],
        return_exceptions=False,
    )

    for result in results:
        if not result:
            continue

        article_id, extracted = result
        extracted_anything = bool(
            extracted.get("content") or extracted.get("summary") or extracted.get("image_url")
        )

        try:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    UPDATE public.articles
                    SET content = COALESCE(%s, content),
                        summary = COALESCE(summary, %s),
                        image_url = COALESCE(image_url, %s),
                        content_extracted = content_extracted OR %s
                    WHERE id = %s
                    """,
                    (
                        extracted.get("content") or None,
                        extracted.get("summary") or None,
                        extracted.get("image_url") or None,
                        extracted_anything,
                        article_id,
                    ),
                )
        except Exception:
            logger.exception("Feed backfill DB update failed for article %s", article_id)


def _derive_summary(content: str | None) -> str | None:
    """Build a compact fallback summary from extracted content when RSS summary is missing."""
    if not content:
        return None

    collapsed = " ".join(content.split())
    if len(collapsed) < MIN_CANDIDATE_TEXT_LENGTH:
        return None

    return collapsed[:280]


def _parse_interests(raw) -> dict | None:
    """Parse interests from DB text column (JSON string) into a dict."""
    if raw and isinstance(raw, str):
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            logger.warning("Invalid interests JSON encountered while loading preferences")
            return None
    if isinstance(raw, dict):
        return raw
    return None


def _log_score_distribution(scores: list[float], threshold: float, context: str) -> None:
    """Emit compact score distribution logs for debugging personalization quality."""
    if not scores:
        logger.info("Feed scoring produced no scores (%s)", context)
        return

    numeric_scores = [float(score) for score in scores]
    count = len(numeric_scores)
    above_threshold = sum(score >= threshold for score in numeric_scores)
    low_relevance = sum(score <= 0.2 for score in numeric_scores)
    mean_score = sum(numeric_scores) / count

    logger.info(
        "Feed score distribution (%s): count=%d min=%.2f max=%.2f mean=%.2f <=0.2=%d >=%.1f=%d <%.1f=%d",
        context,
        count,
        min(numeric_scores),
        max(numeric_scores),
        mean_score,
        low_relevance,
        threshold,
        above_threshold,
        threshold,
        count - above_threshold,
    )


def _load_cached_feed(conn, user_uuid) -> list[dict] | None:
    """Load cached feed if it's still fresh (< TTL minutes old)."""
    cutoff = datetime.now(timezone.utc) - timedelta(minutes=FEED_CACHE_TTL_MINUTES)

    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT ufc.relevance_score, ufc.created_at,
                   a.id, a.url, a.title, a.summary, a.content, a.author,
                   a.source_name, a.image_url, a.published_at, a.category
            FROM public.user_feed_cache ufc
            JOIN public.articles a ON a.id = ufc.article_id
            WHERE ufc.user_id = %s AND ufc.created_at > %s
            ORDER BY ufc.relevance_score DESC
            """,
            (user_uuid, cutoff),
        )
        rows = cur.fetchall()

    if not rows:
        return None

    articles = []
    for row in rows:
        published_at = row.get("published_at")
        if isinstance(published_at, datetime):
            published_at_str = published_at.replace(tzinfo=timezone.utc).isoformat()
        else:
            published_at_str = None

        articles.append({
            "id": str(row["id"]),
            "title": row.get("title", ""),
            "summary": row.get("summary"),
            "content": (row.get("content") or "")[:500],
            "author": row.get("author"),
            "source": row.get("source_name"),
            "image_url": row.get("image_url"),
            "url": row.get("url"),
            "published_at": published_at_str,
            "category": row.get("category"),
            "relevance_score": row.get("relevance_score"),
        })

    return articles


def _save_feed_cache(conn, user_uuid, articles: list[dict]) -> None:
    """Save scored articles to the feed cache table."""
    with conn.cursor() as cur:
        # Clear old cache for this user
        cur.execute(
            "DELETE FROM public.user_feed_cache WHERE user_id = %s",
            (user_uuid,),
        )

        for i, article in enumerate(articles):
            article_id = article.get("id")
            score = article.get("_score", 0.5)
            try:
                cur.execute(
                    """
                    INSERT INTO public.user_feed_cache (user_id, article_id, relevance_score)
                    VALUES (%s, %s, %s)
                    ON CONFLICT (user_id, article_id) DO UPDATE SET relevance_score = EXCLUDED.relevance_score, created_at = now()
                    """,
                    (user_uuid, _uuid.UUID(article_id), score),
                )
            except Exception:
                logger.exception("Feed cache error caching article %s", article_id)


async def get_article_by_id(article_id: str, conn) -> dict | None:
    """
    Load a single article by ID. If content hasn't been extracted yet,
    extract it on-demand using BeautifulSoup.
    """
    article_uuid = _uuid.UUID(article_id)

    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT id, url, title, summary, content, author, source_name,
                   image_url, published_at, category, content_extracted
            FROM public.articles
            WHERE id = %s
            """,
            (article_uuid,),
        )
        row = cur.fetchone()

    if not row:
        return None

    # If content not yet extracted and we have a URL, extract now
    if not row.get("content_extracted") and row.get("url"):
        extracted = await extract_article_content(row["url"])
        if extracted.get("content"):
            with conn.cursor() as cur:
                cur.execute(
                    """
                    UPDATE public.articles
                    SET content = %s,
                        summary = COALESCE(summary, %s),
                        image_url = COALESCE(image_url, %s),
                        content_extracted = true
                    WHERE id = %s
                    """,
                    (
                        extracted["content"],
                        extracted.get("summary"),
                        extracted.get("image_url"),
                        article_uuid,
                    ),
                )
            # Update row with extracted data
            row = dict(row)
            row["content"] = extracted["content"]
            if not row.get("summary"):
                row["summary"] = extracted.get("summary")
            if not row.get("image_url"):
                row["image_url"] = extracted.get("image_url")
            row["content_extracted"] = True

    published_at = row.get("published_at")
    if isinstance(published_at, datetime):
        published_at_str = published_at.replace(tzinfo=timezone.utc).isoformat()
    else:
        published_at_str = None

    return {
        "id": str(row["id"]),
        "title": row.get("title", ""),
        "summary": row.get("summary"),
        "content": row.get("content"),
        "author": row.get("author"),
        "source": row.get("source_name"),
        "image_url": row.get("image_url"),
        "url": row.get("url"),
        "published_at": published_at_str,
        "category": row.get("category"),
    }
