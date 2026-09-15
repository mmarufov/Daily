"""
RSS feed ingestion service for fetching news articles from multiple sources.
Replaces the old NewsAPI-based approach with free RSS feeds.
"""
import asyncio
import hashlib
import json
import logging
from datetime import datetime, timedelta, timezone
from typing import Optional
from urllib.parse import quote, urlparse

import httpx
import feedparser

from app.services.image_extraction import fetch_best_source_image
from app.services.article_content import article_content_transaction, register_ingested_article

logger = logging.getLogger(__name__)

# Minimum length for `content:encoded` to count as a real article body rather
# than an expanded teaser.
FEED_CONTENT_MIN_LENGTH = 600

# Broad news feeds plus a small set of niche feeds for strict topic matching.
RSS_FEEDS = [
    # Wire services / breaking news
    "https://news.google.com/rss?hl=en-US&gl=US&ceid=US:en",
    # US major outlets
    "https://rss.nytimes.com/services/xml/rss/nyt/HomePage.xml",
    "https://rss.nytimes.com/services/xml/rss/nyt/World.xml",
    "https://rss.nytimes.com/services/xml/rss/nyt/Technology.xml",
    "https://rss.nytimes.com/services/xml/rss/nyt/Business.xml",
    "https://feeds.npr.org/1001/rss.xml",
    "https://feeds.npr.org/1004/rss.xml",  # World
    # International
    "https://feeds.bbci.co.uk/news/rss.xml",
    "https://www.theguardian.com/world/rss",
    "https://www.theguardian.com/technology/rss",
    "https://www.theguardian.com/business/rss",
    "https://www.aljazeera.com/xml/rss/all.xml",
    "https://rss.dw.com/rdf/rss-en-all",
    # Tech
    "https://feeds.arstechnica.com/arstechnica/index",
    "https://www.theverge.com/rss/index.xml",
    "https://techcrunch.com/feed/",
    "https://www.wired.com/feed/rss",
    "https://9to5mac.com/feed/",
    # Gaming
    "https://www.polygon.com/rss/index.xml",
    "https://www.pcgamer.com/rss/",
    "https://www.eurogamer.net/feed",
    "https://www.rockpapershotgun.com/feed",
    "https://www.gameinformer.com/rss.xml",
    "https://www.gamesindustry.biz/feed",
    "https://www.destructoid.com/feed/",
    "https://www.gamesradar.com/rss/",
    # AI / Machine Learning
    "https://openai.com/blog/rss/",
    "https://blog.google/technology/ai/rss/",
    "https://www.artificialintelligence-news.com/feed/",
    "https://venturebeat.com/category/ai/feed/",
    "https://spectrum.ieee.org/feeds/topic/artificial-intelligence",
    # Business
    "https://www.cnbc.com/id/100003114/device/rss/rss.html",
    "https://fortune.com/feed/",
    # Science
    "https://www.sciencedaily.com/rss/all.xml",
    "https://rss.nytimes.com/services/xml/rss/nyt/Science.xml",
    # Sports
    "https://www.espn.com/espn/rss/news",
    # Entertainment / Culture
    "https://rss.nytimes.com/services/xml/rss/nyt/Arts.xml",
    "https://www.theguardian.com/culture/rss",
]

# Map feed URL patterns to categories
FEED_CATEGORIES = {
    "ai": ["openai", "artificialintelligence", "artificial-intelligence", "deepmind", "/ai/"],
    "technology": ["technology", "tech", "arstechnica", "theverge", "techcrunch", "wired"],
    "gaming": [
        "polygon",
        "pcgamer",
        "eurogamer",
        "rockpapershotgun",
        "gameinformer",
        "gamesindustry",
        "destructoid",
        "gamesradar",
        "gaming",
        "videogame",
        "video-game",
        "esports",
    ],
    "world": ["world", "worldnews", "aljazeera"],
    "business": ["business", "markets", "cnbc", "bloomberg"],
    "science": ["science", "sciencedaily"],
    "sports": ["espn", "sports"],
    "politics": ["politics"],
}


def _guess_category(feed_url: str) -> Optional[str]:
    """Guess article category from the feed URL."""
    url_lower = feed_url.lower()
    for category, patterns in FEED_CATEGORIES.items():
        if any(p in url_lower for p in patterns):
            return category
    return "general"


