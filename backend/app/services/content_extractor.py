"""Origin-page article extraction with explicit safety and quality states.

Only complete, identity-validated publisher text is returned in ``content``.
Partial pages, access walls, error pages, and identity mismatches are classified
for an honest source-reader fallback instead of being presented as full text.
"""
from __future__ import annotations

import ipaddress
import json
import re
import socket
import time
from collections.abc import Iterable
from urllib.parse import urldefrag, urljoin, urlparse

import trafilatura
from bs4 import BeautifulSoup

from app.services.image_extraction import extract_best_image_url
from app.services.safe_http import (
    SafeFetchError,
    SafeFetchPolicy,
    hosts_match,
    is_public_ip,
    normalize_host,
    safe_fetch,
)


_MAX_CONTENT_CHARS = 50_000
_MIN_STRUCTURAL_COMPLETE_WORDS = 350
_EXTRACTOR_VERSION = 4
_PUBLICATION_TITLE_SUFFIX = re.compile(r"\s+(?:[-|—–]\s+).{1,50}$")
_WORD_RE = re.compile(r"[^\W_]+(?:['’][^\W_]+)?", re.UNICODE)
_TITLE_STOPWORDS = {
    "a", "an", "and", "at", "by", "for", "from", "in", "is", "it", "of",
    "on", "or", "the", "to", "with", "news", "latest", "live", "update",
}

_PAYWALL_PATTERNS = re.compile(
    r"(?:"
    r"subscribe\s+(?:now\s+)?(?:to|in order to)\s+(?:continue|read|unlock)"
    r"|subscription\s+(?:is\s+)?required"
    r"|this\s+(?:article|content)\s+is\s+(?:available\s+)?(?:only\s+)?(?:for|to)\s+subscribers"
    r"|already\s+a\s+subscriber\?\s+(?:sign|log)\s+in"
    r"|you(?:'ve| have)\s+reached\s+your\s+(?:free\s+)?article\s+limit"
    r")",
    re.IGNORECASE,
)
_LOGIN_PATTERNS = re.compile(
    r"(?:sign|log)\s+in\s+(?:to|in order to)\s+(?:continue|read|view)|authentication\s+required",
    re.IGNORECASE,
)
_CONSENT_PATTERNS = re.compile(
    r"before\s+you\s+continue|manage\s+(?:your\s+)?consent|consent\s+(?:is\s+)?required|"
    r"please\s+(?:accept|enable)\s+(?:our\s+)?cookies",
    re.IGNORECASE,
)
_ERROR_PATTERNS = re.compile(
    r"(?:404\s*(?:error|not found)?|page\s+not\s+found|access\s+denied|"
    r"service\s+unavailable|internal\s+server\s+error|checking\s+your\s+browser|"
    r"verify\s+you\s+are\s+human)",
    re.IGNORECASE,
)
_TEASER_END_PATTERNS = re.compile(
    r"(?:continue\s+reading|read\s+the\s+full\s+(?:article|story)|read\s+more|\.\.\.)\s*$",
    re.IGNORECASE,
)

_JUNK_PATTERNS = re.compile(
    r"^("
    r"share this article"
    r"|share on (facebook|twitter|linkedin|x|email)"
    r"|follow us on"
    r"|subscribe to"
    r"|sign up for"
    r"|related articles?"
    r"|read more:?"
    r"|recommended for you"
    r"|you may also like"
    r"|more from"
    r"|advertisement"
    r"|sponsored content"
    r"|newsletter"
    r"|copyright \d{4}"
    r"|all rights reserved"
    r"|terms of (use|service)"
    r"|privacy policy"
    r"|cookie (policy|settings)"
    r")$",
    re.IGNORECASE,
)


def _domain_of(url: str) -> str:
    try:
        return normalize_host(urlparse(url).hostname or "")
    except Exception:
        return ""


