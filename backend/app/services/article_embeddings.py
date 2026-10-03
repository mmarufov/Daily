"""The ingestion loop's embedding step: vectors for articles whose analysis
text has no current embedding.

Newest first, so after an outage the articles readers are most likely to see
are embedded before the old backlog. The write is fenced on
`analysis_content_version`, so a slow response cannot attach a vector to a
newer body.
"""
from __future__ import annotations

import asyncio
import logging

logger = logging.getLogger(__name__)

PENDING_SQL = """
    SELECT id, title, summary, analysis_text, analysis_content_version
    FROM public.articles
    WHERE analysis_text IS NOT NULL
      AND (embedding IS NULL OR embedding_content_version
           IS DISTINCT FROM analysis_content_version)
    ORDER BY ingested_at DESC
    LIMIT %s
"""

WRITE_SQL = """
    UPDATE public.articles
    SET embedding = %s::vector,
        embedding_content_version = %s
    WHERE id = %s
      AND analysis_content_version = %s
"""


def embedding_text(row: dict) -> str:
    return f"{row['title']}. {row.get('summary') or ''}. {(row.get('analysis_text') or '')[:2000]}"


async def embed_pending(conn, openai_svc, *, limit: int = 50, concurrency: int = 6) -> dict:
    """Embed up to `limit` pending articles; return attempted and written counts."""
    with conn.cursor() as cur:
        cur.execute(PENDING_SQL, (limit,))
        pending = cur.fetchall()
    if not pending:
        return {"attempted": 0, "written": 0}

    semaphore = asyncio.Semaphore(concurrency)

    async def embed_one(row):
        async with semaphore:
            try:
                return row, await openai_svc.generate_embedding(embedding_text(row))
            except Exception:
                logger.exception("Embedding generation failed for article %s", row.get("id"))
                return row, None

    results = await asyncio.gather(*[embed_one(row) for row in pending])
    written = 0
    for row, embedding in results:
        if not embedding:
            continue
        with conn.cursor() as cur:
            cur.execute(WRITE_SQL, (str(embedding), row["analysis_content_version"],
                                    row["id"], row["analysis_content_version"]))
            written += max(cur.rowcount, 0)
    return {"attempted": len(pending), "written": written}