def _category_for_topic(topic: str) -> str:
    """Map a user interest topic to an article category."""
    topic_lower = topic.lower()
    for category, patterns in FEED_CATEGORIES.items():
        if topic_lower == category or any(p in topic_lower for p in patterns):
            return category
    return "general"


async def _resolve_redirect_urls(_client: httpx.AsyncClient, articles: list[dict]) -> None:
    """Resolve Google News redirects through the shared SSRF-safe fetcher.

    The client argument remains for caller compatibility, but intentionally is
    not used: an ordinary ``httpx`` redirect chain can cross from a public URL
    to a private address without re-validating each hop.
    """
    redirected = [a for a in articles if "news.google.com" in (a.get("url") or "")]
    if not redirected:
        return

    # Lazy import keeps the pure feed parsing helpers usable in constrained
    # test/tooling environments that intentionally stub the HTTP client.
    from app.services.safe_http import SafeFetchPolicy, safe_fetch

    semaphore = asyncio.Semaphore(5)

    async def _resolve(article: dict) -> None:
        async with semaphore:
            try:
                fetched = await safe_fetch(
                    article["url"],
                    policy=SafeFetchPolicy(
                        timeout_seconds=10.0,
                        max_redirects=5,
                        max_wire_bytes=256_000,
                        max_decoded_bytes=256_000,
                        allowed_content_types=None,
                    ),
                )
                resolved = fetched.url
                if resolved != article["url"]:
                    article["url"] = resolved
            except Exception:
                pass  # Keep original URL on failure

    await asyncio.gather(*[_resolve(a) for a in redirected], return_exceptions=True)


def _extract_image_url(entry: dict) -> Optional[str]:
    """Extract image URL from RSS entry (media:content, enclosure, or media:thumbnail)."""
    # media:content
    media_content = entry.get("media_content", [])
    if media_content:
        for media in media_content:
            if media.get("medium") == "image" or (media.get("type", "").startswith("image")):
                return media.get("url")
        # Fallback: first media_content with a URL
        if media_content[0].get("url"):
            return media_content[0]["url"]

    # media:thumbnail
    media_thumbnail = entry.get("media_thumbnail", [])
    if media_thumbnail and media_thumbnail[0].get("url"):
        return media_thumbnail[0]["url"]

    # enclosure
    enclosures = entry.get("enclosures", [])
    if not enclosures:
        links = entry.get("links", [])
        enclosures = [l for l in links if l.get("rel") == "enclosure"]
    for enc in enclosures:
        if enc.get("type", "").startswith("image"):
            return enc.get("href") or enc.get("url")

    return None


def _parse_date(entry: dict) -> Optional[datetime]:
    """Parse published date from RSS entry."""
    date_str = entry.get("published") or entry.get("updated")
    if not date_str:
        return None
    parsed = entry.get("published_parsed") or entry.get("updated_parsed")
    if parsed:
        try:
            # feedparser's *_parsed struct_time is already UTC (it normalizes
            # every feed's timezone/offset before handing it back). mktime()
            # instead interprets a struct_time as *local* time and converts
            # to a local epoch -- on any host not running in UTC, that silently
            # shifts every parsed date by the host's UTC offset, then the
            # result gets mislabeled `tz=timezone.utc` on top of that.
            # calendar.timegm() is the UTC-correct inverse of gmtime().
            from calendar import timegm
            return datetime.fromtimestamp(timegm(parsed), tz=timezone.utc)
        except (ValueError, OverflowError, OSError):
            pass
    return None


def _clean_html(text: str) -> str:
    """Remove HTML tags from text."""
    if not text:
        return ""
    # Skip if text doesn't look like HTML
    if "<" not in text:
        return text.strip()
    from bs4 import BeautifulSoup
    return BeautifulSoup(text, "html.parser").get_text(separator=" ", strip=True)