def _is_safe_public_url(url: str) -> bool:
    """Compatibility helper for cheap initial URL checks.

    Production fetches use ``safe_fetch``, which additionally validates and
    pins every redirect hop. This synchronous helper is retained for callers
    and tests that used the prior API.
    """
    try:
        parsed = urlparse(url)
        port = parsed.port
    except (TypeError, ValueError):
        return False
    if parsed.scheme.lower() not in {"http", "https"} or not parsed.hostname:
        return False
    if parsed.username is not None or parsed.password is not None:
        return False
    if port is not None and port not in {80, 443}:
        return False

    host = normalize_host(parsed.hostname)
    try:
        literal = ipaddress.ip_address(host.split("%", 1)[0])
    except ValueError:
        try:
            infos = socket.getaddrinfo(host, port or 443, type=socket.SOCK_STREAM)
        except (socket.gaierror, OSError):
            return False
        addresses = [info[4][0] for info in infos if info[4]]
        return bool(addresses) and all(is_public_ip(address) for address in addresses)
    return is_public_ip(str(literal))


def _normalized_allowed_domains(values: Iterable[str] | None) -> frozenset[str]:
    domains: set[str] = set()
    for value in values or ():
        raw = str(value).strip()
        if not raw:
            continue
        host = _domain_of(raw) if "://" in raw else normalize_host(raw)
        if host:
            domains.add(host)
    return frozenset(domains)


def _failure_class_for_fetch(code: str, status_code: int | None) -> str:
    """Map transport errors to the job scheduler's stable operational classes."""
    if code in {"invalid_url", "missing_host"}:
        return "invalid_url"
    if code in {
        "unsafe_scheme", "credentials_not_allowed", "port_not_allowed",
        "host_not_allowed",
    }:
        return "unsafe_url"
    if code == "unsafe_address":
        return "private_address"
    if code == "unsafe_redirect":
        return "unsafe_redirect"
    if code in {"redirect_loop", "redirect_limit", "redirect_missing_location"}:
        return "invalid_document"
    if code in {"dns_failure", "timeout", "network_error"}:
        return code
    if code in {"unsupported_content_type", "response_too_large"}:
        return code
    if code == "http_status":
        if status_code in {404, 410}:
            return "not_found"
        if status_code in {401, 403, 451}:
            return "access_denied"
        if status_code == 429:
            return "rate_limited"
        if status_code is not None and 500 <= status_code <= 599:
            return "server_error"
        return "http_error"
    return "internal_error"


def _base_result(url: str, domain: str) -> dict:
    return {
        "error": None,
        "failure_class": None,
        "content_state": "fetch_failed",
        "completeness": "unknown",
        "completeness_score": 0.0,
        "confidence": 0.0,
        "identity_valid": False,
        "retry_after_seconds": None,
        "extractor_version": _EXTRACTOR_VERSION,
        "title": "",
        "summary": "",
        "content": "",
        "partial_content": "",
        "image_url": "",
        "source_name": domain,
        "extraction_method": None,
        "domain": domain,
        "final_url": url,
        "final_domain": domain,
        "canonical_url": "",
        "title_similarity": None,
        "attempts": [],
    }


