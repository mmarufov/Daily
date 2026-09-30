"""Prove each feed-quality metric can fail: inject a known fault, replay offline, re-score.

A metric that never moves is not evidence. Each fault below breaks one behaviour
on purpose and declares, before any measured run, which metrics must respond,
in which direction, and by how much. The matrix then replays every fault from
the committed LLM cache and checks the declarations.

Every fault acts DOWNSTREAM of the model call (on the verdicts, the ranked
feed, or the labels), so each request hashes to the same cache key as the clean
run. That is what keeps the whole matrix offline at $0, and it is checked, not
assumed: every fault run must touch exactly the clean run's cache keys and
raise zero offline cache misses.

Registration rules (fixed at registration, not after):
  * threshold: 0.05 for every target, the regression gate's own TOLERANCE
    (`tests/test_eval_gate.py`). A fault "is detected" iff it moves the metric
    further than the gate already tolerates.
  * statistic: the pooled mean over every persona-snapshot pair (10 personas x
    3 snapshots) where the metric is defined in both the clean and the faulted
    run, faulted minus clean. Pairs where either value is undefined are
    excluded and counted.
  * `unchanged` metrics must be identical on every pair; they are the checks
    that a fault acts only where it claims to.
  * `blind` faults predict the opposite: no metric moves by the threshold or
    more. A blind fault that passes is a named gap in the harness.
  * Sign counts and a one-sided exact sign test are reported, not asserted.

Prior exposure, stated because it matters: a scratch prototype run on
2026-09-30, before this registry existed, had already measured the cells listed
in each fault's `seen_before_registration`. Targets for those cells were chosen
with those numbers in view. Cells not listed there are out of sample.
"""
from __future__ import annotations

THRESHOLD = 0.05          # == tests/test_eval_gate.py TOLERANCE, fixed before any run

SNAPSHOTS = ("2026-08-31", "2026-08-31-quiet", "2026-09-02")

# Every per-persona metric the matrix measures. Higher is better except the
# two rates of junk in the feed.
METRICS = ("recall_at_k", "recall_at_retrieval", "need_to_know_recall", "followup_recall",
           "never_rate", "event_delivery", "needle_recall", "lookalike_rate",
           "judge_precision", "judge_recall")

PROD, PROTO = "prod", "proto-s0-legacy-v1"
_SEEN_ALL_PROD = [(PROD, s) for s in SNAPSHOTS]

REGISTRY: dict[str, dict] = {
    "rotate_verdicts": {
        "runner": PROD,
        "what": "Replays the list-position bug: each batch's verdict bodies shift one slot, so "
                "every article is judged by its neighbour's verdict. Any article id stays in place.",
        "targets": {"recall_at_k": "down", "never_rate": "up", "needle_recall": "down",
                    "judge_precision": "down", "judge_recall": "down"},
        "unchanged": ["recall_at_retrieval"],
        "seen_before_registration": _SEEN_ALL_PROD,
    },
    "reverse_feed": {
        "runner": PROD,
        "what": "Reverses the final ranked feed, so the worst-ranked articles fill the top 12.",
        "targets": {"recall_at_k": "down", "needle_recall": "down"},
        "unchanged": ["recall_at_retrieval", "judge_precision", "judge_recall"],
        "seen_before_registration": [(PROD, "2026-08-31")],
    },
    "all_relevant": {
        "runner": PROD,
        "what": "The scorer marks every article relevant (score floored at 0.6).",
        "targets": {"judge_precision": "down", "never_rate": "up", "lookalike_rate": "up"},
        "unchanged": ["recall_at_retrieval"],
        "seen_before_registration": [(PROD, "2026-08-31")],
    },
    "swap_labels": {
        "runner": PROD,
        "what": "Grades persona i against persona i+1's labels: the ground truth is wrong, the feed is not.",
        "targets": {"recall_at_k": "down", "need_to_know_recall": "down", "followup_recall": "down",
                    "needle_recall": "down", "judge_precision": "down", "judge_recall": "down"},
        "unchanged": [],
        "seen_before_registration": [(PROD, "2026-08-31")],
    },
    "no_diversity": {
        "runner": PROD,
        "what": "Skips the diversity stage (_enforce_diversity returns its input).",
        "blind": True,
        "targets": {},
        "unchanged": ["recall_at_retrieval", "judge_precision", "judge_recall"],
        "seen_before_registration": [(PROD, "2026-08-31")],
    },
    "reverse_top_k": {
        "runner": PROD,
        "what": "Reverses the order inside the top 12 only. Every metric is a set over the top 12, "
                "so this is predicted invisible by construction.",
        "blind": True,
        "targets": {},
        "unchanged": list(METRICS),
        "seen_before_registration": [],
    },
    "proto_rotate_bodies": {
        "runner": PROTO,
        "what": "Prototype judge: verdict bodies shift one slot while each echoed id stays put, "
                "which defeats the id-keyed join.",
        "targets": {"recall_at_k": "down", "never_rate": "up", "needle_recall": "down",
                    "need_to_know_recall": "down", "judge_precision": "down", "judge_recall": "down"},
        "unchanged": ["recall_at_retrieval"],
        "seen_before_registration": [(PROTO, "2026-08-31")],
    },
    "proto_rotate_list": {
        "runner": PROTO,
        "what": "Prototype judge: the whole verdict list rotates, ids travelling with their bodies. "
                "The id-keyed join should make this a no-op.",
        "blind": True,
        "targets": {},
        "unchanged": list(METRICS),
        "seen_before_registration": [(PROTO, "2026-08-31")],
    },
    "proto_no_forced": {
        "runner": PROTO,
        "what": "Prototype assembly ignores forced world-critical event slots.",
        "targets": {"event_delivery": "down"},
        "unchanged": ["recall_at_retrieval"],
        "seen_before_registration": [(PROTO, "2026-08-31")],
    },
}

# Not a matrix fault: an UPSTREAM change on purpose. It removes planted needles
# before scoring, which changes every scorer request, so the cache misses. The
# production scorer swallows the miss and falls back to keyword scoring. The
# gate must now fail it on raised offline misses.
GATE_CONTROL = {
    "name": "drop_plants_prefilter",
    "runner": PROD,
    "snapshot": "2026-08-31",
    "expect": "offline_misses_total > 0, so the gate's offline check fails",
    "seen_before_registration": [(PROD, "2026-08-31")],
}
