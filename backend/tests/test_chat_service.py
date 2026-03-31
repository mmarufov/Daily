from __future__ import annotations

import asyncio
import os
import sys
import types
import unittest
from datetime import datetime, timedelta, timezone
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
        parser = SectionStreamParser([{"kind": "answer", "heading": None}])

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
        fake_newsapi = _FakeNewsAPIService()
        service = ChatService(openai_service=fake_openai, newsapi_service=fake_newsapi)
        service._semantic_lookup = AsyncMock(return_value=[_article("a2", "Support coverage", similarity=0.7)])
        store = _InMemoryChatStore(kind="today")
        fake_feed = AsyncMock(return_value=[_article("a1", "Main feed story", similarity=0.9)])

        with _patched_chat_repo(store), patch("app.services.chat_service.get_personalized_feed", fake_feed):
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
        self.assertEqual(fake_openai.news_answer_stream_calls, 0)
        self.assertEqual(fake_openai.news_roundup_stream_calls, 0)
        self.assertEqual(fake_openai.route_calls, 0)
        self.assertEqual(store.updated_message["blocks_json"][0]["kind"], "headline")
        self.assertEqual(store.source_article_ids, ["a1", "a2"])

    async def test_general_chat_greeting_skips_retrieval_and_sources(self):
        fake_openai = _FakeOpenAIService()
        fake_newsapi = _FakeNewsAPIService()
        service = ChatService(openai_service=fake_openai, newsapi_service=fake_newsapi)
        service._semantic_lookup = AsyncMock(return_value=[_article("a2", "Unused support")])
        store = _InMemoryChatStore(kind="manual")
        fake_feed = AsyncMock(return_value=[_article("a1", "Unused feed story")])

        with _patched_chat_repo(store), patch("app.services.chat_service.get_personalized_feed", fake_feed):
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
        self.assertEqual(fake_openai.news_answer_stream_calls, 1)
        self.assertEqual(fake_openai.news_roundup_stream_calls, 0)
        self.assertEqual(fake_openai.plan_calls, 0)
        self.assertEqual(fake_feed.await_count, 0)
        service._semantic_lookup.assert_not_awaited()
        self.assertEqual(fake_newsapi.search_calls, 0)
        self.assertEqual(fake_newsapi.headline_calls, 0)
        self.assertEqual(store.updated_message["blocks_json"][0]["kind"], "answer")
        self.assertEqual(store.updated_message["generation_meta"]["response_mode"], "general_chat")
        self.assertFalse(store.updated_message["generation_meta"]["retrieval_used"])
        self.assertFalse(store.updated_message["generation_meta"]["live_search_used"])
        self.assertEqual(store.source_article_ids, [])

    async def test_broad_news_prompt_routes_to_roundup_and_retitles_weak_manual_thread(self):
        fake_openai = _FakeOpenAIService()
        fake_newsapi = _FakeNewsAPIService()
        service = ChatService(openai_service=fake_openai, newsapi_service=fake_newsapi)
        service._semantic_lookup = AsyncMock(
            return_value=[_article("a2", "Support coverage", similarity=0.82)]
        )
        store = _InMemoryChatStore(kind="manual", title="Yo")
        store.messages = [
            store.make_existing_message("user", "Yo"),
            store.make_existing_message("assistant", "Hey there! How can I help you today?"),
        ]
        fake_feed = AsyncMock(return_value=[_article("a1", "Main feed story", similarity=0.91)])

        with _patched_chat_repo(store), patch("app.services.chat_service.get_personalized_feed", fake_feed):
            generator = await service.stream_thread_message(
                conn=object(),
                user_id="user-1",
                thread_id="thread-1",
                content="What are the most interesting topics and news today mate",
                intent=None,
            )
            events = [event async for event in generator]

        self.assertTrue(any('"label": "Scanning your feed"' in event for event in events))
        self.assertTrue(any('"label": "Writing your roundup"' in event for event in events))
        self.assertEqual(fake_openai.route_calls, 0)
        self.assertEqual(fake_openai.news_roundup_stream_calls, 1)
        self.assertEqual(fake_openai.news_answer_stream_calls, 0)
        self.assertEqual(store.updated_message["blocks_json"][0]["kind"], "headline")
        self.assertEqual(store.updated_message["generation_meta"]["response_mode"], "news_roundup")
        self.assertEqual(store.source_article_ids, ["a1", "a2"])
        self.assertEqual(store.thread["title"], "What are the most interesting topics and news t...")

    async def test_news_answer_uses_live_search_when_internal_context_is_weak(self):
        fake_openai = _FakeOpenAIService(
            route_response={
                "response_mode": "news_answer",
                "needs_retrieval": True,
                "needs_related_coverage": False,
                "allow_live_search": True,
                "reason": "current-events question",
            }
        )
        fake_newsapi = _FakeNewsAPIService(
            search_results=[_live_article("Fed decision live", url="https://example.com/live-fed")]
        )
        service = ChatService(openai_service=fake_openai, newsapi_service=fake_newsapi)
        stale = datetime.now(timezone.utc) - timedelta(days=3)
        service._semantic_lookup = AsyncMock(
            return_value=[_article("a1", "Weak match", similarity=0.12, published_at=stale)]
        )
        store = _InMemoryChatStore(kind="manual")
        fake_feed = AsyncMock(return_value=[])

        with _patched_chat_repo(store), patch("app.services.chat_service.get_personalized_feed", fake_feed):
            generator = await service.stream_thread_message(
                conn=object(),
                user_id="user-1",
                thread_id="thread-1",
                content="What changed with Nvidia margins today?",
                intent=None,
            )
            events = [event async for event in generator]

        self.assertTrue(any('"label": "Searching live coverage"' in event for event in events))
        self.assertEqual(fake_openai.route_calls, 1)
        self.assertEqual(fake_openai.news_answer_stream_calls, 1)
        self.assertEqual(fake_newsapi.search_calls, 1)
        self.assertEqual(fake_newsapi.headline_calls, 0)
        self.assertTrue(store.updated_message["generation_meta"]["live_search_used"])
        self.assertEqual(store.updated_message["generation_meta"]["response_mode"], "news_answer")
        self.assertEqual(store.source_article_ids, ["a1", "live-1"])

    async def test_article_thread_uses_current_article_first(self):
        fake_openai = _FakeOpenAIService()
        fake_newsapi = _FakeNewsAPIService()
        service = ChatService(openai_service=fake_openai, newsapi_service=fake_newsapi)
        service._semantic_lookup = AsyncMock(return_value=[_article("a2", "Related coverage", similarity=0.64)])
        store = _InMemoryChatStore(
            kind="article",
            article_id="article-1",
            article_title="Tesla supply chain",
        )
        store.articles_by_id = {
            "article-1": _article("article-1", "Tesla supply chain"),
        }
        fake_feed = AsyncMock(return_value=[])

        with _patched_chat_repo(store), patch("app.services.chat_service.get_personalized_feed", fake_feed):
            generator = await service.stream_thread_message(
                conn=object(),
                user_id="user-1",
                thread_id="thread-1",
                content="What does this mean for Tesla?",
                intent=None,
            )
            events = [event async for event in generator]

        self.assertTrue(any('"label": "Reading this story"' in event for event in events))
        self.assertEqual(fake_openai.route_calls, 0)
        self.assertEqual(fake_openai.news_answer_stream_calls, 1)
        self.assertEqual(store.updated_message["generation_meta"]["response_mode"], "article_qa")
        self.assertEqual(store.source_article_ids, ["article-1", "a2"])

    async def test_article_thread_pivots_to_new_manual_thread_for_broad_news_prompt(self):
        fake_openai = _FakeOpenAIService(
            route_response={
                "response_mode": "news_roundup",
                "needs_retrieval": True,
                "needs_related_coverage": False,
                "allow_live_search": True,
                "reason": "broader news pivot",
            }
        )
        fake_newsapi = _FakeNewsAPIService()
        service = ChatService(openai_service=fake_openai, newsapi_service=fake_newsapi)
        service._semantic_lookup = AsyncMock(return_value=[_article("a2", "Broader coverage", similarity=0.72)])
        store = _InMemoryChatStore(
            kind="article",
            article_id="article-1",
            article_title="Tesla supply chain",
        )
        store.articles_by_id = {
            "article-1": _article("article-1", "Tesla supply chain"),
        }
        store.recent_source_articles = [_article("article-1", "Tesla supply chain")]
        fake_feed = AsyncMock(return_value=[_article("a1", "Main feed story", similarity=0.91)])

        with _patched_chat_repo(store), patch("app.services.chat_service.get_personalized_feed", fake_feed):
            generator = await service.stream_thread_message(
                conn=object(),
                user_id="user-1",
                thread_id="thread-1",
                content="what are the news",
                intent=None,
            )
            events = [event async for event in generator]

        self.assertTrue(any('"kind": "manual"' in event for event in events if "event: meta" in event))
        self.assertNotEqual(store.updated_message["thread_id"], "thread-1")
        self.assertEqual(store.updated_message["generation_meta"]["response_mode"], "news_roundup")
        self.assertNotIn("article-1", store.source_article_ids)

    async def test_news_answer_prefers_relevant_semantic_results_over_old_cited_articles(self):
        fake_openai = _FakeOpenAIService(
            route_response={
                "response_mode": "news_answer",
                "needs_retrieval": True,
                "needs_related_coverage": False,
                "allow_live_search": True,
                "reason": "company question",
            }
        )
        fake_newsapi = _FakeNewsAPIService()
        service = ChatService(openai_service=fake_openai, newsapi_service=fake_newsapi)
        service._semantic_lookup = AsyncMock(
            return_value=[_article("nvidia-1", "Nvidia margins jump", similarity=0.82)]
        )
        store = _InMemoryChatStore(kind="manual")
        store.recent_source_articles = [_article("old-1", "Tesla robotaxi hype")]
        fake_feed = AsyncMock(return_value=[_article("feed-1", "Sports media rights")])

        with _patched_chat_repo(store), patch("app.services.chat_service.get_personalized_feed", fake_feed):
            generator = await service.stream_thread_message(
                conn=object(),
                user_id="user-1",
                thread_id="thread-1",
                content="What changed with Nvidia margins today?",
                intent=None,
            )
            _ = [event async for event in generator]

        self.assertEqual(store.source_article_ids[0], "nvidia-1")
        self.assertNotIn("old-1", store.source_article_ids[:2])

    async def test_article_thread_non_article_question_uses_classifier_instead_of_forced_article_mode(self):
        fake_openai = _FakeOpenAIService(
            route_response={
                "response_mode": "news_answer",
                "needs_retrieval": True,
                "needs_related_coverage": False,
                "allow_live_search": True,
                "reason": "different company",
            }
        )
        fake_newsapi = _FakeNewsAPIService()
        service = ChatService(openai_service=fake_openai, newsapi_service=fake_newsapi)
        service._semantic_lookup = AsyncMock(
            return_value=[_article("nvidia-1", "Nvidia margins jump", similarity=0.82)]
        )
        store = _InMemoryChatStore(
            kind="article",
            article_id="article-1",
            article_title="Tesla supply chain",
        )
        store.articles_by_id = {
            "article-1": _article("article-1", "Tesla supply chain"),
        }
        fake_feed = AsyncMock(return_value=[])

        with _patched_chat_repo(store), patch("app.services.chat_service.get_personalized_feed", fake_feed):
            generator = await service.stream_thread_message(
                conn=object(),
                user_id="user-1",
                thread_id="thread-1",
                content="What changed with Nvidia margins today?",
                intent=None,
            )
            _ = [event async for event in generator]

        self.assertEqual(fake_openai.route_calls, 1)
        self.assertEqual(store.updated_message["generation_meta"]["response_mode"], "news_answer")
        self.assertNotEqual(store.updated_message["thread_id"], "thread-1")

    async def test_live_search_still_triggers_when_feed_has_irrelevant_fill(self):
        fake_openai = _FakeOpenAIService(
            route_response={
                "response_mode": "news_answer",
                "needs_retrieval": True,
                "needs_related_coverage": False,
                "allow_live_search": True,
                "reason": "latest company question",
            }
        )
        fake_newsapi = _FakeNewsAPIService(
            search_results=[_live_article("Nvidia live update", url="https://example.com/live-nvidia")]
        )
        service = ChatService(openai_service=fake_openai, newsapi_service=fake_newsapi)
        service._semantic_lookup = AsyncMock(return_value=[])
        store = _InMemoryChatStore(kind="manual")
        fake_feed = AsyncMock(
            return_value=[
                _article("feed-1", "Sports media rights"),
                _article("feed-2", "Taylor Swift tour"),
                _article("feed-3", "Travel demand climbs"),
                _article("feed-4", "Movie box office"),
            ]
        )

        with _patched_chat_repo(store), patch("app.services.chat_service.get_personalized_feed", fake_feed):
            generator = await service.stream_thread_message(
                conn=object(),
                user_id="user-1",
                thread_id="thread-1",
                content="What changed with Nvidia margins today?",
                intent=None,
            )
            events = [event async for event in generator]

        self.assertTrue(any('"label": "Searching live coverage"' in event for event in events))
        self.assertTrue(store.updated_message["generation_meta"]["live_search_used"])
        self.assertIn("live-1", store.source_article_ids)

    async def test_roundup_uses_live_headlines_when_internal_context_is_stale(self):
        fake_openai = _FakeOpenAIService()
        fake_newsapi = _FakeNewsAPIService(
            headline_results=[_live_article("Top headline", url="https://example.com/top-headline")]
        )
        service = ChatService(openai_service=fake_openai, newsapi_service=fake_newsapi)
        stale = datetime.now(timezone.utc) - timedelta(days=5)
        service._semantic_lookup = AsyncMock(
            return_value=[_article("a2", "Old support story", similarity=0.18, published_at=stale)]
        )
        store = _InMemoryChatStore(kind="manual")
        fake_feed = AsyncMock(return_value=[_article("a1", "Older feed story", published_at=stale)])

        with _patched_chat_repo(store), patch("app.services.chat_service.get_personalized_feed", fake_feed):
            generator = await service.stream_thread_message(
                conn=object(),
                user_id="user-1",
                thread_id="thread-1",
                content="What's happening today?",
                intent=None,
            )
            events = [event async for event in generator]

        self.assertTrue(any('"label": "Searching live coverage"' in event for event in events))
        self.assertEqual(fake_openai.news_roundup_stream_calls, 1)
        self.assertEqual(fake_newsapi.headline_calls, 1)
        self.assertTrue(store.updated_message["generation_meta"]["live_search_used"])
        self.assertEqual(store.updated_message["generation_meta"]["response_mode"], "news_roundup")
        self.assertEqual(store.source_article_ids, ["a1", "a2", "live-1"])


