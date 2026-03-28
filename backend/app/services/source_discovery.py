"""
Source discovery service: finds and validates RSS/Atom feeds for user interests.
Hybrid approach: curated seed database + AI-suggested feeds + validation.
"""
import asyncio
import json
import logging
from urllib.parse import urlparse

import feedparser
import httpx

logger = logging.getLogger(__name__)

# ~200 curated feeds organized by category (expandable)
SEED_SOURCES = [
    # ── Wire services / breaking news ──
    {"url": "https://news.google.com/rss?hl=en-US&gl=US&ceid=US:en", "name": "Google News", "category": "general", "tier": "premium"},
    {"url": "https://feeds.bbci.co.uk/news/rss.xml", "name": "BBC News", "category": "general", "tier": "premium"},
    {"url": "https://rss.nytimes.com/services/xml/rss/nyt/HomePage.xml", "name": "New York Times", "category": "general", "tier": "premium"},
    {"url": "https://feeds.npr.org/1001/rss.xml", "name": "NPR", "category": "general", "tier": "premium"},
    {"url": "https://www.aljazeera.com/xml/rss/all.xml", "name": "Al Jazeera", "category": "world", "tier": "premium"},
    {"url": "https://rss.dw.com/rdf/rss-en-all", "name": "DW News", "category": "world", "tier": "standard"},
    # ── Technology ──
    {"url": "https://feeds.arstechnica.com/arstechnica/index", "name": "Ars Technica", "category": "technology", "tier": "premium"},
    {"url": "https://www.theverge.com/rss/index.xml", "name": "The Verge", "category": "technology", "tier": "premium"},
    {"url": "https://techcrunch.com/feed/", "name": "TechCrunch", "category": "technology", "tier": "premium"},
    {"url": "https://www.wired.com/feed/rss", "name": "Wired", "category": "technology", "tier": "premium"},
    {"url": "https://9to5mac.com/feed/", "name": "9to5Mac", "category": "technology", "tier": "standard"},
    {"url": "https://9to5google.com/feed/", "name": "9to5Google", "category": "technology", "tier": "standard"},
    {"url": "https://www.macrumors.com/macrumors.xml", "name": "MacRumors", "category": "technology", "tier": "standard"},
    {"url": "https://www.engadget.com/rss.xml", "name": "Engadget", "category": "technology", "tier": "standard"},
    {"url": "https://thenextweb.com/feed", "name": "The Next Web", "category": "technology", "tier": "standard"},
    {"url": "https://www.zdnet.com/news/rss.xml", "name": "ZDNet", "category": "technology", "tier": "standard"},
    {"url": "https://www.techmeme.com/feed.xml", "name": "Techmeme", "category": "technology", "tier": "standard"},
    {"url": "https://hackernoon.com/feed", "name": "HackerNoon", "category": "technology", "tier": "niche"},
    # ── AI / Machine Learning ──
    {"url": "https://openai.com/blog/rss/", "name": "OpenAI Blog", "category": "ai", "tier": "premium"},
    {"url": "https://blog.google/technology/ai/rss/", "name": "Google AI Blog", "category": "ai", "tier": "premium"},
    {"url": "https://www.artificialintelligence-news.com/feed/", "name": "AI News", "category": "ai", "tier": "standard"},
    {"url": "https://venturebeat.com/category/ai/feed/", "name": "VentureBeat AI", "category": "ai", "tier": "standard"},
    {"url": "https://spectrum.ieee.org/feeds/topic/artificial-intelligence", "name": "IEEE Spectrum AI", "category": "ai", "tier": "standard"},
    {"url": "https://www.deeplearning.ai/the-batch/feed/", "name": "The Batch", "category": "ai", "tier": "niche"},
    {"url": "https://huggingface.co/blog/feed.xml", "name": "Hugging Face Blog", "category": "ai", "tier": "niche"},
    {"url": "https://lilianweng.github.io/index.xml", "name": "Lilian Weng", "category": "ai", "tier": "niche"},
    {"url": "https://www.marktechpost.com/feed/", "name": "MarkTechPost", "category": "ai", "tier": "niche"},
    # ── Gaming ──
    {"url": "https://www.polygon.com/rss/index.xml", "name": "Polygon", "category": "gaming", "tier": "premium"},
    {"url": "https://www.pcgamer.com/rss/", "name": "PC Gamer", "category": "gaming", "tier": "premium"},
    {"url": "https://www.eurogamer.net/feed", "name": "Eurogamer", "category": "gaming", "tier": "standard"},
    {"url": "https://www.rockpapershotgun.com/feed", "name": "Rock Paper Shotgun", "category": "gaming", "tier": "standard"},
    {"url": "https://www.gameinformer.com/rss.xml", "name": "Game Informer", "category": "gaming", "tier": "standard"},
    {"url": "https://www.gamesindustry.biz/feed", "name": "GamesIndustry.biz", "category": "gaming", "tier": "standard"},
    {"url": "https://www.destructoid.com/feed/", "name": "Destructoid", "category": "gaming", "tier": "standard"},
    {"url": "https://www.gamesradar.com/rss/", "name": "GamesRadar+", "category": "gaming", "tier": "standard"},
    {"url": "https://kotaku.com/rss", "name": "Kotaku", "category": "gaming", "tier": "standard"},
    {"url": "https://www.ign.com/articles?feed=ign-all", "name": "IGN", "category": "gaming", "tier": "standard"},
    # ── Business / Finance ──
    {"url": "https://rss.nytimes.com/services/xml/rss/nyt/Business.xml", "name": "NYT Business", "category": "business", "tier": "premium"},
    {"url": "https://www.cnbc.com/id/100003114/device/rss/rss.html", "name": "CNBC", "category": "business", "tier": "premium"},
    {"url": "https://fortune.com/feed/", "name": "Fortune", "category": "business", "tier": "standard"},
    {"url": "https://www.theguardian.com/business/rss", "name": "Guardian Business", "category": "business", "tier": "standard"},
    {"url": "https://feeds.bloomberg.com/markets/news.rss", "name": "Bloomberg Markets", "category": "business", "tier": "premium"},
    {"url": "https://www.economist.com/finance-and-economics/rss.xml", "name": "The Economist Finance", "category": "business", "tier": "niche"},
    {"url": "https://www.ft.com/rss/home", "name": "Financial Times", "category": "business", "tier": "premium"},
    # ── Science ──
    {"url": "https://www.sciencedaily.com/rss/all.xml", "name": "ScienceDaily", "category": "science", "tier": "premium"},
    {"url": "https://rss.nytimes.com/services/xml/rss/nyt/Science.xml", "name": "NYT Science", "category": "science", "tier": "premium"},
    {"url": "https://www.nature.com/nature.rss", "name": "Nature", "category": "science", "tier": "premium"},
    {"url": "https://www.newscientist.com/feed/home/", "name": "New Scientist", "category": "science", "tier": "standard"},
    {"url": "https://phys.org/rss-feed/", "name": "Phys.org", "category": "science", "tier": "standard"},
    {"url": "https://www.livescience.com/feeds/all", "name": "Live Science", "category": "science", "tier": "standard"},
    # ── Health ──
    {"url": "https://rss.nytimes.com/services/xml/rss/nyt/Health.xml", "name": "NYT Health", "category": "health", "tier": "premium"},
    {"url": "https://www.statnews.com/feed/", "name": "STAT News", "category": "health", "tier": "standard"},
    {"url": "https://www.theguardian.com/society/health/rss", "name": "Guardian Health", "category": "health", "tier": "standard"},
    # ── Sports ──
    {"url": "https://www.espn.com/espn/rss/news", "name": "ESPN", "category": "sports", "tier": "premium"},
    {"url": "https://www.theguardian.com/football/rss", "name": "Guardian Football", "category": "sports", "tier": "standard"},
    {"url": "https://www.bbc.co.uk/sport/rss.xml", "name": "BBC Sport", "category": "sports", "tier": "standard"},
    # ── Politics ──
    {"url": "https://rss.nytimes.com/services/xml/rss/nyt/Politics.xml", "name": "NYT Politics", "category": "politics", "tier": "premium"},
    {"url": "https://www.theguardian.com/us-news/rss", "name": "Guardian US News", "category": "politics", "tier": "standard"},
    {"url": "https://feeds.npr.org/1014/rss.xml", "name": "NPR Politics", "category": "politics", "tier": "standard"},
    {"url": "https://www.politico.com/rss/politicopicks.xml", "name": "Politico", "category": "politics", "tier": "standard"},
    # ── World / International ──
    {"url": "https://rss.nytimes.com/services/xml/rss/nyt/World.xml", "name": "NYT World", "category": "world", "tier": "premium"},
    {"url": "https://feeds.npr.org/1004/rss.xml", "name": "NPR World", "category": "world", "tier": "standard"},
    {"url": "https://www.theguardian.com/world/rss", "name": "Guardian World", "category": "world", "tier": "standard"},
    # ── Entertainment / Culture ──
    {"url": "https://rss.nytimes.com/services/xml/rss/nyt/Arts.xml", "name": "NYT Arts", "category": "entertainment", "tier": "premium"},
    {"url": "https://www.theguardian.com/culture/rss", "name": "Guardian Culture", "category": "entertainment", "tier": "standard"},
    {"url": "https://www.hollywoodreporter.com/feed/", "name": "Hollywood Reporter", "category": "entertainment", "tier": "standard"},
    {"url": "https://variety.com/feed/", "name": "Variety", "category": "entertainment", "tier": "standard"},
    # ── Startups / VC ──
    {"url": "https://techcrunch.com/category/startups/feed/", "name": "TechCrunch Startups", "category": "startups", "tier": "standard"},
    {"url": "https://www.saastr.com/feed/", "name": "SaaStr", "category": "startups", "tier": "niche"},
    # ── Crypto / Web3 ──
    {"url": "https://www.coindesk.com/arc/outboundfeeds/rss/", "name": "CoinDesk", "category": "crypto", "tier": "standard"},
    {"url": "https://cointelegraph.com/rss", "name": "CoinTelegraph", "category": "crypto", "tier": "standard"},
    {"url": "https://decrypt.co/feed", "name": "Decrypt", "category": "crypto", "tier": "niche"},
    # ── Climate / Environment ──
    {"url": "https://www.theguardian.com/environment/rss", "name": "Guardian Environment", "category": "climate", "tier": "standard"},
    {"url": "https://grist.org/feed/", "name": "Grist", "category": "climate", "tier": "niche"},
    # ── Space ──
    {"url": "https://www.space.com/feeds/all", "name": "Space.com", "category": "space", "tier": "standard"},
    {"url": "https://spacenews.com/feed/", "name": "SpaceNews", "category": "space", "tier": "standard"},
    # ── Design / UX ──
    {"url": "https://www.fastcompany.com/section/design/rss", "name": "Fast Company Design", "category": "design", "tier": "standard"},
    # ── Cybersecurity ──
    {"url": "https://www.bleepingcomputer.com/feed/", "name": "BleepingComputer", "category": "cybersecurity", "tier": "standard"},
    {"url": "https://krebsonsecurity.com/feed/", "name": "Krebs on Security", "category": "cybersecurity", "tier": "standard"},
    {"url": "https://www.darkreading.com/rss.xml", "name": "Dark Reading", "category": "cybersecurity", "tier": "niche"},
    # ── Programming / Dev ──
    {"url": "https://dev.to/feed", "name": "DEV Community", "category": "programming", "tier": "standard"},
    {"url": "https://blog.pragmaticengineer.com/rss/", "name": "Pragmatic Engineer", "category": "programming", "tier": "niche"},
]

