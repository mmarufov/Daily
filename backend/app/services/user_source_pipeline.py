from __future__ import annotations

import asyncio
import logging
import time
import uuid as _uuid

import httpx

from app.services.feed_service import (
    _canonicalize_url,
    _load_cached_feed,
    _load_user_preferences,
    get_personalized_feed,
)
from app.services.news_ingestion import (
    _fetch_single_feed,
    _fetch_source_images,
    _resolve_redirect_urls,
)
from app.services.source_discovery import determine_profile_specificity

logger = logging.getLogger(__name__)

QUALITY_GATE_BY_SPECIFICITY = {
    "specific": 6,
    "mixed": 10,
    "broad": 15,
}


def _load_active_user_sources(conn, user_id: str) -> list[dict]:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT id, source_url, source_name, category, discovery_method,
                   source_kind, scope, matched_targets, discovery_score, selection_rank
            FROM public.user_sources
            WHERE user_id = %s AND active = true
            ORDER BY selection_rank ASC, discovery_score DESC, source_name ASC
            """,
            (user_id,),
        )
        return cur.fetchall()


def _update_source_fetch_outcomes(conn, source_results: list[dict]) -> None:
    with conn.cursor() as cur:
        for result in source_results:
            source = result["source"]
            if result.get("error"):
                cur.execute(
                    """
                    UPDATE public.user_sources
                    SET failure_count = failure_count + 1,
                        active = CASE WHEN failure_count >= 4 THEN false ELSE active END
                    WHERE id = %s
                    """,
                    (source["id"],),
                )
                continue

            cur.execute(
                """
                UPDATE public.user_sources
                SET last_fetched_at = now(),
                    failure_count = 0,
                    validated_at = now()
                WHERE id = %s
                """,
                (source["id"],),
            )


def _merge_fetched_articles(articles: list[dict]) -> list[dict]:
    merged: dict[str, dict] = {}

    for article in articles:
        canonical_url = _canonicalize_url(article.get("url")) or (article.get("url") or "").strip()
        if not canonical_url:
            continue

        record = dict(article)
        record["url"] = canonical_url

        existing = merged.get(canonical_url)
        if not existing:
            merged[canonical_url] = record
            continue

        existing["_source_urls"] = sorted(set(existing.get("_source_urls", []) + record.get("_source_urls", [])))
        if not existing.get("summary") and record.get("summary"):
            existing["summary"] = record["summary"]
        if not existing.get("author") and record.get("author"):
            existing["author"] = record["author"]
        if not existing.get("image_url") and record.get("image_url"):
            existing["image_url"] = record["image_url"]
        if not existing.get("published_at") and record.get("published_at"):
            existing["published_at"] = record["published_at"]
        if not existing.get("category") and record.get("category"):
            existing["category"] = record["category"]

    return list(merged.values())


def _upsert_articles_and_links(conn, articles: list[dict]) -> int:
    linked_count = 0

    with conn.cursor() as cur:
        for article in articles:
            cur.execute(
                """
                INSERT INTO public.articles (
                    url, title, summary, author, source_name, image_url, published_at, category, ingested_at
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, now())
                ON CONFLICT (url) DO UPDATE SET
                    title = COALESCE(NULLIF(EXCLUDED.title, ''), public.articles.title),
                    summary = COALESCE(public.articles.summary, EXCLUDED.summary),
                    author = COALESCE(public.articles.author, EXCLUDED.author),
                    source_name = COALESCE(public.articles.source_name, EXCLUDED.source_name),
                    image_url = COALESCE(public.articles.image_url, EXCLUDED.image_url),
                    published_at = COALESCE(public.articles.published_at, EXCLUDED.published_at),
                    category = COALESCE(public.articles.category, EXCLUDED.category),
                    ingested_at = now()
                RETURNING id
                """,
                (
                    article.get("url"),
                    article.get("title") or "Untitled",
                    article.get("summary"),
                    article.get("author"),
                    article.get("source_name"),
                    article.get("image_url"),
                    article.get("published_at"),
                    article.get("category"),
                ),
            )
            row = cur.fetchone()
            article_id = row["id"]

            for source_url in article.get("_source_urls", []):
                cur.execute(
                    """
                    INSERT INTO public.article_source_links (article_id, source_url, fetched_at, published_at)
                    VALUES (%s, %s, now(), %s)
                    ON CONFLICT (article_id, source_url) DO UPDATE SET
                        fetched_at = now(),
                        published_at = COALESCE(EXCLUDED.published_at, public.article_source_links.published_at)
                    """,
                    (article_id, source_url, article.get("published_at")),
                )
                linked_count += 1

    return linked_count


async def _fetch_from_user_sources(conn, sources: list[dict]) -> int:
    if not sources:
        return 0

    semaphore = asyncio.Semaphore(8)

    async with httpx.AsyncClient(timeout=15.0, follow_redirects=True) as client:
        async def _fetch_one(source: dict) -> dict:
            async with semaphore:
                try:
                    articles = await _fetch_single_feed(client, source["source_url"])
                    for article in articles:
                        article["category"] = source.get("category") or article.get("category")
                    return {"source": source, "articles": articles, "error": None}
                except Exception as exc:
                    logger.warning("Error fetching user source %s: %s", source.get("source_url"), exc)
                    return {"source": source, "articles": [], "error": exc}

        source_results = await asyncio.gather(*[_fetch_one(source) for source in sources])

        flattened: list[dict] = []
        for result in source_results:
            source = result["source"]
            for article in result.get("articles") or []:
                article["_source_urls"] = [source["source_url"]]
                flattened.append(article)

        if flattened:
            await _resolve_redirect_urls(client, flattened)

    _update_source_fetch_outcomes(conn, source_results)

    merged = _merge_fetched_articles(flattened)
    if not merged:
        return 0

    await _fetch_source_images(merged)
    return _upsert_articles_and_links(conn, merged)


def get_feed_state(conn, user_id: str, limit: int = 50) -> dict:
    user_uuid = _uuid.UUID(user_id)
    _ai_profile, interests, preferences_updated_at = _load_user_preferences(conn, user_uuid)

    sources = _load_active_user_sources(conn, user_id)
    if not sources:
        return {"status": "needs_discovery", "articles": []}

    cached = _load_cached_feed(
        conn,
        user_uuid,
        preferences_updated_at=preferences_updated_at,
        max_age_minutes=None,
    )
    if not cached:
        return {"status": "needs_build", "articles": []}

    ready_articles = [article for article in cached if article.get("relevant", False)]
    if not ready_articles:
        return {"status": "needs_build", "articles": []}

    return {"status": "ready", "articles": ready_articles[:limit]}


async def build_feed_for_user(conn, user_id: str, limit: int = 50) -> dict:
    sources = _load_active_user_sources(conn, user_id)
    if not sources:
        return {
            "status": "needs_discovery",
            "articles": [],
            "article_count": 0,
            "quality_met": False,
            "build_time_seconds": 0.0,
        }

    started = time.perf_counter()
    await _fetch_from_user_sources(conn, sources)

    articles = await get_personalized_feed(user_id, conn, limit=limit, force_refresh=True)

    user_uuid = _uuid.UUID(user_id)
    ai_profile, interests, _preferences_updated_at = _load_user_preferences(conn, user_uuid)
    specificity = determine_profile_specificity(interests, ai_profile)
    threshold = QUALITY_GATE_BY_SPECIFICITY[specificity]

    return {
        "status": "ready",
        "articles": articles,
        "article_count": len(articles),
        "quality_met": len(articles) >= threshold,
        "build_time_seconds": round(time.perf_counter() - started, 2),
        "profile_specificity": specificity,
    }
