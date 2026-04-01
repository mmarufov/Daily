from __future__ import annotations

"""
Source discovery service: finds and validates RSS/Atom feeds for user interests.
Hybrid approach: curated seed database + exact-topic query feeds + AI suggestions.
"""
import asyncio
import json
import logging
import math
from urllib.parse import quote, urlparse

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
MAX_QUERY_FEEDS = 6
TARGET_SOURCE_LIMIT = {
    "specific": 12,
    "mixed": 16,
    "broad": 20,
}
OFFICIAL_SOURCE_CAP_RATIO = 0.35
GENERAL_INTENT_TERMS = {
    "general", "general news", "news", "headlines", "current events",
    "world news", "global news", "breaking news", "top stories",
}
ANALYST_DOMAIN_HINTS = {
    "lilianweng.github.io",
    "marktechpost.com",
    "pragmaticengineer.com",
}
OFFICIAL_DOMAIN_HINTS = {
    "openai.com",
    "blog.google",
    "huggingface.co",
    "anthropic.com",
    "formula1.com",
}


def _normalize_term(value: str | None) -> str:
    return " ".join((value or "").strip().lower().split())


def _dedupe_preserve(values: list[str]) -> list[str]:
    seen = set()
    deduped: list[str] = []
    for value in values:
        normalized = _normalize_term(value)
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        deduped.append(value.strip())
    return deduped


def _extract_interest_terms(interests: dict | None) -> list[str]:
    if not isinstance(interests, dict):
        return []

    ordered_terms: list[str] = []
    for key in ("topics", "people", "industries", "locations"):
        values = interests.get(key)
        if not isinstance(values, list):
            continue
        ordered_terms.extend(str(value).strip() for value in values if str(value).strip())
    return _dedupe_preserve(ordered_terms)


def _categories_for_terms(terms: list[str]) -> set[str]:
    matched: set[str] = set()
    for term in terms:
        normalized = _normalize_term(term)
        for category, keywords in CATEGORY_KEYWORDS.items():
            if (
                normalized == category
                or normalized in keywords
                or any(keyword in normalized for keyword in keywords)
            ):
                matched.add(category)
    return matched


def _has_general_intent(interests: dict | None, ai_profile: str | None = None) -> bool:
    haystacks = _extract_interest_terms(interests)
    if ai_profile:
        haystacks.append(ai_profile)
    searchable = " ".join(_normalize_term(value) for value in haystacks if value)
    return any(term in searchable for term in GENERAL_INTENT_TERMS)


def _exact_interest_terms(interests: dict | None) -> list[str]:
    exact_terms: list[str] = []
    for term in _extract_interest_terms(interests):
        normalized = _normalize_term(term)
        if normalized in GENERAL_INTENT_TERMS:
            continue
        if len(normalized.split()) >= 2:
            exact_terms.append(term)
            continue
        if normalized not in CATEGORY_KEYWORDS and normalized not in {"tech", "technology", "coding", "programming", "sports", "business"}:
            exact_terms.append(term)
    return _dedupe_preserve(exact_terms)


def determine_profile_specificity(interests: dict | None, ai_profile: str | None = None) -> str:
    """Classify a profile as specific, mixed, or broad for source discovery and quality gates."""
    terms = _extract_interest_terms(interests)
    if not terms:
        return "broad"

    if _has_general_intent(interests, ai_profile):
        return "broad"

    exact_terms = _exact_interest_terms(interests)
    matched_categories = _categories_for_terms(terms)

    if len(exact_terms) >= 2:
        return "specific"
    if len(exact_terms) == 1 and matched_categories:
        return "specific"
    if len(matched_categories) >= 2:
        return "mixed"
    if len(matched_categories) == 1:
        return "mixed"
    return "broad"


def _category_for_term(term: str) -> str:
    normalized = _normalize_term(term)
    for category, keywords in CATEGORY_KEYWORDS.items():
        if (
            normalized == category
            or normalized in keywords
            or any(keyword in normalized for keyword in keywords)
        ):
            return category
    return "general"


