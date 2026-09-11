"""S10 Tier 0: the one reward definition, shared by the legacy and S5 learning
loops. Pure function, no DB/network access -- see tasks/s10-learning-audit.md
section 6 and tasks/s10-implementation-plan.md batch C.

Before this module existed, `feedback_signals.py` (legacy) and
`reader_feedback.py` (S5) each hard-coded their own copy of the same delta
table. Both had the same six numeric values; nothing enforced that they stay
the same, and neither had anywhere to express an implicit (not explicitly
tapped) signal. This module is the single place those numbers live now, and
the only place new implicit terms are added.

Deliberately excluded, per the product instruction this system is built to
satisfy ("optimize usefulness and reader satisfaction -- not addictive
engagement or clicks alone"): raw dwell seconds are never a reward term, an
impression *count* is never a positive term (only ever a discount), and there
is no click-through-rate concept anywhere in this module. Every term is
either an explicit reader action or a qualified/bounded implicit one.
"""
from __future__ import annotations

import math

from .reader_contract import canonical_hash

# Versioned so a future change to the formula is distinguishable, in stored
# `reward_recipe_hash` values, from a change in what readers actually did.
# Bump the version string whenever a constant or the shape of `reward()`
# changes; never silently reinterpret old stored deltas under a new formula.
REWARD_RECIPE = {"version": "s10-reward-v1"}


def reward_recipe_hash() -> str:
    return canonical_hash(REWARD_RECIPE)


# Per-explicit-action base delta. Negative feedback bites harder than
# positive reward, because a reader who bothers to reject something is
# giving a much stronger signal than one who taps a heart.
DELTAS = {
    "not_relevant": -0.30,
    "less_like_this": -0.15,
    "more_like_this": 0.20,
    "important": 0.15,
}

# How much each kind of attribution counts when an explicit delta is spread
# across the recorded reasons an article was shown (legacy path only; the S5
# path spreads evenly across confirmed intents instead -- see
# reader_feedback.py). The matched interest is the reason the article was
# selected at all, so it carries the most; a publisher is weaker evidence; a
# category is weakest.
KIND_FACTORS = {"topic": 1.0, "source": 0.6, "category": 0.35}

# Per-signal accumulation limits (the stored, decayed weight itself).
WEIGHT_FLOOR, WEIGHT_CEILING = -1.0, 0.8

# Total per-event/per-article adjustment, also asymmetric: negative feedback
# may sink a score outright, positive feedback may only promote it. Applies
# both to a single event's reward() output and to a summed per-article score
# adjustment (feedback_signals.feedback_adjustment) -- one bound, one
# invariant: no single interaction or signal combination can move a score by
# more than this in either direction.
ADJUSTMENT_FLOOR, ADJUSTMENT_CEILING = -0.50, 0.25

# Signals fade. 30-day half-life, matching both loops.
HALF_LIFE_DAYS = 30.0

# Small implicit terms -- deliberately much smaller than any explicit DELTAS
# value, so an implicit signal can nudge but never outweigh an explicit one
# (S10 audit invariant 1: explicit beats learned, always).
QUALIFIED_READ_BONUS = 0.05
QUICK_BACK_PENALTY = 0.05

# Repeated-impression discount (Lee et al. 2014 KDD, "impression discounting"
# -- a bounded counter, not a model). The first few impressions of a topic a
# reader hasn't engaged with are not evidence of anything; only sustained
# non-engagement is. Capped well below ADJUSTMENT_FLOOR's magnitude so this
# alone can never drive a score to the floor.
IMPRESSION_DISCOUNT_THRESHOLD = 3
IMPRESSION_DISCOUNT_PER_STEP = 0.02
IMPRESSION_DISCOUNT_CAP = 0.15


def impression_discount(repeated_impressions: int) -> float:
    """Monotonic, bounded discount for a topic shown repeatedly with no
    engagement. 0 for the first IMPRESSION_DISCOUNT_THRESHOLD impressions;
    grows by IMPRESSION_DISCOUNT_PER_STEP per impression after that, capped
    at IMPRESSION_DISCOUNT_CAP. Never negative regardless of input."""
    n = max(0, int(repeated_impressions))
    if n <= IMPRESSION_DISCOUNT_THRESHOLD:
        return 0.0
    steps = n - IMPRESSION_DISCOUNT_THRESHOLD
    return min(IMPRESSION_DISCOUNT_CAP, steps * IMPRESSION_DISCOUNT_PER_STEP)


def reward(action: str | None, *, qualified_read: bool = False,
           quick_back: bool = False, repeated_impressions: int = 0) -> float:
    """Deterministic, versioned event-level reward. Never a function of raw
    dwell seconds, an open/impression count taken as a positive, or a
    click-through rate -- only an explicit action and qualified/bounded
    implicit terms. Bounded to [ADJUSTMENT_FLOOR, ADJUSTMENT_CEILING].

    `qualified_read` must already reflect length-normalized dwell AND a
    verified native-body content-hash match (see feed_service/assembly
    integration) -- this function trusts its caller's qualification, it does
    not compute it.
    """
    delta = DELTAS.get(action, 0.0)
    if qualified_read:
        delta += QUALIFIED_READ_BONUS
    if quick_back:
        delta -= QUICK_BACK_PENALTY
    delta -= impression_discount(repeated_impressions)
    if not math.isfinite(delta):
        return 0.0
    return max(ADJUSTMENT_FLOOR, min(ADJUSTMENT_CEILING, delta))