def _extract_feed_content(entry: dict) -> Optional[str]:
    """Return the longest substantial ``content:encoded`` candidate.

    Presence in a feed is useful provenance but is not, by itself, permission
    or proof that the value is a complete article. ``article_content`` keeps it
    non-display until that source has an explicitly reviewed full-text policy.
    """
    values = entry.get("content")
    if not isinstance(values, list):
        return None

    best = ""
    for item in values:
        if not isinstance(item, dict):
            continue
        text = _clean_html(item.get("value") or "")
        if len(text) > len(best):
            best = text

    return best if len(best) >= FEED_CONTENT_MIN_LENGTH else None


async def _fetch_single_feed(client: httpx.AsyncClient, feed_url: str) -> list[dict]:
    """Fetch and parse a single RSS feed, returning list of article dicts.

    ``client`` remains for caller compatibility but is intentionally unused:
    an ordinary httpx client with ``follow_redirects=True`` (as both callers
    of this function construct) can hop from a public feed URL to a
    private/internal address on any redirect hop without re-validating it.
    Every recurring feed fetch goes through the shared SSRF-safe fetcher
    instead, matching every other outbound fetch in this codebase (see
    ``_resolve_redirect_urls`` above for the same pattern and reasoning).
    """
    from app.services.safe_http import SafeFetchError, SafeFetchPolicy, safe_fetch

    articles = []
    try:
        try:
            fetched = await safe_fetch(
                feed_url,
                policy=SafeFetchPolicy(
                    timeout_seconds=15.0,
                    max_redirects=5,
                    max_wire_bytes=5_000_000,
                    max_decoded_bytes=5_000_000,
                    # Feed content-type headers are inconsistent across
                    # publishers (rss+xml, atom+xml, xml, even text/html on
                    # misconfigured servers); the safety property that
                    # matters here is DNS-pinning and redirect
                    # re-validation, not content-type gating.
                    allowed_content_types=None,
                ),
            )
        except SafeFetchError as exc:
            print(f"RSS: {exc.code} ({exc.status_code or '-'}) for {feed_url}")
            return []

        feed = feedparser.parse(fetched.text)
        category = _guess_category(feed_url)
        fetched_feed_url = fetched.url

        for entry in feed.entries:
            link = entry.get("link", "").strip()
            if not link:
                continue

            title = _clean_html(entry.get("title", "")).strip()
            if not title:
                continue

            summary = _clean_html(entry.get("summary", "") or entry.get("description", ""))
            # Truncate very long summaries
            if len(summary) > 1000:
                summary = summary[:1000]

            author = entry.get("author")
            entry_source = entry.get("source") or {}
            source_name = (
                entry_source.get("title")
                or feed.feed.get("title")
                or urlparse(feed_url).netloc
            )
            image_url = _extract_image_url(entry)
            published_at = _parse_date(entry)
            feed_content = _extract_feed_content(entry)

            # Skip articles older than 7 days
            if published_at and published_at < datetime.now(timezone.utc) - timedelta(days=7):
                continue

            articles.append({
                "url": link,
                "title": title,
                "summary": summary or None,
                "content": feed_content,
                "feed_url": fetched_feed_url,
                "author": author,
                "source_name": source_name,
                "image_url": image_url,
                "image_origin": "publisher_feed" if image_url else None,
                "image_source_url": feed_url if image_url else None,
                "image_attribution": source_name if image_url else None,
                "image_is_illustrative": False,
                "published_at": published_at,
                "category": category,
            })

    except Exception as e:
        print(f"RSS: Error fetching {feed_url}: {e}")

    return articles


async def _fetch_source_image(article: dict) -> None:
    """Fetch the best source-authentic image from an article page."""
    try:
        image_url = await fetch_best_source_image(article["url"], timeout=5.0)
        if image_url:
            article["image_url"] = image_url
            article["image_origin"] = "publisher_page"
            article["image_source_url"] = article["url"]
            article["image_attribution"] = article.get("source_name")
            article["image_is_illustrative"] = False
    except Exception:
        pass


async def _fetch_source_images(articles: list[dict]) -> int:
    """Fetch source-authentic images for articles missing image_url. Returns count of images found."""
    missing = [a for a in articles if not a.get("image_url")]
    if not missing:
        return 0

    found = 0
    semaphore = asyncio.Semaphore(3)

    async def _fetch_with_limit(article):
        async with semaphore:
            await _fetch_source_image(article)

    tasks = [_fetch_with_limit(a) for a in missing]
    await asyncio.gather(*tasks, return_exceptions=True)

    for a in missing:
        if a.get("image_url"):
            found += 1

    return found