async def extract_article_content(
    url: str,
    *,
    expected_title: str | None = None,
    allowed_domains: Iterable[str] | None = None,
) -> dict:
    """Fetch and validate a publisher article.

    Existing callers can still pass only ``url`` and consume the legacy fields.
    New stable fields are ``error``, ``failure_class``, ``content_state``,
    semantic ``completeness``, numeric ``completeness_score``/``confidence``,
    ``identity_valid``, ``retry_after_seconds``, and canonical/final URLs.

    ``content`` is deliberately empty unless ``content_state == 'complete'``.
    A rejected candidate is available as ``partial_content`` for diagnostics,
    never as publisher-attributed display text.
    """
    original_domain = _domain_of(url)
    result = _base_result(url, original_domain)
    attempts: list[dict] = result["attempts"]
    allowed = _normalized_allowed_domains(allowed_domains)
    # Even without an explicit source registry entry, an article fetch is
    # constrained to its original publisher host. Cross-host publisher
    # redirects must be intentionally supplied through ``allowed_domains``.
    fetch_hosts = frozenset(host for host in {original_domain, *allowed} if host)
    fetch_start = time.monotonic()

    try:
        fetched = await safe_fetch(
            url,
            policy=SafeFetchPolicy(
                timeout_seconds=15.0,
                max_redirects=3,
                max_wire_bytes=2_000_000,
                max_decoded_bytes=2_000_000,
                allowed_content_types=("text/html", "application/xhtml+xml"),
                allowed_hosts=fetch_hosts,
                # Only the original host, its conventional www alias, and
                # explicit registry aliases may serve an article. Arbitrary
                # subdomains can be attacker-controlled or multi-tenant.
                allow_subdomains=False,
            ),
        )
    except SafeFetchError as exc:
        attempts.append({
            "method": "fetch",
            "char_count": 0,
            "duration_ms": int((time.monotonic() - fetch_start) * 1000),
            "error": exc.code,
        })
        result.update({
            "error": exc.code,
            "failure_class": _failure_class_for_fetch(exc.code, exc.status_code),
            "content_state": "fetch_failed",
            "final_url": exc.url or url,
            "http_status": exc.status_code,
            "error_reason": exc.reason,
            "retry_after_seconds": exc.retry_after_seconds,
        })
        return result
    except Exception:
        attempts.append({
            "method": "fetch",
            "char_count": 0,
            "duration_ms": int((time.monotonic() - fetch_start) * 1000),
            "error": "unexpected_fetch_error",
        })
        result.update({
            "error": "unexpected_fetch_error",
            "failure_class": "internal_error",
            "content_state": "fetch_failed",
        })
        return result

    html = fetched.text
    final_url = fetched.url
    final_domain = _domain_of(final_url)
    attempts.append({
        "method": "fetch",
        "char_count": len(html),
        "duration_ms": int((time.monotonic() - fetch_start) * 1000),
        "error": None,
    })

    soup = BeautifulSoup(html, "html.parser")
    title = _extract_title(soup)
    summary = _extract_summary(soup)
    canonical_url = _extract_canonical_url(soup, final_url) or final_url
    main_node = soup.find("article") or soup.find("main") or soup.body
    image_url = extract_best_image_url(soup, final_url, content_root=main_node)
    declared_word_count = _extract_declared_word_count(soup)
    candidate, extraction_method = _extract_best_candidate(html, soup, final_url, attempts)
    candidate = _normalize_paragraph_boundaries(candidate)
    was_truncated = len(candidate) > _MAX_CONTENT_CHARS
    if was_truncated:
        candidate = _truncate_at_sentence(candidate, _MAX_CONTENT_CHARS)

    result.update({
        "title": title,
        "summary": summary,
        "image_url": image_url,
        "source_name": final_domain or original_domain,
        "extraction_method": extraction_method,
        "final_url": final_url,
        "final_domain": final_domain,
        "canonical_url": canonical_url,
    })

    barrier_state = _classify_access_or_error_page(soup, html, candidate)
    if barrier_state:
        code = {
            "paywalled": "paywall_detected",
            "login_required": "login_required",
            "consent_required": "consent_required",
            "error_page": "error_page_detected",
        }[barrier_state]
        result.update({
            "error": code,
            "failure_class": {
                "paywalled": "paywall",
                "login_required": "access_denied",
                "consent_required": "access_denied",
                "error_page": "invalid_document",
            }[barrier_state],
            "content_state": barrier_state,
            "completeness": "invalid",
            "partial_content": candidate,
        })
        return result

    title_similarity = _title_similarity(expected_title or "", title)
    result["title_similarity"] = title_similarity if expected_title else None
    identity_error = _identity_error(
        original_domain=original_domain,
        final_domain=final_domain,
        canonical_url=canonical_url,
        expected_title=expected_title or "",
        actual_title=title,
        title_similarity=title_similarity,
        allowed_domains=allowed,
    )
    if identity_error:
        is_mismatch = identity_error != "identity_unverified"
        result.update({
            "error": identity_error,
            "failure_class": "origin_mismatch" if is_mismatch else "identity_unverified",
            "content_state": "identity_mismatch" if is_mismatch else "identity_unverified",
            "completeness": "invalid" if is_mismatch else (
                "partial" if candidate else "unknown"
            ),
            "partial_content": candidate,
        })
        return result

    result["identity_valid"] = True
    completeness_score = _completeness_score(
        candidate,
        summary=summary,
        declared_word_count=declared_word_count,
        was_truncated=was_truncated,
    )
    result["completeness_score"] = completeness_score
    result["confidence"] = completeness_score
    words = _word_count(candidate)
    paragraphs = _substantive_paragraphs(candidate)
    has_terminal_punctuation = bool(re.search(r"[.!?][\"'’”)]?\s*$", candidate))
    declared_coverage = (
        words / max(declared_word_count, 1) if declared_word_count else None
    )
    has_declared_completion_evidence = bool(
        declared_coverage is not None
        and words >= 80
        and 0.90 <= declared_coverage <= 1.25
        and has_terminal_punctuation
    )
    has_structural_completion_evidence = bool(
        words >= 350
        and len(paragraphs) >= 3
        and has_terminal_punctuation
    )

    if was_truncated:
        result.update({
            "error": "article_too_long",
            "failure_class": "incomplete_document",
            "content_state": "partial",
            "completeness": "partial",
            "partial_content": candidate,
        })
    elif completeness_score >= 0.80 and (
        has_declared_completion_evidence or has_structural_completion_evidence
    ):
        result.update({
            "content_state": "complete",
            "completeness": "complete",
            "content": candidate,
        })
    elif candidate:
        result.update({
            "error": "partial_document",
            "failure_class": "incomplete_document",
            "content_state": "partial",
            "completeness": "partial",
            "partial_content": candidate,
        })
    else:
        result.update({
            "error": "empty_document",
            "failure_class": "empty_document",
            "content_state": "empty",
            "completeness": "unknown",
        })
    return result


