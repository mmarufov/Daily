"""
Web search service using Tavily API.
Finds full article content from alternative sources when primary extraction fails.
"""
import asyncio
import logging
import os

logger = logging.getLogger(__name__)

MIN_USEFUL_CONTENT = 300  # chars — below this, content isn't worth using


class WebSearchService:
    def __init__(self):
        self.api_key = os.getenv("TAVILY_API_KEY")
        self._client = None

    @property
    def available(self) -> bool:
        return bool(self.api_key)

    def _get_client(self):
        if self._client is None:
            from tavily import TavilyClient
            self._client = TavilyClient(api_key=self.api_key)
        return self._client

    async def search_article_content(
        self, title: str, summary: str = ""
    ) -> dict | None:
        """
        Search for article content using Tavily.

        Returns the best matching full article content from an alternative source,
        or None if nothing useful found.

        Return shape: {"content": str, "source_url": str, "source_name": str}
        """
        if not self.available:
            return None

        query = title.strip()
        if not query:
            return None

        try:
            client = self._get_client()
            response = await asyncio.to_thread(
                client.search,
                query=query,
                search_depth="advanced",
                include_raw_content=True,
                max_results=5,
            )
        except Exception:
            logger.exception("Tavily search failed for: %s", title[:60])
            return None

        results = response.get("results", [])
        if not results:
            return None

        # Pick the best result with substantial raw content
        best = None
        best_score = 0.0

        for result in results:
            raw = (result.get("raw_content") or "").strip()
            score = result.get("score", 0.0)

            if len(raw) < MIN_USEFUL_CONTENT:
                continue
            if score > best_score:
                best = result
                best_score = score

        if not best:
            # Fall back to combining snippets if no raw content available
            return self._combine_snippets(results)

        return {
            "content": best["raw_content"].strip(),
            "source_url": best.get("url", ""),
            "source_name": _domain_from_url(best.get("url", "")),
        }

    def _combine_snippets(self, results: list[dict]) -> dict | None:
        """Combine snippet content from multiple results as a last resort."""
        snippets = []
        source_url = ""
        for result in results:
            snippet = (result.get("content") or "").strip()
            if snippet and len(snippet) > 50:
                snippets.append(snippet)
                if not source_url:
                    source_url = result.get("url", "")

        combined = "\n\n".join(snippets)
        if len(combined) < MIN_USEFUL_CONTENT:
            return None

        return {
            "content": combined,
            "source_url": source_url,
            "source_name": _domain_from_url(source_url),
        }


def _domain_from_url(url: str) -> str:
    try:
        from urllib.parse import urlparse
        return urlparse(url).netloc.replace("www.", "")
    except Exception:
        return ""


_web_search_service: WebSearchService | None = None


def get_web_search_service() -> WebSearchService:
    global _web_search_service
    if _web_search_service is None:
        _web_search_service = WebSearchService()
    return _web_search_service
