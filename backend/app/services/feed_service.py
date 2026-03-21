"""
Feed service: pre-filter articles from shared pool, batch-score with AI, cache results.
"""
import uuid as _uuid
from datetime import datetime, timezone, timedelta

from app.services.openai_service import get_openai_service
from app.services.content_extractor import extract_article_content


FEED_CACHE_TTL_MINUTES = 15


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
    2. Load user's ai_profile from user_preferences
    3. Query articles table for last 24h, limit 50
    4. Batch-score with AI in a single call
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
    with conn.cursor() as cur:
        cur.execute(
            "SELECT ai_profile FROM public.user_preferences WHERE user_id = %s AND completed = true",
            (user_uuid,),
        )
        row = cur.fetchone()
        if row:
            ai_profile = row.get("ai_profile")

    # 3. Query candidate articles from the shared pool
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT id, url, title, summary, content, author, source_name, image_url,
                   published_at, ingested_at, category
            FROM public.articles
            WHERE ingested_at > now() - interval '24 hours'
            ORDER BY published_at DESC NULLS LAST
            LIMIT 200
            """,
        )
        rows = cur.fetchall()

    if not rows:
        return []

    candidates = []
    for row in rows:
        published_at = row.get("published_at")
        if isinstance(published_at, datetime):
            published_at_str = published_at.replace(tzinfo=timezone.utc).isoformat()
        else:
            published_at_str = None

        candidates.append({
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
        })

    # 3b. Filter out low-quality articles (no image or too short)
    candidates = [
        c for c in candidates
        if c.get("image_url")
        and len(
            (c.get("title", "") + (c.get("summary") or "") + (c.get("content") or ""))
        ) >= 100
    ]

    if not candidates:
        return []

    # 4. AI scoring
    if ai_profile:
        openai_service = get_openai_service()
        scores = await openai_service.score_articles_batch(candidates, ai_profile)
        # Attach scores
        for i, candidate in enumerate(candidates):
            candidate["_score"] = scores[i] if i < len(scores) else 0.5
    else:
        # No profile yet — just use recency (all articles get equal score)
        for candidate in candidates:
            candidate["_score"] = 0.5

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
        result = [a for a in result if a.get("relevance_score", 0.5) >= 0.4]
    # "all" or None: no additional filtering

    return result


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
            "content": row.get("content"),
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
            except Exception as e:
                print(f"Feed cache: Error caching article {article_id}: {e}")


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
