"""
OpenAI Service for analyzing news articles
"""
import os
import asyncio
import json
from typing import Dict, List, Optional

import httpx
from bs4 import BeautifulSoup
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

    async def extract_article_with_tools(self, article_url: str) -> Dict:
        """
        Use OpenAI tool calling to fetch a news article page and extract:
        - Cleaned main text
        - Title
        - Best image URL (e.g., og:image)
        - Source name (domain)
        """

        async def fetch_and_extract_article(url: str) -> Dict:
            """Fetch HTML and extract main content + metadata."""
            try:
                async with httpx.AsyncClient(timeout=15.0) as client:
                    response = await client.get(
                        url,
                        headers={
                            "User-Agent": "Mozilla/5.0 (compatible; DailyNewsBot/1.0)"
                        },
                    )
                    response.raise_for_status()
                    html = response.text
            except Exception as e:
                return {
                    "error": f"Error fetching URL: {str(e)}",
                    "html": "",
                    "title": "",
                    "image_url": "",
                    "source_name": "",
                }

            soup = BeautifulSoup(html, "html.parser")

            # Title from og:title or <title>
            title = ""
            og_title = soup.find("meta", property="og:title") or soup.find(
                "meta", attrs={"name": "og:title"}
            )
            if og_title and og_title.get("content"):
                title = og_title["content"].strip()
            elif soup.title and soup.title.string:
                title = soup.title.string.strip()

            # Main image from og:image if available
            image_url = ""
            og_image = soup.find("meta", property="og:image") or soup.find(
                "meta", attrs={"name": "og:image"}
            )
            if og_image and og_image.get("content"):
                image_url = og_image["content"].strip()

            # Very simple main-text extraction: prefer <article>, then <main>, then body text
            main_node = soup.find("article") or soup.find("main") or soup.body
            if main_node:
                # Remove scripts/styles/nav/footer/header from main_node
                for tag in main_node.find_all(
                    ["script", "style", "nav", "footer", "header", "aside"]
                ):
                    tag.decompose()
                raw_text = main_node.get_text(separator="\n", strip=True)
            else:
                raw_text = soup.get_text(separator="\n", strip=True)

            # Limit length to keep token usage manageable
            cleaned_text = raw_text[:8000]

            # Basic source name from domain
            source_name = ""
            try:
                from urllib.parse import urlparse

                domain = urlparse(url).netloc
                source_name = domain.replace("www.", "")
            except Exception:
                source_name = ""

            return {
                "error": "",
                "html": "",
                "title": title,
                "content": cleaned_text,
                "image_url": image_url,
                "source_name": source_name,
            }

        tools = [
            {
                "type": "function",
                "function": {
                    "name": "fetch_and_extract_article",
                    "description": "Fetch a news article by URL and return cleaned main text plus basic metadata",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "url": {
                                "type": "string",
                                "description": "The URL of the article to fetch",
                            }
                        },
                        "required": ["url"],
                    },
                },
            }
        ]

        system_prompt = (
            "You are a news article formatter. You will be given cleaned article text "
            "and basic metadata from a tool. Return a JSON object with:\n"
            '- "title": short, clean title for the article (string)\n'
            '- "summary": 1–3 sentence intro/lede (string)\n'
            '- "content": 4–8 paragraphs of readable article text (string)\n'
            '- "image_url": URL of the best image to show (string, can be empty)\n'
            '- "source_name": short human-readable source name (string)\n'
        )

        user_prompt = (
            "Fetch and format this news article so it can be read comfortably in a mobile app. "
            f"URL: {article_url}\n\n"
            "1. Use the tool to fetch and extract the article.\n"
            "2. Based on the extracted text, write a clear, neutral news article.\n"
            "3. Do not invent facts that are not supported by the text.\n"
            "4. Return only JSON as specified."
        )

        # First call: let the model decide to call the tool
        first_response = await asyncio.to_thread(
            self.client.chat.completions.create,
            model=self.model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            tools=tools,
            tool_choice="auto",
            temperature=0.3,
        )

        first_message = first_response.choices[0].message
        tool_calls = getattr(first_message, "tool_calls", None)

        if not tool_calls:
            # Fallback: we didn't get a tool call, just return a minimal structure
            return {
                "title": "",
                "summary": "",
                "content": "",
                "image_url": "",
                "source_name": "",
            }

        # For now we handle a single tool call
        tool_call = tool_calls[0]
        if tool_call.function.name != "fetch_and_extract_article":
            return {
                "title": "",
                "summary": "",
                "content": "",
                "image_url": "",
                "source_name": "",
            }

        # Parse arguments and run the tool
        try:
            args = json.loads(tool_call.function.arguments)
            url = args.get("url", article_url)
        except Exception:
            url = article_url

        extracted = await fetch_and_extract_article(url)

        # Second call: send tool result back so model can structure the final article JSON
        second_response = await asyncio.to_thread(
            self.client.chat.completions.create,
            model=self.model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
                first_message,
                {
                    "role": "tool",
                    "tool_call_id": tool_call.id,
                    "name": "fetch_and_extract_article",
                    "content": json.dumps(extracted),
                },
            ],
            response_format={"type": "json_object"},
            temperature=0.2,
        )

        try:
            result_raw = second_response.choices[0].message.content
            result = json.loads(result_raw)
        except Exception:
            # If parsing fails, fall back to extracted text
            return {
                "title": extracted.get("title", ""),
                "summary": "",
                "content": extracted.get("content", ""),
                "image_url": extracted.get("image_url", ""),
                "source_name": extracted.get("source_name", ""),
            }

        return {
            "title": result.get("title", extracted.get("title", "")),
            "summary": result.get("summary", ""),
            "content": result.get("content", extracted.get("content", "")),
            "image_url": result.get("image_url", extracted.get("image_url", "")),
            "source_name": result.get("source_name", extracted.get("source_name", "")),
        }

    async def search_unsplash_images(
        self,
        query: str,
        per_page: int = 10
    ) -> List[Dict]:
        """
        Search Unsplash for images matching the query.
        
        Args:
            query: Search keywords
            per_page: Number of results to fetch (max 30)
        
        Returns:
            List of image dicts with url, description, alt_description
        """
        unsplash_key = os.getenv("UNSPLASH_ACCESS_KEY")
        
        if not unsplash_key:
            print("Warning: UNSPLASH_ACCESS_KEY not set, skipping image search")
            return []
        
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.get(
                    "https://api.unsplash.com/search/photos",
                    params={
                        "query": query[:100],  # Limit query length
                        "per_page": min(per_page, 30),
                        "orientation": "landscape",  # Better for article thumbnails
                    },
                    headers={"Authorization": f"Client-ID {unsplash_key}"}
                )
                
                if response.status_code == 200:
                    data = response.json()
                    results = data.get("results", [])
                    
                    # Format results
                    images = []
                    for img in results:
                        images.append({
                            "url": img["urls"]["regular"],  # or "small" for faster loading
                            "description": img.get("description"),
                            "alt_description": img.get("alt_description"),
                            "id": img.get("id")
                        })
                    return images
                else:
                    print(f"Unsplash API error: {response.status_code} - {response.text}")
                    return []
        except Exception as e:
            print(f"Error searching Unsplash: {e}")
            import traceback
            traceback.print_exc()
            return []

    async def select_best_image(
        self,
        article: Dict,
        image_candidates: List[Dict]
    ) -> Optional[Dict]:
        """
        Use ChatGPT to select the best matching image from Unsplash results.
        
        Args:
            article: Article dict with title, summary, etc.
            image_candidates: List of dicts with 'url', 'description', 'alt_description' from Unsplash
        
        Returns:
            Best matching image dict, or None if none match well
        """
        if not image_candidates:
            return None
        
        article_text = f"Title: {article.get('title', '')}\n"
        if article.get('summary'):
            article_text += f"Summary: {article.get('summary', '')[:300]}"
        
        # Format image candidates for GPT
        image_list = []
        for i, img in enumerate(image_candidates):
            desc = img.get('description') or img.get('alt_description') or 'No description'
            image_list.append(f"{i+1}. {desc}")
        
        system_prompt = """You are an image selector for news articles. 
Analyze the article and select the best matching image from the candidates.

Return JSON with:
- selected_index: 0-based index of best image (or -1 if none match well)
- reasoning: brief explanation of why this image matches

Only select an image if it's clearly relevant to the article topic."""
        
        user_prompt = f"""Article:
{article_text}

Available Images:
{chr(10).join(image_list)}

Select the best matching image (0-based index) or return -1 if none are relevant."""
        
        try:
            response = await asyncio.to_thread(
                self.client.chat.completions.create,
                model=self.model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt}
                ],
                response_format={"type": "json_object"},
                temperature=0.3,
            )
            
            result = json.loads(response.choices[0].message.content)
            selected_index = result.get("selected_index", -1)
            
            if selected_index >= 0 and selected_index < len(image_candidates):
                return image_candidates[selected_index]
            return None
        except Exception as e:
            print(f"Error selecting image: {e}")
            import traceback
            traceback.print_exc()
            # Fallback: return first image
            return image_candidates[0] if image_candidates else None


# Singleton instance
_openai_service: Optional[OpenAIService] = None

def get_openai_service() -> OpenAIService:
    """Get or create OpenAI service singleton"""
    global _openai_service
    if _openai_service is None:
        _openai_service = OpenAIService()
    return _openai_service

