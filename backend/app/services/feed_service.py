from __future__ import annotations

"""
Feed service: score articles from shared pool with AI, cache results, return personalized feed.
"""
import asyncio
import json
import logging
import re
import uuid as _uuid
from datetime import datetime, timezone, timedelta
from difflib import SequenceMatcher
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from app.services.content_extractor import extract_article_content
from app.services.image_extraction import fetch_best_source_image
from app.services.openai_service import get_openai_service

logger = logging.getLogger(__name__)


FEED_CACHE_TTL_MINUTES = 60
CANDIDATE_EXPANSION_STEPS = (
    (24 * 3, 300),    # 3 days, 300 articles (was 2d/250)
    (24 * 7, 600),    # 7 days, 600 (was 500)
    (24 * 14, 1200),  # 14 days, 1200 (was 1000)
)
MIN_CANDIDATE_TEXT_LENGTH = 40
MAX_LLM_CANDIDATES = 200
MIN_SHORTLIST_SIZE = 24
_DEDUPE_TRACKING_PARAMS = {"fbclid", "gclid", "ocid", "cmpid", "taid"}
_DEDUPE_STOPWORDS = {
    "a", "about", "an", "and", "article", "articles", "around", "be", "coverage",
    "focus", "for", "from", "general", "give", "i", "in", "include", "just", "me", "my",
    "news", "of", "on", "or", "show", "stories", "story", "the", "to", "want", "with",
    "only",
}
_STOPWORDS = set(_DEDUPE_STOPWORDS)


