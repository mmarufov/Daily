"""World-critical event detection.

Two different things get conflated under "big news", and treating them the same
is why a war can go missing from a feed:

  BREADTH  — many outlets ran it. Measurable, cheap, and *wrong on its own*: a
             telescope launch covered by six tech blogs scores higher than a war
             whose coverage is worded differently at every outlet.
  GRAVITY  — an informed adult anywhere would need to know today. Not derivable
             from counting. It needs a model.

So: cluster semantically (title tokens cannot group "US strikes Larak Island"
with "Battle for Hormuz"), measure breadth across outlets/verticals/regions to
shortlist, then spend ONE model call classifying gravity. That call is global,
not per user — every reader shares the same answer, so its cost amortises to
nothing.

A `world_critical` event is then injected into every feed with a guaranteed
slot. The per-user judge does not get to reject it; that is the whole point.
"""
from __future__ import annotations

import json
from collections import Counter

import numpy as np

# Where each outlet is based. Used to prefer a reader's own press for the same
# story — a Dushanbe trader should hear about a regional trade shock from
# Asia-Plus before the Guardian.
SOURCE_REGION = {
    "Asia-Plus TJ": "central-asia", "Astana Times": "central-asia",
    "Times of Cent.Asia": "central-asia", "Eurasianet": "central-asia",
    "bne IntelliNews": "central-asia", "The Diplomat": "asia",
    "Moscow Times": "russia", "Meduza EN": "russia",
    "Straits Times": "singapore", "CNA Singapore": "singapore",
    "e27": "singapore", "Business Times SG": "singapore",
    "NJ.com": "us-nj", "NJ Spotlight": "us-nj", "Gothamist": "us-nj",
    "NJ Monitor": "us-nj",
    "NPR": "us", "NPR World": "us", "Guardian US": "us", "CNBC": "us",
    "Fortune": "us", "MarketWatch": "us", "ESPN": "us", "ESPN NHL": "us",
    "ESPN NFL": "us", "CBS Sports NHL": "us", "Yahoo Sports NHL": "us",
    "BBC": "uk", "BBC World": "uk", "Guardian World": "uk",
    "Guardian Business": "uk", "The Register": "uk",
    "Al Jazeera": "mena", "DW": "europe",
}

# Which press a reader counts as "home", by profile location.
LOCATION_REGION = {
    "tajikistan": "central-asia", "dushanbe": "central-asia",
    "kazakhstan": "central-asia", "uzbekistan": "central-asia",
    "central asia": "central-asia", "russia": "russia",
    "singapore": "singapore", "southeast asia": "singapore",
    "new jersey": "us-nj", "newark": "us-nj", "essex county": "us-nj",
    "united states": "us", "china": "asia",
}


def home_regions(persona: dict) -> set[str]:
    locs = persona["user_profile_v2"].get("locations") or []
    out = {LOCATION_REGION[l.strip().lower()] for l in locs
           if l.strip().lower() in LOCATION_REGION}
    # A local paper implies the national press is also home ground.
    if "us-nj" in out:
        out.add("us")
    return out


# ---------------------------------------------------------------------------
# Semantic clustering
# ---------------------------------------------------------------------------

def semantic_clusters(emb: np.ndarray, threshold: float = 0.62) -> list[list[int]]:
    """Greedy centroid clustering over L2-normalised embeddings.

    Deliberately simple: one pass, first-match-wins. Story clusters are tight
    and small, so the usual failure of greedy clustering (drifting centroids on
    large diffuse groups) does not bite here.
    """
    centroids: list[np.ndarray] = []
    members: list[list[int]] = []
    for i in range(emb.shape[0]):
        v = emb[i]
        if centroids:
            sims = np.asarray([c @ v for c in centroids])
            j = int(np.argmax(sims))
            if sims[j] >= threshold:
                members[j].append(i)
                m = len(members[j])
                c = centroids[j] * ((m - 1) / m) + v / m
                centroids[j] = c / (np.linalg.norm(c) + 1e-9)
                continue
        centroids.append(v.copy())
        members.append([i])
    return members


def score_breadth(docs: list[dict], idxs: list[int]) -> dict:
    srcs = {docs[i]["source"] for i in idxs}
    verts = {docs[i]["feed_vertical"] for i in idxs}
    regions = {SOURCE_REGION.get(docs[i]["source"], "other") for i in idxs}
    return {
        "n": len(idxs),
        "sources": len(srcs),
        "verticals": len(verts),
        "regions": len(regions),
        # Cross-vertical and cross-region spread separate a genuinely global
        # story from one vertical's obsession. Six tech blogs on a telescope
        # score 1 vertical; a war shows up in world, business AND local press.
        "spread": len(srcs) + 2 * len(verts) + 2 * len(regions),
        "source_names": sorted(srcs),
        "vertical_names": sorted(verts),
    }


# ---------------------------------------------------------------------------
# Gravity classification — one global call
# ---------------------------------------------------------------------------

