"""
Content extraction service using BeautifulSoup.
Replaces the OpenAI tool-calling approach for extracting full article text.
Zero AI cost — pure HTML parsing.
"""
from urllib.parse import urlparse

import httpx
from bs4 import BeautifulSoup

from app.services.image_extraction import extract_best_image_url


async def extract_article_content(url: str) -> dict:
    """
    Fetch a URL and extract the main article content using BeautifulSoup.

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

    # Title: og:title → <title>
    title = ""
    og_title = soup.find("meta", property="og:title") or soup.find("meta", attrs={"name": "og:title"})
    if og_title and og_title.get("content"):
        title = og_title["content"].strip()
    elif soup.title and soup.title.string:
        title = soup.title.string.strip()

    # Summary: og:description → meta description
    summary = ""
    og_desc = soup.find("meta", property="og:description") or soup.find("meta", attrs={"name": "description"})
    if og_desc and og_desc.get("content"):
        summary = og_desc["content"].strip()

    # Main text: prefer <article>, then <main>, then <body>
    main_node = soup.find("article") or soup.find("main") or soup.body
    if main_node:
        # Remove non-content elements
        for tag in main_node.find_all(["script", "style", "nav", "footer", "header", "aside", "form", "iframe"]):
            tag.decompose()
        raw_text = main_node.get_text(separator="\n", strip=True)
    else:
        raw_text = soup.get_text(separator="\n", strip=True)

    # Clean up text: normalize whitespace, limit length
    lines = raw_text.split("\n")
    # Filter out very short lines (likely navigation/UI elements)
    paragraphs = []
    for line in lines:
        line = line.strip()
        if len(line) > 40:  # Only keep substantial lines
            paragraphs.append(line)

    content = "\n\n".join(paragraphs)
    # Cap at reasonable length
    if len(content) > 10000:
        content = content[:10000]

    # Source name from domain
    source_name = ""
    try:
        domain = urlparse(url).netloc
        source_name = domain.replace("www.", "")
    except Exception:
        pass

    image_url = extract_best_image_url(soup, url, content_root=main_node)

    return {
        "title": title,
        "summary": summary,
        "content": content,
        "image_url": image_url,
        "source_name": source_name,
    }