async def get_personalized_feed(
    user_id: str,
    conn,
    limit: int = 50,
    force_refresh: bool = False,
) -> list[dict]:
    """Return a personalized news feed for the given user."""
    user_uuid = _uuid.UUID(user_id)
    if conn is None or not hasattr(conn, "cursor"):
        ai_profile, interests, preferences_updated_at = _load_user_preferences(conn, user_uuid)
        user_profile_v2 = None
    else:
        ai_profile, interests, user_profile_v2, _source_selection_brief, preferences_updated_at = _load_user_preferences_full(conn, user_uuid)

    if conn is not None and hasattr(conn, "cursor"):
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT 1
                FROM public.user_sources
                WHERE user_id = %s AND active = true
                LIMIT 1
                """,
                (user_uuid,),
            )
            has_sources = bool(cur.fetchone())
        if not has_sources:
            return []

    logger.info(
        "Feed scoring prefs loaded for user %s: ai_profile=%s interests=%s",
        user_id,
        bool(ai_profile),
        bool(interests),
    )

    if not force_refresh:
        cached = _load_cached_feed(conn, user_uuid, preferences_updated_at)
        if cached is not None:
            cached = _collapse_duplicate_coverage(cached)
            relevant = [a for a in cached if a.get("relevant", False)]
            if relevant:
                relevant = relevant[:limit]
                await _hydrate_missing_feed_images(conn, relevant)
                return relevant
            if any(a.get("relevance_reason") for a in cached):
                return []
            logger.info("Cache for user %s exists but lacks reasons; treating as stale", user_id)

    # --- LLM Editor-in-Chief: single editorial pass replaces 6-signal scoring ---
    candidates = await _load_candidates(conn, limit, user_uuid=user_uuid)
    if not candidates:
        return []

    # Small candidate pool: skip LLM, serve by recency
    if len(candidates) < MIN_EDITORIAL_CANDIDATES:
        for i, c in enumerate(candidates):
            c["_score"] = 1.0 - (i / max(len(candidates), 1))
            c["_relevant"] = True
            c["_reason"] = "Served by recency (small candidate pool)"
            c["_feed_role"] = "worth_knowing"
        candidates.sort(key=lambda a: a.get("published_at") or "", reverse=True)
        _save_feed_cache(conn, user_uuid, candidates)
        deduped = _collapse_duplicate_coverage(candidates)
        deduped = deduped[:limit]
        await _hydrate_missing_feed_images(conn, deduped)
        return _finalize_curated_articles(deduped)

    # Deduplicate before sending to LLM
    candidates = _collapse_duplicate_coverage(candidates)

    # Single LLM editorial call
    openai_service = get_openai_service()
    editorial_picks = await openai_service.curate_feed_editorial(
        ai_profile=ai_profile or "",
        interests=interests,
        user_profile_v2=user_profile_v2,
        candidates=candidates,
    )

    # LLM failure fallback: serve last cached feed (any age)
    if not editorial_picks:
        logger.warning("Editorial curation failed for user %s; falling back to cache", user_id)
        cached_fallback = _load_cached_feed(conn, user_uuid, preferences_updated_at=None, max_age_minutes=None)
        if cached_fallback:
            relevant = [a for a in cached_fallback if a.get("relevant", False)]
            if relevant:
                await _hydrate_missing_feed_images(conn, relevant[:limit])
                return relevant[:limit]
        # No cache either: serve by recency
        for i, c in enumerate(candidates):
            c["_score"] = 1.0 - (i / max(len(candidates), 1))
            c["_relevant"] = True
            c["_reason"] = "Editorial unavailable; served by recency"
            c["_feed_role"] = "worth_knowing"
        candidates.sort(key=lambda a: a.get("published_at") or "", reverse=True)
        _save_feed_cache(conn, user_uuid, candidates[:limit])
        await _hydrate_missing_feed_images(conn, candidates[:limit])
        return _finalize_curated_articles(candidates[:limit])

    # Map editorial picks back to candidate articles
    candidate_map = {c["id"]: c for c in candidates}
    total_picks = len(editorial_picks)
    curated = []
    for pick in editorial_picks:
        article = candidate_map.get(pick["article_id"])
        if not article:
            continue
        article["_score"] = 1.0 - (pick["rank"] / max(total_picks + 1, 1))
        article["_relevant"] = True
        article["_reason"] = pick["why_for_you"]
        article["_feed_role"] = pick["category_tag"]
        curated.append(article)

    _save_feed_cache(conn, user_uuid, curated)
    curated = curated[:limit]
    await _hydrate_missing_feed_images(conn, curated)
    return _finalize_curated_articles(curated)



def _parse_json_object(raw: Any) -> dict | None:
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, str) and raw:
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError:
            return None
        return payload if isinstance(payload, dict) else None
    return None


def _load_user_preferences_full(conn, user_uuid) -> tuple[str | None, dict | None, dict | None, dict | None, datetime | None]:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT ai_profile, interests, user_profile_v2, source_selection_brief, updated_at
            FROM public.user_preferences
            WHERE user_id = %s AND completed = true
            """,
            (user_uuid,),
        )
        row = cur.fetchone()

    if not row:
        return None, None, None, None, None

    return (
        row.get("ai_profile"),
        _parse_interests(row.get("interests")),
        _parse_json_object(row.get("user_profile_v2")),
        _parse_json_object(row.get("source_selection_brief")),
        row.get("updated_at"),
    )


def _load_user_preferences(conn, user_uuid) -> tuple[str | None, dict | None, datetime | None]:
    if conn is None or not hasattr(conn, "cursor"):
        return None, None, None
    ai_profile, interests, _user_profile_v2, _source_selection_brief, updated_at = _load_user_preferences_full(conn, user_uuid)
    return ai_profile, interests, updated_at


async def _load_candidates(
    conn,
    limit: int,
    user_uuid=None,
) -> list[dict]:
    """Load candidates using time-window expansion without keyword pre-filtering.

    The LLM editorial pass handles all filtering — we just need a pool of
    recent articles from the user's curated sources.
    """
    seen_ids: set[str] = set()
    gathered: list[dict] = []
    cap = min(max(limit * 2, MIN_SHORTLIST_SIZE), MAX_LLM_CANDIDATES)

    for lookback_hours, row_limit in CANDIDATE_EXPANSION_STEPS:
        rows = _query_candidate_rows(conn, lookback_hours=lookback_hours, row_limit=row_limit, user_uuid=user_uuid)
        for candidate in _rows_to_candidates(rows):
            candidate_id = candidate["id"]
            if candidate_id in seen_ids:
                continue
            seen_ids.add(candidate_id)
            gathered.append(candidate)

        logger.info("Loaded candidates for %dh window (total=%d)", lookback_hours, len(gathered))
        if len(gathered) >= cap:
            break

    if not gathered:
        return []

    gathered.sort(key=lambda a: a.get("published_at") or "", reverse=True)
    return gathered[:MAX_LLM_CANDIDATES]