def _extract_title(soup: BeautifulSoup) -> str:
    node = (
        soup.find("meta", property="og:title")
        or soup.find("meta", attrs={"name": "og:title"})
        or soup.find("meta", attrs={"name": "twitter:title"})
    )
    if node and node.get("content"):
        return str(node["content"]).strip()
    headline = soup.find("h1")
    if headline:
        text = headline.get_text(" ", strip=True)
        if text:
            return text
    if soup.title:
        return soup.title.get_text(" ", strip=True)
    return ""


def _extract_summary(soup: BeautifulSoup) -> str:
    node = (
        soup.find("meta", property="og:description")
        or soup.find("meta", attrs={"name": "description"})
        or soup.find("meta", attrs={"name": "twitter:description"})
    )
    return str(node["content"]).strip() if node and node.get("content") else ""


def _extract_canonical_url(soup: BeautifulSoup, final_url: str) -> str:
    node = soup.find("link", rel=lambda value: value and "canonical" in value)
    if not node or not node.get("href"):
        og_url = soup.find("meta", property="og:url")
        candidate = str(og_url.get("content", "")).strip() if og_url else ""
    else:
        candidate = str(node["href"]).strip()
    if not candidate:
        return ""
    resolved, _fragment = urldefrag(urljoin(final_url, candidate))
    try:
        parsed = urlparse(resolved)
        port = parsed.port
    except (TypeError, ValueError):
        return ""
    if (
        parsed.scheme.lower() not in {"http", "https"}
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or (port is not None and port not in {80, 443})
        or any(ord(character) < 32 or ord(character) == 127 for character in resolved)
    ):
        return ""
    return resolved