def _classify_source_kind(url: str, discovery_method: str) -> str:
    if discovery_method == "query_feed":
        return "aggregator_query"

    domain = (urlparse(url).netloc or "").lower()
    if any(hint in domain for hint in ANALYST_DOMAIN_HINTS):
        return "analyst"
    if any(hint in domain for hint in OFFICIAL_DOMAIN_HINTS):
        return "official"
    return "publisher"


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


def _match_seed_sources(conn, interests: dict, profile_specificity: str, ai_profile: str | None = None) -> list[dict]:
    """Select relevant seed sources without auto-injecting broad/general news."""
    matched_categories = _categories_for_terms(_extract_interest_terms(interests))
    if profile_specificity == "broad" or _has_general_intent(interests, ai_profile):
        matched_categories.add("general")

    if not matched_categories:
        return []

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

    normalized_targets = {_normalize_term(term) for term in _extract_interest_terms(interests)}
    candidates: list[dict] = []
    for seed in seeds:
        source_text = " ".join(
            [
                _normalize_term(seed.get("name")),
                _normalize_term(seed.get("category")),
                _normalize_term(seed.get("url")),
            ]
        )
        matched_targets = [
            term
            for term in normalized_targets
            if term and term in source_text
        ]
        candidates.append({
            "url": seed["url"],
            "name": seed["name"],
            "category": seed.get("category") or "general",
            "discovery_method": "seed",
            "source_kind": _classify_source_kind(seed["url"], "seed"),
            "matched_targets": matched_targets,
            "selection_rank": 10,
        })
    return candidates


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


async def _fetch_feed_sample(client: httpx.AsyncClient, url: str) -> tuple[bool, list[str]]:
    """Fetch a feed and sample a few titles for discovery scoring."""
    try:
        resp = await client.get(
            url,
            headers={"User-Agent": "DailyNewsApp/1.0 (RSS Reader)"},
            timeout=10.0,
        )
        if resp.status_code != 200:
            return False, []
        feed = feedparser.parse(resp.text)
        titles = [str(entry.get("title", "")).strip() for entry in feed.entries[:5] if str(entry.get("title", "")).strip()]
        return bool(feed.entries), titles
    except Exception:
        return False, []


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


def _build_query_feed_candidates(interests: dict) -> list[dict]:
    query_terms = _exact_interest_terms(interests) or _extract_interest_terms(interests)
    candidates: list[dict] = []
    for index, term in enumerate(query_terms[:MAX_QUERY_FEEDS]):
        candidates.append({
            "url": f"https://news.google.com/rss/search?q={quote(term)}&hl=en-US&gl=US&ceid=US:en",
            "name": f"{term} News Search",
            "category": _category_for_term(term),
            "discovery_method": "query_feed",
            "source_kind": "aggregator_query",
            "matched_targets": [term],
            "selection_rank": 20 + index,
        })
    return candidates


def _build_ai_candidates(suggestions: list[dict], base_rank: int = 40) -> list[dict]:
    candidates: list[dict] = []
    for index, suggestion in enumerate(suggestions):
        url = suggestion.get("url")
        if not url:
            continue
        discovery_method = "ai_suggested"
        source_kind = _classify_source_kind(url, discovery_method)
        candidates.append({
            "url": url,
            "name": suggestion.get("name") or urlparse(url).netloc,
            "category": suggestion.get("category") or "general",
            "discovery_method": discovery_method,
            "source_kind": source_kind,
            "matched_targets": suggestion.get("matched_targets") or [],
            "selection_rank": base_rank + index,
        })
    return candidates


def _dedupe_candidates(candidates: list[dict]) -> list[dict]:
    deduped: list[dict] = []
    seen = set()
    for candidate in candidates:
        url = candidate.get("url")
        if not url or url in seen:
            continue
        seen.add(url)
        deduped.append(candidate)
    return deduped


