"""Quality evidence must not pass via abstention, leakage, or tiny samples."""
from copy import deepcopy
import asyncio
import json
from pathlib import Path

import pytest

from scripts.pilot_s3_understanding import run_pilot, select_articles

from evals.understanding import (
    ROOT, assign_story_splits, evaluate, prepare_review_queue, story_metrics,
)


def row(i, story=None, **changes):
    return {"article_id": str(i), "url": f"https://example.org/{i}",
            "review_status": "adjudicated", "label_provenance": "agent",
            "reviewed_by": "independent-editor", "story_id": story or str(i),
            "language": "en", "evidence_tier": "title_only", "split": "holdout",
            "labels": {"kind": "report", "primary_topic": "science", "entity_ids": ["entity:1"],
                       "place_ids": ["place:1"], "promotional": False}, **changes}


def manifest():
    return json.loads((ROOT / "acceptance.json").read_text())


def prediction(**changes):
    return {"kind": "report", "primary_topic": "science", "entity_ids": ["entity:1"],
            "place_ids": ["place:1"], "auto_suppressed": False, **changes}


def test_pilot_sample_is_distinct_reproducible_and_has_no_fabricated_body():
    sample = select_articles("2026-09-02")
    assert sample == select_articles("2026-09-02")
    assert len(sample) == len({row["metadata"]["url"] for row in sample}) == 20
    assert all(row["fields"]["body"] == "" and row["manifest"]["artifact"] is None for row in sample)
    assert all(row["entity_candidates"] == [] and row["place_candidates"] == [] for row in sample)
    with pytest.raises(ValueError):
        select_articles("2026-09-02", 21)


def test_pilot_replays_both_models_and_shared_embedding_without_rebilling(tmp_path):
    from app.services.understanding_provider import ProviderOutcome

    class Provider:
        calls = 0

        def prepare_request(self, bundle, recipe, stage):
            model = recipe["model"] if stage == "facets" else recipe["embedding_model"]
            return "/fake", {"model": model, "input": bundle["input_hash"], "stage": stage}, 0.001

        async def generate(self, bundle, recipe, stage):
            self.calls += 1
            return ProviderOutcome({"test_only": True}, 0.0001, "req-test")

    provider = Provider()
    options = dict(snapshot="2026-09-02", count=2, cache_dir=tmp_path / "cache",
                   output=tmp_path / "pilot.json", budget_usd=5, ledger_dir=tmp_path / "ledger")
    first = asyncio.run(run_pilot(provider, paid=True, **options))
    assert provider.calls == 6
    assert first["status"] == "completed"
    assert first["semantic_quality_validated"] is False
    second = asyncio.run(run_pilot(provider, paid=False, **options))
    assert provider.calls == 6
    assert len(second["results"]) == second["cache_hits"] == 6
    assert first["budget"] == second["budget"]
    assert second["budget"]["spent_usd"] == pytest.approx(0.0006)
    with pytest.raises(ValueError, match="another frozen run"):
        asyncio.run(run_pilot(provider, paid=False, **{**options, "count": 3}))


def test_pilot_records_safe_failure_and_stops_on_provider_wide_error(tmp_path):
    from app.services.understanding_provider import ProviderFailure

    class Provider:
        calls = 0

        def prepare_request(self, bundle, recipe, stage):
            return "/fake", {"model": recipe["model"]}, 0.001

        async def generate(self, *args):
            self.calls += 1
            raise ProviderFailure("authentication", provider_wide=True, usage_usd=0)

    provider = Provider()
    report = asyncio.run(run_pilot(provider, snapshot="2026-09-02", count=2,
        cache_dir=tmp_path / "cache", output=tmp_path / "pilot.json", budget_usd=5, paid=True,
        ledger_dir=tmp_path / "ledger"))
    assert report["status"] == "stopped"
    assert provider.calls == len(report["results"]) == 1
    assert report["results"][0]["failure"] == "authentication"
    assert json.loads((tmp_path / "pilot.json").read_text())["status"] == "stopped"


def test_committed_queue_is_distinct_unlabeled_and_reproducible():
    committed = json.loads((ROOT / "review_queue.json").read_text())
    assert committed == prepare_review_queue(committed["snapshots"])
    assert committed["article_count"] == 600
    assert len({item["url"] for item in committed["articles"]}) == 600
    assert all(item["labels"] is None and item["story_id"] is None
               and item["review_status"] == "unreviewed" for item in committed["articles"])
    with pytest.raises(ValueError, match="independent adjudicated"):
        assign_story_splits(committed["articles"], "frozen-v1")


def test_snapshot_integrity_and_minimum_are_required(monkeypatch):
    with pytest.raises(ValueError, match="at least 600"):
        prepare_review_queue([], 599)
    monkeypatch.setattr("evals.understanding.verify_snapshot", lambda name: False)
    with pytest.raises(ValueError, match="content hash"):
        prepare_review_queue(["corrupt"])


