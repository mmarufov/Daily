from __future__ import annotations

import asyncio
import re
from datetime import datetime, timedelta, timezone
from typing import Any

from fastapi import HTTPException

from app.services import chat_repository
from app.services.chat_streaming import (
    SectionStreamParser,
    blocks_plain_text,
    build_blocks_from_text,
    sse_event,
)
from app.services.feed_service import get_personalized_feed
from app.services.newsapi_service import get_newsapi_service
from app.services.openai_service import get_openai_service


def _section(kind: str, heading: str | None = None, tag: str | None = None) -> dict[str, Any]:
    return {"kind": kind, "heading": heading, "tag": tag or kind}


INTENT_LIBRARY: dict[str, dict[str, Any]] = {
    "your_briefing": {
        "title": "Your Briefing",
        "default_prompt": "Give me the smartest briefing from today's coverage.",
        "layout": "briefing",
        "retrieval": "today",
        "sections": [
            _section("headline", "Headline"),
            _section("summary", "TL;DR"),
            _section("bullet_list", "Key Points"),
            _section("why_it_matters", "Why It Matters"),
            _section("watchlist", "What To Watch"),
        ],
        "follow_ups": [
            "What changed in the last few hours?",
            "Which story matters most for me?",
            "Give me the skeptical take.",
        ],
    },
    "what_changed_today": {
        "title": "What Changed Today",
        "default_prompt": "What actually changed today across the most important stories in my feed?",
        "layout": "change_log",
        "retrieval": "today",
        "sections": [
            _section("headline", "Headline"),
            _section("summary", "TL;DR"),
            _section("timeline", "What Changed"),
            _section("why_it_matters", "Why It Matters"),
        ],
        "follow_ups": [
            "What should I ignore?",
            "Which update is still unclear?",
            "Compare this with yesterday.",
        ],
    },
    "why_this_matters": {
        "title": "Why This Matters",
        "default_prompt": "Explain why the most important story in my feed matters right now.",
        "layout": "analysis",
        "retrieval": "today",
        "sections": [
            _section("headline", "Headline"),
            _section("summary", "TL;DR"),
            _section("why_it_matters", "Why It Matters"),
            _section("watchlist", "What To Watch"),
        ],
        "follow_ups": [
            "Give me the plain-English version.",
            "What is the contrarian view?",
            "What should I watch next?",
        ],
    },
    "positive_signal": {
        "title": "Positive Signal",
        "default_prompt": "Find the most credible positive signal in today's coverage and explain why it matters.",
        "layout": "positive_signal",
        "retrieval": "today",
        "sections": [
            _section("headline", "Headline"),
            _section("summary", "TL;DR"),
            _section("bullet_list", "What Looks Good"),
            _section("why_it_matters", "Why It Matters"),
        ],
        "follow_ups": [
            "Give me one more positive signal.",
            "What's the risk to this upside case?",
            "Which source was most convincing?",
        ],
    },
    "explain_simply": {
        "title": "Explain Simply",
        "default_prompt": "Break this article down in plain English.",
        "layout": "article_breakdown",
        "retrieval": "article",
        "sections": [
            _section("headline", "Headline"),
            _section("summary", "TL;DR"),
            _section("bullet_list", "Key Points"),
            _section("why_it_matters", "Why It Matters"),
        ],
        "follow_ups": [
            "What's the technical version?",
            "What is still unclear?",
            "Who wins or loses here?",
        ],
    },
    "bull_vs_bear": {
        "title": "Bull vs Bear",
        "default_prompt": "Give me the strongest bull case and bear case for this story.",
        "layout": "bull_bear",
        "retrieval": "article",
        "sections": [
            _section("headline", "Headline"),
            _section("summary", "TL;DR"),
            _section("bullet_list", "Bull Case"),
            _section("bullet_list", "Bear Case", tag="bullet_list_2"),
            _section("watchlist", "What To Watch"),
        ],
        "follow_ups": [
            "Which side looks stronger right now?",
            "What evidence would flip the story?",
            "What should I track next?",
        ],
    },
    "whats_missing": {
        "title": "What's Missing",
        "default_prompt": "Tell me what's missing from this article and what context I still need.",
        "layout": "gap_analysis",
        "retrieval": "article",
        "sections": [
            _section("headline", "Headline"),
            _section("summary", "TL;DR"),
            _section("bullet_list", "What's Missing"),
            _section("watchlist", "What To Watch"),
        ],
        "follow_ups": [
            "Which source fills this gap best?",
            "What would a skeptic ask here?",
            "What follow-up should I read?",
        ],
    },
    "what_to_watch": {
        "title": "What To Watch",
        "default_prompt": "What should I watch next after this story?",
        "layout": "watchlist",
        "retrieval": "article",
        "sections": [
            _section("headline", "Headline"),
            _section("summary", "TL;DR"),
            _section("watchlist", "What To Watch"),
            _section("why_it_matters", "Why It Matters"),
        ],
        "follow_ups": [
            "Which company or person matters most here?",
            "What happens next week?",
            "Find related coverage.",
        ],
    },
}

