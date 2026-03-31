from __future__ import annotations

import json
from typing import Any


def ensure_chat_tables(conn) -> None:
    with conn.cursor() as cur:
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS public.chat_threads (
                id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                user_id UUID NOT NULL REFERENCES public.users(id) ON DELETE CASCADE,
                kind TEXT NOT NULL DEFAULT 'manual',
                title TEXT NOT NULL,
                article_id UUID REFERENCES public.articles(id) ON DELETE SET NULL,
                article_title TEXT,
                local_day DATE,
                archived BOOLEAN DEFAULT false,
                last_message_preview TEXT,
                created_at TIMESTAMPTZ DEFAULT now(),
                updated_at TIMESTAMPTZ DEFAULT now()
            );
            """
        )
        cur.execute(
            """
            CREATE UNIQUE INDEX IF NOT EXISTS idx_chat_threads_today_unique
            ON public.chat_threads (user_id, local_day)
            WHERE kind = 'today';
            """
        )
        cur.execute(
            """
            CREATE UNIQUE INDEX IF NOT EXISTS idx_chat_threads_article_unique
            ON public.chat_threads (user_id, article_id)
            WHERE kind = 'article' AND article_id IS NOT NULL;
            """
        )
        cur.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_chat_threads_user_updated
            ON public.chat_threads (user_id, updated_at DESC)
            WHERE archived = false;
            """
        )

        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS public.chat_messages (
                id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                thread_id UUID NOT NULL REFERENCES public.chat_threads(id) ON DELETE CASCADE,
                role TEXT NOT NULL,
                plain_text TEXT,
                blocks_json JSONB DEFAULT '[]'::jsonb,
                follow_ups JSONB DEFAULT '[]'::jsonb,
                degraded BOOLEAN DEFAULT false,
                generation_meta JSONB DEFAULT '{}'::jsonb,
                created_at TIMESTAMPTZ DEFAULT now()
            );
            """
        )
        cur.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_chat_messages_thread_created
            ON public.chat_messages (thread_id, created_at ASC);
            """
        )

        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS public.chat_message_sources (
                message_id UUID NOT NULL REFERENCES public.chat_messages(id) ON DELETE CASCADE,
                article_id UUID NOT NULL REFERENCES public.articles(id) ON DELETE CASCADE,
                source_rank INTEGER NOT NULL DEFAULT 0,
                PRIMARY KEY (message_id, article_id)
            );
            """
        )
        cur.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_chat_message_sources_message_rank
            ON public.chat_message_sources (message_id, source_rank ASC);
            """
        )

        cur.execute(
            "ALTER TABLE public.chat_messages ADD COLUMN IF NOT EXISTS blocks_json JSONB DEFAULT '[]'::jsonb;"
        )
        cur.execute(
            "ALTER TABLE public.chat_messages ADD COLUMN IF NOT EXISTS follow_ups JSONB DEFAULT '[]'::jsonb;"
        )
        cur.execute(
            "ALTER TABLE public.chat_messages ADD COLUMN IF NOT EXISTS degraded BOOLEAN DEFAULT false;"
        )
        cur.execute(
            "ALTER TABLE public.chat_messages ADD COLUMN IF NOT EXISTS generation_meta JSONB DEFAULT '{}'::jsonb;"
        )


def create_or_reuse_thread(
    conn,
    *,
    user_id: str,
    kind: str,
    title: str,
    article_id: str | None = None,
    article_title: str | None = None,
    local_day: str | None = None,
) -> dict[str, Any]:
    with conn.cursor() as cur:
        if kind == "today":
            cur.execute(
                """
                SELECT id, user_id, kind, title, article_id, article_title, local_day,
                       archived, last_message_preview, created_at, updated_at
                FROM public.chat_threads
                WHERE user_id = %s AND kind = 'today' AND local_day = %s AND archived = false
                LIMIT 1
                """,
                (user_id, local_day),
            )
            existing = cur.fetchone()
            if existing:
                return existing
        elif kind == "article" and article_id:
            cur.execute(
                """
                SELECT id, user_id, kind, title, article_id, article_title, local_day,
                       archived, last_message_preview, created_at, updated_at
                FROM public.chat_threads
                WHERE user_id = %s AND kind = 'article' AND article_id = %s AND archived = false
                LIMIT 1
                """,
                (user_id, article_id),
            )
            existing = cur.fetchone()
            if existing:
                return existing

        cur.execute(
            """
            INSERT INTO public.chat_threads
            (user_id, kind, title, article_id, article_title, local_day)
            VALUES (%s, %s, %s, %s, %s, %s)
            RETURNING id, user_id, kind, title, article_id, article_title, local_day,
                      archived, last_message_preview, created_at, updated_at
            """,
            (user_id, kind, title, article_id, article_title, local_day),
        )
        return cur.fetchone()