class _FakeOpenAIService:
    def __init__(self, route_response=None):
        self.route_response = route_response or {
            "response_mode": "general_chat",
            "needs_retrieval": False,
            "needs_related_coverage": False,
            "allow_live_search": False,
            "reason": "default general chat",
        }
        self.route_calls = 0
        self.route_inputs = []
        self.plan_calls = 0
        self.structured_stream_calls = 0
        self.news_roundup_stream_calls = 0
        self.news_answer_stream_calls = 0

    async def generate_embedding(self, text: str):
        return None

    async def route_chat_turn(self, **kwargs):
        self.route_calls += 1
        self.route_inputs.append(dict(kwargs))
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

    async def stream_news_roundup_response(self, **kwargs):
        self.news_roundup_stream_calls += 1
        chunks = [
            "<headline>Top stories today</headline>",
            "<summary>Fresh roundup.</summary>",
            "<bullet_list>- One\n- Two</bullet_list>",
            "<why_it_matters>Signal is shifting.</why_it_matters>",
        ]
        for chunk in chunks:
            await asyncio.sleep(0)
            yield chunk

    async def stream_news_answer_response(self, **kwargs):
        self.news_answer_stream_calls += 1
        chunks = [
            "<answer>Direct answer.",
            " With context when useful.</answer>",
        ]
        for chunk in chunks:
            await asyncio.sleep(0)
            yield chunk


