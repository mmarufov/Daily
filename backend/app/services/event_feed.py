"""Final, uncached S4 feed composition over existing S2-public ordinary rows.

The request integration owns database authorization, current account policy and
client capability. This module does no database/model/network work, and stores
neither priority nor invented delivered/seen acknowledgments in the legacy cache.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Callable, Mapping, Sequence

from app.services.article_content import serialize_article
from app.services.event_consumers import ReaderPolicy, select_event_candidates


@dataclass
class FeedResult:
    payload: dict
    # Raw eligible scoped major candidates: caller may pass these to the existing
    # S7 scoring path. They are never serialized or forced into the feed here.
    major_candidates: list[dict]
    decisions: list[dict]


def apply_event_feed(
    ordinary_result: Mapping[str, Any], candidates: Sequence[Mapping[str, Any]], policy: ReaderPolicy,
    *, now: datetime | str, limit: int, hard_allowed: Callable[[Mapping[str, Any]], bool],
) -> FeedResult:
    """Compose fresh priority without trusting cached priority or model policy.

    ``ordinary_result.articles`` must already have passed the existing public S2
    serializer and current account-policy checks. ``hard_allowed`` applies the
    application's current deterministic exclusions/hides/authorization to each
    RAW event representative; returning anything except True fails closed. It
    must not impose the user-linked-source recall limitation or soft-topic rank.
    Exceptions from that policy lookup reject the representative, not ordinary
    news. Repository reads and cache publication fences remain caller-owned.
    """
    if not isinstance(ordinary_result, Mapping) or not isinstance(ordinary_result.get("articles"), list):
        raise ValueError("existing public feed envelope required")
    if not callable(hard_allowed):
        raise ValueError("explicit current hard-policy check required")
    # Validate caller bounds/time before evaluating any representative callback.
    select_event_candidates([], [], policy, now=now, limit=limit)
    if len(candidates) > 256 or len(ordinary_result["articles"]) > 10000:
        raise ValueError("selection input exceeds bounded retrieval contract")
    admitted = []
    if policy.delivery_enabled is True and policy.client_supports_event_expiry is True:
        for candidate in candidates:
            if not isinstance(candidate, Mapping):
                admitted.append(candidate)
                continue
            copied = dict(candidate)
            representatives = candidate.get("representatives")
            if not isinstance(representatives, (list, tuple)) or len(representatives) > 128:
                copied["representatives"] = []
                admitted.append(copied)
                continue
            checked = []
            for representative in representatives:
                if not isinstance(representative, Mapping):
                    continue
                item = dict(representative)
                article = item.get("article")
                allowed = False
                if isinstance(article, Mapping) and item.get("eligible") is True:
                    try:
                        # A direct but inaccessible/unavailable item cannot fill
                        # a reserved slot. Source-web is an eligible S2 route.
                        allowed = hard_allowed(article) is True and serialize_article(
                            article, include_body=False)["presentation"]["mode"] != "unavailable"
                    except Exception:
                        allowed = False
                item["eligible"] = allowed
                checked.append(item)
            copied["representatives"] = checked
            admitted.append(copied)
    else:
        admitted = list(candidates)
    selected = select_event_candidates(ordinary_result["articles"], admitted, policy, now=now, limit=limit)
    public = []
    for item in selected.items:
        metadata = item.get("event_delivery")
        if metadata is not None:
            # Only selector-produced priority reaches here. No dictionary merge
            # with the private evidence-bearing article is permitted.
            row = serialize_article(item, include_body=False)
            row.update(event_delivery=dict(metadata), relevant=True,
                       relevance_reason="Current evidence-backed critical development",
                       feed_role="world_critical")
        else:
            row = dict(item)
            row.pop("event_delivery", None)
            row.pop("s4_development_id", None)
        public.append(row)
    payload = dict(ordinary_result)
    payload["articles"] = public
    if public:
        payload["status"] = "ready"
    if "article_count" in payload:
        payload["article_count"] = len(public)
    # Do not turn a source-pool quality failure into a passing quality gate just
    # because one independent event arrived. Discovery can continue separately.
    return FeedResult(payload=payload, major_candidates=selected.major_candidates, decisions=selected.decisions)
