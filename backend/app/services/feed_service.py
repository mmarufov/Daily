from __future__ import annotations

"""
Feed service: score articles from shared pool with AI, cache results, return personalized feed.
"""
import asyncio
import json
import logging
import re
import uuid as _uuid
from dataclasses import dataclass, field
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
BATCH_SCORING_SIZE = 40
MIN_CANDIDATE_TEXT_LENGTH = 40
MAX_LLM_CANDIDATES = 200
MIN_SHORTLIST_SIZE = 24
MIN_FEED_SIZE = 6
DETERMINISTIC_MATCH_THRESHOLD = 1.5
STRICT_MATCH_THRESHOLD = 2.5
DETERMINISTIC_STRONG_MATCH = 3.0
DETERMINISTIC_SCORE_NORMALIZER = 8.0
FALLBACK_SCORE_NORMALIZER = 5.0
_FALLBACK_REASONS = {"scoring incomplete", "scoring unavailable", "scoring error"}
_DEDUPE_TRACKING_PARAMS = {"fbclid", "gclid", "ocid", "cmpid", "taid"}
_DEDUPE_STOPWORDS = {
    "a", "about", "an", "and", "article", "articles", "around", "be", "coverage",
    "focus", "for", "from", "general", "give", "i", "in", "include", "just", "me", "my",
    "news", "of", "on", "or", "show", "stories", "story", "the", "to", "want", "with",
    "only",
}
_STOPWORDS = set(_DEDUPE_STOPWORDS)
_CATEGORY_HINTS = {
    "ai": {"ai", "artificial intelligence", "llm", "machine learning", "openai", "anthropic", "chatgpt"},
    "technology": {"technology", "tech", "software", "hardware", "developer", "programming", "apple", "google", "microsoft"},
    "business": {"business", "finance", "economy", "markets", "company", "companies", "startup", "startups", "venture capital"},
    "gaming": {"gaming", "video game", "video games", "game", "games", "nintendo", "playstation", "xbox", "steam", "esports", "dlc"},
    "science": {"science", "research", "medical", "medicine", "health", "biotech", "space"},
    "sports": {"sports", "nba", "nfl", "mlb", "soccer", "football", "tennis"},
    "world": {"world", "international", "global", "geopolitics", "europe", "asia", "middle east"},
    "politics": {"politics", "policy", "election", "congress", "government", "white house"},
}
_POSITIVE_PROMPT_PATTERNS = [
    re.compile(
        r"(?:interested in|care about|focus on|follow|prefer|show me|cover|about|around"
        r"|(?:i\s+)?like|(?:i\s+)?love|(?:i\s+)?enjoy|(?:i\s+)?want|give me"
        r"|keep me updated on|track|looking for|into)\s+([^.;\n]+)",
        re.IGNORECASE,
    ),
]
_NEGATIVE_PROMPT_PATTERNS = [
    re.compile(r"(?:avoid|exclude|skip|without|not interested in|don't want|do not want|don't show|do not show|no)\s+([^.;\n]+)", re.IGNORECASE),
]
_STRICT_PROMPT_PATTERNS = [
    re.compile(r"\bonly\s+(?:about|show|want|interested|care|cover|focus|give)\b", re.IGNORECASE),
    re.compile(r"\bonly\s+(?!(?:read|get|check|see|browse|watch|hear)\s)\w+(?:\s+\w+){0,2}\s+news\b", re.IGNORECASE),
    re.compile(r"\bexclusively\b", re.IGNORECASE),
    re.compile(r"\bnothing else\b", re.IGNORECASE),
    re.compile(r"\bnothing but\b", re.IGNORECASE),
]
_GAMING_SOURCE_HINTS = {
    "polygon", "pc gamer", "eurogamer", "rock paper shotgun",
    "game informer", "gamesindustry", "destructoid", "gamesradar",
}
_GAMING_CORE_HINTS = {
    "gaming", "video game", "video games", "game", "games", "nintendo", "playstation", "xbox",
    "steam", "epic games", "esports", "dlc", "patch", "update", "trailer", "launch",
    "release date", "studio", "publisher", "developer",
}
_GAMING_DEAL_HINTS = {"best price", "deal", "discount", "sale", "lowest price", "price drop"}
_GAMING_HARDWARE_HINTS = {
    "controller", "headset", "keyboard", "mouse", "monitor", "gpu", "graphics card",
    "accessory", "peripheral", "console bundle",
}
_GAMING_NEWS_EVENT_HINTS = {
    "announce", "announced", "announcement", "launch", "launched", "release", "released",
    "reveal", "revealed", "trailer", "patch", "update", "expansion", "dlc", "tournament",
}
_GAMING_HARDWARE_PROMPT_HINTS = {
    "hardware", "console", "consoles", "controller", "controllers", "accessory",
    "accessories", "peripheral", "peripherals", "gpu", "graphics card", "handheld",
}


