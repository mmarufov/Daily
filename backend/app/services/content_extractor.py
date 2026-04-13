"""
Content extraction service using trafilatura (primary) with BeautifulSoup fallback.
Extracts clean article text from news pages — zero AI cost, pure HTML parsing.
"""
import re
from urllib.parse import urlparse

import httpx
import trafilatura
from bs4 import BeautifulSoup

from app.services.image_extraction import extract_best_image_url

_MAX_CONTENT_CHARS = 50_000  # safety cap (~10k words)

# Patterns that indicate boilerplate lines (case-insensitive)
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


async def extract_article_content(url: str) -> dict:
    """
    Fetch a URL and extract the main article content.

    Uses trafilatura for high-quality extraction with BeautifulSoup fallback.
    Returns dict with: title, summary, content, image_url, source_name
    """
    try:
        async with httpx.AsyncClient(timeout=15.0, follow_redirects=True) as client:
            response = await client.get(
                url,
                headers={"User-Agent": "Mozilla/5.0 (compatible; DailyNewsBot/1.0)"},
            )
            response.raise_for_status()
            html = response.text
    except Exception as e:
        return {"error": str(e), "title": "", "content": "", "image_url": "", "source_name": ""}

    soup = BeautifulSoup(html, "html.parser")

    # --- Metadata (always via BeautifulSoup) ---

    title = ""
    og_title = soup.find("meta", property="og:title") or soup.find("meta", attrs={"name": "og:title"})
    if og_title and og_title.get("content"):
        title = og_title["content"].strip()
    elif soup.title and soup.title.string:
        title = soup.title.string.strip()

    summary = ""
    og_desc = soup.find("meta", property="og:description") or soup.find("meta", attrs={"name": "description"})
    if og_desc and og_desc.get("content"):
        summary = og_desc["content"].strip()

    source_name = ""
    try:
        domain = urlparse(url).netloc
        source_name = domain.replace("www.", "")
    except Exception:
        pass

    # --- Content extraction ---

    # Primary: trafilatura
    content = trafilatura.extract(
        html,
        url=url,
        include_comments=False,
        include_tables=True,
        favor_precision=True,
        deduplicate=True,
    )

    # Fallback: improved BeautifulSoup if trafilatura returns nothing useful
    if not content or len(content.strip()) < 100:
        content = _fallback_bs4_extract(soup)

    # Safety cap with sentence-boundary truncation
    if content and len(content) > _MAX_CONTENT_CHARS:
        content = _truncate_at_sentence(content, _MAX_CONTENT_CHARS)

    # --- Image ---
    main_node = soup.find("article") or soup.find("main") or soup.body
    image_url = extract_best_image_url(soup, url, content_root=main_node)

    return {
        "title": title,
        "summary": summary,
        "content": content or "",
        "image_url": image_url,
        "source_name": source_name,
    }


def _fallback_bs4_extract(soup: BeautifulSoup) -> str:
    """Improved BeautifulSoup extraction as fallback when trafilatura fails."""
    main_node = soup.find("article") or soup.find("main") or soup.body
    if not main_node:
        return ""

    # Remove non-content elements
    for tag in main_node.find_all(
        ["script", "style", "nav", "footer", "header", "aside", "form", "iframe"]
    ):
        tag.decompose()

    # Remove common boilerplate containers
    for tag in main_node.find_all(attrs={"class": re.compile(
        r"(related|sidebar|widget|social|share|comment|newsletter|promo|ad-|advertisement)",
        re.IGNORECASE,
    )}):
        tag.decompose()

    raw_text = main_node.get_text(separator="\n", strip=True)
    lines = raw_text.split("\n")

    paragraphs = []
    for line in lines:
        line = line.strip()
        if not line:
            continue
        # Skip lines that match known junk patterns
        if _JUNK_PATTERNS.match(line):
            continue
        paragraphs.append(line)

    return "\n\n".join(paragraphs)


def _truncate_at_sentence(text: str, max_chars: int) -> str:
    """Truncate text at the last sentence boundary before max_chars."""
    if len(text) <= max_chars:
        return text

    truncated = text[:max_chars]
    # Find the last sentence-ending punctuation followed by a space or newline
    last_sentence_end = -1
    for match in re.finditer(r'[.!?][\s\n]', truncated):
        last_sentence_end = match.end()

    if last_sentence_end > max_chars // 2:
        return truncated[:last_sentence_end].rstrip()

    # If no good sentence boundary found, truncate at last paragraph break
    last_para = truncated.rfind("\n\n")
    if last_para > max_chars // 2:
        return truncated[:last_para].rstrip()

    return truncated.rstrip()
