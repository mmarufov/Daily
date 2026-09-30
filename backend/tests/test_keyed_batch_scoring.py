"""The production batch scorer, held to the contract the Lab graded.

`OpenAIService.score_articles_batch` used to join verdicts to articles by list
position. It now sends each article's id, parses the response with
`lab/contract/versions/keyed_v2.py`, and refuses a batch whose ids are
duplicated, missing or extra, or whose completion was truncated.

Three kinds of test live here:

  * The 64 Lab cases replayed through the production scorer itself, not the
    Lab's copy of a parser: the recorded response is what the stubbed client
    returns, and the grade is what `score_articles_batch` hands back.
  * A pin that the module production imports is byte for byte the file the
    Lab graded, so "the graded contract is the production contract" is a
    checked fact rather than a claim.
  * Unit tests for the retry, refusal and id-join paths, including
    feed_service's join, which used to flatten batches by position too.

Every block has a control that swaps in the old positional behaviour and
expects the same assertions to fail.
"""
import asyncio
import contextlib
import hashlib
import json
import os
import sys
import types
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
os.environ.setdefault("OPENAI_API_KEY", "test-key-not-used")

from app.services import openai_service as osvc  # noqa: E402
from app.services.openai_service import OpenAIService  # noqa: E402
from lab.contract.versions import keyed_v2, positional_v0  # noqa: E402

BACKEND = Path(__file__).resolve().parent.parent
REPO = BACKEND.parent
CASES = [
    case
    for group in ("observed", "synthetic")
    for case in json.loads((BACKEND / "lab" / "cases" / f"{group}.json").read_text())["cases"]
]
UNSCORED = "scoring unavailable"


def _completion(content, finish_reason="stop"):
    message = types.SimpleNamespace(content=content)
    choice = types.SimpleNamespace(message=message, finish_reason=finish_reason)
    return types.SimpleNamespace(choices=[choice])


class _StubClient:
    """Returns `behaviour(call_number)` from chat.completions.create."""

    def __init__(self, behaviour):
        self.calls = 0
        self.kwargs = []

        def create(**kwargs):
            self.calls += 1
            self.kwargs.append(kwargs)
            return behaviour(self.calls)

        self.chat = types.SimpleNamespace(completions=types.SimpleNamespace(create=create))


def _score(service, articles):
    async def _no_sleep(_seconds):
        return None

    with patch("app.services.openai_service.asyncio.sleep", _no_sleep):
        return asyncio.run(service.score_articles_batch(articles, "A reader."))


def _service(behaviour):
    with patch.object(osvc, "OpenAI", lambda **kw: None):
        service = OpenAIService()
    service.client = _StubClient(behaviour)
    return service


def _replay(case):
    """What the recorded response looks like from the SDK's side."""
    response = case["response"]
    if response.get("error"):
        # A provider that timed out, was cancelled or had no answer raises;
        # it never returns a completion.
        def behaviour(_n):
            raise RuntimeError(f"provider error: {response['error']}")
    else:
        def behaviour(_n):
            return _completion(response.get("content"), response.get("finish_reason"))
    return behaviour


def _applicable(case):
    return case["family"] == "universal-refusal" or case["protocol"] == "keyed-v2"


def _grade(case, verdicts):
    """True when production did what the case expects.

    refuse: nothing from the response was applied; every article came back
            unscored.
    parse:  every article got exactly its expected verdict, matched by id.
    """
    articles = case["articles"]
    if [v.get("article_id") for v in verdicts] != [a["id"] for a in articles]:
        return False
    if case["expectation"]["expect"] == "refuse":
        return all(v["reason"] == UNSCORED and v["score"] == 0.0 for v in verdicts)
    expected = case["expectation"]["association"]
    return all(
        v["relevant"] is expected[v["article_id"]]["relevant"]
        and abs(v["score"] - expected[v["article_id"]]["score"]) < 1e-9
        for v in verdicts
    )


def _grade_all(service_for):
    scored = [c for c in CASES if _applicable(c)]
    correct = sum(_grade(c, _score(service_for(c), c["articles"])) for c in scored)
    return correct, len(scored)


@contextlib.contextmanager
def _positional_parser():
    """The old join: verdict i belongs to article i, whatever the model sent."""
    def parse(articles, response):
        result = positional_v0.parse(articles, response)
        if result.get("ok"):
            result = {**result, "verdicts": [
                {**v, "article_id": a["id"]} for a, v in zip(articles, result["verdicts"])
            ]}
        return result

    with patch.object(osvc, "keyed_v2", types.SimpleNamespace(parse=parse)):
        yield


