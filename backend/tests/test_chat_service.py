from __future__ import annotations

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
        payload = sse_event("status", {"label": "Thinking"})
        self.assertIn("event: status", payload)
        self.assertIn('"label": "Thinking"', payload)
        self.assertTrue(payload.endswith("\n\n"))

    def test_section_stream_parser_handles_split_answer_tags(self):
        parser = SectionStreamParser(
            [
                {"kind": "answer", "heading": None},
            ]
        )

        first = parser.feed("<ans")
        second = parser.feed("wer>Hello")
        third = parser.feed(" there</answer>")

        self.assertEqual(first, [])
        self.assertEqual(second[0][0], "section_open")
        self.assertEqual(third[0][1]["kind"], "answer")
        self.assertEqual(third[0][1]["delta"], "Hello there")

    def test_build_blocks_from_text_parses_answer_block(self):
        blocks = build_blocks_from_text(
            "<answer>Direct answer.</answer>",
            [{"kind": "answer", "heading": None}],
        )
        self.assertEqual(blocks[0]["kind"], "answer")
        self.assertEqual(blocks[0]["text"], "Direct answer.")

    def test_build_blocks_from_text_falls_back_to_body(self):
        blocks = build_blocks_from_text(
            "Plain response without tags.",
            [{"kind": "answer", "heading": None}],
        )
        self.assertEqual(blocks[0]["kind"], "body")
        self.assertIn("Plain response", blocks[0]["text"])


class ChatServiceFlowTests(unittest.IsolatedAsyncioTestCase):
    async def test_structured_intent_keeps_briefing_flow(self):
        fake_openai = _FakeOpenAIService()
        service = ChatService(openai_service=fake_openai)
        service._semantic_lookup = AsyncMock(return_value=[_article("a2", "Support coverage", similarity=0.7)])
        store = _InMemoryChatStore(kind="today")
        fake_feed = AsyncMock(return_value=[_article("a1", "Main feed story", similarity=0.9)])

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
                content="",
                intent="your_briefing",
            )
            events = [event async for event in generator]

        self.assertTrue(any("event: sources" in event for event in events))
        self.assertEqual(fake_openai.plan_calls, 1)
        self.assertEqual(fake_openai.structured_stream_calls, 1)
        self.assertEqual(fake_openai.qa_stream_calls, 0)
        self.assertEqual(fake_openai.route_calls, 0)
        self.assertEqual(store.updated_message["blocks_json"][0]["kind"], "headline")
        self.assertEqual(store.source_article_ids, ["a1", "a2"])

    async def test_general_chat_greeting_skips_retrieval_and_sources(self):
        fake_openai = _FakeOpenAIService()
        service = ChatService(openai_service=fake_openai)
        service._semantic_lookup = AsyncMock(return_value=[_article("a2", "Unused support")])
        store = _InMemoryChatStore(kind="manual")
        fake_feed = AsyncMock(return_value=[_article("a1", "Unused feed story")])

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
                content="what's up?",
                intent=None,
            )
            events = [event async for event in generator]

        self.assertTrue(any('"label": "Thinking"' in event for event in events))
        self.assertFalse(any("event: sources" in event for event in events))
        self.assertEqual(fake_openai.route_calls, 0)
        self.assertEqual(fake_openai.qa_stream_calls, 1)
        self.assertEqual(fake_openai.plan_calls, 0)
        service._semantic_lookup.assert_not_awaited()
        self.assertEqual(fake_feed.await_count, 0)
        self.assertEqual(store.updated_message["blocks_json"][0]["kind"], "answer")
        self.assertEqual(store.updated_message["generation_meta"]["response_mode"], "general_chat")
        self.assertEqual(store.updated_message["generation_meta"]["retrieval_used"], False)
        self.assertEqual(store.source_article_ids, [])

    async def test_today_freeform_question_routes_to_news_qa_without_briefing(self):
        fake_openai = _FakeOpenAIService(
            route_response={
                "response_mode": "news_qa",
                "needs_retrieval": True,
                "needs_related_coverage": False,
                "reason": "current-events question",
            }
        )
        service = ChatService(openai_service=fake_openai)
        service._semantic_lookup = AsyncMock(
            return_value=[
                _article("a1", "Nvidia margins jump", similarity=0.92),
                _article("a2", "Chip stocks react", similarity=0.88),
            ]
        )
        store = _InMemoryChatStore(kind="today")
        fake_feed = AsyncMock(return_value=[_article("a3", "Unused feed story")])

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
                content="What changed with Nvidia margins today?",
                intent=None,
            )
            events = [event async for event in generator]

        self.assertTrue(any('"label": "Checking your feed"' in event for event in events))
        self.assertTrue(any('"label": "Writing answer"' in event for event in events))
        self.assertEqual(fake_openai.route_calls, 1)
        self.assertEqual(fake_openai.plan_calls, 0)
        self.assertEqual(fake_openai.qa_stream_calls, 1)
        self.assertEqual(fake_feed.await_count, 0)
        self.assertEqual(store.updated_message["blocks_json"][0]["kind"], "answer")
        self.assertEqual(store.updated_message["generation_meta"]["response_mode"], "news_qa")
        self.assertEqual(store.source_article_ids, ["a1", "a2"])

    async def test_article_freeform_question_uses_current_article_first(self):
        fake_openai = _FakeOpenAIService()
        service = ChatService(openai_service=fake_openai)
        service._semantic_lookup = AsyncMock(return_value=[_article("a2", "Related coverage", similarity=0.6)])
        store = _InMemoryChatStore(
            kind="article",
            article_id="article-1",
            article_title="Tesla supply chain",
        )
        store.articles_by_id = {
            "article-1": _article("article-1", "Tesla supply chain"),
        }
        fake_feed = AsyncMock(return_value=[_article("a3", "Unused feed story")])

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
                content="What does this mean for Tesla?",
                intent=None,
            )
            events = [event async for event in generator]

        self.assertTrue(any('"label": "Reading this story"' in event for event in events))
        self.assertTrue(any('"label": "Checking related coverage"' in event for event in events))
        self.assertEqual(fake_openai.route_calls, 0)
        self.assertEqual(fake_openai.plan_calls, 0)
        self.assertEqual(fake_openai.qa_stream_calls, 1)
        self.assertEqual(service._semantic_lookup.await_count, 1)
        self.assertEqual(fake_feed.await_count, 0)
        self.assertEqual(store.updated_message["blocks_json"][0]["kind"], "answer")
        self.assertEqual(store.updated_message["generation_meta"]["response_mode"], "article_qa")
        self.assertEqual(store.source_article_ids, ["article-1", "a2"])

    async def test_news_qa_uses_feed_when_semantic_results_are_weak(self):
        fake_openai = _FakeOpenAIService(
            route_response={
                "response_mode": "news_qa",
                "needs_retrieval": True,
                "needs_related_coverage": False,
                "reason": "news question",
            }
        )
        service = ChatService(openai_service=fake_openai)
        service._semantic_lookup = AsyncMock(return_value=[_article("a1", "Weak match", similarity=0.1)])
        store = _InMemoryChatStore(kind="manual")
        fake_feed = AsyncMock(return_value=[_article("a2", "Feed article", similarity=0.9)])

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
                content="What happened in markets today?",
                intent=None,
            )
            _ = [event async for event in generator]

        self.assertEqual(fake_feed.await_count, 1)
        self.assertEqual(store.source_article_ids, ["a1", "a2"])