GRAVITY_SYSTEM = """You triage news events by how universally important they are.

For each numbered event you get a representative headline and how widely it is
being covered. Assign exactly one tier:

- "world_critical": an informed adult ANYWHERE should know this today. Armed
  conflict between states, attacks, mass-casualty disasters, a government
  falling, a major economy or market breaking, a pandemic, a rupture in
  relations between major powers. If a reader would be embarrassed not to know
  it, it is world_critical.
- "major": genuinely significant but bounded to a region, industry or interest.
  A big product launch, a national election in a mid-size country, a notable
  scientific result.
- "routine": everything else. Sports results, business as usual, features.

Be strict. In a normal news day zero to two events are world_critical. Treating
ordinary news as world_critical is worse than missing it, because it overrides
every reader's preferences.

Return JSON: {"events":[{"id":<int>,"tier":"world_critical|major|routine",
"what":"<max 10 words, what actually happened>"}]}
Echo every id exactly once."""


def classify_gravity(events: list[dict], llm_call, top_n: int = 24) -> dict[int, dict]:
    """Classify the widest-spread events. One call, shared by every user."""
    if type(top_n) is not int or top_n < 1 or top_n > 100:
        raise ValueError("Gravity shortlist must be a bounded positive integer")
    ranked = sorted(events, key=lambda e: -e["spread"])[:top_n]
    if not ranked or llm_call is None:
        return {}

    lines = []
    for e in ranked:
        lines.append(
            f'{e["id"]}. "{e["title"][:110]}"\n'
            f'   covered by {e["sources"]} outlets across {e["verticals"]} sections'
            f' / {e["regions"]} regions: {", ".join(e["source_names"][:6])}'
        )
    verdicts = llm_call(GRAVITY_SYSTEM, "EVENTS:\n" + "\n\n".join(lines))

    out: dict[int, dict] = {}
    valid = {e["id"] for e in ranked}
    if not isinstance(verdicts, list) or len(verdicts) > len(ranked):
        return {}
    duplicate_ids = {v["id"] for v in verdicts if isinstance(v, dict) and type(v.get("id")) is int
                     and sum(isinstance(other, dict) and type(other.get("id")) is int
                             and other["id"] == v["id"] for other in verdicts) > 1}
    for v in verdicts:
        if not isinstance(v, dict) or set(v) != {"id", "tier", "what"}:
            continue
        vid = v.get("id")
        if type(vid) is int and vid in valid and vid not in duplicate_ids:
            tier = v.get("tier")
            what = v.get("what")
            if (isinstance(tier, str) and tier in {"world_critical", "major", "routine"}
                    and isinstance(what, str) and what.strip() and len(what) <= 500):
                out[vid] = {"tier": tier, "what": what}
    return out


def detect_events(docs: list[dict], emb: np.ndarray, llm_call,
                  threshold: float = 0.62, min_sources: int = 2) -> list[dict]:
    """Full pass: cluster -> measure breadth -> classify gravity."""
    clusters = semantic_clusters(emb, threshold)
    events: list[dict] = []
    for cid, idxs in enumerate(clusters):
        b = score_breadth(docs, idxs)
        if b["sources"] < min_sources:
            continue
        # Representative = the copy with the most substance behind it.
        rep = max(idxs, key=lambda i: len(docs[i].get("summary") or ""))
        events.append({"id": len(events), "members": idxs, "rep": rep,
                       "title": docs[rep]["title"], **b})

    gravity = classify_gravity(events, llm_call)
    for e in events:
        g = gravity.get(e["id"])
        e["tier"] = g["tier"] if g else "unknown"
        e["assessment_status"] = "ready" if g else "unassessed"
        e["what"] = g["what"] if g else ""
    return events


def pick_for_reader(event: dict, docs: list[dict], regions: set[str],
                    emb=None, centrality_floor: float | None = None) -> int:
    """Choose which copy of a story a given reader sees.

    Home press is preferred — a Tajik reader should hear it from Asia-Plus, a
    Singaporean from the Straits Times. But only among copies that are actually
    about the event. Without the centrality check this picks a side-angle: a
    US reader was handed "Oil rises 1% after US forces strike Iranian rockets"
    instead of "US strikes Iranian launchers in the strait of Hormuz". Same
    cluster, wrong story.
    """
    # How much directness we are willing to trade for a familiar masthead.
    # For a world-critical event the reader needs the clearest account of what
    # happened, so home press must be essentially as on-event as the best copy
    # available. For a regional story, local framing is itself worth something.
    if centrality_floor is None:
        centrality_floor = 0.95 if event.get("tier") == "world_critical" else 0.82

    if not regions:
        return event["rep"]

    local = [i for i in event["members"]
             if SOURCE_REGION.get(docs[i]["source"]) in regions]
    if not local:
        return event["rep"]

    if emb is not None:
        centroid = emb[event["members"]].mean(axis=0)
        centroid = centroid / ((centroid @ centroid) ** 0.5 + 1e-9)
        rep_sim = float(emb[event["rep"]] @ centroid)
        scored = sorted(local, key=lambda i: -float(emb[i] @ centroid))
        best = scored[0]
        # Only swap to home press if that copy is nearly as on-event as the
        # best available one. Otherwise the reader gets a familiar masthead
        # attached to the wrong angle.
        if float(emb[best] @ centroid) >= centrality_floor * rep_sim:
            return best
        return event["rep"]

    return max(local, key=lambda i: len(docs[i].get("summary") or ""))