def _finalize_curated_articles(articles: list[dict]) -> list[dict]:
    """Map internal scoring keys to public field names for curated feed."""
    finalized: list[dict] = []
    for article in articles:
        row = dict(article)
        row["relevance_score"] = row.pop("_score", row.get("relevance_score", 0.0))
        row["relevant"] = row.pop("_relevant", row.get("relevant", False))
        row["relevance_reason"] = row.pop("_reason", row.get("relevance_reason", ""))
        row["feed_role"] = row.pop("_feed_role", row.get("feed_role"))
        row.setdefault("why_this_story", None)
        row.setdefault("why_now", None)
        row.setdefault("matched_profile_signals", [])
        row.setdefault("cluster_id", None)
        row.setdefault("importance_score", 0.0)
        row.pop("_prefilter_score", None)
        row.pop("_prefilter_reason", None)
        row.pop("_prefilter_excluded", None)
        finalized.append(row)
    return finalized


MIN_EDITORIAL_CANDIDATES = 30


def _query_candidate_rows(conn, lookback_hours: int, row_limit: int, user_uuid=None) -> list[dict]:
    with conn.cursor() as cur:
        if user_uuid is None:
            cur.execute(
                f"""
                SELECT id, url, title, summary, content, author, source_name, image_url,
                       published_at, ingested_at, category
                FROM public.articles
                WHERE COALESCE(published_at, ingested_at) > now() - interval '{lookback_hours} hours'
                ORDER BY COALESCE(published_at, ingested_at) DESC
                LIMIT {row_limit}
                """,
            )
        else:
            cur.execute(
                f"""
                SELECT scoped.id, scoped.url, scoped.title, scoped.summary, scoped.content,
                       scoped.author, scoped.source_name, scoped.image_url,
                       scoped.published_at, scoped.ingested_at, scoped.category,
                       scoped.coverage_role, scoped.selection_reason, scoped.matched_topics,
                       scoped.matched_entities, scoped.precision_score, scoped.breadth_score
                FROM (
                    SELECT DISTINCT ON (a.id)
                           a.id, a.url, a.title, a.summary, a.content, a.author, a.source_name,
                           a.image_url,
                           COALESCE(asl.published_at, a.published_at) AS published_at,
                           a.ingested_at,
                           COALESCE(us.category, a.category) AS category,
                           us.coverage_role,
                           us.selection_reason,
                           us.matched_topics,
                           us.matched_entities,
                           us.precision_score,
                           us.breadth_score,
                           COALESCE(asl.published_at, a.published_at, a.ingested_at) AS scoped_published_at
                    FROM public.articles a
                    JOIN public.article_source_links asl ON asl.article_id = a.id
                    JOIN public.user_sources us
                      ON us.user_id = %s
                     AND us.active = true
                     AND us.source_url = asl.source_url
                    WHERE COALESCE(asl.published_at, a.published_at, a.ingested_at) > now() - interval '{lookback_hours} hours'
                    ORDER BY a.id, COALESCE(asl.published_at, a.published_at, a.ingested_at) DESC
                ) AS scoped
                ORDER BY scoped.scoped_published_at DESC
                LIMIT {row_limit}
                """,
                (user_uuid,),
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
            "description": summary,
            "content": (row.get("content") or "")[:2000],
            "author": row.get("author"),
            "source": row.get("source_name"),
            "image_url": row.get("image_url"),
            "url": row.get("url"),
            "published_at": published_at_str,
            "category": row.get("category"),
            "source_coverage_role": row.get("coverage_role"),
            "source_selection_reason": row.get("selection_reason"),
            "source_matched_topics": row.get("matched_topics") or [],
            "source_matched_entities": row.get("matched_entities") or [],
            "source_precision_score": row.get("precision_score") or 0.0,
            "source_breadth_score": row.get("breadth_score") or 0.0,
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


def _parse_article_datetime(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    if not isinstance(value, str) or not value:
        return None

    normalized = value.replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def _canonicalize_url(url: str | None) -> str:
    if not url:
        return ""

    parts = urlsplit(url.strip())
    if not parts.scheme or not parts.netloc:
        return ""

    filtered_query = [
        (key, value)
        for key, value in parse_qsl(parts.query, keep_blank_values=True)
        if not key.lower().startswith("utm_") and key.lower() not in _DEDUPE_TRACKING_PARAMS
    ]
    return urlunsplit((
        parts.scheme.lower(),
        parts.netloc.lower(),
        parts.path or "/",
        urlencode(filtered_query, doseq=True),
        "",
    ))


def _normalize_title_for_dedupe(title: str | None) -> str:
    if not title:
        return ""

    normalized = title.strip()
    normalized = re.sub(r"\s+[|-]\s+[A-Za-z0-9&.' ]{2,30}$", "", normalized)
    normalized = re.sub(r"[^a-z0-9\s]", " ", normalized.lower())
    normalized = re.sub(r"\s+", " ", normalized).strip()
    return normalized


def _title_token_set(title: str | None) -> set[str]:
    normalized = _normalize_title_for_dedupe(title)
    tokens = {
        token
        for token in normalized.split()
        if token and token not in _DEDUPE_STOPWORDS and len(token) > 2
    }
    return tokens


def _articles_are_near_duplicates(a: dict, b: dict) -> bool:
    date_a = _parse_article_datetime(a.get("published_at"))
    date_b = _parse_article_datetime(b.get("published_at"))
    if date_a and date_b and abs(date_a - date_b) > timedelta(hours=36):
        return False

    url_a = _canonicalize_url(a.get("url"))
    url_b = _canonicalize_url(b.get("url"))
    if url_a and url_b and url_a == url_b:
        return True

    title_a = _normalize_title_for_dedupe(a.get("title"))
    title_b = _normalize_title_for_dedupe(b.get("title"))
    if not title_a or not title_b:
        return False

    similarity = SequenceMatcher(None, title_a, title_b).ratio()
    if similarity >= 0.88:
        return True

    tokens_a = _title_token_set(a.get("title"))
    tokens_b = _title_token_set(b.get("title"))
    if not tokens_a or not tokens_b:
        return False

    union = tokens_a | tokens_b
    if not union:
        return False
    overlap = len(tokens_a & tokens_b) / len(union)
    return overlap >= 0.75


def _article_rank_score(article: dict) -> float:
    score = article.get("relevance_score")
    if score is None:
        score = article.get("_score", 0.0)
    try:
        return float(score)
    except (TypeError, ValueError):
        return 0.0


def _select_best_duplicate_representative(cluster: list[dict]) -> dict:
    def sort_key(article: dict) -> tuple[int, int, int, float, float]:
        published = _parse_article_datetime(article.get("published_at"))
        return (
            1 if article.get("image_url") else 0,
            len(article.get("content") or ""),
            len(article.get("summary") or ""),
            _article_rank_score(article),
            published.timestamp() if published else 0.0,
        )

    return max(cluster, key=sort_key)


def _collapse_duplicate_coverage(articles: list[dict]) -> list[dict]:
    if len(articles) < 2:
        return articles

    consumed: set[int] = set()
    deduped: list[dict] = []

    for index, article in enumerate(articles):
        if index in consumed:
            continue

        cluster = [article]
        consumed.add(index)

        for candidate_index in range(index + 1, len(articles)):
            if candidate_index in consumed:
                continue
            candidate = articles[candidate_index]
            if any(_articles_are_near_duplicates(existing, candidate) for existing in cluster):
                cluster.append(candidate)
                consumed.add(candidate_index)

        deduped.append(_select_best_duplicate_representative(cluster))

    return deduped


async def _hydrate_missing_feed_images(conn, articles: list[dict], max_articles: int = 15) -> None:
    if not conn:
        return

    missing = [article for article in articles if not article.get("image_url") and article.get("url")][:max_articles]
    if not missing:
        return

    semaphore = asyncio.Semaphore(8)

    async def _fetch(article: dict) -> tuple[dict, str]:
        async with semaphore:
            image_url = await fetch_best_source_image(article["url"], timeout=3.0)
            return article, image_url

    results = await asyncio.gather(*[_fetch(article) for article in missing], return_exceptions=True)

    for result in results:
        if isinstance(result, Exception):
            logger.debug("Feed image hydration failed", exc_info=result)
            continue

        article, image_url = result
        if not image_url:
            continue

        article["image_url"] = image_url
        try:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    UPDATE public.articles
                    SET image_url = COALESCE(image_url, %s)
                    WHERE id = %s
                    """,
                    (image_url, _uuid.UUID(article["id"])),
                )
        except Exception:
            logger.exception("Failed to persist hydrated image for article %s", article.get("id"))


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


def _load_cached_feed(
    conn,
    user_uuid,
    preferences_updated_at: datetime | None = None,
    max_age_minutes: int | None = FEED_CACHE_TTL_MINUTES,
) -> list[dict] | None:
    """Load cached feed if it's still fresh (< TTL minutes old)."""
    with conn.cursor() as cur:
        if max_age_minutes is None:
            cur.execute(
                """
                SELECT ufc.relevance_score, ufc.relevant, ufc.relevance_reason, ufc.created_at,
                       ufc.feed_role, ufc.why_this_story, ufc.why_now, ufc.matched_profile_signals,
                       ufc.cluster_id, ufc.importance_score,
                       a.id, a.url, a.title, a.summary, a.content, a.author,
                       a.source_name, a.image_url, a.published_at, a.category
                FROM public.user_feed_cache ufc
                JOIN public.articles a ON a.id = ufc.article_id
                WHERE ufc.user_id = %s
                ORDER BY ufc.relevance_score DESC
                """,
                (user_uuid,),
            )
        else:
            cutoff = datetime.now(timezone.utc) - timedelta(minutes=max_age_minutes)
            cur.execute(
                """
                SELECT ufc.relevance_score, ufc.relevant, ufc.relevance_reason, ufc.created_at,
                       ufc.feed_role, ufc.why_this_story, ufc.why_now, ufc.matched_profile_signals,
                       ufc.cluster_id, ufc.importance_score,
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

    newest_cache_entry = max((row.get("created_at") for row in rows if row.get("created_at")), default=None)
    if preferences_updated_at and newest_cache_entry and preferences_updated_at > newest_cache_entry:
        logger.info("Cached feed is older than preferences update; treating cache as stale")
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
            "feed_role": row.get("feed_role"),
            "why_this_story": row.get("why_this_story"),
            "why_now": row.get("why_now"),
            "matched_profile_signals": row.get("matched_profile_signals") or [],
            "cluster_id": row.get("cluster_id"),
            "importance_score": row.get("importance_score") or 0.0,
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
            feed_role = article.get("_feed_role")
            why_this_story = article.get("_why_this_story")
            why_now = article.get("_why_now")
            matched_profile_signals = article.get("_matched_profile_signals") or []
            cluster_id = article.get("_cluster_id")
            importance_score = article.get("_importance_score", 0.0)
            try:
                cur.execute(
                    """
                    INSERT INTO public.user_feed_cache (
                        user_id, article_id, relevance_score, relevant, relevance_reason,
                        feed_role, why_this_story, why_now, matched_profile_signals, cluster_id, importance_score
                    )
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb, %s, %s)
                    ON CONFLICT (user_id, article_id) DO UPDATE SET
                        relevance_score = EXCLUDED.relevance_score,
                        relevant = EXCLUDED.relevant,
                        relevance_reason = EXCLUDED.relevance_reason,
                        feed_role = EXCLUDED.feed_role,
                        why_this_story = EXCLUDED.why_this_story,
                        why_now = EXCLUDED.why_now,
                        matched_profile_signals = EXCLUDED.matched_profile_signals,
                        cluster_id = EXCLUDED.cluster_id,
                        importance_score = EXCLUDED.importance_score,
                        created_at = now()
                    """,
                    (
                        user_uuid,
                        _uuid.UUID(article_id),
                        score,
                        relevant,
                        reason,
                        feed_role,
                        why_this_story,
                        why_now,
                        json.dumps(matched_profile_signals),
                        cluster_id,
                        importance_score,
                    ),
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