class _FakeNewsAPIService:
    def __init__(self, *, search_results=None, headline_results=None):
        self.search_results = search_results or []
        self.headline_results = headline_results or []
        self.search_calls = 0
        self.headline_calls = 0

    async def search_recent_for_prompt(self, prompt: str, *, page_size: int = 6):
        self.search_calls += 1
        return [dict(article) for article in self.search_results[:page_size]]

    async def top_headlines_for_roundup(self, *, country: str = "us", page_size: int = 20):
        self.headline_calls += 1
        return [dict(article) for article in self.headline_results[:page_size]]


class _InMemoryChatStore:
    def __init__(self, *, kind="manual", article_id=None, article_title=None, title=None):
        self.thread = {
            "id": "thread-1",
            "kind": kind,
            "title": title or ("New chat" if kind == "manual" else "Today" if kind == "today" else "Article discussion"),
            "article_id": article_id,
            "article_title": article_title,
            "local_day": None,
            "archived": False,
            "last_message_preview": None,
            "created_at": None,
            "updated_at": None,
            "message_count": 0,
        }
        self.threads = {self.thread["id"]: self.thread}
        self.messages = []
        self.updated_message = None
        self.source_article_ids = []
        self.recent_source_articles = []
        self.articles_by_id = {}
        self.articles_by_url = {}
        self._external_counter = 0

    def get_thread(self, conn, *, user_id: str, thread_id: str):
        return self.threads.get(thread_id)

    def get_thread_messages(self, conn, *, thread_id: str):
        return [dict(message) for message in self.messages if message["thread_id"] == thread_id]

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
        if thread_id in self.threads:
            thread_messages = [message for message in self.messages if message["thread_id"] == thread_id]
            self.threads[thread_id]["message_count"] = len(thread_messages)
        return row

    def make_existing_message(self, role: str, plain_text: str):
        return {
            "id": f"existing-{len(self.messages) + 1}",
            "thread_id": "thread-1",
            "role": role,
            "plain_text": plain_text,
            "blocks_json": [],
            "follow_ups": [],
            "degraded": False,
            "generation_meta": {},
            "created_at": None,
        }

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
            message_id: [self._article_for_id(article_id) for article_id in self.source_article_ids]
            for message_id in message_ids
        }

    def get_recent_thread_source_articles(self, conn, *, thread_id: str, limit: int = 6):
        if thread_id != "thread-1":
            return []
        return list(self.recent_source_articles[:limit])

    def get_articles_by_ids(self, conn, *, article_ids):
        return [self._article_for_id(article_id) for article_id in article_ids if article_id in self.articles_by_id]

    def get_articles_by_urls(self, conn, *, urls):
        return [self.articles_by_url[url] for url in urls if url in self.articles_by_url]

    def upsert_external_articles(self, conn, *, articles):
        rows = []
        for article in articles:
            url = article["url"]
            if url in self.articles_by_url:
                rows.append(self.articles_by_url[url])
                continue
            self._external_counter += 1
            article_id = f"live-{self._external_counter}"
            row = _article(
                article_id,
                article.get("title") or f"Article {article_id}",
                published_at=article.get("published_at"),
            )
            row["summary"] = article.get("summary")
            row["source_name"] = article.get("source_name") or "Live"
            row["url"] = url
            self.articles_by_url[url] = row
            self.articles_by_id[article_id] = row
            rows.append(row)
        return rows

    def update_thread_title(self, conn, *, thread_id: str, title: str):
        if thread_id in self.threads:
            self.threads[thread_id]["title"] = title

    def create_or_reuse_thread(
        self,
        conn,
        *,
        user_id: str,
        kind: str,
        title: str,
        article_id=None,
        article_title=None,
        local_day=None,
    ):
        if kind == "article" and article_id:
            for thread in self.threads.values():
                if thread["kind"] == "article" and thread["article_id"] == article_id:
                    return thread
        if kind == "today" and local_day:
            for thread in self.threads.values():
                if thread["kind"] == "today" and thread["local_day"] == local_day:
                    return thread

        thread_id = f"thread-{len(self.threads) + 1}"
        row = {
            "id": thread_id,
            "kind": kind,
            "title": title,
            "article_id": article_id,
            "article_title": article_title,
            "local_day": local_day,
            "archived": False,
            "last_message_preview": None,
            "created_at": None,
            "updated_at": None,
            "message_count": 0,
        }
        self.threads[thread_id] = row
        return row

    def _article_for_id(self, article_id: str):
        return self.articles_by_id.get(article_id, _article(article_id, f"Article {article_id}"))


