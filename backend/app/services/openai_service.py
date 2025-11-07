"""
OpenAI Service for analyzing news articles
"""
import os
import asyncio
from typing import Dict, List, Optional
from openai import OpenAI
from dotenv import load_dotenv

load_dotenv()

class OpenAIService:
    """Service for interacting with OpenAI API to analyze news articles"""
    
    def __init__(self):
        api_key = os.getenv("OPENAI_API_KEY")
        if not api_key:
            raise ValueError("OPENAI_API_KEY environment variable is not set")
        
        # Support OpenAI project tracking (optional)
        project_id = os.getenv("OPENAI_PROJECT")
        client_kwargs = {"api_key": api_key}
        if project_id:
            client_kwargs["default_headers"] = {"OpenAI-Project": project_id}
        
        self.client = OpenAI(**client_kwargs)
        
        # Use model from env or default to cost-effective option
        # Note: "gpt-5" doesn't exist - using gpt-4o-mini as default
        # Valid models: gpt-4o, gpt-4o-mini, gpt-4-turbo, etc.
        self.model = os.getenv("OPENAI_MODEL", "gpt-4o-mini")
    
    async def analyze_article(
        self,
        article: Dict,
        prompt: str
    ) -> Dict:
        """
        Analyze a single article to determine if it matches the prompt criteria
        
        Args:
            article: Dictionary containing article data (title, description, content, etc.)
            prompt: The prompt describing what kind of articles to select
        
        Returns:
            Dictionary with:
                - selected: bool - whether article matches criteria
                - relevance_score: float (0-1) - how relevant it is
                - reasoning: str - explanation of why it was selected/rejected
        """
        article_text = self._format_article(article)
        
        system_prompt = """You are a news curator. Analyze news articles and determine if they match specific criteria.
Return your response as JSON with these exact fields:
{
    "selected": true/false,
    "relevance_score": 0.0-1.0,
    "reasoning": "brief explanation"
}"""
        
        user_prompt = f"""Analyze this news article:

{article_text}

Selection Criteria: {prompt}

Return JSON response with selected (boolean), relevance_score (0-1), and reasoning (string)."""
        
        try:
            # Run synchronous OpenAI call in thread pool
            response = await asyncio.to_thread(
                self.client.chat.completions.create,
                model=self.model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt}
                ],
                response_format={"type": "json_object"},
                temperature=0.3,  # Lower temperature for more consistent results
            )
            
            import json
            result = json.loads(response.choices[0].message.content)
            
            return {
                "selected": result.get("selected", False),
                "relevance_score": float(result.get("relevance_score", 0.0)),
                "reasoning": result.get("reasoning", ""),
            }
        except Exception as e:
            # If analysis fails, default to not selected
            return {
                "selected": False,
                "relevance_score": 0.0,
                "reasoning": f"Error during analysis: {str(e)}",
            }
    
    async def analyze_articles_batch(
        self,
        articles: List[Dict],
        prompt: str,
        batch_size: int = 10
    ) -> List[Dict]:
        """
        Analyze multiple articles in batches
        
        Args:
            articles: List of article dictionaries
            prompt: The prompt describing what kind of articles to select
            batch_size: Number of articles to process in parallel (OpenAI handles concurrency)
        
        Returns:
            List of analysis results, one per article
        """
        results = []
        for i in range(0, len(articles), batch_size):
            batch = articles[i:i + batch_size]
            batch_results = await asyncio.gather(*[
                self.analyze_article(article, prompt)
                for article in batch
            ])
            results.extend(batch_results)
        return results
    
    def _format_article(self, article: Dict) -> str:
        """Format article data into a readable string for AI analysis"""
        parts = []
        
        if article.get("title"):
            parts.append(f"Title: {article['title']}")
        
        if article.get("description"):
            parts.append(f"Description: {article['description']}")
        
        if article.get("content"):
            # Truncate content if too long (keep first 2000 chars)
            content = article['content'][:2000]
            parts.append(f"Content: {content}")
        
        if article.get("author"):
            parts.append(f"Author: {article['author']}")
        
        # Handle source - it might be a string or a dict
        source = article.get("source")
        if source:
            if isinstance(source, dict):
                source_name = source.get("name", "")
            else:
                source_name = str(source)
            if source_name:
                parts.append(f"Source: {source_name}")
        
        return "\n\n".join(parts) if parts else "No article content available"


# Singleton instance
_openai_service: Optional[OpenAIService] = None

def get_openai_service() -> OpenAIService:
    """Get or create OpenAI service singleton"""
    global _openai_service
    if _openai_service is None:
        _openai_service = OpenAIService()
    return _openai_service

