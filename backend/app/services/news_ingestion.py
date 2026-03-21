"""
RSS feed ingestion service for fetching news articles from multiple sources.
Replaces the old NewsAPI-based approach with free RSS feeds.
"""
import asyncio
import hashlib
from datetime import datetime, timezone
from typing import Optional
from urllib.parse import urlparse

import httpx
import feedparser

# ~30 RSS feeds from major news outlets
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
            from time import mktime
            return datetime.fromtimestamp(mktime(parsed), tz=timezone.utc)
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


async def _fetch_single_feed(client: httpx.AsyncClient, feed_url: str) -> list[dict]:
    """Fetch and parse a single RSS feed, returning list of article dicts."""
    articles = []
    try:
        response = await client.get(
            feed_url,
            headers={"User-Agent": "DailyNewsApp/1.0 (RSS Reader)"},
        )
        if response.status_code != 200:
            print(f"RSS: HTTP {response.status_code} for {feed_url}")
            return []

        feed = feedparser.parse(response.text)
        category = _guess_category(feed_url)

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
            source_name = feed.feed.get("title", urlparse(feed_url).netloc)
            image_url = _extract_image_url(entry)
            published_at = _parse_date(entry)

            articles.append({
                "url": link,
                "title": title,
                "summary": summary or None,
                "author": author,
                "source_name": source_name,
                "image_url": image_url,
                "published_at": published_at,
                "category": category,
            })

    except Exception as e:
        print(f"RSS: Error fetching {feed_url}: {e}")

    return articles


async def _fetch_og_image(client: httpx.AsyncClient, article: dict) -> None:
    """Fetch og:image from an article's URL and update the article dict in place."""
    try:
        response = await client.get(
            article["url"],
            headers={"User-Agent": "Mozilla/5.0 (compatible; DailyNewsBot/1.0)"},
        )
        if response.status_code != 200:
            return
        from bs4 import BeautifulSoup
        soup = BeautifulSoup(response.text[:50000], "html.parser")
        og_image = soup.find("meta", property="og:image") or soup.find("meta", attrs={"name": "og:image"})
        if og_image and og_image.get("content"):
            article["image_url"] = og_image["content"].strip()
    except Exception:
        pass


async def _fetch_og_images(articles: list[dict]) -> int:
    """Fetch og:image for articles missing image_url. Returns count of images found."""
    missing = [a for a in articles if not a.get("image_url")]
    if not missing:
        return 0

    found = 0
    semaphore = asyncio.Semaphore(10)

    async def _fetch_with_limit(client, article):
        async with semaphore:
            await _fetch_og_image(client, article)

    async with httpx.AsyncClient(timeout=5.0, follow_redirects=True) as client:
        tasks = [_fetch_with_limit(client, a) for a in missing]
        await asyncio.gather(*tasks, return_exceptions=True)

    for a in missing:
        if a.get("image_url"):
            found += 1

    return found


async def fetch_rss_feeds(conn) -> int:
    """
    Fetch all RSS feeds in parallel and insert new articles into the articles table.
    Returns the number of new articles inserted.
    """
    new_count = 0

    async with httpx.AsyncClient(timeout=15.0, follow_redirects=True) as client:
        tasks = [_fetch_single_feed(client, url) for url in RSS_FEEDS]
        results = await asyncio.gather(*tasks, return_exceptions=True)

    all_articles = []
    for result in results:
        if isinstance(result, list):
            all_articles.extend(result)

    if not all_articles:
        print("RSS: No articles fetched from any feed")
        return 0

    print(f"RSS: Fetched {len(all_articles)} total entries from {len(RSS_FEEDS)} feeds")

    # Deduplicate by URL within this batch
    seen_urls = set()
    unique_articles = []
    for article in all_articles:
        if article["url"] not in seen_urls:
            seen_urls.add(article["url"])
            unique_articles.append(article)

    # Fetch og:image for articles missing images from RSS metadata
    og_count = await _fetch_og_images(unique_articles)
    if og_count:
        print(f"RSS: Fetched og:image for {og_count} articles missing RSS images")

    # Insert into database, skipping duplicates
    with conn.cursor() as cur:
        for article in unique_articles:
            try:
                cur.execute(
                    """
                    INSERT INTO public.articles (url, title, summary, author, source_name, image_url, published_at, category)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (url) DO NOTHING
                    """,
                    (
                        article["url"],
                        article["title"],
                        article["summary"],
                        article["author"],
                        article["source_name"],
                        article["image_url"],
                        article["published_at"],
                        article["category"],
                    ),
                )
                # rowcount == 1 means the row was actually inserted (not a conflict)
                if cur.rowcount == 1:
                    new_count += 1
            except Exception as e:
                print(f"RSS: Error inserting article '{article['title'][:50]}': {e}")

    print(f"RSS: Inserted {new_count} new articles (skipped {len(unique_articles) - new_count} duplicates)")
    return new_count