QA_RESPONSE_LAYOUT = {
    "title": "Answer",
    "layout": "qa",
    "sections": [_section("answer")],
    "follow_ups": [],
}

ROUNDUP_RESPONSE_LAYOUT = {
    "title": "Top stories today",
    "layout": "news_roundup",
    "sections": [
        _section("headline", "Headline"),
        _section("summary", "TL;DR"),
        _section("bullet_list", "Key Themes"),
        _section("why_it_matters", "Why It Matters"),
    ],
    "follow_ups": [
        "Which story matters most for me?",
        "What changed in the last few hours?",
        "Give me the skeptical take.",
    ],
}

PHATIC_PROMPT_RE = re.compile(
    r"^\s*(?:hey|hi|hello|yo|sup|what'?s up|whats up|how are you|thanks|thank you|thx|lol|lmao|haha|ok|okay|cool|nice|gm|good morning|good evening)\b[\s!?.,]*$",
    re.IGNORECASE,
)

BROAD_NEWS_PROMPT_RE = re.compile(
    r"\b("
    r"what(?:'s| is) happening(?: today| right now)?|"
    r"what(?:'s| is) going on(?: today| right now)?|"
    r"top news|"
    r"biggest stories|"
    r"interesting (?:topics|stories|news)|"
    r"most important (?:stories|news)|"
    r"what should i know today|"
    r"what changed today|"
    r"news today"
    r")\b",
    re.IGNORECASE,
)

FRESH_NEWS_RE = re.compile(
    r"\b(today|latest|right now|breaking|just happened|fresh|newest)\b",
    re.IGNORECASE,
)

WEAK_THREAD_TITLE_RE = re.compile(
    r"^\s*(?:new chat|hey|hi|hello|yo|sup|what'?s up|gm|good morning|good evening)\s*$",
    re.IGNORECASE,
)


