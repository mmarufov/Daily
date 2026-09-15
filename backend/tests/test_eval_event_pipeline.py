"""The legacy prototype cannot overflow or bypass explicit exclusions."""
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from evals.pipeline import BM25Backend, Candidate, Rubric, assemble, run_pipeline


def test_forced_reservations_are_bounded_and_article_deduplicated():
    rubric = Rubric("test", "test", "breaking")
    titles = ["Earthquake destroys homes", "Hurricane approaches coast", "Election result announced",
              "Court changes legislation", "Scientists discover medicine"]
    candidates = [Candidate(i, {"id": f"a{i}", "title": title}) for i, title in enumerate(titles)]
    result = assemble(candidates, rubric, size=3, forced=[candidates[0], candidates[0]] + candidates[1:])
    assert len(result) <= 3
    assert len({c.article["id"] for c in result}) == len(result)
    assert [c.doc_idx for c in result[:2]] == [0, 1]
    assert assemble(candidates, rubric, size=0, forced=candidates) == []
    with pytest.raises(ValueError):
        assemble(candidates, rubric, size=-1, forced=candidates)


def test_more_than_two_critical_events_remain_detected_without_all_being_forced():
    persona = {"key": "test", "name": "Test", "interests": {}, "user_profile_v2": {}}
    docs = [{"id": f"a{i}", "title": f"Event number {i}", "summary": "test", "source": "test"}
            for i in range(5)]
    events = [{"id": i, "tier": "world_critical", "members": [i], "rep": i, "what": f"Event {i}"}
              for i in range(5)]
    result = run_pipeline(persona, docs, BM25Backend(docs), feed_size=3, events=events, with_salience=False)
    assert len(events) == 5
    assert len(result["feed"]) <= 3
    assert sum(bool(c.article.get("_forced")) for c in result["recalled_cands"]) == 2


def test_critical_event_cannot_bypass_explicit_topic_exclusion():
    persona = {"key": "test", "name": "Test", "interests": {"excluded_topics": ["crypto"]},
               "user_profile_v2": {"excluded_topics": ["crypto"]}}
    docs = [{"id": "a", "title": "Crypto crisis news", "summary": "crypto", "source": "test"}]
    events = [{"id": 0, "tier": "world_critical", "members": [0], "rep": 0, "what": "Crypto crisis"}]
    result = run_pipeline(persona, docs, BM25Backend(docs), feed_size=3, events=events, with_salience=False)
    assert result["feed"] == []


def test_reserved_items_do_not_reintroduce_deduplicated_coverage():
    rubric = Rubric("test", "test", "breaking")
    articles = [{"id": "a", "title": "Major earthquake destroys coastal homes"},
                {"id": "b", "title": "Major earthquake destroys coastal homes today"}]
    candidates = [Candidate(i, article) for i, article in enumerate(articles)]
    result = assemble(candidates, rubric, size=5, forced=candidates)
    assert [c.article["id"] for c in result] == ["a"]