class LabCasesThroughProductionTests(unittest.TestCase):
    def test_all_64_cases_are_replayed(self):
        self.assertEqual(len(CASES), 64)
        self.assertEqual(sum(_applicable(c) for c in CASES), 60)

    def test_production_scorer_is_correct_on_every_applicable_case(self):
        with self.assertLogs("app.services.openai_service", level="WARNING"):
            correct, scored = _grade_all(lambda c: _service(_replay(c)))
        self.assertEqual((correct, scored), (60, 60))

    def test_control_the_positional_join_fails_the_same_grading(self):
        with _positional_parser(), self.assertLogs("app.services.openai_service", level="WARNING"):
            correct, scored = _grade_all(lambda c: _service(_replay(c)))
        self.assertEqual(scored, 60)
        self.assertLess(correct, 60)


class GradedBytesAreShippedBytesTests(unittest.TestCase):
    def test_production_imports_the_file_the_lab_graded(self):
        artifact = json.loads((REPO / "web" / "public" / "lab-artifacts" / "keyed-v2-clean.json").read_text())
        self.assertEqual(artifact["verdict"], "accepted-for-review")
        graded = artifact["candidate"]["source_sha256"]
        shipped = hashlib.sha256(Path(osvc.keyed_v2.__file__).read_bytes()).hexdigest()
        self.assertEqual(shipped, graded)
        self.assertIs(osvc.keyed_v2, keyed_v2)

    def test_control_a_one_byte_change_would_not_match(self):
        source = Path(keyed_v2.__file__).read_bytes()
        graded = json.loads(
            (REPO / "web" / "public" / "lab-artifacts" / "keyed-v2-clean.json").read_text()
        )["candidate"]["source_sha256"]
        self.assertNotEqual(hashlib.sha256(source + b" ").hexdigest(), graded)

    def test_the_image_ships_the_contract(self):
        dockerfile = (BACKEND / "Dockerfile").read_text()
        self.assertIn("lab/contract/versions/keyed_v2.py", dockerfile)


ARTICLES = [
    {"id": "a-weather", "title": "Tornado warnings issued in N.J.", "source": "NJ.com"},
    {"id": "a-giants", "title": "Giants' 53-man roster to include Odell Beckham", "source": "NJ.com"},
    {"id": "a-music", "title": "Indie band announces surprise music EP", "source": "Pitchfork"},
]


def _entry(article_id, score, reason):
    return {"article_id": article_id, "relevant": score >= 0.5, "score": score, "reason": reason}


GOOD = [
    _entry("a-weather", 0.9, "Local severe weather."),
    _entry("a-giants", 0.2, "Sports roster news."),
    _entry("a-music", 0.05, "Music, excluded."),
]


def _json(results):
    return _completion(json.dumps({"results": results}))


class KeyedScorerTests(unittest.TestCase):
    def test_request_carries_every_id_and_an_output_cap(self):
        service = _service(lambda _n: _json(GOOD))
        _score(service, ARTICLES)
        kwargs = service.client.kwargs[0]
        prompt = kwargs["messages"][1]["content"]
        for article in ARTICLES:
            self.assertIn(f"article_id: {article['id']}", prompt)
        self.assertEqual(kwargs["max_tokens"], osvc.BATCH_SCORING_MAX_OUTPUT_TOKENS)

    def test_reordered_response_is_applied_by_id(self):
        service = _service(lambda _n: _json(list(reversed(GOOD))))
        scored = _score(service, ARTICLES)
        self.assertEqual(
            [(v["article_id"], v["reason"]) for v in scored],
            [("a-weather", "Local severe weather."), ("a-giants", "Sports roster news."),
             ("a-music", "Music, excluded.")],
        )

    def test_missing_id_is_refused_then_retried(self):
        responses = {1: _json(GOOD[:1] + GOOD[2:]), 2: _json(GOOD)}
        service = _service(lambda n: responses[n])
        with self.assertLogs("app.services.openai_service", level="WARNING") as logs:
            scored = _score(service, ARTICLES)
        self.assertEqual(service.client.calls, 2)
        self.assertIn("missing_id", "\n".join(logs.output))
        self.assertEqual(scored[1]["reason"], "Sports roster news.")

    def test_duplicate_extra_and_truncated_responses_are_never_applied(self):
        bad = {
            "duplicate_id": _json(GOOD + [GOOD[0]]),
            "unknown_id": _json(GOOD + [_entry("a-invented", 0.9, "Not in the request.")]),
            "truncated_response": _completion(json.dumps({"results": GOOD}), finish_reason="length"),
        }
        for kind, response in bad.items():
            with self.subTest(kind=kind):
                service = _service(lambda _n, r=response: r)
                with self.assertLogs("app.services.openai_service", level="WARNING") as logs:
                    scored = _score(service, ARTICLES)
                self.assertEqual(service.client.calls, 3)
                self.assertIn(kind, "\n".join(logs.output))
                self.assertEqual([v["reason"] for v in scored], [UNSCORED] * 3)
                self.assertEqual([v["article_id"] for v in scored], [a["id"] for a in ARTICLES])

    def test_control_the_positional_join_applies_a_short_response(self):
        # The case above, under the old join: the music verdict lands on the
        # Giants article. This is the bug, and the reason the test exists.
        service = _service(lambda _n: _json(GOOD[:1] + GOOD[2:]))
        with _positional_parser():
            scored = _score(service, ARTICLES)
        self.assertNotEqual(scored[1]["reason"], UNSCORED)

    def test_harness_stop_signals_propagate(self):
        for name in ("CacheMiss", "BudgetExceeded"):
            with self.subTest(name=name):
                signal = type(name, (RuntimeError,), {})

                def behaviour(_n, signal=signal):
                    raise signal("stop")

                with self.assertRaises(signal):
                    _score(_service(behaviour), ARTICLES)

    def test_duplicate_ids_in_the_request_are_not_sent(self):
        service = _service(lambda _n: _json(GOOD))
        with self.assertLogs("app.services.openai_service", level="WARNING"):
            scored = _score(service, [ARTICLES[0], ARTICLES[0]])
        self.assertEqual(service.client.calls, 0)
        self.assertEqual([v["reason"] for v in scored], [UNSCORED] * 2)