def _extract_declared_word_count(soup: BeautifulSoup) -> int | None:
    def find_word_count(value) -> int | None:
        if isinstance(value, list):
            for item in value:
                found = find_word_count(item)
                if found:
                    return found
        elif isinstance(value, dict):
            raw = value.get("wordCount")
            if isinstance(raw, (int, float)) and 0 < raw < 1_000_000:
                return int(raw)
            if isinstance(raw, str):
                match = re.search(r"\d+", raw.replace(",", ""))
                if match and 0 < int(match.group()) < 1_000_000:
                    return int(match.group())
            for child in value.values():
                found = find_word_count(child)
                if found:
                    return found
        return None

    for node in soup.find_all("script", attrs={"type": "application/ld+json"}):
        raw = (node.string or node.get_text() or "").strip()
        if not raw:
            continue
        try:
            payload = json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            continue
        found = find_word_count(payload)
        if found:
            return found
    return None


def _extract_best_candidate(
    html: str,
    soup: BeautifulSoup,
    final_url: str,
    attempts: list[dict],
) -> tuple[str, str | None]:
    candidates: list[tuple[str, str]] = []

    def run_trafilatura(method: str, *, favor_precision: bool, favor_recall: bool) -> str:
        started = time.monotonic()
        try:
            value = trafilatura.extract(
                html,
                url=final_url,
                include_comments=False,
                include_tables=True,
                favor_precision=favor_precision,
                favor_recall=favor_recall,
                deduplicate=True,
            ) or ""
            error = None
        except Exception:
            value = ""
            error = "extractor_error"
        value = value.strip()
        attempts.append({
            "method": method,
            "char_count": len(value),
            "duration_ms": int((time.monotonic() - started) * 1000),
            "error": error,
        })
        return value

    precision = run_trafilatura(
        "trafilatura", favor_precision=True, favor_recall=False,
    )
    if precision:
        candidates.append((precision, "trafilatura"))

    # A precision result shorter than the structural completion floor may be
    # a publisher teaser. Always try recall before accepting it as the best
    # available candidate.
    if _word_count(precision) < _MIN_STRUCTURAL_COMPLETE_WORDS:
        recall = run_trafilatura(
            "trafilatura_recall", favor_precision=False, favor_recall=True,
        )
        if recall:
            candidates.append((recall, "trafilatura_recall"))

    if max(
        (_word_count(value) for value, _method in candidates), default=0
    ) < _MIN_STRUCTURAL_COMPLETE_WORDS:
        started = time.monotonic()
        try:
            fallback_soup = BeautifulSoup(str(soup), "html.parser")
            fallback = _fallback_bs4_extract(fallback_soup).strip()
            error = None
        except Exception:
            fallback = ""
            error = "extractor_error"
        attempts.append({
            "method": "bs4",
            "char_count": len(fallback),
            "duration_ms": int((time.monotonic() - started) * 1000),
            "error": error,
        })
        if fallback:
            candidates.append((fallback, "bs4"))

    if not candidates:
        return "", None
    if precision and _word_count(precision) >= _MIN_STRUCTURAL_COMPLETE_WORDS:
        return precision, "trafilatura"
    return max(candidates, key=lambda item: len(item[0]))


