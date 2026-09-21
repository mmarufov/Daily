"""Regression tests for the production batch scorer's output alignment.

Background. `OpenAIService.score_articles_batch` numbers the articles in its
prompt and asks for a JSON array "one entry per article, same order". No
article id is sent and the model is never asked to echo an index back, so the
response carries nothing that identifies which article a verdict belongs to.

The parse used to be purely positional, and a count mismatch was logged and
then ignored: the code fell through to `for i in range(len(articles))` and
assigned `results_list[i]` to `articles[i]` regardless. One missing or merged
entry therefore shifted every later verdict onto the wrong article.

That is visible in the committed scorecards. In
`backend/evals/results/47edb50-prod-llm-2026-08-31.json`, persona `ray` has a
Giants roster headline dropped with the reason "The article discusses a music
EP", while persona `dilshod` has an Uzbekistan decree headline dropped for
"discusses NFL team rosters" -- a clean offset, not noise.

Misattributed relevance is worse than absent relevance. Absent scoring surfaces
downstream as a fallback reason; a shifted verdict silently drops a story the
reader needed and files a rationale about a different one.

The prototype pipeline never had this problem: `backend/evals/pipeline.py`
requires each verdict to echo its `id` and drops unmatched verdicts rather than
trusting position. `backend/app/services/ranking_provider.py` (S7) does the same
with a strict JSON schema and an explicit output cap, but it is gated behind
`S7_PROVIDER_ENABLED` and is not what the live feed path calls.
"""
import asyncio
import json
import os
import sys
import types
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

os.environ.setdefault("OPENAI_API_KEY", "test-key-not-used")

from app.services.openai_service import OpenAIService  # noqa: E402


def _response(payload: dict) -> types.SimpleNamespace:
    """Mimic the shape the OpenAI SDK returns for a chat completion."""
    message = types.SimpleNamespace(content=json.dumps(payload))
    return types.SimpleNamespace(choices=[types.SimpleNamespace(message=message)])


class _StubCompletions:
    def __init__(self, behaviour):
        self._behaviour = behaviour
        self.calls = 0

    def create(self, **kwargs):
        self.calls += 1
        self._last_kwargs = kwargs
        return self._behaviour(self.calls)


class _StubClient:
    def __init__(self, behaviour):
        self.completions = _StubCompletions(behaviour)
        self.chat = types.SimpleNamespace(completions=self.completions)


class CacheMiss(RuntimeError):
    """Same name and base class as evals.llm_cache.CacheMiss."""


class BudgetExceeded(RuntimeError):
    """Same name and base class as evals.llm_cache.BudgetExceeded."""


ARTICLES = [
    {"title": "Tornado warnings issued in N.J. as strong thunderstorms lash region",
     "source": "NJ.com", "summary": "Severe weather across the state."},
    {"title": "Giants' 53-man roster to include Odell Beckham", "source": "NJ.com",
     "summary": "Roster moves ahead of the season."},
    {"title": "Indie band announces surprise music EP", "source": "Pitchfork",
     "summary": "A four-track release."},
]

PROFILE = "Reader in New Jersey who follows local news and transit. Not interested in music."


def _score(service, articles=ARTICLES):
    # The retry path sleeps 1s, 2s, 4s between attempts; no test needs to wait.
    async def _no_sleep(_seconds):
        return None

    with patch("app.services.openai_service.asyncio.sleep", _no_sleep):
        return asyncio.run(service.score_articles_batch(articles, PROFILE))


