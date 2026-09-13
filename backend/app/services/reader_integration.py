"""S5 serving boundary. No provider calls, timestamp-only caches or hidden policy fallback.

The initial serving implementation deliberately rebuilds its bounded candidate slice instead
of maintaining another cache. Revision locking at delivery is still required: request work
can race edits even without a cache. S2 presentation authorization remains independent.
"""
from __future__ import annotations

import os
import re
import uuid
from contextlib import nullcontext
from datetime import datetime, timezone
from urllib.parse import urlparse


def enabled():
    return os.getenv("S5_READER_ENABLED", "false").lower() == "true"


def snapshot_for(conn, user_id):
    if not enabled():
        return None
    from .reader_repository import load_reader
    return load_reader(conn, user_id)


def stamp(snapshot):
    return tuple(snapshot[k] for k in ("generation", "revision", "learning_revision"))


def is_current(conn, user_id, snapshot):
    from .reader_repository import load_reader
    current = load_reader(conn, user_id, create=False)
    return current is not None and stamp(current) == stamp(snapshot)


def _active(item, now):
    expiry = item.get("expires_at")
    if not expiry:
        return True
    if isinstance(expiry, str):
        expiry = datetime.fromisoformat(expiry.replace("Z", "+00:00"))
    if expiry.tzinfo is None:
        return False
    return expiry > now


def host(value):
    try:
        return (urlparse(value if "://" in value else "https://" + value).hostname or "").lower().removeprefix("www.")
    except (TypeError, ValueError):
        return ""


def phrase_in(phrase, text):
    """Unicode word boundaries, retaining punctuation-bearing subjects such as C++."""
    phrase = " ".join(phrase.casefold().split())
    return bool(phrase and re.search(r"(?<!\w)" + re.escape(phrase) + r"(?!\w)",
                                    " ".join(text.casefold().split())))


def allowed(profile, article, *, now=None):
    """Conservative recommendation rules; unknown canonical subject evidence is withheld.

    This function must not decide whether a directly requested article may be read.
    Publisher blocks are exact normalized hosts (including www alias), not fuzzy names.
    """
    from .reader_compiler import policy_allows
    return article.get("analysis_revoked") is not True and policy_allows(profile, article, now=now)


def filter_articles(snapshot, articles):
    return [a for a in articles if allowed(snapshot["profile"], {**a, **a.get("_reader_policy_evidence", {})})]


def publication_context(conn, user_id, snapshot):
    if snapshot is None:
        return nullcontext()
    from .reader_repository import publication_guard
    return publication_guard(conn, user_id, snapshot)


def finalize_feed(conn, user_id, result):
    """Reauthorize after optional S4 composition; never label old work as the new reader."""
    from .ranking_service import enabled as ranking_enabled
    if ranking_enabled():
        # S7 publishes and receipts the final edition atomically. Never apply
        # legacy composition/receipt attribution to an unchecked old result.
        if result.get("ranking_recipe"):
            return result
        return {"status": "needs_build", "articles": [], "article_count": 0}
    if not enabled() or result.get("status") != "ready":
        return result
    from .reader_repository import load_reader, publication_guard, ReaderConflict
    from .reader_feedback import record_delivery
    snapshot = load_reader(conn, user_id)
    if (result.get("reader_generation"), result.get("reader_revision")) != (snapshot["generation"], snapshot["revision"]):
        raise ReaderConflict("reader_changed", snapshot)
    with publication_guard(conn, user_id, snapshot):
        articles = filter_articles(snapshot, result.get("articles", []))
        request_id = result.get("feed_request_id") or str(uuid.uuid4())
        record_delivery(conn, user_id, request_id, snapshot, articles)
        # `delivery_position` has to be stamped here, on the same enumeration of
        # the same post-filter list `record_delivery` just wrote as
        # `final_position`. Without it the card is incomplete and the client's
        # `NewsArticle.deliveryReceipt` stays nil (it requires all four of
        # feed_request_id / delivery_position / reader_generation /
        # reader_revision), so every tap, read and "already knew" on this path
        # arrived with feed_request_id: null -- unattributable, and unable to
        # match S4's `ON r.feed_request_id = d.feed_request_id` suppression join.
        # S7's `_public` has always done exactly this; the legacy S5 path never did.
        public = [{**{k: v for k, v in a.items() if not k.startswith("_reader_")},
                   "feed_request_id": request_id, "reader_generation": snapshot["generation"],
                   "reader_revision": snapshot["revision"],
                   "delivery_position": a.get("delivery_position", position)}
                  for position, a in enumerate(articles)]
        return {**result, "articles": public, "article_count": len(public), "feed_request_id": request_id}