def _classify_access_or_error_page(
    soup: BeautifulSoup,
    html: str,
    candidate: str,
) -> str | None:
    words = _word_count(candidate)
    title = _extract_title(soup)
    visible = " ".join(soup.stripped_strings)
    signal_text = f"{title}\n{visible[-12_000:]}"
    structure_parts: list[str] = []
    for node in soup.find_all(True, limit=2_000):
        for key in ("id", "class", "data-testid"):
            value = node.get(key)
            if isinstance(value, (list, tuple)):
                structure_parts.extend(str(part) for part in value)
            elif value is not None:
                structure_parts.append(str(value))
    structural = " ".join(structure_parts)
    combined = f"{signal_text}\n{structural}\n{html[:5_000]}"

    # Strong structural gates remain authoritative even if the hidden DOM also
    # contains a long article body. Textual phrases are considered only on a
    # short document to avoid matching subscription language in normal footers.
    if re.search(
        r"(?:^|[\s_\-])(paywall|subscription-wall|metered-wall)(?:$|[\s_\-])",
        structural,
        re.IGNORECASE,
    ):
        return "paywalled"
    if re.search(
        r"(?:consent-wall|cookie-wall|onetrust-consent)",
        structural,
        re.IGNORECASE,
    ):
        return "consent_required"
    if soup.find("input", attrs={"type": "password"}) is not None and words < 120:
        return "login_required"
    if words >= 350:
        return None
    if _PAYWALL_PATTERNS.search(combined):
        return "paywalled"
    if _LOGIN_PATTERNS.search(combined):
        return "login_required"
    if _CONSENT_PATTERNS.search(combined):
        return "consent_required"
    if _ERROR_PATTERNS.search(combined):
        return "error_page"
    return None


def _title_tokens(value: str) -> set[str]:
    without_suffix = _PUBLICATION_TITLE_SUFFIX.sub("", value.casefold())
    return {
        token
        for token in _WORD_RE.findall(without_suffix)
        if len(token) > 1 and token not in _TITLE_STOPWORDS
    }


def _title_similarity(expected: str, actual: str) -> float:
    expected_tokens = _title_tokens(expected)
    actual_tokens = _title_tokens(actual)
    if not expected_tokens or not actual_tokens:
        return 0.0
    # Sørensen-Dice is symmetric. Dividing by the shorter title made a generic
    # two-word hub title look like a perfect match whenever it was a subset of
    # the real headline.
    overlap = len(expected_tokens & actual_tokens)
    return round((2 * overlap) / (len(expected_tokens) + len(actual_tokens)), 3)


def _identity_error(
    *,
    original_domain: str,
    final_domain: str,
    canonical_url: str,
    expected_title: str,
    actual_title: str,
    title_similarity: float,
    allowed_domains: frozenset[str],
) -> str | None:
    identity_domains = frozenset({original_domain, *allowed_domains})
    if original_domain and final_domain and not any(
        hosts_match(final_domain, allowed, allow_subdomains=False)
        for allowed in identity_domains
    ):
        return "source_domain_mismatch"

    canonical_domain = _domain_of(canonical_url)
    if canonical_domain and final_domain and not (
        hosts_match(canonical_domain, final_domain, allow_subdomains=False)
        or any(
            hosts_match(canonical_domain, allowed, allow_subdomains=False)
            for allowed in allowed_domains
        )
    ):
        return "canonical_domain_mismatch"

    # A shared domain is necessary but not sufficient: homepages, consent
    # interstitials, and unrelated articles all live on that same origin. A
    # positive, non-placeholder title match is required before body text can
    # become an identity-valid artifact.
    expected_tokens = _title_tokens(expected_title)
    actual_tokens = _title_tokens(actual_title)
    if len(expected_tokens) < 2 or len(actual_tokens) < 2:
        return "identity_unverified"
    overlap = len(expected_tokens & actual_tokens)
    expected_coverage = overlap / len(expected_tokens)
    actual_coverage = overlap / len(actual_tokens)
    threshold = 0.60 if len(expected_tokens) <= 3 else 0.45
    # Native display is intentionally precision-biased. Both titles must cover
    # meaningful portions of one another; a short category/index title or a
    # long loosely related SEO title cannot pass on subset overlap alone.
    if (
        title_similarity < threshold
        or expected_coverage < (0.60 if len(expected_tokens) <= 3 else 0.50)
        or actual_coverage < 0.35
    ):
        return "title_mismatch"
    return None


def _word_count(text: str) -> int:
    return len(_WORD_RE.findall(text))