class BatchScoringAlignmentTests(unittest.TestCase):
    def setUp(self):
        self.service = OpenAIService()

    def test_short_response_is_discarded_rather_than_shifted(self):
        """A response with fewer entries than articles must not be applied.

        Without the alignment guard this returned the music-EP verdict attached
        to the Giants roster article -- exactly the misattribution visible in
        the committed scorecards -- plus a synthetic "scoring incomplete" tail.
        """
        payload = {
            "results": [
                {"relevant": True, "score": 0.9, "reason": "Local severe weather."},
                # The middle entry is missing, which is what shifts the rest.
                {"relevant": False, "score": 0.05, "reason": "The article discusses a music EP."},
            ]
        }
        self.service.client = _StubClient(lambda _n: _response(payload))

        scored = _score(self.service)

        self.assertEqual(len(scored), len(ARTICLES))
        reasons = [entry["reason"] for entry in scored]
        # The music-EP rationale must not be attached to any article, because
        # nothing in the response says which article it belongs to.
        self.assertNotIn(
            "The article discusses a music EP.",
            reasons,
            msg="a verdict from a short response was applied by position",
        )
        # And the batch must report itself unscored rather than partly guessed.
        self.assertEqual(reasons, ["scoring unavailable"] * len(ARTICLES))
        self.assertTrue(all(entry["score"] == 0.0 for entry in scored))
        self.assertTrue(all(entry["relevant"] is False for entry in scored))

    def test_short_response_is_retried_before_giving_up(self):
        """A transient mismatch should be retried, not immediately abandoned."""
        good = {
            "results": [
                {"relevant": True, "score": 0.9, "reason": "Local severe weather."},
                {"relevant": False, "score": 0.2, "reason": "Sports roster news."},
                {"relevant": False, "score": 0.05, "reason": "Music, excluded."},
            ]
        }
        short = {"results": [{"relevant": True, "score": 0.9, "reason": "Local severe weather."}]}

        def behaviour(call_number):
            return _response(short if call_number == 1 else good)

        self.service.client = _StubClient(behaviour)

        scored = _score(self.service)

        self.assertEqual(self.service.client.completions.calls, 2)
        self.assertEqual(
            [entry["reason"] for entry in scored],
            ["Local severe weather.", "Sports roster news.", "Music, excluded."],
        )

    def test_long_response_is_also_discarded(self):
        """More entries than articles is the same ambiguity in the other direction."""
        payload = {
            "results": [
                {"relevant": True, "score": 0.9, "reason": "Local severe weather."},
                {"relevant": False, "score": 0.2, "reason": "Sports roster news."},
                {"relevant": False, "score": 0.05, "reason": "Music, excluded."},
                {"relevant": False, "score": 0.0, "reason": "An entry with no article."},
            ]
        }
        self.service.client = _StubClient(lambda _n: _response(payload))

        scored = _score(self.service)

        self.assertEqual(len(scored), len(ARTICLES))
        self.assertEqual([entry["reason"] for entry in scored], ["scoring unavailable"] * 3)

    def test_aligned_response_is_applied_in_order(self):
        """The ordinary path is unchanged: equal lengths are applied positionally."""
        payload = {
            "results": [
                {"relevant": True, "score": 0.95, "reason": "Local severe weather."},
                {"relevant": False, "score": 0.2, "reason": "Sports roster news."},
                {"relevant": False, "score": 0.05, "reason": "Music, excluded."},
            ]
        }
        self.service.client = _StubClient(lambda _n: _response(payload))

        scored = _score(self.service)

        self.assertEqual(self.service.client.completions.calls, 1)
        self.assertEqual(scored[0]["score"], 0.95)
        self.assertEqual(scored[1]["reason"], "Sports roster news.")
        self.assertEqual(scored[2]["relevant"], False)

    def test_scores_are_clamped_to_the_unit_interval(self):
        payload = {
            "results": [
                {"relevant": True, "score": 4.2, "reason": "Over."},
                {"relevant": False, "score": -1.0, "reason": "Under."},
                {"relevant": False, "score": 0.5, "reason": "Fine."},
            ]
        }
        self.service.client = _StubClient(lambda _n: _response(payload))

        scored = _score(self.service)

        self.assertEqual(scored[0]["score"], 1.0)
        self.assertEqual(scored[1]["score"], 0.0)


class OfflineReplayFailClosedTests(unittest.TestCase):
    """The evaluation harness's stop signals must not be swallowed.

    `ProductionRunner` injects the harness's caching client straight into this
    service, so a cache miss surfaces here as an exception. Both `CacheMiss` and
    `BudgetExceeded` subclass `RuntimeError`, and the blanket handler used to
    catch them -- retrying three times and then returning the all-zero fallback.
    An offline replay that should have failed closed instead produced a fully
    degraded run which still reported zero cache misses, because the harness
    only counts a miss on the live network path.
    """

    def setUp(self):
        self.service = OpenAIService()

    def test_cache_miss_propagates(self):
        def behaviour(_call_number):
            raise CacheMiss("no cached response for this request hash")

        self.service.client = _StubClient(behaviour)

        with self.assertRaises(CacheMiss):
            _score(self.service)

        # Raised on the first attempt: a missing cache entry is not transient.
        self.assertEqual(self.service.client.completions.calls, 1)

    def test_budget_exceeded_propagates(self):
        def behaviour(_call_number):
            raise BudgetExceeded("run budget exhausted")

        self.service.client = _StubClient(behaviour)

        with self.assertRaises(BudgetExceeded):
            _score(self.service)

    def test_ordinary_provider_errors_still_fall_back(self):
        """Transient provider failures keep their retry-then-fallback behaviour."""
        def behaviour(_call_number):
            raise RuntimeError("upstream 503")

        self.service.client = _StubClient(behaviour)

        scored = _score(self.service)

        self.assertEqual(self.service.client.completions.calls, 3)
        self.assertEqual([entry["reason"] for entry in scored], ["scoring unavailable"] * 3)


class RequestBytesUnchangedTests(unittest.TestCase):
    """The fix must not alter the request, or every committed cache entry misses.

    The regression gate replays responses keyed by a content hash of the request
    (`evals/llm_cache.cache_key`). Changing the prompt, model, temperature or
    response format would invalidate the whole committed `prod-llm` cache, which
    is the evidence base the gate runs against. The complete fix -- id-keyed
    output, as ranking_provider.py already does -- necessarily changes the
    prompt, which is why it is staged separately rather than bundled here.
    """

    def test_request_kwargs_are_the_expected_shape(self):
        service = OpenAIService()
        payload = {
            "results": [
                {"relevant": True, "score": 0.9, "reason": "a"},
                {"relevant": False, "score": 0.1, "reason": "b"},
                {"relevant": False, "score": 0.1, "reason": "c"},
            ]
        }
        service.client = _StubClient(lambda _n: _response(payload))

        _score(service)

        kwargs = service.client.completions._last_kwargs
        self.assertEqual(set(kwargs), {"model", "messages", "response_format", "temperature"})
        self.assertEqual(kwargs["response_format"], {"type": "json_object"})
        self.assertEqual(kwargs["temperature"], 0.2)
        self.assertEqual(len(kwargs["messages"]), 2)
        # No article id is sent, and no index echo is requested. This assertion
        # documents the remaining defect rather than asserting it is fixed.
        system = kwargs["messages"][0]["content"]
        self.assertIn("same order", system)
        self.assertNotIn("article_id", system)


if __name__ == "__main__":
    unittest.main()