class FeedJoinTests(unittest.IsolatedAsyncioTestCase):
    """feed_service used to flatten per-batch lists by position as well."""

    async def _feed(self, verdicts_for):
        from unittest.mock import AsyncMock

        from app.services import feed_service

        matching = {
            "id": "11111111-1111-1111-1111-111111111111", "title": "OpenAI launches enterprise agents",
            "summary": "A major AI product launch aimed at software teams.", "content": "",
            "source": "OpenAI", "image_url": None, "url": "https://example.com/openai-agents",
            "published_at": "2026-03-23T10:00:00+00:00", "category": "ai",
        }
        off_topic = {
            "id": "22222222-2222-2222-2222-222222222222", "title": "Spring recipes for home cooks",
            "summary": "A food roundup for the weekend.", "content": "",
            "source": "Bon Appetit", "image_url": None, "url": "https://example.com/food",
            "published_at": "2026-03-23T09:00:00+00:00", "category": "general",
        }
        fake = AsyncMock()
        fake.score_articles_batch.return_value = verdicts_for(matching, off_topic)
        with patch.object(feed_service, "_load_user_preferences",
                          return_value=("Show me OpenAI and AI product news.", {"topics": ["OpenAI", "AI"]}, None)), \
             patch.object(feed_service, "_load_cached_feed", return_value=None), \
             patch.object(feed_service, "_load_candidates_for_profile",
                          new=AsyncMock(return_value=[matching, off_topic])), \
             patch.object(feed_service, "_save_feed_cache"), \
             patch.object(feed_service, "get_openai_service", return_value=fake):
            return await feed_service.get_personalized_feed("33333333-3333-3333-3333-333333333333", conn=None, limit=10)

    async def test_verdicts_in_any_order_land_on_their_own_article(self):
        # Reversed: position 0 now holds the off-topic verdict. A positional
        # join would give the AI launch the recipe's rejection.
        articles = await self._feed(lambda m, o: [
            {"article_id": o["id"], "relevant": False, "score": 0.03, "reason": "Recipes, not AI."},
            {"article_id": m["id"], "relevant": True, "score": 0.92, "reason": "AI product launch."},
        ])
        self.assertEqual(articles[0]["title"], "OpenAI launches enterprise agents")
        self.assertEqual(articles[0]["relevance_reason"], "AI product launch.")
        self.assertNotIn("Recipes, not AI.", [a.get("relevance_reason") for a in articles])

    async def test_a_verdict_for_no_candidate_is_dropped_and_its_article_left_unscored(self):
        articles = await self._feed(lambda m, o: [
            {"article_id": "not-a-candidate", "relevant": True, "score": 0.99, "reason": "Stray."},
            {"article_id": o["id"], "relevant": False, "score": 0.03, "reason": "Recipes, not AI."},
        ])
        self.assertNotIn("Stray.", [a.get("relevance_reason") for a in articles])
