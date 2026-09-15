"""Deterministic source delta. No provider calls and no source-graph replacement."""
import json
from urllib.parse import quote

from .reader_compiler import compile_reader
from .reader_repository import publication_guard
from .reader_worker import intent_query


def query_sources(profile):
    # Explicit queries only. Biography/context never leaves through RSS search.
    return [{"url": "https://news.google.com/rss/search?q=" + quote(intent_query(i), safe="") +
             "&hl=en-US&gl=US&ceid=US:en", "name": i["label"] + " News Search", "intent_id": i["id"]}
            for i in compile_reader(profile)["intents"]]


def reconcile_reader_sources(conn, user_id, snapshot):
    if snapshot["migration_status"] != "ready":
        return {"sources_found": 0, "exact_sources": 0, "supporting_sources": 0,
                "sources": [], "status": "needs_reader_review"}
    desired = query_sources(snapshot["profile"])
    urls = [s["url"] for s in desired]
    with publication_guard(conn, user_id, snapshot):
        # Only retire associations owned by this reconciler. Manual/legacy inactive
        # sources may encode a hide or fetch failure; never guess or reactivate them.
        conn.execute("""UPDATE public.user_sources SET active=false,discovery_method='reader_retired' WHERE user_id=%s
          AND discovery_method='reader_query' AND NOT(source_url=ANY(%s::text[]))""", (user_id, urls))
        for index, source in enumerate(desired):
            conn.execute("""INSERT INTO public.user_sources(user_id,source_url,source_name,
              discovery_method,source_kind,scope,matched_targets,selection_rank,selection_reason,active)
              VALUES(%s,%s,%s,'reader_query','aggregator_query','exact',%s::jsonb,%s,
                'Explicit reader interest; publisher policies are enforced on articles',true)
              ON CONFLICT(user_id,source_url) DO UPDATE SET
                active=CASE WHEN user_sources.discovery_method='reader_retired' THEN true ELSE user_sources.active END,
                discovery_method=CASE WHEN user_sources.discovery_method='reader_retired' THEN 'reader_query' ELSE user_sources.discovery_method END,
                matched_targets=CASE WHEN user_sources.discovery_method='reader_query'
                  THEN EXCLUDED.matched_targets ELSE user_sources.matched_targets END,
                selection_rank=CASE WHEN user_sources.discovery_method='reader_query'
                  THEN EXCLUDED.selection_rank ELSE user_sources.selection_rank END""",
              (user_id, source["url"], source["name"], json.dumps([source["intent_id"]]), index))
        conn.execute("""UPDATE public.reader_jobs SET state='completed',updated_at=now()
          WHERE user_id=%s AND kind='source_reconcile' AND generation=%s AND revision<=%s""",
          (user_id, snapshot["generation"], snapshot["revision"]))
        # Intent snapshots, not these hint rows, are the embedding worker's durable input.
        conn.execute("DELETE FROM public.reader_jobs WHERE user_id=%s AND (state='completed' OR kind='embeddings')", (user_id,))
    return {"sources_found": len(desired), "exact_sources": len(desired), "supporting_sources": 0,
            "sources": [{"source_url": s["url"], "source_name": s["name"],
                         "scope": "exact", "matched_targets": [s["intent_id"]]} for s in desired],
            "profile_specificity": "mixed", "discovery_time_seconds": 0,
            "status": "ready", "validated": False}