def _score_candidate_source(
    candidate: dict,
    interests: dict,
    profile_specificity: str,
    sample_titles: list[str],
    *,
    profile_v2: dict | None = None,
    source_selection_brief: dict | None = None,
) -> tuple[float, str, list[str], list[str], str, str, float, float]:
    exact_targets = _exact_interest_terms(interests)
    all_targets = _extract_interest_terms(interests)
    profile_v2 = profile_v2 or {}
    source_selection_brief = source_selection_brief or {}
    priority_topics = [_normalize_term(term) for term in source_selection_brief.get("priority_topics", [])]
    must_cover_entities = [_normalize_term(term) for term in source_selection_brief.get("must_cover_entities", [])]
    coverage_targets = [_normalize_term(term) for term in source_selection_brief.get("coverage_targets", [])]
    searchable = " ".join(
        [
            _normalize_term(candidate.get("name")),
            _normalize_term(candidate.get("category")),
            _normalize_term(candidate.get("url")),
            *[_normalize_term(title) for title in sample_titles],
        ]
    )

    matched_exact = [term for term in exact_targets if _normalize_term(term) in searchable]
    matched_any = matched_exact[:]
    for term in all_targets:
        normalized = _normalize_term(term)
        if normalized and normalized in searchable and term not in matched_any:
            matched_any.append(term)

    matched_entities = [
        entity
        for entity in source_selection_brief.get("must_cover_entities", [])
        if _normalize_term(entity) in searchable
    ]

    score = 0.0
    if candidate.get("discovery_method") == "seed":
        score += 0.55
    elif candidate.get("discovery_method") == "query_feed":
        score += 0.8
    else:
        score += 0.35

    if matched_exact:
        score += 0.4 + 0.1 * min(len(matched_exact), 3)
    elif matched_any:
        score += 0.25
    if matched_entities:
        score += 0.35 + 0.05 * min(len(matched_entities), 2)

    priority_hits = sum(1 for term in priority_topics if term and term in searchable)
    if priority_hits:
        score += min(priority_hits * 0.12, 0.36)

    coverage_hits = sum(1 for term in coverage_targets if term and term in searchable)
    if coverage_hits:
        score += min(coverage_hits * 0.08, 0.24)

    if candidate.get("category") in _categories_for_terms(all_targets):
        score += 0.15

    if candidate.get("source_kind") == "official":
        score += 0.15
    elif candidate.get("source_kind") == "analyst":
        score += 0.1

    if candidate.get("category") == "general" and profile_specificity != "broad":
        score -= 1.0

    if matched_entities or any(term in searchable for term in must_cover_entities):
        coverage_role = "entity-tracking"
    elif candidate.get("category") == "general" or coverage_hits:
        coverage_role = "breadth"
    elif matched_exact or priority_hits >= 2 or candidate.get("discovery_method") == "query_feed":
        coverage_role = "core"
    else:
        coverage_role = "adjacent"

    precision_score = min(
        1.0,
        0.25
        + (0.3 if matched_exact else 0.0)
        + (0.2 if matched_entities else 0.0)
        + min(priority_hits * 0.08, 0.24),
    )
    breadth_score = min(
        1.0,
        0.2
        + (0.35 if candidate.get("category") == "general" else 0.0)
        + min(coverage_hits * 0.1, 0.3)
        + (0.1 if candidate.get("source_kind") == "publisher" else 0.0),
    )
    scope = "exact" if coverage_role in {"core", "entity-tracking"} else "supporting"
    matched_labels = matched_entities or matched_exact or matched_any or coverage_targets[:1]
    selection_reason = (
        f"{coverage_role.replace('-', ' ').title()} coverage for "
        + ", ".join(matched_labels[:3])
        if matched_labels
        else f"{coverage_role.replace('-', ' ').title()} coverage"
    )
    return (
        score,
        scope,
        matched_any,
        matched_entities,
        coverage_role,
        selection_reason,
        round(precision_score, 4),
        round(breadth_score, 4),
    )


async def _validate_candidate_sources(candidates: list[dict]) -> list[dict]:
    async with httpx.AsyncClient(follow_redirects=True) as client:
        semaphore = asyncio.Semaphore(8)

        async def _validate(candidate: dict) -> dict | None:
            async with semaphore:
                is_valid, sample_titles = await _fetch_feed_sample(client, candidate["url"])
                if not is_valid:
                    return None
                enriched = dict(candidate)
                enriched["sample_titles"] = sample_titles
                return enriched

        results = await asyncio.gather(*[_validate(candidate) for candidate in candidates], return_exceptions=True)

    validated: list[dict] = []
    for result in results:
        if isinstance(result, dict):
            validated.append(result)
    return validated