def _patched_chat_repo(store: _InMemoryChatStore):
    return patch.multiple(
        "app.services.chat_service.chat_repository",
        create_or_reuse_thread=store.create_or_reuse_thread,
        get_thread=store.get_thread,
        get_thread_messages=store.get_thread_messages,
        create_message=store.create_message,
        update_message=store.update_message,
        set_message_sources=store.set_message_sources,
        get_message_sources=store.get_message_sources,
        get_recent_thread_source_articles=store.get_recent_thread_source_articles,
        get_articles_by_ids=store.get_articles_by_ids,
        get_articles_by_urls=store.get_articles_by_urls,
        upsert_external_articles=store.upsert_external_articles,
        update_thread_title=store.update_thread_title,
    )


def _article(
    article_id: str,
    title: str,
    *,
    similarity: float | None = None,
    published_at: datetime | None = None,
):
    article = {
        "id": article_id,
        "title": title,
        "summary": "Summary",
        "content": "Content",
        "author": None,
        "source_name": "Daily",
        "image_url": None,
        "published_at": published_at,
        "category": "technology",
        "url": f"https://example.com/{article_id}",
    }
    if similarity is not None:
        article["similarity"] = similarity
    return article


def _live_article(title: str, *, url: str):
    return {
        "title": title,
        "summary": "Live summary",
        "content": "Live content",
        "author": None,
        "source_name": "LiveWire",
        "image_url": None,
        "published_at": datetime.now(timezone.utc),
        "category": "business",
        "url": url,
    }