@dataclass
class PreferenceProfile:
    positive_phrases: list[str] = field(default_factory=list)
    negative_phrases: list[str] = field(default_factory=list)
    keyword_terms: set[str] = field(default_factory=set)
    preferred_categories: set[str] = field(default_factory=set)
    strict_mode: bool = False
    required_topic_groups: set[str] = field(default_factory=set)
    allows_gaming_hardware: bool = False
    is_specific: bool = False

    @property
    def has_preferences(self) -> bool:
        return bool(self.positive_phrases or self.negative_phrases or self.keyword_terms or self.preferred_categories)

    @property
    def has_positive_signals(self) -> bool:
        return bool(self.positive_phrases or self.keyword_terms or self.preferred_categories)


async def get_personalized_feed(
    user_id: str,
    conn,
    limit: int = 50,
    force_refresh: bool = False,
) -> list[dict]:
    """Return a personalized news feed for the given user."""
    user_uuid = _uuid.UUID(user_id)
    ai_profile, interests, preferences_updated_at = _load_user_preferences(conn, user_uuid)

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

    profile = _build_preference_profile(ai_profile or "", interests)

    candidates = await _load_candidates_for_profile(conn, profile, limit, user_uuid=user_uuid)
    if not candidates:
        return []

    if not profile.has_preferences:
        for candidate in candidates:
            candidate["_score"] = 0.5
            candidate["_relevant"] = True
            candidate["_reason"] = "no profile available"
        candidates.sort(key=lambda article: article.get("published_at") or "", reverse=True)
        _save_feed_cache(conn, user_uuid, candidates)
        finalized = _collapse_duplicate_coverage(_finalize_articles(candidates))
        finalized = finalized[:limit]
        await _hydrate_missing_feed_images(conn, finalized)
        return finalized

    # Load behavioral signals, entity pins, source quality for scoring context
    _prepare_scoring_context(conn, user_id)

    openai_service = get_openai_service()
    batches = [
        candidates[i:i + BATCH_SCORING_SIZE]
        for i in range(0, len(candidates), BATCH_SCORING_SIZE)
    ]
    batch_coros = [
        openai_service.score_articles_batch(b, ai_profile or "", interests=interests)
        for b in batches
    ]
    batch_results_list = await asyncio.gather(*batch_coros)
    analysis_results = [r for results in batch_results_list for r in results]

    _apply_individual_analysis_results(candidates, analysis_results, profile)
    candidates.sort(
        key=lambda article: (article.get("_score", 0.0), article.get("published_at") or ""),
        reverse=True,
    )
    _save_feed_cache(conn, user_uuid, candidates)
    finalized = _collapse_duplicate_coverage(_finalize_articles(candidates))
    relevant = [article for article in finalized if article.get("relevant", False)]
    relevant = _enforce_diversity(relevant)
    relevant = relevant[:limit]
    await _hydrate_missing_feed_images(conn, relevant)
    return relevant


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


