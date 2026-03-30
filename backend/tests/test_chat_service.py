import asyncio
import os
import sys
import types
import unittest
from unittest.mock import AsyncMock, patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

if "httpx" not in sys.modules:
    sys.modules["httpx"] = types.SimpleNamespace(AsyncClient=object)
if "bs4" not in sys.modules:
    sys.modules["bs4"] = types.SimpleNamespace(BeautifulSoup=object)
if "fastapi" not in sys.modules:
    class _HTTPException(Exception):
        def __init__(self, status_code, detail):
            super().__init__(detail)
            self.status_code = status_code
            self.detail = detail

    sys.modules["fastapi"] = types.SimpleNamespace(HTTPException=_HTTPException)
if "openai" not in sys.modules:
    sys.modules["openai"] = types.SimpleNamespace(OpenAI=object)
if "dotenv" not in sys.modules:
    sys.modules["dotenv"] = types.SimpleNamespace(load_dotenv=lambda *args, **kwargs: None)

from app.services.chat_service import ChatService
from app.services.chat_streaming import SectionStreamParser, build_blocks_from_text, sse_event


class ChatStreamingTests(unittest.TestCase):
    def test_sse_event_formats_named_event(self):
        payload = sse_event("status", {"label": "Scanning your feed"})
        self.assertIn("event: status", payload)
        self.assertIn('"label": "Scanning your feed"', payload)
        self.assertTrue(payload.endswith("\n\n"))

    def test_section_stream_parser_handles_split_tags(self):
        parser = SectionStreamParser(
            [
                {"kind": "headline", "heading": "Headline"},
                {"kind": "summary", "heading": "TL;DR"},
            ]
        )

        first = parser.feed("<head")
        second = parser.feed("line>Big move</headline><summary>Short")
        third = parser.feed(" explanation</summary>")

        self.assertEqual(first, [])
        self.assertEqual(second[0][0], "section_open")
        self.assertEqual(second[1][1]["delta"], "Big move")
        self.assertEqual(second[2][0], "section_open")
        self.assertIn("Short explanation", third[0][1]["delta"])

    def test_build_blocks_from_text_falls_back_to_body(self):
        blocks = build_blocks_from_text(
            "Plain response without tags.",
            [{"kind": "summary", "heading": "TL;DR"}],
        )
        self.assertEqual(blocks[0]["kind"], "body")
        self.assertIn("Plain response", blocks[0]["text"])


class ChatServiceFlowTests(unittest.IsolatedAsyncioTestCase):
    async def test_stream_thread_message_emits_done_and_persists_sources(self):
        service = ChatService(openai_service=_FakeOpenAIService())
        service._semantic_lookup = AsyncMock(
            return_value=[
                _article("a2", "Follow-up coverage"),
            ]
        )

        store = _InMemoryChatStore()

        async def fake_feed(*args, **kwargs):
            return [_article("a1", "Main feed story")]

        with patch("app.services.chat_service.get_personalized_feed", fake_feed), patch.multiple(
            "app.services.chat_service.chat_repository",
            get_thread=store.get_thread,
            get_thread_messages=store.get_thread_messages,
            create_message=store.create_message,
            update_message=store.update_message,
            set_message_sources=store.set_message_sources,
            get_message_sources=store.get_message_sources,
            get_recent_thread_source_articles=store.get_recent_thread_source_articles,
            get_articles_by_ids=store.get_articles_by_ids,
            update_thread_title=store.update_thread_title,
        ):
            generator = await service.stream_thread_message(
                conn=object(),
                user_id="user-1",
                thread_id="thread-1",
                content="What matters most?",
                intent=None,
            )
            events = [event async for event in generator]

        self.assertTrue(any("event: meta" in event for event in events))
        self.assertTrue(any("event: done" in event for event in events))
        self.assertEqual(store.updated_message["plain_text"], "Headline\nBig move\nTL;DR\nShort summary\nKey Points\n- One\n- Two\nWhy It Matters\nIt changes the trajectory.")
        self.assertEqual(store.source_article_ids, ["a1", "a2"])


class _FakeOpenAIService:
    async def generate_embedding(self, text: str):
        return None

    async def plan_news_chat_response(self, **kwargs):
        return {
            "title": "Big move",
            "layout": "analysis",
            "section_order": ["headline", "summary", "bullet_list", "why_it_matters"],
            "follow_ups": ["What changed?", "Who benefits?", "What next?"],
        }

    async def stream_structured_chat_response(self, **kwargs):
        chunks = [
            "<headline>Big move</headline>",
            "<summary>Short summary</summary>",
            "<bullet_list>- One\n- Two</bullet_list>",
            "<why_it_matters>It changes the trajectory.</why_it_matters>",
        ]
        for chunk in chunks:
            await asyncio.sleep(0)
            yield chunk


class _InMemoryChatStore:
    def __init__(self):
        self.thread = {
            "id": "thread-1",
            "kind": "manual",
            "title": "New chat",
            "article_id": None,
            "article_title": None,
            "local_day": None,
            "archived": False,
            "last_message_preview": None,
            "created_at": None,
            "updated_at": None,
            "message_count": 0,
        }
        self.messages = []
        self.updated_message = None
        self.source_article_ids = []

    def get_thread(self, conn, *, user_id: str, thread_id: str):
        return self.thread if thread_id == "thread-1" else None

    def get_thread_messages(self, conn, *, thread_id: str):
        return list(self.messages)

    def create_message(self, conn, *, thread_id: str, role: str, plain_text=None, blocks_json=None, follow_ups=None, degraded=False, generation_meta=None):
        row = {
            "id": f"message-{len(self.messages) + 1}",
            "thread_id": thread_id,
            "role": role,
            "plain_text": plain_text or "",
            "blocks_json": blocks_json or [],
            "follow_ups": follow_ups or [],
            "degraded": degraded,
            "generation_meta": generation_meta or {},
            "created_at": None,
        }
        self.messages.append(row)
        self.thread["message_count"] = len(self.messages)
        return row

    def update_message(self, conn, *, message_id: str, thread_id: str, plain_text: str, blocks_json, follow_ups, degraded, generation_meta):
        for message in self.messages:
            if message["id"] == message_id:
                message["plain_text"] = plain_text
                message["blocks_json"] = blocks_json
                message["follow_ups"] = follow_ups
                message["degraded"] = degraded
                message["generation_meta"] = generation_meta
                self.updated_message = message
                return message
        raise AssertionError("message not found")

    def set_message_sources(self, conn, *, message_id: str, article_ids):
        self.source_article_ids = article_ids

    def get_message_sources(self, conn, *, message_ids):
        return {
            "message-2": [_article("a1", "Main feed story"), _article("a2", "Follow-up coverage")]
        }

    def get_recent_thread_source_articles(self, conn, *, thread_id: str, limit: int = 6):
        return []

    def get_articles_by_ids(self, conn, *, article_ids):
        return []

    def update_thread_title(self, conn, *, thread_id: str, title: str):
        self.thread["title"] = title


def _article(article_id: str, title: str):
    return {
        "id": article_id,
        "title": title,
        "summary": "Summary",
        "content": "Content",
        "author": None,
        "source_name": "Daily",
        "image_url": None,
        "published_at": None,
        "category": "technology",
        "url": "https://example.com/story",
    }