def list_threads(conn, *, user_id: str, limit: int = 40) -> list[dict[str, Any]]:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT t.id, t.user_id, t.kind, t.title, t.article_id, t.article_title,
                   t.local_day, t.archived, t.last_message_preview, t.created_at,
                   t.updated_at, COALESCE(msg_counts.message_count, 0) AS message_count
            FROM public.chat_threads t
            LEFT JOIN (
                SELECT thread_id, COUNT(*) AS message_count
                FROM public.chat_messages
                GROUP BY thread_id
            ) msg_counts ON msg_counts.thread_id = t.id
            WHERE t.user_id = %s AND t.archived = false
            ORDER BY CASE WHEN t.kind = 'today' THEN 0 ELSE 1 END, t.updated_at DESC
            LIMIT %s
            """,
            (user_id, limit),
        )
        return cur.fetchall()


def get_thread(conn, *, user_id: str, thread_id: str) -> dict[str, Any] | None:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT t.id, t.user_id, t.kind, t.title, t.article_id, t.article_title,
                   t.local_day, t.archived, t.last_message_preview, t.created_at,
                   t.updated_at, COALESCE(msg_counts.message_count, 0) AS message_count
            FROM public.chat_threads t
            LEFT JOIN (
                SELECT thread_id, COUNT(*) AS message_count
                FROM public.chat_messages
                GROUP BY thread_id
            ) msg_counts ON msg_counts.thread_id = t.id
            WHERE t.user_id = %s AND t.id = %s AND t.archived = false
            LIMIT 1
            """,
            (user_id, thread_id),
        )
        return cur.fetchone()


def get_thread_messages(conn, *, thread_id: str) -> list[dict[str, Any]]:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT id, thread_id, role, plain_text, blocks_json, follow_ups,
                   degraded, generation_meta, created_at
            FROM public.chat_messages
            WHERE thread_id = %s
            ORDER BY created_at ASC
            """,
            (thread_id,),
        )
        return cur.fetchall()


def create_message(
    conn,
    *,
    thread_id: str,
    role: str,
    plain_text: str | None = None,
    blocks_json: list[dict[str, Any]] | None = None,
    follow_ups: list[str] | None = None,
    degraded: bool = False,
    generation_meta: dict[str, Any] | None = None,
) -> dict[str, Any]:
    blocks_json = blocks_json or []
    follow_ups = follow_ups or []
    generation_meta = generation_meta or {}

    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO public.chat_messages
            (thread_id, role, plain_text, blocks_json, follow_ups, degraded, generation_meta)
            VALUES (%s, %s, %s, %s::jsonb, %s::jsonb, %s, %s::jsonb)
            RETURNING id, thread_id, role, plain_text, blocks_json, follow_ups,
                      degraded, generation_meta, created_at
            """,
            (
                thread_id,
                role,
                plain_text,
                json.dumps(blocks_json),
                json.dumps(follow_ups),
                degraded,
                json.dumps(generation_meta),
            ),
        )
        row = cur.fetchone()

    if plain_text:
        touch_thread(conn, thread_id=thread_id, preview=plain_text)

    return row


def update_message(
    conn,
    *,
    message_id: str,
    thread_id: str,
    plain_text: str,
    blocks_json: list[dict[str, Any]],
    follow_ups: list[str],
    degraded: bool,
    generation_meta: dict[str, Any],
) -> dict[str, Any] | None:
    with conn.cursor() as cur:
        cur.execute(
            """
            UPDATE public.chat_messages
            SET plain_text = %s,
                blocks_json = %s::jsonb,
                follow_ups = %s::jsonb,
                degraded = %s,
                generation_meta = %s::jsonb
            WHERE id = %s
            RETURNING id, thread_id, role, plain_text, blocks_json, follow_ups,
                      degraded, generation_meta, created_at
            """,
            (
                plain_text,
                json.dumps(blocks_json),
                json.dumps(follow_ups),
                degraded,
                json.dumps(generation_meta),
                message_id,
            ),
        )
        row = cur.fetchone()

    touch_thread(conn, thread_id=thread_id, preview=plain_text)
    return row


def set_message_sources(
    conn,
    *,
    message_id: str,
    article_ids: list[str],
) -> None:
    with conn.cursor() as cur:
        cur.execute(
            "DELETE FROM public.chat_message_sources WHERE message_id = %s",
            (message_id,),
        )
        for rank, article_id in enumerate(article_ids):
            cur.execute(
                """
                INSERT INTO public.chat_message_sources (message_id, article_id, source_rank)
                VALUES (%s, %s, %s)
                ON CONFLICT (message_id, article_id)
                DO UPDATE SET source_rank = EXCLUDED.source_rank
                """,
                (message_id, article_id, rank),
            )