def _load_user_preferences(conn, user_uuid) -> tuple[str | None, dict | None, datetime | None]:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT ai_profile, interests, updated_at
            FROM public.user_preferences
            WHERE user_id = %s AND completed = true
            """,
            (user_uuid,),
        )
        row = cur.fetchone()

    if not row:
        return None, None, None

    return row.get("ai_profile"), _parse_interests(row.get("interests")), row.get("updated_at")


async def _load_candidates_for_profile(
    conn,
    profile: PreferenceProfile,
    limit: int,
    user_uuid=None,
) -> list[dict]:
    """Load and widen candidate windows until we have enough strong matches."""
    seen_ids: set[str] = set()
    gathered: list[dict] = []
    desired_shortlist = min(max(max(limit, 10) * 2, MIN_SHORTLIST_SIZE), MAX_LLM_CANDIDATES)

    for lookback_hours, row_limit in CANDIDATE_EXPANSION_STEPS:
        rows = _query_candidate_rows(conn, lookback_hours=lookback_hours, row_limit=row_limit, user_uuid=user_uuid)
        window_candidates = []
        for candidate in _rows_to_candidates(rows):
            candidate_id = candidate["id"]
            if candidate_id in seen_ids:
                continue
            seen_ids.add(candidate_id)
            window_candidates.append(candidate)

        gathered.extend(window_candidates)
        logger.info(
            "Loaded %d candidates for %dh/%d window (total=%d)",
            len(window_candidates),
            lookback_hours,
            row_limit,
            len(gathered),
        )

        if not profile.has_preferences:
            continue

        shortlisted = _prefilter_candidates(gathered, profile, max_candidates=desired_shortlist)
        logger.info(
            "Shortlisted %d candidates after %dh expansion for strict=%s categories=%s",
            len(shortlisted),
            lookback_hours,
            profile.strict_mode,
            sorted(profile.preferred_categories),
        )
        if len(shortlisted) >= desired_shortlist:
            return shortlisted

    if not gathered:
        return []

    if not profile.has_preferences:
        gathered.sort(key=lambda article: article.get("published_at") or "", reverse=True)
        return gathered[:max(limit, MAX_LLM_CANDIDATES)]

    shortlisted = _prefilter_candidates(gathered, profile, max_candidates=desired_shortlist)
    logger.info("Returning %d shortlisted candidates after exhausting expansion windows", len(shortlisted))
    return shortlisted


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
                       scoped.published_at, scoped.ingested_at, scoped.category
                FROM (
                    SELECT DISTINCT ON (a.id)
                           a.id, a.url, a.title, a.summary, a.content, a.author, a.source_name,
                           a.image_url,
                           COALESCE(asl.published_at, a.published_at) AS published_at,
                           a.ingested_at,
                           COALESCE(us.category, a.category) AS category,
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


def _normalize_text(value: str | None) -> str:
    if not value:
        return ""
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9+.#-]+", " ", value.lower())).strip()


def _dedupe_terms(values: list[str]) -> list[str]:
    seen = set()
    deduped: list[str] = []
    for value in values:
        normalized = _normalize_text(value)
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        deduped.append(value.strip())
    return deduped


def _split_profile_clause(text: str) -> list[str]:
    return [
        piece.strip(" ,.;:()[]{}")
        for piece in re.split(r",|/|\band\b|\bor\b", text, flags=re.IGNORECASE)
        if piece.strip(" ,.;:()[]{}")
    ]


def _extract_prompt_terms(ai_profile: str) -> tuple[list[str], list[str]]:
    positive: list[str] = []
    negative: list[str] = []

    for pattern in _POSITIVE_PROMPT_PATTERNS:
        for match in pattern.finditer(ai_profile):
            positive.extend(_split_profile_clause(match.group(1)))

    for pattern in _NEGATIVE_PROMPT_PATTERNS:
        for match in pattern.finditer(ai_profile):
            negative.extend(_split_profile_clause(match.group(1)))

    return _dedupe_terms(positive), _dedupe_terms(negative)


def _interest_values(interests: dict | None, key: str) -> list[str]:
    if not isinstance(interests, dict):
        return []
    values = interests.get(key)
    if not isinstance(values, list):
        return []
    return [str(value).strip() for value in values if str(value).strip()]


def _categories_for_terms(terms: list[str]) -> set[str]:
    categories: set[str] = set()
    for term in terms:
        normalized = _normalize_text(term)
        for category, hints in _CATEGORY_HINTS.items():
            if normalized == category or normalized in hints or any(hint in normalized for hint in hints):
                categories.add(category)
    return categories


def _keyword_terms(phrases: list[str]) -> set[str]:
    keywords: set[str] = set()
    for phrase in phrases:
        for token in re.findall(r"[A-Za-z0-9+.#-]{2,}", phrase.lower()):
            if token in _STOPWORDS:
                continue
            keywords.add(token)
            if len(token) > 3 and token.endswith("s"):
                keywords.add(token[:-1])
    return keywords


def _contains_any(text: str, terms: set[str]) -> bool:
    for term in terms:
        if len(term) <= 3 and term.isalnum():
            if re.search(rf"(?<![a-z0-9]){re.escape(term)}(?![a-z0-9])", text):
                return True
        elif term in text:
            return True
    return False


def _is_strict_profile(ai_profile: str) -> bool:
    return any(pattern.search(ai_profile or "") for pattern in _STRICT_PROMPT_PATTERNS)


def _allows_gaming_hardware(ai_profile: str, positive_phrases: list[str]) -> bool:
    searchable = " ".join(_normalize_text(value) for value in [ai_profile, *positive_phrases] if value)
    return _contains_any(searchable, _GAMING_HARDWARE_PROMPT_HINTS)


def _candidate_matches_gaming_topic(fields: dict[str, str], searchable: str, profile: PreferenceProfile) -> bool:
    source_or_category = fields["category"] == "gaming" or _contains_any(fields["source"], _GAMING_SOURCE_HINTS)
    core_match = _contains_any(searchable, _GAMING_CORE_HINTS)

    if not (source_or_category or core_match):
        return False

    if _contains_any(searchable, _GAMING_DEAL_HINTS):
        return profile.allows_gaming_hardware

    if _contains_any(searchable, _GAMING_HARDWARE_HINTS) and not profile.allows_gaming_hardware:
        return _contains_any(searchable, _GAMING_NEWS_EVENT_HINTS)

    return True


def _candidate_matches_topic_group(
    fields: dict[str, str],
    searchable: str,
    topic_group: str,
    profile: PreferenceProfile,
) -> bool:
    if topic_group == "gaming":
        return _candidate_matches_gaming_topic(fields, searchable, profile)

    hints = _CATEGORY_HINTS.get(topic_group, set())
    if fields["category"] == topic_group:
        return True
    if hints and _contains_any(fields["source"], hints):
        return True
    return bool(hints and _contains_any(searchable, hints))


def _is_specific_interests(interests: dict | None) -> bool:
    """Detect narrow/specific interests (e.g. 'Claude AI') vs broad (e.g. 'AI, gaming')."""
    if not interests:
        return False
    all_terms: list[str] = []
    for key in ("topics", "people"):
        values = interests.get(key)
        if isinstance(values, list):
            all_terms.extend(str(v).strip() for v in values if str(v).strip())
    if not all_terms or len(all_terms) > 3:
        return False
    specific_count = sum(
        1 for t in all_terms if len(t.split()) >= 2 or (t and t[0].isupper())
    )
    return specific_count > 0


def _build_preference_profile(ai_profile: str, interests: dict | None) -> PreferenceProfile:
    prompt_positive, prompt_negative = _extract_prompt_terms(ai_profile)
    positive_terms = prompt_positive + _interest_values(interests, "topics")
    positive_terms += _interest_values(interests, "people")
    positive_terms += _interest_values(interests, "locations")
    positive_terms += _interest_values(interests, "industries")
    negative_terms = prompt_negative + _interest_values(interests, "excluded_topics")

    positive_phrases = _dedupe_terms(positive_terms)
    negative_phrases = _dedupe_terms(negative_terms)
    categories = _categories_for_terms(positive_phrases)
    keywords = _keyword_terms(positive_phrases)
    strict_mode = _is_strict_profile(ai_profile)

    return PreferenceProfile(
        positive_phrases=positive_phrases,
        negative_phrases=negative_phrases,
        keyword_terms=keywords,
        preferred_categories=categories,
        strict_mode=strict_mode,
        required_topic_groups=set(categories) if strict_mode else set(),
        allows_gaming_hardware=_allows_gaming_hardware(ai_profile, positive_phrases),
        is_specific=_is_specific_interests(interests),
    )


def _candidate_search_fields(candidate: dict[str, Any]) -> dict[str, str]:
    return {
        "title": _normalize_text(candidate.get("title")),
        "summary": _normalize_text(candidate.get("summary")),
        "content": _normalize_text(candidate.get("content")),
        "source": _normalize_text(candidate.get("source")),
        "category": _normalize_text(candidate.get("category")),
    }


def _score_candidate(candidate: dict[str, Any], profile: PreferenceProfile) -> tuple[float, str, bool]:
    fields = _candidate_search_fields(candidate)
    searchable = " ".join(value for value in fields.values() if value)

    for phrase in profile.negative_phrases:
        normalized = _normalize_text(phrase)
        if normalized and normalized in searchable:
            return 0.0, f"Excluded topic match: {phrase}", True

    if not profile.has_positive_signals:
        return 1.0, "Matches general preference constraints", False

    score = 0.0
    matched_terms: list[str] = []
    matched_topic_groups = [
        topic_group
        for topic_group in profile.required_topic_groups
        if _candidate_matches_topic_group(fields, searchable, topic_group, profile)
    ]

    if profile.required_topic_groups and not matched_topic_groups:
        return 0.2, "Outside primary topics", False

    if matched_topic_groups:
        score += 2.5 * len(matched_topic_groups)
        matched_terms.extend(matched_topic_groups)

    for phrase in profile.positive_phrases:
        normalized = _normalize_text(phrase)
        if not normalized:
            continue

        if normalized in fields["title"]:
            score += 4.0
            matched_terms.append(phrase)
        elif normalized in fields["category"] or normalized in fields["source"]:
            score += 3.0
            matched_terms.append(phrase)
        elif normalized in fields["summary"]:
            score += 2.0
            matched_terms.append(phrase)
        elif normalized in searchable:
            score += 1.0
            matched_terms.append(phrase)

        phrase_tokens = [
            token for token in re.findall(r"[A-Za-z0-9+.#-]{2,}", normalized)
            if token not in _STOPWORDS
        ]
        if len(phrase_tokens) >= 2:
            matched_token_count = 0
            for token in phrase_tokens:
                token_variants = {token}
                if len(token) > 3 and token.endswith("s"):
                    token_variants.add(token[:-1])
                if any(variant and variant in searchable for variant in token_variants):
                    matched_token_count += 1
            if matched_token_count >= 2:
                score += 2.0
                matched_terms.append(phrase)

    if fields["category"] in profile.preferred_categories:
        score += 2.5
        matched_terms.append(candidate.get("category") or fields["category"])

    keyword_hits = 0
    for keyword in profile.keyword_terms:
        if keyword in fields["title"]:
            keyword_hits += 2
        elif keyword in fields["summary"] or keyword in fields["category"] or keyword in fields["source"]:
            keyword_hits += 1

    score += min(keyword_hits * 0.4, 2.4)

    if score <= 0:
        return 0.0, "No clear preference match", False

    unique_matches = _dedupe_terms(matched_terms)
    reason = "Matched: " + ", ".join(unique_matches[:3]) if unique_matches else "Matched your profile"
    return score, reason, False


def _prefilter_candidates(
    candidates: list[dict],
    profile: PreferenceProfile,
    max_candidates: int = MAX_LLM_CANDIDATES,
) -> list[dict]:
    """Score candidates deterministically but don't drop any except excluded topics.
    Prefilter score is used as a SIGNAL (blended at 35% weight), not a gate."""
    non_excluded: list[dict] = []

    for candidate in candidates:
        score, reason, excluded = _score_candidate(candidate, profile)
        candidate["_prefilter_score"] = score
        candidate["_prefilter_reason"] = reason
        candidate["_prefilter_excluded"] = excluded

        if excluded:
            continue
        non_excluded.append(candidate)

    # Sort by prefilter score to prioritize strong matches for LLM batching
    non_excluded.sort(
        key=lambda article: (article.get("_prefilter_score", 0.0), article.get("published_at") or ""),
        reverse=True,
    )

    return non_excluded[:max_candidates]


# Module-level closures set per scoring call — avoids threading these through every function
_behavior_signals: dict = {}
_entity_pins: list[str] = []
_entity_patterns: dict = {}
_source_quality: dict = {}


def _extract_domain(source_name: str) -> str:
    """Extract a rough domain key from source_name for quality lookup."""
    return (source_name or "").lower().strip()


def _load_behavior_signals(conn, user_id: str) -> dict:
    """Load cached behavioral signals from user_preferences.behavior_cache."""
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT behavior_cache FROM public.user_preferences WHERE user_id = %s",
                (user_id,),
            )
            row = cur.fetchone()
        if row and row.get("behavior_cache"):
            return json.loads(row["behavior_cache"])
    except Exception:
        pass
    return {}


def _load_entity_pins(conn, user_id: str) -> list[str]:
    """Load entity pin names for a user."""
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT entity_name FROM public.entity_pins WHERE user_id = %s",
                (user_id,),
            )
            return [row["entity_name"] for row in cur.fetchall()]
    except Exception:
        return []


def _load_source_quality(conn) -> dict:
    """Load global source quality scores."""
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT source_domain, quality_score FROM public.source_quality")
            return {row["source_domain"]: row["quality_score"] for row in cur.fetchall()}
    except Exception:
        return {}


def _build_entity_patterns(pins: list[str]) -> dict:
    """Pre-compile word-boundary regex patterns for entity matching (ENG-6)."""
    patterns = {}
    for name in pins:
        try:
            patterns[name] = re.compile(r'\b' + re.escape(name.lower()) + r'\b')
        except re.error:
            pass
    return patterns


def _prepare_scoring_context(conn, user_id: str) -> None:
    """Load all scoring context (behavior, entities, source quality) into module-level state."""
    global _behavior_signals, _entity_pins, _entity_patterns, _source_quality
    _behavior_signals = _load_behavior_signals(conn, user_id)
    _entity_pins = _load_entity_pins(conn, user_id)
    _entity_patterns = _build_entity_patterns(_entity_pins)
    _source_quality = _load_source_quality(conn)


def _apply_individual_analysis_results(candidates: list[dict], results: list[dict], profile: PreferenceProfile) -> None:
    normalized_results = []
    for index, candidate in enumerate(candidates):
        if index < len(results):
            normalized_results.append(results[index])
        else:
            normalized_results.append({"relevant": False, "score": 0.0, "reason": "scoring incomplete"})

    _log_score_distribution(normalized_results, context="individual-analysis")

    for candidate, result in zip(candidates, normalized_results):
        prefilter_score, prefilter_reason, excluded = _score_candidate(candidate, profile)
        deterministic_score = min(prefilter_score / DETERMINISTIC_SCORE_NORMALIZER, 1.0)
        reason = str(result.get("reason", "")).strip()
        model_score = max(0.0, min(1.0, float(result.get("score", 0.0))))
        model_relevant = bool(result.get("relevant", False))
        accept_threshold = STRICT_MATCH_THRESHOLD if profile.strict_mode else DETERMINISTIC_MATCH_THRESHOLD

        if excluded:
            candidate["_score"] = 0.0
            candidate["_relevant"] = False
            candidate["_reason"] = prefilter_reason
            continue

        if reason in _FALLBACK_REASONS or reason.startswith("Error during analysis:"):
            candidate["_score"] = min(prefilter_score / FALLBACK_SCORE_NORMALIZER, 1.0)
            candidate["_relevant"] = prefilter_score >= accept_threshold
            candidate["_reason"] = prefilter_reason or reason
            continue

        blended_score = 0.65 * model_score + 0.35 * deterministic_score

        # Behavioral boost from cached reading signals (ENG-5)
        behavior = _behavior_signals or {}
        if behavior:
            category = candidate.get("category", "")
            source = candidate.get("source_name", "")
            cat_boost = behavior.get("category_boost", {}).get(category, 0.0)
            src_boost = behavior.get("source_boost", {}).get(source, 0.0)
            blended_score = min(blended_score + min(cat_boost + src_boost, 0.15), 1.0)

        # Entity boost from pinned entities
        if _entity_pins:
            title_lower = candidate.get("title", "").lower()
            summary_lower = (candidate.get("summary") or "").lower()
            searchable = title_lower + " " + summary_lower
            for pin_name in _entity_pins:
                pattern = _entity_patterns.get(pin_name)
                if pattern and pattern.search(searchable):
                    blended_score = min(blended_score + 0.2, 1.0)
                    model_relevant = True
                    break

        # Source quality adjustment
        if _source_quality:
            domain = _extract_domain(candidate.get("source_name", ""))
            sq = _source_quality.get(domain)
            if sq is not None:
                if sq > 0.6:
                    blended_score = min(blended_score + 0.05, 1.0)
                elif sq < 0.3:
                    blended_score = max(blended_score - 0.05, 0.0)

        candidate["_score"] = blended_score
        candidate["_relevant"] = model_relevant and blended_score >= 0.35
        candidate["_reason"] = reason or prefilter_reason


def _enforce_diversity(articles: list[dict], max_per_category_pct: float = 0.4) -> list[dict]:
    """Ensure no single category dominates the feed."""
    if len(articles) <= 5:
        return articles
    max_per_cat = max(3, int(len(articles) * max_per_category_pct))
    by_category: dict[str, list[dict]] = {}
    for article in articles:
        cat = article.get("category") or "general"
        by_category.setdefault(cat, []).append(article)
    result: list[dict] = []
    overflow: list[dict] = []
    for group in by_category.values():
        result.extend(group[:max_per_cat])
        overflow.extend(group[max_per_cat:])
    overflow.sort(key=lambda a: a.get("relevance_score", 0), reverse=True)
    result.extend(overflow)
    result.sort(key=lambda a: a.get("relevance_score", 0), reverse=True)
    return result


def _finalize_articles(articles: list[dict]) -> list[dict]:
    finalized: list[dict] = []
    for article in articles:
        row = dict(article)
        row["relevance_score"] = row.pop("_score", row.get("relevance_score", 0.0))
        row["relevant"] = row.pop("_relevant", row.get("relevant", False))
        row["relevance_reason"] = row.pop("_reason", row.get("relevance_reason", ""))
        row.pop("_prefilter_score", None)
        row.pop("_prefilter_reason", None)
        row.pop("_prefilter_excluded", None)
        finalized.append(row)
    return finalized


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
