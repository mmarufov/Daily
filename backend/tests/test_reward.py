"""S10 C: the shared reward function. See tasks/s10-learning-audit.md section 6
and tasks/s10-implementation-plan.md batch C.

Locks down: reward() is pure and bounded; no term is ever a function of raw
dwell seconds or a bare impression/open count (the product instruction this
system exists to satisfy -- "not addictive engagement or clicks alone"); the
legacy and S5 loops compute an identical number for the same input, so they
can no longer silently drift; reward_recipe_hash is deterministic and changes
only when the recipe changes.
"""
import inspect
import math

from app.services import feedback_signals, reward


class TestPureFunction:
    def test_same_input_same_output_no_side_effects(self):
        a = reward.reward("not_relevant", qualified_read=True, quick_back=False, repeated_impressions=5)
        b = reward.reward("not_relevant", qualified_read=True, quick_back=False, repeated_impressions=5)
        assert a == b

    def test_unknown_action_with_no_implicit_terms_is_neutral(self):
        assert reward.reward("not-a-real-action") == 0.0
        assert reward.reward(None) == 0.0

    def test_never_a_function_of_raw_duration_or_impression_count_as_a_positive(self):
        """Static check: no reward component multiplies by a raw duration or
        treats a bare impression/open count as a positive term."""
        source = inspect.getsource(reward)
        assert "duration_seconds" not in source
        assert "* duration" not in source
        # impression_discount is the ONLY place a count appears, and it is
        # always subtracted (a discount), never added.
        assert source.count("repeated_impressions") >= 1
        assert "+ impression_discount" not in source
        assert "+= impression_discount" not in source


class TestSignAndBounds:
    def test_explicit_deltas_have_the_documented_signs(self):
        assert reward.reward("not_relevant") < 0
        assert reward.reward("less_like_this") < 0
        assert reward.reward("more_like_this") > 0
        assert reward.reward("important") > 0

    def test_negative_outweighs_positive(self):
        assert abs(reward.DELTAS["not_relevant"]) > reward.DELTAS["more_like_this"]

    def test_qualified_read_bonus_is_positive_and_small(self):
        base = reward.reward(None)
        boosted = reward.reward(None, qualified_read=True)
        assert boosted > base
        assert boosted - base == reward.QUALIFIED_READ_BONUS
        # Smaller than any explicit action -- implicit signals nudge, never
        # outweigh an explicit one (S10 audit invariant 1).
        assert reward.QUALIFIED_READ_BONUS < min(abs(v) for v in reward.DELTAS.values())

    def test_quick_back_penalty_is_negative_and_small(self):
        base = reward.reward(None)
        penalized = reward.reward(None, quick_back=True)
        assert penalized < base
        assert base - penalized == reward.QUICK_BACK_PENALTY
        assert reward.QUICK_BACK_PENALTY < min(abs(v) for v in reward.DELTAS.values())

    def test_output_is_always_within_adjustment_bounds(self):
        for action in [*reward.DELTAS, "already_knew", "hide_source", None, "junk"]:
            for qr in (True, False):
                for qb in (True, False):
                    for n in (0, 3, 4, 50, 10_000):
                        value = reward.reward(action, qualified_read=qr, quick_back=qb,
                                               repeated_impressions=n)
                        assert reward.ADJUSTMENT_FLOOR <= value <= reward.ADJUSTMENT_CEILING
                        assert math.isfinite(value)


class TestImpressionDiscount:
    def test_zero_below_threshold(self):
        for n in range(0, reward.IMPRESSION_DISCOUNT_THRESHOLD + 1):
            assert reward.impression_discount(n) == 0.0

    def test_grows_monotonically_then_caps(self):
        values = [reward.impression_discount(n) for n in range(0, 200)]
        assert values == sorted(values)  # monotonic non-decreasing
        assert values[-1] == reward.IMPRESSION_DISCOUNT_CAP

    def test_never_negative_even_for_bad_input(self):
        assert reward.impression_discount(-5) == 0.0

    def test_capped_below_adjustment_floor_magnitude(self):
        """The discount alone can never drive a score to the floor."""
        assert reward.IMPRESSION_DISCOUNT_CAP < abs(reward.ADJUSTMENT_FLOOR)


class TestLegacyAndS5Parity:
    """The bug this whole batch exists to prevent: two copies of the same
    numbers that could silently diverge. Now there is exactly one."""

    def test_feedback_signals_reexports_the_same_objects(self):
        assert feedback_signals.FEEDBACK_DELTAS is reward.DELTAS
        assert feedback_signals.KIND_FACTORS is reward.KIND_FACTORS
        assert feedback_signals.WEIGHT_FLOOR == reward.WEIGHT_FLOOR
        assert feedback_signals.WEIGHT_CEILING == reward.WEIGHT_CEILING
        assert feedback_signals.ADJUSTMENT_FLOOR == reward.ADJUSTMENT_FLOOR
        assert feedback_signals.ADJUSTMENT_CEILING == reward.ADJUSTMENT_CEILING
        assert feedback_signals.HALF_LIFE_DAYS == reward.HALF_LIFE_DAYS

    def test_reader_feedback_module_uses_the_same_deltas(self):
        from app.services import reader_feedback
        assert reader_feedback.DELTAS is reward.DELTAS

    def test_every_shared_action_yields_the_same_base_reward(self):
        for action in reward.DELTAS:
            assert reward.reward(action) == reward.DELTAS[action]


class TestRecipeVersioning:
    def test_deterministic(self):
        assert reward.reward_recipe_hash() == reward.reward_recipe_hash()

    def test_looks_like_a_hash(self):
        h = reward.reward_recipe_hash()
        assert isinstance(h, str) and len(h) == 64
        assert all(c in "0123456789abcdef" for c in h)

    def test_changes_when_the_recipe_changes(self, monkeypatch):
        before = reward.reward_recipe_hash()
        monkeypatch.setitem(reward.REWARD_RECIPE, "version", "s10-reward-v2-test-only")
        after = reward.reward_recipe_hash()
        assert before != after

    def test_stable_across_an_ordinary_call_with_the_same_recipe(self):
        """A plain decay-and-accumulate update (no recipe change) must not
        appear to change the recipe hash."""
        first = reward.reward_recipe_hash()
        reward.reward("not_relevant")
        second = reward.reward_recipe_hash()
        assert first == second