# Category keyword mapping for matching user interests to seed sources
CATEGORY_KEYWORDS = {
    "ai": ["artificial intelligence", "machine learning", "deep learning", "llm", "gpt", "neural", "ai", "ml", "nlp", "computer vision", "generative ai"],
    "technology": ["tech", "technology", "software", "hardware", "gadgets", "apps", "mobile", "devices", "innovation"],
    "gaming": ["gaming", "video games", "esports", "game development", "nintendo", "playstation", "xbox", "steam", "pc gaming"],
    "business": ["business", "finance", "economy", "markets", "investing", "stocks", "banking", "entrepreneurship", "management"],
    "science": ["science", "physics", "chemistry", "biology", "research", "discovery", "scientific"],
    "health": ["health", "medicine", "wellness", "fitness", "mental health", "nutrition", "healthcare"],
    "sports": ["sports", "football", "basketball", "soccer", "tennis", "olympics", "nfl", "nba", "formula 1", "f1"],
    "politics": ["politics", "government", "policy", "election", "democracy", "law", "legislation", "congress"],
    "world": ["world", "international", "global", "foreign affairs", "geopolitics"],
    "entertainment": ["entertainment", "movies", "film", "music", "tv", "television", "celebrity", "pop culture"],
    "startups": ["startup", "venture capital", "vc", "saas", "founder", "fundraising"],
    "crypto": ["crypto", "cryptocurrency", "bitcoin", "ethereum", "blockchain", "web3", "defi", "nft"],
    "climate": ["climate", "environment", "sustainability", "renewable", "green energy", "carbon"],
    "space": ["space", "nasa", "astronomy", "rocket", "satellite", "mars", "spacex"],
    "design": ["design", "ux", "ui", "user experience", "product design", "typography"],
    "cybersecurity": ["cybersecurity", "security", "hacking", "privacy", "infosec", "malware"],
    "programming": ["programming", "coding", "developer", "software engineering", "devops", "open source"],
}

