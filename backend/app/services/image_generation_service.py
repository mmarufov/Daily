"""
Image generation service using Gemini 2.5 Flash.
Generates editorial article images and uploads to Supabase Storage.
"""
import asyncio
import logging
import os
import uuid

import httpx

logger = logging.getLogger(__name__)


class ImageGenerationService:
    def __init__(self):
        self.gemini_key = os.getenv("GEMINI_API_KEY")
        self.supabase_url = os.getenv("SUPABASE_URL")
        self.supabase_key = os.getenv("SUPABASE_SERVICE_KEY")
        self._client = None

    @property
    def available(self) -> bool:
        return bool(self.gemini_key and self.supabase_url and self.supabase_key)

    def _get_client(self):
        if self._client is None:
            from google import genai
            self._client = genai.Client(api_key=self.gemini_key)
        return self._client

    async def generate_article_image(
        self, title: str, category: str = ""
    ) -> str | None:
        """
        Generate an editorial image for a news article.

        Returns a public URL to the uploaded image, or None on failure.
        """
        if not self.available:
            return None

        prompt = _build_image_prompt(title, category)

        try:
            image_bytes = await self._generate_image(prompt)
            if not image_bytes:
                return None

            url = await self._upload_to_supabase(image_bytes)
            return url
        except Exception:
            logger.exception("Image generation failed for: %s", title[:60])
            return None

    async def _generate_image(self, prompt: str) -> bytes | None:
        """Call Gemini 2.5 Flash to generate an image. Returns PNG bytes."""
        try:
            from google.genai import types

            client = self._get_client()
            response = await asyncio.to_thread(
                client.models.generate_content,
                model="gemini-2.5-flash-preview-04-17",
                contents=prompt,
                config=types.GenerateContentConfig(
                    response_modalities=["IMAGE"],
                    image_config=types.ImageConfig(
                        number_of_images=1,
                    ),
                ),
            )

            if not response.candidates:
                logger.warning("Gemini returned no candidates for image generation")
                return None

            for part in response.candidates[0].content.parts:
                if part.inline_data and part.inline_data.data:
                    return part.inline_data.data

            logger.warning("Gemini response contained no image data")
            return None
        except Exception:
            logger.exception("Gemini image generation API call failed")
            return None

    async def _upload_to_supabase(self, image_bytes: bytes) -> str | None:
        """Upload image bytes to Supabase Storage. Returns public URL."""
        bucket = "article-images"
        filename = f"{uuid.uuid4().hex}.png"
        path = f"{filename}"

        upload_url = f"{self.supabase_url}/storage/v1/object/{bucket}/{path}"

        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.post(
                    upload_url,
                    content=image_bytes,
                    headers={
                        "Authorization": f"Bearer {self.supabase_key}",
                        "Content-Type": "image/png",
                        "x-upsert": "true",
                    },
                )
                response.raise_for_status()

            public_url = f"{self.supabase_url}/storage/v1/object/public/{bucket}/{path}"
            return public_url
        except Exception:
            logger.exception("Supabase Storage upload failed")
            return None


def _build_image_prompt(title: str, category: str = "") -> str:
    """Build an editorial image generation prompt that avoids content policy issues."""
    category_style = {
        "technology": "modern tech aesthetic with clean lines and digital elements",
        "ai": "abstract neural network visualization with flowing data patterns",
        "science": "scientific illustration with elegant diagrams and natural elements",
        "business": "professional corporate setting with charts and modern architecture",
        "gaming": "vibrant digital art with dynamic lighting and futuristic elements",
        "sports": "dynamic athletic motion with bold colors and energy",
        "world": "global landscape with diverse cultural elements and geography",
        "politics": "civic architecture and symbolic elements of governance",
    }

    style = category_style.get(category, "clean editorial photography style")

    return (
        f"Create a visually striking editorial illustration for a news article. "
        f"Topic: {title[:200]}. "
        f"Style: {style}. "
        f"The image should be abstract and evocative, not literal. "
        f"No text, no logos, no watermarks, no people's faces. "
        f"Professional news publication quality. Wide 16:9 composition."
    )


_image_gen_service: ImageGenerationService | None = None


def get_image_generation_service() -> ImageGenerationService:
    global _image_gen_service
    if _image_gen_service is None:
        _image_gen_service = ImageGenerationService()
    return _image_gen_service