def serve_feed(conn, user_id, *, limit=50):
    from .ranking_service import enabled as ranking_enabled, cached_feed
    if ranking_enabled():
        return cached_feed(conn, user_id, limit=limit, ordinary_only=True)
    from .reader_repository import load_reader, publication_guard
    from .reader_retrieval import build_reader_candidates
    from .article_content import serialize_article
    from .reader_feedback import adjust_candidates, record_delivery

    snapshot = load_reader(conn, user_id)
    if snapshot.get("migration_status") == "needs_review":
        return {"status": "needs_reader_review", "articles": [], "reader": snapshot,
                "article_count": 0, "quality_met": False}
    candidates = build_reader_candidates(conn, user_id, snapshot, limit=300)
    candidates = filter_articles(snapshot, candidates)
    candidates = adjust_candidates(conn, user_id, snapshot, candidates)
    # Preserve the retriever's interleaving. A global re-sort would undo minority coverage.
    selected = candidates[:limit]
    request_id = str(uuid.uuid4())
    with publication_guard(conn, user_id, snapshot):
        selected = filter_articles(snapshot, selected)
        record_delivery(conn, user_id, request_id, snapshot, selected)
        articles = []
        labels = {i["id"]: i["label"] for i in snapshot["profile"]["intents"]}
        for candidate in selected:
            item = serialize_article(candidate, include_body=False)
            reasons = [labels[i] for i in candidate.get("_reader_intent_ids", []) if i in labels]
            item.update(relevant=True, relevance_score=candidate.get("_reader_score", 0.5),
                        relevance_reason="Matches your interests" if reasons else "General news",
                        matched_profile_signals=reasons, reader_generation=snapshot["generation"],
                        reader_revision=snapshot["revision"], feed_request_id=request_id)
            item["_reader_policy_evidence"] = {k: candidate[k] for k in
                ("language", "content_language", "canonical_source_domain", "canonical_source_id", "source_id",
                 "topic_ids", "entity_ids", "place_ids", "sector_ids") if k in candidate}
            item["_reader_intent_ids"] = candidate.get("_reader_intent_ids", [])
            articles.append(item)
    return {"status": "ready", "articles": articles, "article_count": len(articles),
            "feed_request_id": request_id, "reader_generation": snapshot["generation"],
            "reader_revision": snapshot["revision"], "quality_met": False,
            "personalization_status": "experimental" if os.getenv("S5_SEMANTIC_ENABLED") == "true" else "lexical",
            "coverage": {"returned": len(articles), "quality_evaluated": False}}


def propose(profile, text, *, operation_id):
    """Supported explicit commands only, always reviewed before mutation; no paid guessing."""
    if not isinstance(text, str) or not 1 <= len(text.strip()) <= 1000:
        raise ValueError("Enter a tuning instruction of 1–1000 characters")
    match = re.fullmatch(r"\s*(more(?:\s+of)?|less(?:\s+of)?|follow|stop following)\s+(.+?)\s*", text, re.I)
    if not match:
        raise ValueError("Use ‘More <topic>’, ‘Less <topic>’, ‘Follow <topic>’ or ‘Stop following <topic>’. Review complex changes in Settings.")
    command, label = match[1].lower(), match[2].strip()
    # Do not turn mixed commands/negation into a broad invented interest.
    if len(label) > 280 or re.search(r"[,;\n]|\b(?:but|except|not|and|or)\b", label, re.I):
        raise ValueError("Change one specific interest at a time, or use Settings for qualified interests")
    intents = [dict(i) for i in profile["intents"]]
    existing = next((i for i in intents if i["label"].casefold() == label.casefold()), None)
    if command.startswith("less") or command == "stop following":
        if existing is None:
            raise ValueError("That interest is not followed. ‘Less’ does not create a permanent exclusion; use Settings to add an explicit rule.")
        if command == "stop following":
            intents.remove(existing)
        else:
            existing["priority"] = max(0.1, existing["priority"] - 0.25)
    elif existing:
        existing["priority"] = min(3.0, existing["priority"] + 0.25)
    else:
        intents.append({"id": str(uuid.uuid5(uuid.UUID(str(operation_id)), label)), "kind": "topic",
                        "label": label, "query": label, "priority": 1.0,
                        "qualifiers": [], "provenance": "reviewed_proposal"})
    return {"patch": {"intents": intents}, "summary": f"{command.capitalize()} {label}",
            "requires_confirmation": True}