class _FakeOpenAIService:
    def __init__(self, route_response=None):
        self.route_response = route_response or {
            "response_mode": "general_chat",
            "needs_retrieval": False,
            "needs_related_coverage": False,
            "reason": "default general chat",
        }
        self.route_calls = 0
        self.plan_calls = 0
        self.structured_stream_calls = 0
        self.qa_stream_calls = 0

    async def generate_embedding(self, text: str):
        return None

    async def route_chat_turn(self, **kwargs):
        self.route_calls += 1
        return dict(self.route_response)

    async def plan_news_chat_response(self, **kwargs):
        self.plan_calls += 1
        return {
            "title": "Big move",
            "layout": "analysis",
            "section_order": ["headline", "summary", "bullet_list", "why_it_matters"],
            "follow_ups": ["What changed?", "Who benefits?", "What next?"],
        }

    async def stream_structured_chat_response(self, **kwargs):
        self.structured_stream_calls += 1
        chunks = [
            "<headline>Big move</headline>",
            "<summary>Short summary</summary>",
            "<bullet_list>- One\n- Two</bullet_list>",
            "<why_it_matters>It changes the trajectory.</why_it_matters>",
        ]
        for chunk in chunks:
            await asyncio.sleep(0)
            yield chunk

    async def stream_qa_chat_response(self, **kwargs):
        self.qa_stream_calls += 1
        chunks = [
            "<answer>Direct answer.",
            " With context when useful.</answer>",
        ]
        for chunk in chunks:
            await asyncio.sleep(0)
            yield chunk


class _InMemoryChatStore:
    def __init__(self, *, kind="manual", article_id=None, article_title=None):
        self.thread = {
            "id": "thread-1",
            "kind": kind,
            "title": "New chat" if kind == "manual" else "Today" if kind == "today" else "Article discussion",
            "article_id": article_id,
            "article_title": article_title,
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
        self.recent_source_articles = []
        self.articles_by_id = {}

    def get_thread(self, conn, *, user_id: str, thread_id: str):
        return self.thread if thread_id == "thread-1" else None

    def get_thread_messages(self, conn, *, thread_id: str):
        return list(self.messages)

    def create_message(
        self,
        conn,
        *,
        thread_id: str,
        role: str,
        plain_text=None,
        blocks_json=None,
        follow_ups=None,
        degraded=False,
        generation_meta=None,
    ):
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

    def update_message(
        self,
        conn,
        *,
        message_id: str,
        thread_id: str,
        plain_text: str,
        blocks_json,
        follow_ups,
        degraded,
        generation_meta,
    ):
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
        self.source_article_ids = list(article_ids)

    def get_message_sources(self, conn, *, message_ids):
        return {
            "message-2": [self._article_for_id(article_id) for article_id in self.source_article_ids]
        }

    def get_recent_thread_source_articles(self, conn, *, thread_id: str, limit: int = 6):
        return list(self.recent_source_articles[:limit])

    def get_articles_by_ids(self, conn, *, article_ids):
        return [self._article_for_id(article_id) for article_id in article_ids if article_id in self.articles_by_id]

    def update_thread_title(self, conn, *, thread_id: str, title: str):
        self.thread["title"] = title

    def _article_for_id(self, article_id: str):
        return self.articles_by_id.get(article_id, _article(article_id, f"Article {article_id}"))


def _article(article_id: str, title: str, similarity: float | None = None):
    article = {
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
    if similarity is not None:
        article["similarity"] = similarity
    return article