class ChatService:
    def __init__(self, openai_service=None, newsapi_service=None):
        self.openai_service = openai_service or get_openai_service()
        self.newsapi_service = newsapi_service

    async def list_threads(self, conn, *, user_id: str, limit: int = 40) -> list[dict[str, Any]]:
        rows = chat_repository.list_threads(conn, user_id=user_id, limit=limit)
        return [self._serialize_thread(row) for row in rows]

    async def create_thread(
        self,
        conn,
        *,
        user_id: str,
        kind: str,
        title: str | None = None,
        article_id: str | None = None,
        article_title: str | None = None,
        local_day: str | None = None,
    ) -> dict[str, Any]:
        if kind not in {"today", "manual", "article"}:
            raise HTTPException(status_code=400, detail="Unsupported thread kind")

        if kind == "today":
            title = title or "Today"
        elif kind == "article":
            title = article_title or title or "Article discussion"
            if not article_id:
                raise HTTPException(status_code=400, detail="article_id is required for article threads")
        else:
            title = title or "New chat"

        row = chat_repository.create_or_reuse_thread(
            conn,
            user_id=user_id,
            kind=kind,
            title=title,
            article_id=article_id,
            article_title=article_title,
            local_day=local_day,
        )
        return self._serialize_thread(row)

    async def get_thread_detail(
        self,
        conn,
        *,
        user_id: str,
        thread_id: str,
    ) -> dict[str, Any]:
        thread = chat_repository.get_thread(conn, user_id=user_id, thread_id=thread_id)
        if not thread:
            raise HTTPException(status_code=404, detail="Thread not found")

        messages = chat_repository.get_thread_messages(conn, thread_id=thread_id)
        message_ids = [str(message["id"]) for message in messages if message["role"] == "assistant"]
        message_sources = chat_repository.get_message_sources(conn, message_ids=message_ids)

        serialized_messages = [
            self._serialize_message(message, message_sources.get(str(message["id"]), []))
            for message in messages
        ]
        return {
            "thread": self._serialize_thread(thread),
            "messages": serialized_messages,
        }

    async def stream_thread_message(
        self,
        conn,
        *,
        user_id: str,
        thread_id: str,
        content: str | None,
        intent: str | None,
    ):
        thread = chat_repository.get_thread(conn, user_id=user_id, thread_id=thread_id)
        if not thread:
            raise HTTPException(status_code=404, detail="Thread not found")

        prior_messages = chat_repository.get_thread_messages(conn, thread_id=thread_id)
        intent_spec = self._resolve_intent_spec(intent)
        if intent and not intent_spec:
            raise HTTPException(status_code=400, detail="Unsupported chat intent")

        prompt = (content or "").strip()
        if intent_spec:
            prompt = prompt or intent_spec["default_prompt"]

        if not prompt:
            raise HTTPException(status_code=400, detail="content or intent is required")

        route = (
            {
                "response_mode": "structured_intent",
                "needs_retrieval": True,
                "needs_related_coverage": False,
                "allow_live_search": False,
                "reason": "explicit_intent",
            }
            if intent_spec
            else await self._route_freeform_turn(thread=thread, prompt=prompt)
        )

        if thread["kind"] == "manual" and not prior_messages and not self._is_phatic_prompt(prompt):
            chat_repository.update_thread_title(
                conn,
                thread_id=thread_id,
                title=self._title_from_prompt(prompt),
            )
            thread["title"] = self._title_from_prompt(prompt)

        user_message = chat_repository.create_message(
            conn,
            thread_id=thread_id,
            role="user",
            plain_text=prompt,
        )
        assistant_message = chat_repository.create_message(
            conn,
            thread_id=thread_id,
            role="assistant",
            plain_text="",
            generation_meta={
                "state": "streaming",
                "intent": intent,
                "response_mode": route["response_mode"],
                "router_reason": route.get("reason"),
            },
        )

        async def event_stream():
            yield sse_event(
                "meta",
                {
                    "thread": self._serialize_thread(thread),
                    "user_message_id": str(user_message["id"]),
                    "assistant_message_id": str(assistant_message["id"]),
                    "intent": intent,
                },
            )

            full_text = ""
            selected_articles: list[dict[str, Any]] = []
            plan: dict[str, Any] = {}
            parser: SectionStreamParser | None = None
            live_search_used = False
            try:
                if route["response_mode"] == "structured_intent":
                    yield sse_event("status", {"label": "Scanning your feed"})
                    selected_articles = await self._load_context_for_structured_intent(
                        conn=conn,
                        user_id=user_id,
                        thread=thread,
                        prompt=prompt,
                        intent_spec=intent_spec,
                    )

                    yield sse_event("status", {"label": "Pulling related coverage"})
                    plan = await self._plan_response(
                        thread=thread,
                        prompt=prompt,
                        intent_spec=intent_spec,
                        selected_articles=selected_articles,
                        prior_messages=prior_messages,
                    )

                    source_cards = [
                        self._serialize_source_card(article) for article in selected_articles[:4]
                    ]
                    if source_cards:
                        yield sse_event("sources", {"sources": source_cards})

                    yield sse_event("status", {"label": "Writing your briefing"})
                    parser = SectionStreamParser(plan["sections"])
                    async for delta in self.openai_service.stream_structured_chat_response(
                        plan=plan,
                        prompt=prompt,
                        thread=thread,
                        selected_articles=selected_articles,
                        prior_messages=prior_messages,
                    ):
                        full_text += delta
                        for event_name, payload in parser.feed(delta):
                            yield sse_event(event_name, payload)
                elif route["response_mode"] == "news_roundup":
                    yield sse_event("status", {"label": "Scanning your feed"})
                    yield sse_event("status", {"label": "Pulling related coverage"})
                    selected_articles = await self._load_context_for_news_roundup(
                        conn=conn,
                        user_id=user_id,
                        prompt=prompt,
                    )

                    if route.get("allow_live_search") and self._context_is_weak_or_stale(
                        articles=selected_articles,
                        prompt=prompt,
                        minimum_articles=4,
                    ):
                        yield sse_event("status", {"label": "Searching live coverage"})
                        live_articles = await self._load_live_news_context(
                            conn=conn,
                            prompt=prompt,
                            mode="news_roundup",
                        )
                        if live_articles:
                            live_search_used = True
                            selected_articles = self._dedupe_articles(
                                selected_articles + live_articles,
                                limit=14,
                            )

                    plan = self._roundup_plan(prompt=prompt)
                    source_cards = [
                        self._serialize_source_card(article) for article in selected_articles[:4]
                    ]
                    if source_cards:
                        yield sse_event("sources", {"sources": source_cards})

                    yield sse_event("status", {"label": "Writing your roundup"})
                    parser = SectionStreamParser(plan["sections"])
                    async for delta in self.openai_service.stream_news_roundup_response(
                        plan=plan,
                        prompt=prompt,
                        thread=thread,
                        selected_articles=selected_articles,
                        prior_messages=prior_messages,
                    ):
                        full_text += delta
                        for event_name, payload in parser.feed(delta):
                            yield sse_event(event_name, payload)
                else:
                    if route["response_mode"] == "general_chat":
                        yield sse_event("status", {"label": "Thinking"})
                        selected_articles = []
                    elif route["response_mode"] == "news_answer":
                        yield sse_event("status", {"label": "Checking your feed"})
                        yield sse_event("status", {"label": "Pulling recent coverage"})
                        selected_articles = await self._load_context_for_news_answer(
                            conn=conn,
                            user_id=user_id,
                            thread=thread,
                            prompt=prompt,
                        )
                    else:
                        yield sse_event("status", {"label": "Reading this story"})
                        if route.get("needs_related_coverage"):
                            yield sse_event("status", {"label": "Checking related coverage"})
                        selected_articles = await self._load_context_for_article_qa(
                            conn=conn,
                            thread=thread,
                            prompt=prompt,
                            needs_related_coverage=route.get("needs_related_coverage", False),
                        )

                    if (
                        route["response_mode"] in {"news_answer", "article_qa"}
                        and route.get("allow_live_search")
                        and self._context_is_weak_or_stale(
                            articles=selected_articles,
                            prompt=prompt,
                            minimum_articles=2,
                        )
                    ):
                        yield sse_event("status", {"label": "Searching live coverage"})
                        live_prompt = thread.get("article_title") or prompt
                        live_articles = await self._load_live_news_context(
                            conn=conn,
                            prompt=live_prompt,
                            mode=route["response_mode"],
                        )
                        if live_articles:
                            live_search_used = True
                            selected_articles = self._dedupe_articles(
                                selected_articles + live_articles,
                                limit=10 if route["response_mode"] == "news_answer" else 6,
                            )

                    plan = self._answer_plan(response_mode=route["response_mode"])
                    source_cards = [
                        self._serialize_source_card(article) for article in selected_articles[:4]
                    ]
                    if source_cards:
                        yield sse_event("sources", {"sources": source_cards})

                    yield sse_event("status", {"label": "Writing answer"})
                    parser = SectionStreamParser(plan["sections"])
                    async for delta in self._stream_answer_response(
                        response_mode=route["response_mode"],
                        prompt=prompt,
                        thread=thread,
                        selected_articles=selected_articles,
                        prior_messages=prior_messages,
                    ):
                        full_text += delta
                        for event_name, payload in parser.feed(delta):
                            yield sse_event(event_name, payload)

                for event_name, payload in (parser.finish() if parser else []):
                    yield sse_event(event_name, payload)

                blocks = build_blocks_from_text(full_text, plan["sections"])
                degraded = len(blocks) == 1 and blocks[0]["kind"] == "body"
                plain_text = blocks_plain_text(blocks)
                source_article_ids = [article["id"] for article in selected_articles[:4]]
                generation_meta = {
                    "state": "completed",
                    "intent": intent,
                    "response_mode": route["response_mode"],
                    "retrieval_used": bool(source_article_ids),
                    "live_search_used": live_search_used,
                    "router_reason": route.get("reason"),
                    "layout": plan["layout"],
                    "title": plan["title"],
                    "source_article_ids": source_article_ids,
                }
                updated_message = chat_repository.update_message(
                    conn,
                    message_id=str(assistant_message["id"]),
                    thread_id=thread_id,
                    plain_text=plain_text,
                    blocks_json=blocks,
                    follow_ups=plan["follow_ups"],
                    degraded=degraded,
                    generation_meta=generation_meta,
                )
                chat_repository.set_message_sources(
                    conn,
                    message_id=str(assistant_message["id"]),
                    article_ids=source_article_ids,
                )
                final_sources = chat_repository.get_message_sources(
                    conn,
                    message_ids=[str(assistant_message["id"])],
                )
                serialized_message = self._serialize_message(
                    updated_message,
                    final_sources.get(str(assistant_message["id"]), []),
                )
                if self._should_retitle_thread_after_turn(
                    thread=thread,
                    route=route,
                    prompt=prompt,
                ):
                    new_title = self._title_from_prompt(prompt)
                    chat_repository.update_thread_title(
                        conn,
                        thread_id=thread_id,
                        title=new_title,
                    )
                    thread["title"] = new_title
                if plan["follow_ups"]:
                    yield sse_event("follow_ups", {"follow_ups": plan["follow_ups"]})
                yield sse_event("done", {"message": serialized_message})
            except Exception as exc:
                fallback_text = (
                    full_text.strip()
                    or "I couldn't finish this answer cleanly. Try again in a moment."
                )
                blocks = build_blocks_from_text(fallback_text, plan.get("sections", []))
                plain_text = blocks_plain_text(blocks)
                chat_repository.update_message(
                    conn,
                    message_id=str(assistant_message["id"]),
                    thread_id=thread_id,
                    plain_text=plain_text,
                    blocks_json=blocks,
                    follow_ups=plan.get("follow_ups", []),
                    degraded=True,
                    generation_meta={
                        "state": "error",
                        "intent": intent,
                        "response_mode": route["response_mode"],
                        "live_search_used": live_search_used,
                        "router_reason": route.get("reason"),
                        "error": str(exc),
                    },
                )
                yield sse_event("error", {"detail": "Streaming failed — please try again."})

        return event_stream()

    async def _load_context_for_structured_intent(
        self,
        *,
        conn,
        user_id: str,
        thread: dict[str, Any],
        prompt: str,
        intent_spec: dict[str, Any],
    ) -> list[dict[str, Any]]:
        retrieval = intent_spec["retrieval"]
        articles: list[dict[str, Any]] = []

        if retrieval == "today":
            feed_articles = await get_personalized_feed(user_id, conn, limit=8)
            support_articles = await self._semantic_lookup(
                conn,
                query=prompt,
                limit=6,
                lookback_hours=72,
            )
            articles = feed_articles + support_articles
        elif retrieval == "article":
            article = None
            if thread.get("article_id"):
                article_rows = chat_repository.get_articles_by_ids(
                    conn,
                    article_ids=[str(thread["article_id"])],
                )
                article = article_rows[0] if article_rows else None
            related = await self._semantic_lookup(
                conn,
                query=thread.get("article_title") or prompt,
                limit=4,
                lookback_hours=24 * 7,
            )
            articles = ([article] if article else []) + related
        else:
            cited = chat_repository.get_recent_thread_source_articles(
                conn,
                thread_id=str(thread["id"]),
                limit=4,
            )
            feed_articles = await get_personalized_feed(user_id, conn, limit=6)
            support = await self._semantic_lookup(
                conn,
                query=prompt,
                limit=4,
                lookback_hours=24 * 7,
            )
            articles = cited + feed_articles + support

        return self._dedupe_articles(articles, limit=14)

    async def _route_freeform_turn(
        self,
        *,
        thread: dict[str, Any],
        prompt: str,
    ) -> dict[str, Any]:
        if self._is_phatic_prompt(prompt):
            return {
                "response_mode": "general_chat",
                "needs_retrieval": False,
                "needs_related_coverage": False,
                "allow_live_search": False,
                "reason": "phatic greeting",
            }

        if self._is_broad_news_prompt(prompt):
            return {
                "response_mode": "news_roundup",
                "needs_retrieval": True,
                "needs_related_coverage": False,
                "allow_live_search": True,
                "reason": "broad current-news prompt",
            }

        if thread["kind"] == "article":
            return {
                "response_mode": "article_qa",
                "needs_retrieval": True,
                "needs_related_coverage": self._needs_related_coverage(prompt),
                "allow_live_search": self._mentions_freshness(prompt),
                "reason": "article thread default",
            }

        try:
            route = await self.openai_service.route_chat_turn(
                prompt=prompt,
                thread_kind=str(thread.get("kind") or "manual"),
            )
        except Exception:
            route = {}

        response_mode = str(route.get("response_mode") or "general_chat")
        if response_mode not in {"general_chat", "news_answer", "news_roundup", "article_qa"}:
            response_mode = "general_chat"

        needs_retrieval = bool(route.get("needs_retrieval"))
        if response_mode == "general_chat":
            needs_retrieval = False
        elif response_mode in {"news_answer", "news_roundup", "article_qa"}:
            needs_retrieval = True

        return {
            "response_mode": response_mode,
            "needs_retrieval": needs_retrieval,
            "needs_related_coverage": bool(route.get("needs_related_coverage", False)),
            "allow_live_search": bool(route.get("allow_live_search", response_mode != "general_chat")),
            "reason": str(route.get("reason") or "classifier"),
        }

    async def _load_context_for_news_answer(
        self,
        *,
        conn,
        user_id: str,
        thread: dict[str, Any],
        prompt: str,
    ) -> list[dict[str, Any]]:
        cited = chat_repository.get_recent_thread_source_articles(
            conn,
            thread_id=str(thread["id"]),
            limit=4,
        )
        feed_articles = await get_personalized_feed(user_id, conn, limit=4)
        semantic = await self._semantic_lookup(
            conn,
            query=prompt,
            limit=6,
            lookback_hours=24 * 7,
        )
        articles = cited + feed_articles + semantic
        return self._dedupe_articles(articles, limit=10)

    async def _load_context_for_news_roundup(
        self,
        *,
        conn,
        user_id: str,
        prompt: str,
    ) -> list[dict[str, Any]]:
        feed_articles = await get_personalized_feed(user_id, conn, limit=8)
        support_articles = await self._semantic_lookup(
            conn,
            query=prompt,
            limit=6,
            lookback_hours=72,
        )
        return self._dedupe_articles(feed_articles + support_articles, limit=14)

    async def _load_context_for_article_qa(
        self,
        *,
        conn,
        thread: dict[str, Any],
        prompt: str,
        needs_related_coverage: bool,
    ) -> list[dict[str, Any]]:
        articles: list[dict[str, Any]] = []
        if thread.get("article_id"):
            article_rows = chat_repository.get_articles_by_ids(
                conn,
                article_ids=[str(thread["article_id"])],
            )
            if article_rows:
                articles.append(article_rows[0])

        cited = chat_repository.get_recent_thread_source_articles(
            conn,
            thread_id=str(thread["id"]),
            limit=2,
        )
        articles.extend(cited)

        if not articles or needs_related_coverage:
            related = await self._semantic_lookup(
                conn,
                query=thread.get("article_title") or prompt,
                limit=3,
                lookback_hours=24 * 7,
            )
            articles.extend(related)

        return self._dedupe_articles(articles, limit=4)

    async def _load_live_news_context(
        self,
        *,
        conn,
        prompt: str,
        mode: str,
    ) -> list[dict[str, Any]]:
        newsapi_service = self.newsapi_service
        if newsapi_service is None:
            try:
                newsapi_service = get_newsapi_service()
            except Exception:
                return []

        external_articles: list[dict[str, Any]] = []
        try:
            if mode == "news_roundup":
                external_articles.extend(
                    await newsapi_service.top_headlines_for_roundup(country="us", page_size=20)
                )
                focus_query = self._roundup_focus_query(prompt)
                if focus_query:
                    external_articles.extend(
                        await newsapi_service.search_recent_for_prompt(focus_query, page_size=4)
                    )
            else:
                external_articles.extend(
                    await newsapi_service.search_recent_for_prompt(prompt, page_size=6)
                )
        except Exception:
            return []

        return self._normalize_live_articles(conn, external_articles)

    def _normalize_live_articles(
        self,
        conn,
        articles: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        normalized = []
        for article in articles:
            url = article.get("url")
            if not url:
                continue
            normalized.append(
                {
                    "url": url,
                    "title": article.get("title") or "Untitled",
                    "summary": article.get("summary") or article.get("description"),
                    "author": article.get("author"),
                    "source_name": article.get("source_name") or article.get("source"),
                    "image_url": article.get("image_url"),
                    "published_at": article.get("published_at"),
                    "category": article.get("category"),
                }
            )

        if not normalized:
            return []

        try:
            return chat_repository.upsert_external_articles(conn, articles=normalized)
        except Exception:
            return []

    async def _stream_answer_response(
        self,
        *,
        response_mode: str,
        prompt: str,
        thread: dict[str, Any],
        selected_articles: list[dict[str, Any]],
        prior_messages: list[dict[str, Any]],
    ):
        async for delta in self.openai_service.stream_news_answer_response(
            response_mode=response_mode,
            prompt=prompt,
            thread=thread,
            selected_articles=selected_articles,
            prior_messages=prior_messages,
        ):
            yield delta

    async def _semantic_lookup(
        self,
        conn,
        *,
        query: str,
        limit: int,
        lookback_hours: int,
    ) -> list[dict[str, Any]]:
        embedding = await self.openai_service.generate_embedding(query)
        if not embedding:
            return []

        with conn.cursor() as cur:
            cur.execute(
                f"""
                SELECT id, title, summary, content, author, source_name, image_url,
                       published_at, category, url,
                       1 - (embedding <=> %s::vector) AS similarity
                FROM public.articles
                WHERE embedding IS NOT NULL
                  AND COALESCE(published_at, ingested_at) > now() - interval '{lookback_hours} hours'
                ORDER BY embedding <=> %s::vector
                LIMIT %s
                """,
                (str(embedding), str(embedding), limit),
            )
            return cur.fetchall()

    async def _plan_response(
        self,
        *,
        thread: dict[str, Any],
        prompt: str,
        intent_spec: dict[str, Any],
        selected_articles: list[dict[str, Any]],
        prior_messages: list[dict[str, Any]],
    ) -> dict[str, Any]:
        fallback = {
            "title": intent_spec["title"],
            "layout": intent_spec["layout"],
            "sections": intent_spec["sections"],
            "follow_ups": intent_spec["follow_ups"],
        }
        try:
            planner_response = await self.openai_service.plan_news_chat_response(
                prompt=prompt,
                thread=thread,
                selected_articles=selected_articles,
                prior_messages=prior_messages,
                intent_spec=intent_spec,
            )
        except Exception:
            planner_response = {}

        sections = self._normalize_sections(
            planner_response.get("section_order"),
            intent_spec["sections"],
        )
        title = (planner_response.get("title") or fallback["title"]).strip()[:120]
        follow_ups = self._normalize_follow_ups(
            planner_response.get("follow_ups"),
            fallback["follow_ups"],
        )

        return {
            "title": title,
            "layout": planner_response.get("layout") or fallback["layout"],
            "sections": sections,
            "follow_ups": follow_ups,
        }

    def _serialize_thread(self, row: dict[str, Any]) -> dict[str, Any]:
        return {
            "id": str(row["id"]),
            "kind": row["kind"],
            "title": row["title"],
            "article_id": str(row["article_id"]) if row.get("article_id") else None,
            "article_title": row.get("article_title"),
            "local_day": row["local_day"].isoformat() if row.get("local_day") else None,
            "last_message_preview": row.get("last_message_preview"),
            "message_count": int(row.get("message_count") or 0),
            "created_at": self._iso(row.get("created_at")),
            "updated_at": self._iso(row.get("updated_at")),
        }

    def _serialize_message(
        self,
        row: dict[str, Any] | None,
        sources: list[dict[str, Any]],
    ) -> dict[str, Any]:
        if row is None:
            return {}

        blocks = row.get("blocks_json") or []
        if isinstance(blocks, str):
            import json

            blocks = json.loads(blocks)
        follow_ups = row.get("follow_ups") or []
        if isinstance(follow_ups, str):
            import json

            follow_ups = json.loads(follow_ups)
        return {
            "id": str(row["id"]),
            "thread_id": str(row["thread_id"]),
            "role": row["role"],
            "plain_text": row.get("plain_text") or "",
            "blocks": blocks,
            "follow_ups": follow_ups,
            "degraded": bool(row.get("degraded", False)),
            "created_at": self._iso(row.get("created_at")),
            "sources": [self._serialize_source_card(source) for source in sources],
        }

    def _serialize_source_card(self, article: dict[str, Any]) -> dict[str, Any]:
        published_at = article.get("published_at")
        return {
            "article_id": str(article["id"]),
            "title": article["title"],
            "summary": article.get("summary"),
            "source": article.get("source_name"),
            "image_url": article.get("image_url"),
            "published_at": self._iso(published_at) if isinstance(published_at, datetime) else published_at,
            "category": article.get("category"),
            "url": article.get("url"),
        }

    def _resolve_intent_spec(self, intent: str | None) -> dict[str, Any] | None:
        if intent and intent in INTENT_LIBRARY:
            return INTENT_LIBRARY[intent]
        return None

    def _answer_plan(self, *, response_mode: str) -> dict[str, Any]:
        return {
            "title": "Answer",
            "layout": response_mode,
            "sections": QA_RESPONSE_LAYOUT["sections"],
            "follow_ups": [],
        }

    def _roundup_plan(self, *, prompt: str) -> dict[str, Any]:
        title = "Top stories today"
        focus_query = self._roundup_focus_query(prompt)
        if focus_query:
            title = f"Top {focus_query} stories today"
        return {
            "title": title[:120],
            "layout": ROUNDUP_RESPONSE_LAYOUT["layout"],
            "sections": ROUNDUP_RESPONSE_LAYOUT["sections"],
            "follow_ups": ROUNDUP_RESPONSE_LAYOUT["follow_ups"],
        }

    def _normalize_sections(
        self,
        planned_order: list[str] | None,
        default_sections: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        if not planned_order:
            return default_sections

        normalized: list[dict[str, Any]] = []
        remaining = default_sections[:]
        for entry in planned_order:
            match = next(
                (
                    section
                    for section in remaining
                    if section["kind"] == entry or section.get("tag") == entry
                ),
                None,
            )
            if match:
                normalized.append(match)
                remaining.remove(match)
        return normalized or default_sections

    def _normalize_follow_ups(
        self,
        follow_ups: list[str] | None,
        defaults: list[str],
    ) -> list[str]:
        cleaned = []
        for follow_up in follow_ups or []:
            text = str(follow_up).strip()
            if text and text not in cleaned:
                cleaned.append(text[:100])
        return cleaned[:3] or defaults

    def _title_from_prompt(self, prompt: str) -> str:
        collapsed = " ".join(prompt.split())
        if len(collapsed) <= 50:
            return collapsed
        return f"{collapsed[:47].rstrip()}..."

    def _is_phatic_prompt(self, prompt: str) -> bool:
        collapsed = " ".join(prompt.split())
        if len(collapsed) > 40:
            return False
        return bool(PHATIC_PROMPT_RE.match(collapsed))

    def _is_broad_news_prompt(self, prompt: str) -> bool:
        collapsed = " ".join(prompt.split())
        return bool(BROAD_NEWS_PROMPT_RE.search(collapsed))

    def _mentions_freshness(self, prompt: str) -> bool:
        return bool(FRESH_NEWS_RE.search(prompt))

    def _needs_related_coverage(self, prompt: str) -> bool:
        return bool(
            re.search(
                r"\b(compare|context|broader|related|elsewhere|other coverage|other stories|market|industry|mean for|impact on|what changed)\b",
                prompt,
                re.IGNORECASE,
            )
        )

    def _context_is_weak_or_stale(
        self,
        *,
        articles: list[dict[str, Any]],
        prompt: str,
        minimum_articles: int,
    ) -> bool:
        if len(articles) < minimum_articles:
            return True

        similarities = [
            float(article.get("similarity") or 0.0)
            for article in articles
            if article.get("similarity") is not None
        ]
        if similarities and max(similarities) < 0.35 and len(articles) < minimum_articles + 2:
            return True

        if not self._mentions_freshness(prompt):
            return False

        newest = max(
            (self._coerce_datetime(article.get("published_at")) for article in articles),
            default=None,
        )
        if newest is None:
            return True
        return newest < datetime.now(timezone.utc) - timedelta(hours=24)

    def _roundup_focus_query(self, prompt: str) -> str | None:
        lowered = prompt.lower()
        domains = {
            "markets": "markets",
            "stocks": "markets",
            "ai": "ai",
            "artificial intelligence": "ai",
            "politics": "politics",
            "tech": "technology",
            "technology": "technology",
            "crypto": "crypto",
            "business": "business",
            "world": "world",
        }
        for needle, label in domains.items():
            if needle in lowered:
                return label
        return None

    def _should_retitle_thread_after_turn(
        self,
        *,
        thread: dict[str, Any],
        route: dict[str, Any],
        prompt: str,
    ) -> bool:
        if thread.get("kind") != "manual":
            return False
        if route.get("response_mode") not in {"news_answer", "news_roundup"}:
            return False
        if self._is_phatic_prompt(prompt):
            return False
        title = str(thread.get("title") or "").strip()
        return not title or bool(WEAK_THREAD_TITLE_RE.match(title))

    def _dedupe_articles(
        self,
        articles: list[dict[str, Any]],
        *,
        limit: int,
    ) -> list[dict[str, Any]]:
        deduped: list[dict[str, Any]] = []
        seen: set[str] = set()
        for article in articles:
            if not article or not article.get("id"):
                continue
            article_id = str(article["id"])
            if article_id in seen:
                continue
            seen.add(article_id)
            deduped.append(self._normalize_article(article))
        return deduped[:limit]

    def _normalize_article(self, article: dict[str, Any]) -> dict[str, Any]:
        normalized = dict(article)
        if normalized.get("source") and not normalized.get("source_name"):
            normalized["source_name"] = normalized["source"]
        return normalized

    def _coerce_datetime(self, value: Any) -> datetime | None:
        if isinstance(value, datetime):
            if value.tzinfo is None:
                return value.replace(tzinfo=timezone.utc)
            return value
        if isinstance(value, str):
            try:
                return datetime.fromisoformat(value.replace("Z", "+00:00"))
            except ValueError:
                return None
        return None

    def _iso(self, value: Any) -> str | None:
        if value is None:
            return None
        if isinstance(value, datetime):
            if value.tzinfo is None:
                value = value.replace(tzinfo=timezone.utc)
            return value.isoformat()
        return str(value)