def test_story_split_is_deterministic_order_independent_and_keeps_copies_together():
    rows = [row(1, "story-a"), row(2, "story-a"), row(3, "story-b"), row(4, "story-c")]
    result = assign_story_splits(rows, "frozen-v1")
    assert result[0]["split"] == result[1]["split"]
    assert {r["article_id"]: r["split"] for r in result} == {
        r["article_id"]: r["split"] for r in assign_story_splits(list(reversed(rows)), "frozen-v1")}
    assert {r["split"] for r in result} == {"development", "holdout"}


def test_raw_model_labels_cannot_be_promoted():
    with pytest.raises(ValueError, match="independent adjudicated"):
        evaluate([row(1, label_provenance="model")], {}, manifest())


def test_duplicate_urls_and_story_leakage_are_rejected():
    with pytest.raises(ValueError, match="Duplicate article URLs"):
        evaluate([row(1), row(2, url="https://example.org/1#fragment")], {}, manifest())
    with pytest.raises(ValueError, match="Story leakage"):
        evaluate([row(1, "same", split="development"), row(2, "same")], {}, manifest())


def test_abstentions_count_against_recall_and_coverage():
    result = evaluate([row(1), row(2)], {"1": prediction(), "2": prediction(
        kind="unknown", primary_topic=None, entity_ids=[], place_ids=[])}, manifest())
    assert result["metrics"]["kind"]["coverage"]["value"] == 0.5
    assert result["metrics"]["kind"]["recall"]["value"] == 0.5
    assert result["metrics"]["entities"]["recall"]["value"] == 0.5
    assert result["metrics"]["entities"]["unresolved_resolvable"] == 1
    assert not result["quality_gates_passed"]


def test_missing_predictions_cannot_pass_by_precision():
    result = evaluate([row(1), row(2)], {}, manifest())
    assert result["metrics"]["primary_topic"]["recall"]["value"] == 0
    assert result["metrics"]["primary_topic"]["precision"]["value"] is None
    assert "primary_topic.precision" in result["blockers"]


def test_promotion_false_positive_and_small_perfect_sample_fail():
    rows = [row(1), row(2)]
    rows[1]["labels"]["promotional"] = True
    result = evaluate(rows, {"1": prediction(auto_suppressed=True), "2": prediction(auto_suppressed=True)}, manifest())
    assert result["metrics"]["promotion"]["legitimate_falsely_suppressed"] == 1
    assert result["metrics"]["promotion"]["precision"]["value"] == 0.5
    result = evaluate(rows, {"2": prediction(auto_suppressed=True)}, manifest())
    assert result["metrics"]["promotion"]["precision"]["value"] == 1
    assert "promotion.precision_underpowered" in result["blockers"]


def test_stories_distinguish_false_merges_missed_merges_and_singletons():
    rows = [row(1, "a"), row(2, "a"), row(3, "b")]
    singleton = story_metrics(rows, {})
    assert singleton["precision"]["value"] is None
    assert singleton["recall"]["value"] == 0
    assert singleton["missed_merges"] == 1
    merged = story_metrics(rows, {str(i): {"story_id": "all"} for i in range(1, 4)})
    assert merged["false_merges"] == 2
    assert merged["precision"]["value"] == pytest.approx(1 / 3)
    assert merged["recall"]["value"] == 1
    assert merged["bcubed_precision"] == pytest.approx(5 / 9)


@pytest.mark.parametrize("malformed", [
    {"entity_ids": "entity:1"}, {"place_ids": ["place:1", "place:1"]},
    {"kind": []}, {"story_id": 42}, {"auto_suppressed": "false"},
])
def test_malformed_predictions_rejected(malformed):
    with pytest.raises(ValueError):
        evaluate([row(1)], {"1": malformed}, manifest())


def test_development_metrics_are_never_promotion_evidence():
    result = evaluate([row(1, split="development")], {}, manifest(), split="development")
    assert "development_results_cannot_promote" in result["blockers"]


def test_perfect_large_holdout_passes_only_quality_and_declared_slices():
    rows = [row(i, story=str(i // 2)) for i in range(600)]
    for item in rows:
        item["labels"]["promotional"] = True
    predictions = {item["article_id"]: prediction(story_id=item["story_id"], auto_suppressed=True) for item in rows}
    config = manifest()
    config["supported_slices"] = ["en:title_only"]
    report = evaluate(rows, predictions, config)
    assert report["quality_gates_passed"], report["blockers"]
    assert not report["release_ready"]
    assert report["required_external_gates"]
    config["supported_slices"].append("fr:title_only")
    assert "slice.fr:title_only.insufficient_articles" in evaluate(rows, predictions, config)["blockers"]