def get_message_sources(
    conn,
    *,
    message_ids: list[str],
) -> dict[str, list[dict[str, Any]]]:
    if not message_ids:
        return {}

    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT cms.message_id, cms.source_rank, a.id, a.title, a.summary, a.content,
                   a.author, a.source_name, a.image_url, a.published_at, a.category, a.url
            FROM public.chat_message_sources cms
            JOIN public.articles a ON a.id = cms.article_id
            WHERE cms.message_id = ANY(%s)
            ORDER BY cms.message_id ASC, cms.source_rank ASC
            """,
            (message_ids,),
        )
        rows = cur.fetchall()

    grouped: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        grouped.setdefault(str(row["message_id"]), []).append(row)
    return grouped


def get_recent_thread_source_articles(
    conn,
    *,
    thread_id: str,
    limit: int = 6,
) -> list[dict[str, Any]]:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT DISTINCT ON (a.id)
                   a.id, a.title, a.summary, a.content, a.author,
                   a.source_name, a.image_url, a.published_at, a.category, a.url,
                   cm.created_at
            FROM public.chat_messages cm
            JOIN public.chat_message_sources cms ON cms.message_id = cm.id
            JOIN public.articles a ON a.id = cms.article_id
            WHERE cm.thread_id = %s
            ORDER BY a.id, cm.created_at DESC, cms.source_rank ASC
            """,
            (thread_id,),
        )
        rows = cur.fetchall()

    rows.sort(key=lambda row: row.get("created_at"), reverse=True)
    return rows[:limit]


def get_articles_by_ids(conn, *, article_ids: list[str]) -> list[dict[str, Any]]:
    if not article_ids:
        return []

    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT id, title, summary, content, author, source_name, image_url,
                   published_at, category, url
            FROM public.articles
            WHERE id = ANY(%s)
            """,
            (article_ids,),
        )
        rows = cur.fetchall()

    order = {article_id: index for index, article_id in enumerate(article_ids)}
    rows.sort(key=lambda row: order.get(str(row["id"]), 9999))
    return rows


def get_articles_by_urls(conn, *, urls: list[str]) -> list[dict[str, Any]]:
    if not urls:
        return []

    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT id, title, summary, content, author, source_name, image_url,
                   published_at, category, url
            FROM public.articles
            WHERE url = ANY(%s)
            """,
            (urls,),
        )
        rows = cur.fetchall()

    order = {url: index for index, url in enumerate(urls)}
    rows.sort(key=lambda row: order.get(str(row.get("url")), 9999))
    return rows


def upsert_external_articles(
    conn,
    *,
    articles: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    cleaned = [article for article in articles if article.get("url")]
    if not cleaned:
        return []

    with conn.cursor() as cur:
        for article in cleaned:
            cur.execute(
                """
                INSERT INTO public.articles (
                    url, title, summary, author, source_name, image_url, published_at, category, ingested_at
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, now())
                ON CONFLICT (url) DO UPDATE SET
                    title = COALESCE(NULLIF(EXCLUDED.title, ''), public.articles.title),
                    summary = COALESCE(public.articles.summary, EXCLUDED.summary),
                    author = COALESCE(public.articles.author, EXCLUDED.author),
                    source_name = COALESCE(public.articles.source_name, EXCLUDED.source_name),
                    image_url = COALESCE(public.articles.image_url, EXCLUDED.image_url),
                    published_at = COALESCE(public.articles.published_at, EXCLUDED.published_at),
                    category = COALESCE(public.articles.category, EXCLUDED.category),
                    ingested_at = now()
                """,
                (
                    article.get("url"),
                    article.get("title") or "Untitled",
                    article.get("summary"),
                    article.get("author"),
                    article.get("source_name") or article.get("source"),
                    article.get("image_url"),
                    article.get("published_at"),
                    article.get("category"),
                ),
            )

    return get_articles_by_urls(
        conn,
        urls=[str(article["url"]) for article in cleaned],
    )


def touch_thread(conn, *, thread_id: str, preview: str | None = None) -> None:
    with conn.cursor() as cur:
        cur.execute(
            """
            UPDATE public.chat_threads
            SET updated_at = now(),
                last_message_preview = COALESCE(%s, last_message_preview)
            WHERE id = %s
            """,
            (_truncate_preview(preview), thread_id),
        )


def update_thread_title(conn, *, thread_id: str, title: str) -> None:
    with conn.cursor() as cur:
        cur.execute(
            """
            UPDATE public.chat_threads
            SET title = %s,
                updated_at = now()
            WHERE id = %s
            """,
            (title, thread_id),
        )


def _truncate_preview(preview: str | None) -> str | None:
    if not preview:
        return preview
    collapsed = " ".join(preview.split())
    return collapsed[:220]
