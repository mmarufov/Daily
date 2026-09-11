"""Consumer rollout is explicit and never mixes stale result cohorts."""
import asyncio
from copy import deepcopy
from types import SimpleNamespace

import pytest

from app.services import understanding_consumers as consumers
from app.services.understanding_contract import DEFAULT_RECIPE


def recipe(identifier="recipe-test"):
    return {"id": identifier, "definition": deepcopy(DEFAULT_RECIPE)}


class Connection:
    def __init__(self, rows=(), recipes=None):
        self.rows = list(rows)
        self.recipes = list(recipes) if recipes is not None else [recipe()]
        self.calls = []

    def execute(self, sql, args=None):
        self.calls.append((sql, args))
        if "SELECT r.*" in sql:
            item = self.recipes.pop(0) if len(self.recipes) > 1 else self.recipes[0]
            return SimpleNamespace(fetchone=lambda: item)
        return SimpleNamespace(fetchall=lambda: deepcopy(self.rows))


def article(identifier, **changes):
    return {"id": identifier, "understanding_input_hash": "hash-current",
            "understanding_revision": 2, "understanding_eligibility_generation": 3, **changes}


def current(**changes):
    return {"embedding": [1], "input_hash": "hash-current", "semantic_revision": 2,
            "analysis_eligibility_generation": 3, **changes}


def test_consumer_flag_defaults_off_and_requires_true(monkeypatch):
    monkeypatch.delenv("S3_CONSUMERS_ENABLED", raising=False)
    assert consumers.enabled() is False
    for value in ("", "1", "yes", "false"):
        monkeypatch.setenv("S3_CONSUMERS_ENABLED", value)
        assert consumers.enabled() is False
    monkeypatch.setenv("S3_CONSUMERS_ENABLED", "TRUE")
    assert consumers.enabled() is True


def test_serving_recipe_requires_approval_and_compatible_space():
    with pytest.raises(RuntimeError, match="approved serving recipe"):
        consumers.serving_recipe(Connection(recipes=[None]))
    assert consumers.serving_recipe(Connection())["id"] == "recipe-test"
    for field in ("embedding_model", "dimensions", "query_recipe", "schema_hash", "input_version"):
        mismatch = recipe()
        mismatch["definition"][field] = "incompatible"
        with pytest.raises(RuntimeError, match="incompatible"):
            consumers.serving_recipe(Connection(recipes=[mismatch]))


@pytest.mark.parametrize("failure", [False, True])
def test_query_provider_always_closes(monkeypatch, failure):
    instances = []

    class Provider:
        def __init__(self, key):
            assert key == "test-placeholder"
            self.closed = False
            instances.append(self)

        async def query_embedding(self, query, definition):
            assert query == "science"
            assert definition == DEFAULT_RECIPE
            if failure:
                raise TimeoutError("synthetic")
            return SimpleNamespace(payload={"vector": [1, 2]})

        async def aclose(self):
            self.closed = True

    monkeypatch.setenv("OPENAI_API_KEY", "test-placeholder")
    monkeypatch.setattr("app.services.understanding_provider.OpenAIUnderstandingProvider", Provider)
    if failure:
        with pytest.raises(TimeoutError):
            asyncio.run(consumers.query_vector(Connection(), "science"))
    else:
        assert asyncio.run(consumers.query_vector(Connection(), "science")) == [1, 2]
    assert len(instances) == 1 and instances[0].closed


def test_semantic_rows_exclude_stale_results_and_clamp_query_bounds(monkeypatch):
    rows = [article(str(index)) for index in range(6)]
    states = {
        "0": {}, "1": current(input_hash="old"), "2": current(semantic_revision=1),
        "3": current(analysis_eligibility_generation=2), "4": current(), "5": current(),
    }
    monkeypatch.setattr(consumers, "load_current", lambda conn, identifier, rid: states[identifier])
    conn = Connection(rows)
    vector = [1.0] + [0.0] * 1535
    result = consumers.semantic_rows(conn, vector, limit=1, lookback_hours=99999)
    assert [row["id"] for row in result] == ["4"]
    query_args = next(args for sql, args in conn.calls if "SELECT a.*" in sql)
    assert query_args[1] == "recipe-test" and query_args[2] == 336 and query_args[-1] == 5


def test_private_content_requires_exact_evidence_hash(monkeypatch):
    monkeypatch.setattr(consumers, "load_current", lambda *args: current())
    monkeypatch.setattr(consumers, "evidence_for_article", lambda conn, identifier:
        {"input_hash": "hash-current" if identifier == "good" else "old",
         "fields": {"body": "Original body", "summary": "Original summary"}})
    conn = Connection([article("old"), article("good", content="legacy unverifiable")])
    result = consumers.semantic_rows(conn, [1.0] + [0.0] * 1535, private=True)
    assert len(result) == 1
    assert result[0]["id"] == "good"
    assert result[0]["content"] == "Original body"
    assert result[0]["summary"] == "Original summary"


def test_promotion_midquery_discards_entire_previous_cohort(monkeypatch):
    monkeypatch.setattr(consumers, "load_current", lambda *args: current())
    conn = Connection([article("good")], recipes=[recipe("old"), recipe("new")])
    assert consumers.semantic_rows(conn, [1.0] + [0.0] * 1535) == []


def test_invalid_vector_never_reaches_similarity_query():
    conn = Connection()
    with pytest.raises(ValueError):
        consumers.semantic_rows(conn, [float("nan")])
    assert all("SELECT a.*" not in sql for sql, args in conn.calls)