def _normalize_paragraph_boundaries(text: str) -> str:
    """Preserve extractor block boundaries in the API's paragraph format.

    Trafilatura 2.x emits one newline between HTML paragraphs while Daily's
    reader and earlier fallback use blank-line-separated paragraphs.
    """
    blocks = [part.strip() for part in re.split(r"\n+", text.strip()) if part.strip()]
    return "\n\n".join(blocks)


def _substantive_paragraphs(text: str) -> list[str]:
    return [part for part in re.split(r"\n+", text) if _word_count(part) >= 5]


def _text_similarity(left: str, right: str) -> float:
    left_tokens = set(_WORD_RE.findall(left.casefold()))
    right_tokens = set(_WORD_RE.findall(right.casefold()))
    if not left_tokens or not right_tokens:
        return 0.0
    return len(left_tokens & right_tokens) / len(left_tokens | right_tokens)


def _completeness_score(
    content: str,
    *,
    summary: str,
    declared_word_count: int | None,
    was_truncated: bool,
) -> float:
    words = _word_count(content)
    paragraphs = _substantive_paragraphs(content)

    if words < 40:
        score = 0.05 if words else 0.0
    elif words < 80:
        score = 0.20
    elif words < 150:
        score = 0.38
    elif words < 250:
        score = 0.55
    elif words < 500:
        score = 0.68
    else:
        score = 0.78

    if len(paragraphs) >= 3:
        score += 0.08
    if len(paragraphs) >= 6:
        score += 0.05
    if re.search(r"[.!?][\"'’”)]?\s*$", content):
        score += 0.04

    if declared_word_count:
        coverage = words / max(declared_word_count, 1)
        if coverage >= 0.90:
            score = max(score, 0.88)
        elif coverage >= 0.80:
            score = max(score, 0.78)
        elif coverage < 0.55:
            score = min(score, 0.45)
    if _TEASER_END_PATTERNS.search(content):
        score = min(score, 0.42)
    if summary and words < 250 and _text_similarity(content, summary) >= 0.72:
        score = min(score, 0.40)
    if was_truncated:
        score = min(score, 0.60)
    return round(max(0.0, min(score, 1.0)), 3)


def _fallback_bs4_extract(soup: BeautifulSoup) -> str:
    """Extract likely article paragraphs when trafilatura cannot."""
    main_node = soup.find("article") or soup.find("main") or soup.body
    if not main_node:
        return ""
    for tag in main_node.find_all(
        ["script", "style", "nav", "footer", "header", "aside", "form", "iframe"]
    ):
        tag.decompose()
    for tag in main_node.find_all(attrs={"class": re.compile(
        r"(related|sidebar|widget|social|share|comment|newsletter|promo|ad-|advertisement)",
        re.IGNORECASE,
    )}):
        tag.decompose()

    paragraph_nodes = main_node.find_all(["p", "blockquote"])
    raw_lines = (
        [node.get_text(" ", strip=True) for node in paragraph_nodes]
        if paragraph_nodes
        else main_node.get_text(separator="\n", strip=True).split("\n")
    )
    paragraphs: list[str] = []
    for line in raw_lines:
        line = re.sub(r"\s+", " ", line).strip()
        if not line or _JUNK_PATTERNS.fullmatch(line):
            continue
        paragraphs.append(line)
    return "\n\n".join(paragraphs)


def _truncate_at_sentence(text: str, max_chars: int) -> str:
    """Truncate text at the last sentence boundary before max_chars."""
    if len(text) <= max_chars:
        return text
    truncated = text[:max_chars]
    boundaries = list(re.finditer(r"[.!?][\"'’”)]?[\s\n]", truncated))
    if boundaries and boundaries[-1].end() > max_chars // 2:
        return truncated[:boundaries[-1].end()].rstrip()
    last_para = truncated.rfind("\n\n")
    if last_para > max_chars // 2:
        return truncated[:last_para].rstrip()
    return truncated.rstrip()