def _select_sources_for_profile(candidates: list[dict], profile_specificity: str) -> list[dict]:
    limit = TARGET_SOURCE_LIMIT[profile_specificity]
    official_cap = max(1, int(limit * OFFICIAL_SOURCE_CAP_RATIO))
    chosen: list[dict] = []
    official_count = 0
    role_counts: dict[str, int] = {}
    role_caps = {
        "core": max(4, math.ceil(limit * 0.45)),
        "adjacent": max(3, math.ceil(limit * 0.25)),
        "breadth": max(2, math.ceil(limit * 0.2)),
        "entity-tracking": max(2, math.ceil(limit * 0.2)),
    }
    category_counts: dict[str, int] = {}
    category_cap = max(3, math.ceil(limit * 0.4))

    for candidate in sorted(candidates, key=lambda item: (-item["discovery_score"], item["selection_rank"])):
        if len(chosen) >= limit:
            break
        if candidate["source_kind"] == "official" and official_count >= official_cap:
            continue
        role = candidate.get("coverage_role") or "adjacent"
        if role_counts.get(role, 0) >= role_caps.get(role, limit):
            continue
        category = candidate.get("category") or "general"
        if category_counts.get(category, 0) >= category_cap:
            continue
        chosen.append(candidate)
        role_counts[role] = role_counts.get(role, 0) + 1
        category_counts[category] = category_counts.get(category, 0) + 1
        if candidate["source_kind"] == "official":
            official_count += 1

    return chosen


