from __future__ import annotations

import ipaddress
import json
import re
from typing import Any
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup


# Meta tags (og:image, twitter:image) — narrow blocklist: these are editorial choices,
# so "thumbnail" and "thumb" in CDN URLs are legitimate (e.g. nytimes thumbnail CDN).
_BLOCKED_IMAGE_HINTS_META = {
    "logo", "icon", "sprite", "avatar", "favicon",
    "placeholder", "badge", "emoji", "apple-touch",
}

# Inline <img> — wider blocklist: inline images with these hints are usually decorative.
_BLOCKED_IMAGE_HINTS_INLINE = _BLOCKED_IMAGE_HINTS_META | {"thumbnail", "thumb", "banner"}

_STRONG_IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".avif"}
_NON_PUBLIC_HOST_SUFFIXES = (
    ".internal",
    ".invalid",
    ".local",
    ".localhost",
    ".test",
    ".example",
    ".home",
    ".lan",
)


def extract_best_image_url(
    soup: BeautifulSoup,
    page_url: str,
    content_root: Any | None = None,
) -> str:
    """Return the best trustworthy source image from an article page."""
    for candidate in _meta_image_candidates(soup):
        normalized = _normalize_image_url(candidate, page_url)
        if normalized and not _is_blocked_image_candidate(normalized):
            return normalized

    for candidate in _json_ld_image_candidates(soup):
        normalized = _normalize_image_url(candidate, page_url)
        if normalized and not _is_blocked_image_candidate(normalized):
            return normalized

    root = content_root or soup.find("article") or soup.find("main") or soup.body
    if root:
        for image in root.find_all("img"):
            normalized = _normalize_image_url(
                image.get("src") or image.get("data-src") or image.get("srcset"),
                page_url,
            )
            if normalized and _is_strong_inline_image(image, normalized):
                return normalized

    return ""


def extract_best_image_from_html(html: str, page_url: str) -> str:
    soup = BeautifulSoup(html, "html.parser")
    return extract_best_image_url(soup, page_url)


async def fetch_best_source_image(article_url: str, timeout: float = 5.0) -> str:
    """Fetch the origin page through the same SSRF boundary as body extraction."""
    # Keep this import lazy so pure HTML parsing remains usable in constrained
    # tooling, while every production network call still goes through safe_http.
    from app.services.safe_http import SafeFetchError, SafeFetchPolicy, safe_fetch

    try:
        article_host = _normalize_host(urlparse(article_url).hostname or "")
    except (TypeError, ValueError):
        return ""
    try:
        fetched = await safe_fetch(
            article_url,
            policy=SafeFetchPolicy(
                timeout_seconds=timeout,
                max_redirects=3,
                max_wire_bytes=1_000_000,
                max_decoded_bytes=1_000_000,
                allowed_content_types=("text/html", "application/xhtml+xml"),
                allowed_hosts=frozenset({article_host}) if article_host else frozenset(),
            ),
        )
    except (SafeFetchError, ValueError):
        return ""

    return extract_best_image_from_html(fetched.text, fetched.url)


def _meta_image_candidates(soup: BeautifulSoup) -> list[str]:
    selectors = (
        ("property", "og:image"),
        ("property", "og:image:secure_url"),
        ("name", "twitter:image"),
        ("name", "twitter:image:src"),
    )
    candidates: list[str] = []
    for attr, value in selectors:
        node = soup.find("meta", attrs={attr: value})
        if node and node.get("content"):
            candidates.append(str(node["content"]).strip())
    return candidates


def _json_ld_image_candidates(soup: BeautifulSoup) -> list[str]:
    candidates: list[str] = []
    for node in soup.find_all("script", attrs={"type": "application/ld+json"}):
        raw = (node.string or node.get_text() or "").strip()
        if not raw:
            continue
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError:
            continue
        _collect_json_ld_images(parsed, candidates)
    return candidates


def _collect_json_ld_images(payload: Any, candidates: list[str]) -> None:
    if isinstance(payload, list):
        for item in payload:
            _collect_json_ld_images(item, candidates)
        return

    if isinstance(payload, dict):
        image = payload.get("image")
        if isinstance(image, str):
            candidates.append(image)
        elif isinstance(image, list):
            for item in image:
                if isinstance(item, str):
                    candidates.append(item)
                elif isinstance(item, dict) and isinstance(item.get("url"), str):
                    candidates.append(item["url"])
        elif isinstance(image, dict) and isinstance(image.get("url"), str):
            candidates.append(image["url"])

        graph = payload.get("@graph")
        if graph:
            _collect_json_ld_images(graph, candidates)


def _normalize_image_url(candidate: str | None, page_url: str) -> str:
    if not candidate:
        return ""

    raw = str(candidate).strip()
    if not raw:
        return ""

    if "," in raw and " " in raw:
        raw = raw.split(",", 1)[0].split(" ", 1)[0]

    resolved = urljoin(page_url, raw)
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
    ):
        return ""

    host = _normalize_host(parsed.hostname)
    try:
        literal = ipaddress.ip_address(host.split("%", 1)[0])
    except ValueError:
        if (
            "." not in host
            or host == "localhost"
            or host.endswith(_NON_PUBLIC_HOST_SUFFIXES)
        ):
            return ""
    else:
        if not _is_public_ip(str(literal)):
            return ""

    return resolved


def _normalize_host(host: str) -> str:
    normalized = host.strip().rstrip(".").lower()
    if not normalized:
        return ""
    try:
        return normalized.encode("idna").decode("ascii")
    except UnicodeError:
        return ""


def _is_public_ip(address: str) -> bool:
    try:
        value = ipaddress.ip_address(address.split("%", 1)[0])
    except ValueError:
        return False
    return value.is_global and not (
        value.is_private
        or value.is_loopback
        or value.is_link_local
        or value.is_multicast
        or value.is_reserved
        or value.is_unspecified
    )


def _is_blocked_image_candidate(url: str, context: str = "") -> bool:
    parsed = urlparse(url)
    haystack = " ".join(filter(None, [parsed.path.lower(), parsed.query.lower(), context.lower()]))
    # Use the wider blocklist when context is present (inline <img>), narrower for meta tags
    hints = _BLOCKED_IMAGE_HINTS_INLINE if context else _BLOCKED_IMAGE_HINTS_META
    if any(hint in haystack for hint in hints):
        return True
    return bool(re.search(r"/(?:icons?|logos?|sprites?|favicons?)/", parsed.path.lower()))


def _is_strong_inline_image(image: Any, url: str) -> bool:
    context_parts = [
        " ".join(image.get("class", [])) if image.get("class") else "",
        image.get("alt", "") or "",
        image.get("id", "") or "",
        image.get("aria-label", "") or "",
    ]
    context = " ".join(part for part in context_parts if part)
    if _is_blocked_image_candidate(url, context):
        return False

    width = _dimension_to_int(image.get("width"))
    height = _dimension_to_int(image.get("height"))
    if (width and width < 120) or (height and height < 120):
        return False

    lower_url = url.lower()
    if not any(lower_url.endswith(ext) for ext in _STRONG_IMAGE_EXTENSIONS) and "image" not in lower_url:
        if not width and not height:
            return False

    return True


def _dimension_to_int(value: Any) -> int:
    if value is None:
        return 0
    match = re.search(r"\d+", str(value))
    return int(match.group(0)) if match else 0
