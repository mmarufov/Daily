"""
NewsAPI Service for fetching news articles
"""
import os
from typing import Dict, List, Optional
import httpx
from dotenv import load_dotenv

load_dotenv()

class NewsAPIService:
    """Service for fetching news articles from NewsAPI"""
    
    BASE_URL = "https://newsapi.org/v2"
    
    def __init__(self):
        api_key = os.getenv("NEWS_API_KEY")
        if not api_key:
            raise ValueError("NEWS_API_KEY environment variable is not set")
        self.api_key = api_key
        self.client = httpx.AsyncClient(timeout=30.0)
    
    async def get_top_headlines(
        self,
        country: Optional[str] = "us",
        category: Optional[str] = None,
        sources: Optional[List[str]] = None,
        page_size: int = 100,
        page: int = 1
    ) -> Dict:
        """
        Get top headlines from NewsAPI
        
        Args:
            country: ISO 3166-1 code (e.g., 'us', 'gb', 'ca')
            category: business, entertainment, general, health, science, sports, technology
            sources: List of source IDs (cannot be used with country/category)
            page_size: Number of results (1-100, default 20)
            page: Page number (default 1)
        
        Returns:
            Dictionary with articles and metadata
        """
        url = f"{self.BASE_URL}/top-headlines"
        params = {
            "apiKey": self.api_key,
            "pageSize": min(page_size, 100),  # Max 100
            "page": page
        }
        
        if sources:
            params["sources"] = ",".join(sources)
        else:
            if country:
                params["country"] = country
            if category:
                params["category"] = category
        
        try:
            response = await self.client.get(url, params=params)
            response.raise_for_status()
            return response.json()
        except httpx.HTTPStatusError as e:
            if e.response.status_code == 429:
                raise ValueError("NewsAPI rate limit exceeded. Free tier: 100 requests/day")
            raise ValueError(f"NewsAPI error: {e.response.status_code} - {e.response.text}")
        except Exception as e:
            raise ValueError(f"Failed to fetch news: {str(e)}")
    
    async def search_everything(
        self,
        query: str,
        language: Optional[str] = "en",
        sort_by: Optional[str] = "publishedAt",  # relevancy, popularity, publishedAt
        page_size: int = 100,
        page: int = 1,
        from_date: Optional[str] = None,  # YYYY-MM-DD
        to_date: Optional[str] = None,  # YYYY-MM-DD
        sources: Optional[List[str]] = None
    ) -> Dict:
        """
        Search for articles across all sources
        
        Args:
            query: Keywords or phrases to search for
            language: ISO 639-1 code (e.g., 'en', 'es', 'fr')
            sort_by: relevancy, popularity, or publishedAt
            page_size: Number of results (1-100)
            page: Page number
            from_date: Start date (YYYY-MM-DD)
            to_date: End date (YYYY-MM-DD)
            sources: List of source IDs
        
        Returns:
            Dictionary with articles and metadata
        """
        url = f"{self.BASE_URL}/everything"
        params = {
            "apiKey": self.api_key,
            "q": query,
            "language": language,
            "sortBy": sort_by,
            "pageSize": min(page_size, 100),
            "page": page
        }
        
        if from_date:
            params["from"] = from_date
        if to_date:
            params["to"] = to_date
        if sources:
            params["sources"] = ",".join(sources)
        
        try:
            response = await self.client.get(url, params=params)
            response.raise_for_status()
            return response.json()
        except httpx.HTTPStatusError as e:
            if e.response.status_code == 429:
                raise ValueError("NewsAPI rate limit exceeded. Free tier: 100 requests/day")
            raise ValueError(f"NewsAPI error: {e.response.status_code} - {e.response.text}")
        except Exception as e:
            raise ValueError(f"Failed to search news: {str(e)}")
    
    async def get_sources(
        self,
        category: Optional[str] = None,
        language: Optional[str] = "en",
        country: Optional[str] = None
    ) -> Dict:
        """
        Get available news sources
        
        Args:
            category: business, entertainment, general, health, science, sports, technology
            language: ISO 639-1 code
            country: ISO 3166-1 code
        
        Returns:
            Dictionary with sources list
        """
        url = f"{self.BASE_URL}/sources"
        params = {
            "apiKey": self.api_key,
            "language": language
        }
        
        if category:
            params["category"] = category
        if country:
            params["country"] = country
        
        try:
            response = await self.client.get(url, params=params)
            response.raise_for_status()
            return response.json()
        except httpx.HTTPStatusError as e:
            if e.response.status_code == 429:
                raise ValueError("NewsAPI rate limit exceeded. Free tier: 100 requests/day")
            raise ValueError(f"NewsAPI error: {e.response.status_code} - {e.response.text}")
        except Exception as e:
            raise ValueError(f"Failed to fetch sources: {str(e)}")
    
    def format_article(self, article: Dict) -> Dict:
        """
        Format NewsAPI article to our standard format
        
        Args:
            article: Raw article from NewsAPI
        
        Returns:
            Formatted article dictionary
        """
        return {
            "title": article.get("title", ""),
            "description": article.get("description"),
            "content": article.get("content"),
            "author": article.get("author"),
            "source": article.get("source", {}).get("name") if isinstance(article.get("source"), dict) else article.get("source"),
            "image_url": article.get("urlToImage"),
            "url": article.get("url"),
            "published_at": article.get("publishedAt"),
            "category": None,  # NewsAPI doesn't provide category per article
        }
    
    async def close(self):
        """Close the HTTP client"""
        await self.client.aclose()


# Singleton instance
_newsapi_service: Optional[NewsAPIService] = None

def get_newsapi_service() -> NewsAPIService:
    """Get or create NewsAPI service singleton"""
    global _newsapi_service
    if _newsapi_service is None:
        _newsapi_service = NewsAPIService()
    return _newsapi_service