def _upsert_ingested_article(conn, article: dict):
    """Atomically persist metadata and register the content lifecycle."""
    with article_content_transaction(conn):
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO public.articles (
                    url, title, summary, content, content_extracted,
                    author, source_name, image_url, image_origin,
                    image_source_url, image_attribution, image_is_illustrative,
                    published_at, category
                )
                VALUES (%s, %s, %s, NULL, false, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (url) DO UPDATE SET
                    title = COALESCE(NULLIF(EXCLUDED.title, ''), public.articles.title),
                    image_url = CASE
                        WHEN EXCLUDED.image_url IS NOT NULL
                         AND (public.articles.image_url IS NULL
                              OR public.articles.image_origin IS NULL
                              OR public.articles.image_origin = 'legacy_unknown')
                        THEN EXCLUDED.image_url ELSE public.articles.image_url END,
                    image_origin = CASE
                        WHEN EXCLUDED.image_url IS NOT NULL
                         AND (public.articles.image_url IS NULL
                              OR public.articles.image_origin IS NULL
                              OR public.articles.image_origin = 'legacy_unknown')
                        THEN EXCLUDED.image_origin ELSE public.articles.image_origin END,
                    image_source_url = CASE
                        WHEN EXCLUDED.image_url IS NOT NULL
                         AND (public.articles.image_url IS NULL
                              OR public.articles.image_origin IS NULL
                              OR public.articles.image_origin = 'legacy_unknown')
                        THEN EXCLUDED.image_source_url ELSE public.articles.image_source_url END,
                    image_attribution = CASE
                        WHEN EXCLUDED.image_url IS NOT NULL
                         AND (public.articles.image_url IS NULL
                              OR public.articles.image_origin IS NULL
                              OR public.articles.image_origin = 'legacy_unknown')
                        THEN EXCLUDED.image_attribution ELSE public.articles.image_attribution END,
                    image_is_illustrative = CASE
                        WHEN EXCLUDED.image_url IS NOT NULL
                         AND (public.articles.image_url IS NULL
                              OR public.articles.image_origin IS NULL
                              OR public.articles.image_origin = 'legacy_unknown')
                        THEN EXCLUDED.image_is_illustrative ELSE public.articles.image_is_illustrative END,
                    summary = COALESCE(public.articles.summary, EXCLUDED.summary),
                    author = COALESCE(public.articles.author, EXCLUDED.author),
                    source_name = COALESCE(public.articles.source_name, EXCLUDED.source_name),
                    published_at = COALESCE(public.articles.published_at, EXCLUDED.published_at),
                    category = COALESCE(public.articles.category, EXCLUDED.category)
                RETURNING id
                """,
                (
                    article["url"],
                    article["title"],
                    article["summary"],
                    article["author"],
                    article["source_name"],
                    article["image_url"],
                    article.get("image_origin"),
                    article.get("image_source_url"),
                    article.get("image_attribution"),
                    bool(article.get("image_is_illustrative", False)),
                    article["published_at"],
                    article["category"],
                ),
            )
            stored = cur.fetchone()
        if not stored:
            return None
        register_ingested_article(
            conn,
            stored["id"],
            canonical_url=article["url"],
            feed_content=article.get("content"),
            feed_url=article.get("feed_url"),
        )
        return stored["id"]


async def fetch_rss_feeds(conn) -> int:
    """
    Fetch all RSS feeds in parallel and insert new articles into the articles table.
    Returns the number of new articles inserted.
    """
    new_count = 0

    semaphore = asyncio.Semaphore(10)

    async def _fetch_with_limit(client, url):
        async with semaphore:
            return await _fetch_single_feed(client, url)

    async with httpx.AsyncClient(timeout=15.0, follow_redirects=True) as client:
        tasks = [_fetch_with_limit(client, url) for url in RSS_FEEDS]
        results = await asyncio.gather(*tasks, return_exceptions=True)

    all_articles = []
    for result in results:
        if isinstance(result, list):
            all_articles.extend(result)

    if not all_articles:
        print("RSS: No articles fetched from any feed")
        return 0

    # The broad source set also includes Google News. Resolve wrappers before
    # dedup and before attributing later page-origin artifacts.
    await _resolve_redirect_urls(None, all_articles)

    print(f"RSS: Fetched {len(all_articles)} total entries from {len(RSS_FEEDS)} feeds")

    # Deduplicate by URL within this batch
    seen_urls = set()
    unique_articles = []
    for article in all_articles:
        if article["url"] not in seen_urls:
            seen_urls.add(article["url"])
            unique_articles.append(article)

    # Fetch article-page images for entries missing RSS metadata
    source_image_count = await _fetch_source_images(unique_articles)
    if source_image_count:
        print(f"RSS: Fetched source images for {source_image_count} articles missing RSS images")

    # Insert the article and register its content job in one transaction. Raw
    # feed text never goes directly into the legacy display-body columns.
    for article in unique_articles:
        try:
            if _upsert_ingested_article(conn, article):
                new_count += 1
        except Exception as e:
            print(f"RSS: Error inserting article '{article['title'][:50]}': {e}")

    print(f"RSS: Inserted {new_count} new articles (skipped {len(unique_articles) - new_count} duplicates)")
    return new_count


def _extract_user_topics(conn) -> set[str]:
    """Collect unique topic terms from all users' structured interests."""
    with conn.cursor() as cur:
        cur.execute(
            "SELECT interests FROM public.user_preferences WHERE completed = true AND interests IS NOT NULL"
        )
        rows = cur.fetchall()

    topics: set[str] = set()
    for row in rows:
        raw = row.get("interests")
        if isinstance(raw, str):
            try:
                raw = json.loads(raw)
            except (json.JSONDecodeError, TypeError):
                continue
        if not isinstance(raw, dict):
            continue
        # Handle both {"topics": [...]} and {"interests": {"topics": [...]}}
        inner = raw.get("interests", raw) if isinstance(raw.get("interests"), dict) else raw
        for key in ("topics", "people", "industries"):
            for term in inner.get(key) or []:
                cleaned = str(term).strip()
                if len(cleaned) >= 2:
                    topics.add(cleaned)
    return topics


async def fetch_topic_feeds(conn) -> int:
    """Fetch Google News RSS for each unique user topic to cover niche interests."""
    topics = _extract_user_topics(conn)
    if not topics:
        return 0

    # Build (url, topic, category) tuples so we can assign categories from the source topic
    topic_feeds = []
    for topic in topics:
        url = f"https://news.google.com/rss/search?q={quote(topic)}&hl=en-US&gl=US&ceid=US:en"
        category = _category_for_topic(topic)
        topic_feeds.append((url, topic, category))

    semaphore = asyncio.Semaphore(5)

    async def _fetch_with_limit(client, url, category):
        async with semaphore:
            articles = await _fetch_single_feed(client, url)
            # Override category from the topic query (Google News URLs don't match _guess_category)
            for a in articles:
                a["category"] = category
            return articles

    async with httpx.AsyncClient(timeout=15.0, follow_redirects=True) as client:
        tasks = [_fetch_with_limit(client, url, cat) for url, _topic, cat in topic_feeds]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        all_articles: list[dict] = []
        for result in results:
            if isinstance(result, list):
                all_articles.extend(result)

        if not all_articles:
            return 0

        # Resolve Google News redirect URLs to actual article URLs for proper dedup
        await _resolve_redirect_urls(client, all_articles)

    # Deduplicate by URL within this batch
    seen_urls: set[str] = set()
    unique: list[dict] = []
    for a in all_articles:
        if a["url"] not in seen_urls:
            seen_urls.add(a["url"])
            unique.append(a)

    # Fetch article-page images (Google News RSS never has image metadata)
    source_image_count = await _fetch_source_images(unique)
    if source_image_count:
        logger.info("Topic RSS: Fetched source images for %d articles", source_image_count)

    new_count = 0
    for article in unique:
        try:
            if _upsert_ingested_article(conn, article):
                new_count += 1
        except Exception as e:
            logger.warning("Topic RSS: Error inserting '%s': %s", article["title"][:50], e)

    logger.info("Topic RSS: Fetched %d entries for %d topics, inserted %d new", len(unique), len(topics), new_count)
    return new_count