async def discover_sources_for_user(
    conn,
    user_id: str,
    interests: dict,
    ai_profile: str,
    *,
    user_profile_v2: dict | None = None,
    source_selection_brief: dict | None = None,
) -> dict:
    """Discover and assign sources for a user based on their profile and exact interests."""
    started = asyncio.get_running_loop().time()
    profile_specificity = determine_profile_specificity(interests, ai_profile)

    try:
        seed_candidates = _match_seed_sources(conn, interests, profile_specificity, ai_profile=ai_profile)
        query_candidates = _build_query_feed_candidates(interests)

        ai_suggestions: list[dict] = []
        try:
            from app.services.openai_service import get_openai_service

            openai_svc = get_openai_service()
            ai_suggestions = await _ai_suggest_feeds(openai_svc, interests, ai_profile)
        except Exception as e:
            logger.warning("AI suggestion failed for user %s: %s", user_id, e)

        candidate_pool = _dedupe_candidates(
            seed_candidates
            + query_candidates
            + _build_ai_candidates(ai_suggestions)
        )
        validated = await _validate_candidate_sources(candidate_pool)

        scored_candidates: list[dict] = []
        for candidate in validated:
            (
                discovery_score,
                scope,
                matched_targets,
                matched_entities,
                coverage_role,
                selection_reason,
                precision_score,
                breadth_score,
            ) = _score_candidate_source(
                candidate,
                interests,
                profile_specificity,
                candidate.get("sample_titles") or [],
                profile_v2=user_profile_v2,
                source_selection_brief=source_selection_brief,
            )
            if discovery_score <= 0:
                continue
            scored = dict(candidate)
            scored["scope"] = scope
            scored["matched_targets"] = matched_targets
            scored["matched_topics"] = matched_targets
            scored["matched_entities"] = matched_entities
            scored["coverage_role"] = coverage_role
            scored["selection_reason"] = selection_reason
            scored["precision_score"] = precision_score
            scored["breadth_score"] = breadth_score
            scored["discovery_score"] = round(discovery_score, 4)
            scored_candidates.append(scored)

        selected = _select_sources_for_profile(scored_candidates, profile_specificity)

        if not selected:
            logger.warning("User %s: discovery found 0 sources, keeping existing sources", user_id)
            return {
                "sources_found": 0,
                "exact_sources": 0,
                "supporting_sources": 0,
                "profile_specificity": profile_specificity,
                "discovery_time_seconds": round(asyncio.get_running_loop().time() - started, 2),
                "sources": [],
            }

        with conn.cursor() as cur:
            cur.execute("DELETE FROM public.user_sources WHERE user_id = %s", (user_id,))
            for index, source in enumerate(selected):
                cur.execute(
                    """
                    INSERT INTO public.user_sources (
                        user_id,
                        source_url,
                        source_name,
                        category,
                        discovery_method,
                        source_kind,
                        scope,
                        matched_targets,
                        selection_reason,
                        coverage_role,
                        matched_topics,
                        matched_entities,
                        precision_score,
                        breadth_score,
                        discovery_score,
                        selection_rank,
                        active,
                        failure_count,
                        validated_at,
                        last_discovered_at,
                        next_fetch_at
                    )
                    VALUES (
                        %s, %s, %s, %s, %s, %s, %s, %s::jsonb, %s, %s,
                        %s::jsonb, %s::jsonb, %s, %s, %s,
                        %s, true, 0, now(), now(), now()
                    )
                    ON CONFLICT (user_id, source_url) DO UPDATE SET
                        source_name = EXCLUDED.source_name,
                        category = EXCLUDED.category,
                        discovery_method = EXCLUDED.discovery_method,
                        source_kind = EXCLUDED.source_kind,
                        scope = EXCLUDED.scope,
                        matched_targets = EXCLUDED.matched_targets,
                        selection_reason = EXCLUDED.selection_reason,
                        coverage_role = EXCLUDED.coverage_role,
                        matched_topics = EXCLUDED.matched_topics,
                        matched_entities = EXCLUDED.matched_entities,
                        precision_score = EXCLUDED.precision_score,
                        breadth_score = EXCLUDED.breadth_score,
                        discovery_score = EXCLUDED.discovery_score,
                        selection_rank = EXCLUDED.selection_rank,
                        active = true,
                        failure_count = 0,
                        validated_at = now(),
                        last_discovered_at = now(),
                        next_fetch_at = now()
                    """,
                    (
                        user_id,
                        source["url"],
                        source.get("name"),
                        source.get("category"),
                        source.get("discovery_method"),
                        source.get("source_kind"),
                        source.get("scope"),
                        json.dumps(source.get("matched_targets") or []),
                        source.get("selection_reason"),
                        source.get("coverage_role"),
                        json.dumps(source.get("matched_topics") or []),
                        json.dumps(source.get("matched_entities") or []),
                        source.get("precision_score", 0.0),
                        source.get("breadth_score", 0.0),
                        source.get("discovery_score", 0.0),
                        index + 1,
                    ),
                )

        exact_sources = sum(1 for source in selected if source.get("scope") == "exact")
        supporting_sources = len(selected) - exact_sources

        logger.info(
            "User %s: discovered %d sources (%d exact / %d supporting) specificity=%s",
            user_id,
            len(selected),
            exact_sources,
            supporting_sources,
            profile_specificity,
        )

        return {
            "sources_found": len(selected),
            "exact_sources": exact_sources,
            "supporting_sources": supporting_sources,
            "profile_specificity": profile_specificity,
            "discovery_time_seconds": round(asyncio.get_running_loop().time() - started, 2),
            "sources": [
                {
                    "source_url": source["url"],
                    "source_name": source.get("name"),
                    "category": source.get("category"),
                    "scope": source.get("scope"),
                    "coverage_role": source.get("coverage_role"),
                    "matched_targets": source.get("matched_targets") or [],
                    "matched_topics": source.get("matched_topics") or [],
                    "matched_entities": source.get("matched_entities") or [],
                    "selection_reason": source.get("selection_reason"),
                    "precision_score": source.get("precision_score", 0.0),
                    "breadth_score": source.get("breadth_score", 0.0),
                    "discovery_score": source.get("discovery_score", 0.0),
                }
                for source in selected
            ],
        }
    except Exception as e:
        logger.error("Source discovery failed for user %s: %s", user_id, e)
        import traceback
        traceback.print_exc()
        raise


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
