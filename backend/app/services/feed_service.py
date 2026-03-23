"""
Feed service: score articles from shared pool with AI, cache results, return personalized feed.
"""
import asyncio
import json
import logging
import uuid as _uuid
from datetime import datetime, timezone, timedelta

from app.services.content_extractor import extract_article_content
from app.services.openai_service import get_openai_service

logger = logging.getLogger(__name__)


FEED_CACHE_TTL_MINUTES = 60
CANDIDATE_LOOKBACK_HOURS = 72
CANDIDATE_QUERY_LIMIT = 150
SCORING_BATCH_SIZE = 50
MIN_CANDIDATE_TEXT_LENGTH = 40


async def get_personalized_feed(
    user_id: str,
    conn,
    limit: int = 50,
    force_refresh: bool = False,
) -> list[dict]:
    """
    Return a personalized news feed for the given user.

    1. Check cache (user_feed_cache) — return if fresh and not force_refresh
    2. Load user's ai_profile + structured interests from user_preferences
    3. Load all recent candidate articles
    4. Batch-score ALL candidates with AI (the LLM decides relevant yes/no)
    5. Cache and return only relevant articles, sorted by score
    """
    user_uuid = _uuid.UUID(user_id)

    # 1. Check cache
    if not force_refresh:
        cached = _load_cached_feed(conn, user_uuid)
        if cached is not None:
            relevant = [a for a in cached if a.get("relevant", True)]
            return relevant[:limit]

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

    # 3. Load all recent candidates
    candidates = await _load_ready_candidates(conn)

    if not candidates:
        return []

    # 4. AI scoring — score ALL candidates in batches
    if ai_profile or interests:
        openai_service = get_openai_service()
        all_results = []

        for batch_start in range(0, len(candidates), SCORING_BATCH_SIZE):
            batch = candidates[batch_start:batch_start + SCORING_BATCH_SIZE]
            batch_results = await openai_service.score_articles_batch(
                batch,
                ai_profile or "",
                interests=interests,
            )
            all_results.extend(batch_results)

        # Attach scores and relevance
        for i, candidate in enumerate(candidates):
            if i < len(all_results):
                candidate["_score"] = all_results[i]["score"]
                candidate["_relevant"] = all_results[i]["relevant"]
                candidate["_reason"] = all_results[i]["reason"]
            else:
                candidate["_score"] = 0.5
                candidate["_relevant"] = True
                candidate["_reason"] = "scoring incomplete"

        _log_score_distribution(all_results, context=f"user_id={user_id}")
    else:
        # No profile yet — show all articles with neutral scores
        for candidate in candidates:
            candidate["_score"] = 0.5
            candidate["_relevant"] = True
            candidate["_reason"] = "no profile available"
        logger.info(
            "Feed scoring skipped for user %s: no profile or interests",
            user_id,
        )

    # Sort by score descending
    candidates.sort(key=lambda x: x.get("_score", 0), reverse=True)

    # 5. Cache ALL scored articles
    _save_feed_cache(conn, user_uuid, candidates)

    # Convert internal fields to response fields
    for article in candidates:
        article["relevance_score"] = article.pop("_score", 0.5)
        article["relevant"] = article.pop("_relevant", True)
        article["relevance_reason"] = article.pop("_reason", "")

    # Only return articles the AI marked as relevant
    relevant = [a for a in candidates if a.get("relevant", False)]

    return relevant[:limit]


def _log_score_distribution(results: list[dict], context: str) -> None:
    """Emit compact score distribution logs for debugging personalization quality."""
    if not results:
        logger.info("Feed scoring produced no results (%s)", context)
        return

    scores = [float(r.get("score", 0.5)) for r in results]
    relevant_count = sum(1 for r in results if r.get("relevant", False))
    count = len(scores)
    mean_score = sum(scores) / count

    logger.info(
        "Feed score distribution (%s): total=%d relevant=%d rejected=%d min=%.2f max=%.2f mean=%.2f",
        context,
        count,
        relevant_count,
        count - relevant_count,
        min(scores),
        max(scores),
        mean_score,
    )


async def _load_ready_candidates(conn) -> list[dict]:
    """Load recent candidates from the pre-populated article pool."""
    rows = _query_candidate_rows(conn)
    candidates = _rows_to_candidates(rows)
    logger.info("Loaded %d ready candidates from article pool", len(candidates))
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


def _load_cached_feed(conn, user_uuid) -> list[dict] | None:
    """Load cached feed if it's still fresh (< TTL minutes old)."""
    cutoff = datetime.now(timezone.utc) - timedelta(minutes=FEED_CACHE_TTL_MINUTES)

    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT ufc.relevance_score, ufc.relevant, ufc.relevance_reason, ufc.created_at,
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
            "relevant": row.get("relevant", True),
            "relevance_reason": row.get("relevance_reason", ""),
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

        for article in articles:
            article_id = article.get("id")
            score = article.get("_score", 0.5)
            relevant = article.get("_relevant", True)
            reason = article.get("_reason", "")
            try:
                cur.execute(
                    """
                    INSERT INTO public.user_feed_cache (user_id, article_id, relevance_score, relevant, relevance_reason)
                    VALUES (%s, %s, %s, %s, %s)
                    ON CONFLICT (user_id, article_id) DO UPDATE SET
                        relevance_score = EXCLUDED.relevance_score,
                        relevant = EXCLUDED.relevant,
                        relevance_reason = EXCLUDED.relevance_reason,
                        created_at = now()
                    """,
                    (user_uuid, _uuid.UUID(article_id), score, relevant, reason),
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