MAX_SOURCES_PER_USER = 100
MAX_AI_SUGGESTIONS = 10


async def populate_seed_sources(conn) -> int:
    """Populate seed_sources table from curated list. Idempotent."""
    with conn.cursor() as cur:
        cur.execute("SELECT COUNT(*) as cnt FROM public.seed_sources")
        count = cur.fetchone()["cnt"]
        if count >= len(SEED_SOURCES) * 0.8:
            return 0  # Already populated

    inserted = 0
    with conn.cursor() as cur:
        for seed in SEED_SOURCES:
            try:
                cur.execute(
                    """
                    INSERT INTO public.seed_sources (url, name, category, quality_tier)
                    VALUES (%s, %s, %s, %s)
                    ON CONFLICT (url) DO NOTHING
                    """,
                    (seed["url"], seed["name"], seed["category"], seed.get("tier", "standard")),
                )
                if cur.rowcount == 1:
                    inserted += 1
            except Exception as e:
                logger.warning("Seed source insert error for %s: %s", seed["name"], e)
    if inserted:
        logger.info("Populated %d seed sources", inserted)
    return inserted


def _match_seed_sources(conn, interests: dict) -> list[dict]:
    """Select relevant seed sources based on user interests."""
    # Extract all topic terms from interests
    topics = set()
    for key in ("topics", "people", "industries", "locations"):
        for term in interests.get(key) or []:
            topics.add(str(term).lower().strip())

    # Find matching categories
    matched_categories = set()
    for topic in topics:
        for category, keywords in CATEGORY_KEYWORDS.items():
            if topic in keywords or any(kw in topic for kw in keywords):
                matched_categories.add(category)

    # Always include 'general' for baseline news
    matched_categories.add("general")

    # Select seeds from matching categories
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT url, name, category, quality_tier
            FROM public.seed_sources
            WHERE active = true AND category = ANY(%s)
            ORDER BY
                CASE quality_tier WHEN 'premium' THEN 0 WHEN 'standard' THEN 1 ELSE 2 END,
                name
            """,
            (list(matched_categories),),
        )
        seeds = cur.fetchall()

    return seeds


async def _validate_feed(client: httpx.AsyncClient, url: str) -> bool:
    """Validate a feed URL: GET request + parse at least 1 entry."""
    try:
        resp = await client.get(
            url,
            headers={"User-Agent": "DailyNewsApp/1.0 (RSS Reader)"},
            timeout=10.0,
        )
        if resp.status_code != 200:
            return False
        feed = feedparser.parse(resp.text)
        return len(feed.entries) > 0
    except Exception:
        return False


async def _ai_suggest_feeds(openai_svc, interests: dict, ai_profile: str) -> list[dict]:
    """Ask OpenAI to suggest RSS feed URLs for niche interests."""
    topics = interests.get("topics") or []
    people = interests.get("people") or []
    industries = interests.get("industries") or []

    if not topics and not people and not industries:
        return []

    prompt = (
        "You are a news feed curator. Based on the user's interests, suggest up to 10 RSS/Atom feed URLs "
        "that would provide highly relevant articles.\n\n"
        f"User profile: {(ai_profile or '')[:300]}\n"
        f"Topics: {', '.join(topics[:10])}\n"
        f"People: {', '.join(people[:5])}\n"
        f"Industries: {', '.join(industries[:5])}\n\n"
        "Return a JSON array of objects with 'url', 'name', and 'category' fields.\n"
        "Only suggest feeds you're confident actually exist (major publications, known blogs).\n"
        "Do NOT suggest Google News URLs.\n"
        "Example: [{\"url\": \"https://example.com/feed.xml\", \"name\": \"Example Blog\", \"category\": \"ai\"}]"
    )

    try:
        response = await openai_svc.client_chat_completion(
            messages=[{"role": "user", "content": prompt}],
            response_format={"type": "json_object"},
            temperature=0.3,
            max_tokens=1000,
        )
        content = response.choices[0].message.content
        data = json.loads(content)
        suggestions = data if isinstance(data, list) else data.get("feeds", data.get("suggestions", []))
        return [
            {"url": s["url"], "name": s.get("name", ""), "category": s.get("category", "general")}
            for s in suggestions[:MAX_AI_SUGGESTIONS]
            if isinstance(s, dict) and s.get("url")
        ]
    except Exception as e:
        logger.warning("AI feed suggestion failed: %s", e)
        return []


async def discover_sources_for_user(conn, user_id: str, interests: dict, ai_profile: str):
    """
    Discover and assign sources for a user based on their interests.
    Called via asyncio.create_task() — fire-and-forget from onboarding.
    """
    try:
        # Check existing source count
        with conn.cursor() as cur:
            cur.execute(
                "SELECT COUNT(*) as cnt FROM public.user_sources WHERE user_id = %s AND active = true",
                (user_id,),
            )
            existing = cur.fetchone()["cnt"]

        if existing >= MAX_SOURCES_PER_USER:
            logger.info("User %s already has %d sources, skipping discovery", user_id, existing)
            return

        # 1. Match interests to seed sources
        seeds = _match_seed_sources(conn, interests)
        logger.info("User %s: matched %d seed sources", user_id, len(seeds))

        # 2. AI suggestions for niche interests
        ai_suggestions = []
        try:
            from app.services.openai_service import get_openai_service
            openai_svc = get_openai_service()
            ai_suggestions = await _ai_suggest_feeds(openai_svc, interests, ai_profile)
            logger.info("User %s: AI suggested %d feeds", user_id, len(ai_suggestions))
        except Exception as e:
            logger.warning("AI suggestion failed for user %s: %s", user_id, e)

        # 3. Validate AI suggestions
        validated_ai = []
        if ai_suggestions:
            async with httpx.AsyncClient(follow_redirects=True) as client:
                sem = asyncio.Semaphore(5)

                async def _validate_one(suggestion):
                    async with sem:
                        if await _validate_feed(client, suggestion["url"]):
                            return suggestion
                        return None

                results = await asyncio.gather(
                    *[_validate_one(s) for s in ai_suggestions],
                    return_exceptions=True,
                )
                validated_ai = [r for r in results if isinstance(r, dict)]
            logger.info("User %s: %d/%d AI suggestions validated", user_id, len(validated_ai), len(ai_suggestions))

        # 4. Store in user_sources (seeds + validated AI)
        inserted = 0
        remaining_slots = MAX_SOURCES_PER_USER - existing
        with conn.cursor() as cur:
            # Add seed sources first (premium first)
            for seed in seeds[:remaining_slots]:
                try:
                    cur.execute(
                        """
                        INSERT INTO public.user_sources (user_id, source_url, source_name, category, discovery_method, validated_at)
                        VALUES (%s, %s, %s, %s, 'seed', now())
                        ON CONFLICT (user_id, source_url) DO NOTHING
                        """,
                        (user_id, seed["url"], seed["name"], seed["category"]),
                    )
                    if cur.rowcount == 1:
                        inserted += 1
                except Exception as e:
                    logger.warning("Error inserting seed source for user %s: %s", user_id, e)

            # Add validated AI suggestions
            for suggestion in validated_ai[: remaining_slots - inserted]:
                try:
                    cur.execute(
                        """
                        INSERT INTO public.user_sources (user_id, source_url, source_name, category, discovery_method, validated_at)
                        VALUES (%s, %s, %s, %s, 'ai_suggested', now())
                        ON CONFLICT (user_id, source_url) DO NOTHING
                        """,
                        (user_id, suggestion["url"], suggestion["name"], suggestion["category"]),
                    )
                    if cur.rowcount == 1:
                        inserted += 1
                except Exception as e:
                    logger.warning("Error inserting AI source for user %s: %s", user_id, e)

        logger.info("User %s: discovered %d sources (%d seeds, %d AI)", user_id, inserted, len(seeds), len(validated_ai))

    except Exception as e:
        logger.error("Source discovery failed for user %s: %s", user_id, e)
        import traceback
        traceback.print_exc()


async def fetch_user_sources(conn) -> int:
    """
    Fetch articles from user-discovered sources that are due for fetching.
    Called from the ingestion loop. Returns count of new articles.
    """
    from app.services.news_ingestion import _fetch_single_feed, _fetch_source_images

    # Get sources due for fetching (next_fetch_at <= now), limit to 50 per cycle
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT DISTINCT ON (source_url) id, user_id, source_url, source_name, category
            FROM public.user_sources
            WHERE active = true AND next_fetch_at <= now()
            ORDER BY source_url, next_fetch_at ASC
            LIMIT 50
            """
        )
        due_sources = cur.fetchall()

    if not due_sources:
        return 0

    semaphore = asyncio.Semaphore(10)
    all_articles = []

    async def _fetch_one(source):
        async with semaphore:
            try:
                async with httpx.AsyncClient(timeout=15.0, follow_redirects=True) as client:
                    articles = await _fetch_single_feed(client, source["source_url"])
                # Override category from source
                for a in articles:
                    if source["category"]:
                        a["category"] = source["category"]
                # Update last_fetched_at and schedule next fetch (15 min)
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        UPDATE public.user_sources
                        SET last_fetched_at = now(), next_fetch_at = now() + interval '15 minutes', failure_count = 0
                        WHERE source_url = %s AND active = true
                        """,
                        (source["source_url"],),
                    )
                return articles
            except Exception as e:
                # Increment failure count, deactivate at 5 failures
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        UPDATE public.user_sources
                        SET failure_count = failure_count + 1,
                            next_fetch_at = now() + interval '30 minutes',
                            active = CASE WHEN failure_count >= 4 THEN false ELSE active END
                        WHERE source_url = %s AND active = true
                        """,
                        (source["source_url"],),
                    )
                logger.warning("Error fetching user source %s: %s", source["source_url"][:60], e)
                return []

    results = await asyncio.gather(*[_fetch_one(s) for s in due_sources], return_exceptions=True)
    for result in results:
        if isinstance(result, list):
            all_articles.extend(result)

    if not all_articles:
        return 0

    # Deduplicate by URL
    seen = set()
    unique = []
    for a in all_articles:
        if a["url"] not in seen:
            seen.add(a["url"])
            unique.append(a)

    # Fetch images for articles missing them
    await _fetch_source_images(unique)

    # Insert into shared articles table
    new_count = 0
    with conn.cursor() as cur:
        for article in unique:
            try:
                cur.execute(
                    """
                    INSERT INTO public.articles (url, title, summary, author, source_name, image_url, published_at, category)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (url) DO UPDATE SET
                        image_url = COALESCE(public.articles.image_url, EXCLUDED.image_url),
                        summary = COALESCE(public.articles.summary, EXCLUDED.summary)
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
                if cur.rowcount == 1:
                    new_count += 1
            except Exception as e:
                logger.warning("User source insert error: %s", e)

    logger.info("User sources: fetched %d sources, %d articles, %d new", len(due_sources), len(unique), new_count)
    return new_count
