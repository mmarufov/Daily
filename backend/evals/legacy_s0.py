"""Frozen S0 baseline protocol, NOT S4 or a production delivery implementation.

The committed baseline/cache used persona-specific event discovery and uncapped
forced delivery. Those defects are intentionally reproduced only by the explicit
proto-s0-legacy-v1 runner. Current proto defaults remain canonical and bounded.
Never migrate responses from this protocol into new request hashes.

Boundary copied from b667985ddc4a1e7b4a871ba33ef7c28ccbeb880d.
Other pipeline components remain shared so their regressions stay observable.
"""
from __future__ import annotations
from typing import Any
from .pipeline import (
    BM25Backend, Candidate, Rubric, _near_dupe, compile_rubric, final_score,
    judge, recall, salience_candidates, triage, triage_score,
)

PROTOCOL = "s0-prototype-persona-global-v1"
SOURCE_COMMIT = "b667985ddc4a1e7b4a871ba33ef7c28ccbeb880d"


def assemble(cands: list[Candidate], rubric: Rubric, size: int = 20,
             max_per_intent: int | None = None,
             min_score: float = 0.7,
             forced: list[Candidate] | None = None) -> list[Candidate]:
    """Dedupe, then fill by intent so no single interest eats the feed.

    Round-robins across intents in weight order, which guarantees a person with
    three unrelated interests sees all three above the fold.

    `min_score` is the important part: a quota is a CEILING, never an obligation.
    Measured on the eval corpus, candidates scoring >=1.0 are almost all on
    target and those under ~0.7 are almost all noise, so filling an underfed
    intent's remaining slots actively makes the feed worse. A short honest feed
    beats a padded one.
    """
    judged_run = any(c.article.get("_judged") for c in cands)
    if judged_run:
        # The model has ruled. Anything it rejected is out regardless of how
        # strongly it was retrieved — that rejection is the whole point.
        ranked = [c for c in sorted(cands, key=lambda c: -final_score(c))
                  if final_score(c) >= 0.0]
    else:
        ranked = [c for c in sorted(cands, key=lambda c: -triage_score(c))
                  if triage_score(c) >= min_score]

    deduped: list[Candidate] = []
    for c in ranked:
        if not any(_near_dupe(c.article, d.article) for d in deduped):
            deduped.append(c)

    if max_per_intent is None:
        max_per_intent = max(2, size // max(len(rubric.intents), 1) + 2)

    buckets: dict[str, list[Candidate]] = {}
    for c in deduped:
        if c.matched_labels:
            buckets.setdefault(c.matched_labels[0], []).append(c)

    order = [i.label for i in sorted(rubric.intents, key=lambda x: -x.weight)]
    out: list[Candidate] = []
    used: set[int] = set()
    for _ in range(max_per_intent):
        for label in order:
            if len(out) >= size:
                break
            for c in buckets.get(label, []):
                if c.doc_idx not in used:
                    out.append(c)
                    used.add(c.doc_idx)
                    break
        if len(out) >= size:
            break

    for c in deduped:                      # top up by score if quotas underfill
        if len(out) >= size:
            break
        if c.doc_idx not in used:
            out.append(c)
            used.add(c.doc_idx)
    out = out[:size]

    # Forced items go to the top, displacing the weakest picks if need be.
    if forced:
        keep = [c for c in out if c.doc_idx not in {f.doc_idx for f in forced}]
        out = forced + keep[:max(0, size - len(forced))]
    return out


def run_pipeline(persona: dict, docs: list[dict], backend: BM25Backend,
                 llm_call=None, feed_size: int = 20,
                 with_salience: bool = True,
                 events: list[dict] | None = None,
                 home: set[str] | None = None,
                 emb=None) -> dict[str, Any]:
    rubric = compile_rubric(persona)
    recalled = recall(rubric, backend, docs)

    # World-critical events bypass everything. If states are exchanging fire,
    # no reader's topic preferences justify hiding it from them — and the
    # per-user judge does not get a vote, because "not about New Jersey" is a
    # correct judgement that produces the wrong feed.
    forced: list[Candidate] = []
    if events:
        from evals.global_events import pick_for_reader
        have = {c.doc_idx for c in recalled}
        for e in events:
            if e.get("tier") == "world_critical":
                idx = pick_for_reader(e, docs, home or set(), emb=emb)
                c = next((x for x in recalled if x.doc_idx == idx), None)
                if c is None:
                    c = Candidate(idx, docs[idx])
                    recalled.append(c)
                c.intent_hits["world event"] = 2.0
                c.intent_kinds["world event"] = "world_critical"
                c.article["_forced"] = e.get("what") or "Major world event"
                forced.append(c)
            elif e.get("tier") == "major":
                idx = pick_for_reader(e, docs, home or set(), emb=emb)
                if idx not in have:
                    c = Candidate(idx, docs[idx])
                    c.intent_hits["major story"] = 0.85
                    c.intent_kinds["major story"] = "salience"
                    recalled.append(c)

    if with_salience:
        # Merge the "big story" leg in. Anything already retrieved by profile
        # keeps its stronger intent match; the rest enter as salience-only and
        # the judge decides whether this reader should see them.
        have = {c.doc_idx for c in recalled}
        for c in salience_candidates(docs, rubric):
            if c.doc_idx in have:
                existing = next(x for x in recalled if x.doc_idx == c.doc_idx)
                existing.intent_hits.setdefault("major story", c.intent_hits["major story"])
                existing.intent_kinds.setdefault("major story", "salience")
            else:
                recalled.append(c)

    triaged = triage(recalled)
    # Guarantee forced items survive the triage cut.
    for c in forced:
        if c not in triaged:
            triaged.insert(0, c)
    judged = judge(rubric, triaged, llm_call)
    feed = assemble(judged, rubric, size=feed_size, forced=forced)
    return {
        "rubric": rubric,
        "pool": len(docs),
        "recalled": len(recalled),
        "triaged": len(triaged),
        "feed": feed,
        # Stage membership, so an evaluator can say where a story was lost.
        "recalled_cands": recalled,
        "triaged_cands": triaged,
        "judged_cands": judged,
    }



