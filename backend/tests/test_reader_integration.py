"""Offline S5 vertical-slice wiring; no API credits, listener or database service."""
import asyncio
import json
import uuid
from contextlib import nullcontext
from datetime import datetime, timedelta, timezone
from unittest.mock import Mock

import pytest

from app.services import reader_integration as serving
from app.services import reader_feedback as feedback
from app.services import reader_repository as repo
from app.services.reader_contract import validate_profile, apply_patch, intent_semantic_hash
from app.services.reader_source_reconcile import query_sources, reconcile_reader_sources


def identifier(number):
    return str(uuid.UUID(int=number))


def profile():
    return validate_profile({"intents": [
        {"id": identifier(1), "kind": "topic", "label": "AI regulation"},
        {"id": identifier(2), "kind": "topic", "label": "Cricket"},
        {"id": identifier(3), "kind": "place", "label": "Новости Душанбе"},
    ]})


def snapshot():
    return {"profile": profile(), "revision": 2, "generation": 1, "learning_revision": 1,
            "migration_status": "ready"}


def test_tune_proposal_is_reviewable_and_does_not_mutate_input():
    base = profile()
    result = serving.propose(base, "More startups", operation_id=identifier(99))
    assert len(base["intents"]) == 3
    assert result["requires_confirmation"]
    changed = apply_patch(base, result["patch"])
    assert changed["intents"][-1]["label"] == "startups"
    assert changed["intents"][-1]["provenance"] == "reviewed_proposal"
    assert result == serving.propose(base, "More startups", operation_id=identifier(99))


@pytest.mark.parametrize("text", ["Change my whole feed", "More AI but not startups", "More AI and gaming",
                                  "Less an unknown interest", "More", "More AI; less gaming"])
def test_unsupported_tune_never_claims_application(text):
    with pytest.raises(ValueError):
        serving.propose(profile(), text, operation_id=identifier(99))


def test_stop_following_retains_other_intent_ids():
    result = serving.propose(profile(), "Stop following Cricket", operation_id=identifier(99))
    assert [i["id"] for i in result["patch"]["intents"]] == [identifier(1), identifier(3)]


def test_more_never_reduces_existing_high_priority():
    base = profile()
    base['intents'][0]['priority'] = 2.9
    result = serving.propose(base, 'More AI regulation', operation_id=identifier(99))
    assert result['patch']['intents'][0]['priority'] == 3.0


def test_discovery_review_response_matches_mobile_required_fields():
    result = reconcile_reader_sources(Mock(), 'user', {**snapshot(), 'migration_status': 'needs_review'})
    assert result['sources_found'] == result['exact_sources'] == result['supporting_sources'] == 0


@pytest.mark.parametrize('reviewed', [True, False])
def test_chat_blocks_excluded_thread_metadata_before_any_provider_call(monkeypatch, reviewed):
    from app.services.chat_service import ChatService
    from app.services import chat_repository
    from fastapi import HTTPException
    service = ChatService(openai_service=Mock(), newsapi_service=Mock())
    state = snapshot()
    state['migration_status'] = 'ready' if reviewed else 'needs_review'
    state['profile']['policies'] = [{'id': identifier(5), 'kind': 'article', 'value': identifier(9)}]
    monkeypatch.setattr(serving, 'snapshot_for', lambda *a: state)
    monkeypatch.setattr(serving, 'is_current', lambda *a: True)
    monkeypatch.setattr(chat_repository, 'get_thread', lambda *a, **k: {'id': identifier(8), 'article_id': identifier(9)})
    monkeypatch.setattr(chat_repository, 'get_thread_messages', lambda *a, **k: [])
    monkeypatch.setattr(chat_repository, 'get_articles_by_ids', lambda *a, **k: [{'id': identifier(9)}])
    with pytest.raises(HTTPException) as error:
        asyncio.run(service.stream_thread_message(Mock(), user_id='user', thread_id=identifier(8), content='Explain', intent=None))
    assert error.value.status_code == 409


def test_decay_before_addition_and_future_time_is_bounded():
    now = datetime.now(timezone.utc)
    assert feedback.decayed(-1, now - timedelta(days=60), now) + 0.2 == pytest.approx(-0.05)
    assert feedback.decayed(-1, now + timedelta(days=1), now) == -1


class Result:
    def __init__(self, row=None, rows=None):
        self.row, self.rows = row, rows or []
    def fetchone(self):
        return self.row
    def fetchall(self):
        return self.rows


def test_feedback_changes_allocation_without_starving_other_interests():
    now = datetime.now(timezone.utc)
    db = Mock()
    db.execute.return_value = Result(rows=[{"intent_id": identifier(1), "weight": 0.8, "updated_at": now,
        "semantic_hash": intent_semantic_hash(profile()["intents"][0])}])
    articles = [{"id": f"{group}-{n}", "_reader_intent_ids": [identifier(group)], "_reader_score": 0.016}
                for n in range(20) for group in (1, 2, 3)]
    selected = feedback.adjust_candidates(db, "user", snapshot(), articles)[:15]
    assert {a["_reader_intent_ids"][0] for a in selected[:3]} == {identifier(1), identifier(2), identifier(3)}
    counts = {i: sum(a["_reader_intent_ids"] == [identifier(i)] for a in selected) for i in (1, 2, 3)}
    assert counts[1] > counts[2] and counts[1] > counts[3]


def test_policy_is_shared_unicode_exact_and_publisher_scoped():
    p = validate_profile({"policies": [{"id": identifier(1), "kind": "lexical", "value": "AI"}]})
    assert serving.allowed(p, {"title": "Retail growth", "url": "https://news.example/story"})
    assert not serving.allowed(p, {"title": "AI regulation", "url": "https://news.example/story"})
    p = validate_profile({"policies": [{"id": identifier(1), "kind": "publisher", "value": "news.example"}]})
    assert not serving.allowed(p, {"title": "A", "url": "https://www.news.example/story"})
    assert serving.allowed(p, {"title": "A", "url": "https://other.example/story"})


def test_migration_review_prevents_retrieval(monkeypatch):
    monkeypatch.setattr(repo, "load_reader", lambda *a, **k: {**snapshot(), "migration_status": "needs_review"})
    from app.services import reader_retrieval
    retrieve = Mock(side_effect=AssertionError("must not retrieve before review"))
    monkeypatch.setattr(reader_retrieval, "build_reader_candidates", retrieve)
    result = serving.serve_feed(Mock(), "user")
    assert result["status"] == "needs_reader_review" and not result["articles"]


def test_feed_uses_candidates_without_legacy_scoring_or_provider(monkeypatch):
    from app.services import reader_retrieval, article_content
    monkeypatch.setattr(repo, "load_reader", lambda *a, **k: snapshot())
    monkeypatch.setattr(repo, "publication_guard", lambda *a, **k: nullcontext())
    candidate = {"id": identifier(55), "title": "Model governance", "url": "https://news.example/a",
                 "_reader_intent_ids": [identifier(1)], "_reader_semantic_only": True, "_reader_score": 0.016}
    monkeypatch.setattr(reader_retrieval, "build_reader_candidates", lambda *a, **k: [candidate])
    monkeypatch.setattr(feedback, "adjust_candidates", lambda conn, user, reader, items: items)
    record = Mock()
    monkeypatch.setattr(feedback, "record_delivery", record)
    monkeypatch.setattr(article_content, "serialize_article", lambda row, **k: {k: row[k] for k in ("id", "title", "url")})
    result = serving.serve_feed(Mock(), "user")
    assert result["articles"][0]["reader_generation"] == 1
    assert result["articles"][0]["matched_profile_signals"] == ["AI regulation"]
    assert result["coverage"]["quality_evaluated"] is False
    record.assert_called_once()


def test_old_feed_is_not_relabeled_as_current(monkeypatch):
    monkeypatch.setenv("S5_READER_ENABLED", "true")
    monkeypatch.setattr(repo, "load_reader", lambda *a, **k: snapshot())
    with pytest.raises(repo.ReaderConflict):
        serving.finalize_feed(Mock(), "user", {"status": "ready", "reader_generation": 1,
                                              "reader_revision": 1, "articles": []})


def test_final_boundary_strips_private_evidence_and_stamps_s4_items(monkeypatch):
    monkeypatch.setenv("S5_READER_ENABLED", "true")
    monkeypatch.setattr(repo, "load_reader", lambda *a, **k: snapshot())
    monkeypatch.setattr(repo, "publication_guard", lambda *a, **k: nullcontext())
    monkeypatch.setattr(feedback, "record_delivery", Mock())
    result = serving.finalize_feed(Mock(), "user", {"status": "ready", "reader_generation": 1,
        "reader_revision": 2, "articles": [{"id": identifier(55), "title": "A", "url": "https://n.example/a",
        "_reader_policy_evidence": {"language": "en"}, "_reader_intent_ids": [identifier(1)]}]})
    assert not any(k.startswith("_reader_") for k in result["articles"][0])
    assert result["articles"][0]["feed_request_id"] == result["feed_request_id"]


def test_source_queries_exclude_private_context_and_keep_each_interest():
    p = {**profile(), "context": "private biography"}
    queries = query_sources(p)
    assert len(queries) == 3
    assert all("private" not in q["url"] for q in queries)
    assert "%D0" in queries[2]["url"]


def test_source_reconciliation_never_deletes_graph_or_reactivates_ambiguous_sources(monkeypatch):
    from app.services import reader_source_reconcile
    monkeypatch.setattr(reader_source_reconcile, "publication_guard", lambda *a: nullcontext())
    conn = Mock()
    result = reconcile_reader_sources(conn, "user", snapshot())
    queries = [" ".join(call.args[0].split()) for call in conn.execute.call_args_list]
    assert not any("DELETE FROM public.user_sources" in q for q in queries)
    assert "reader_retired" in queries[0]
    assert all("ELSE user_sources.active" in q for q in queries if "INSERT INTO public.user_sources" in q)
    assert result["validated"] is False
    assert all(source['source_url'].startswith('https://') and source['source_name']
               for source in result['sources'])


def test_event_batch_validation_isolated_and_acknowledged():
    conn = Mock()
    conn.transaction.return_value = nullcontext()
    conn.execute.return_value = Result(row={"id": identifier(66)})
    event = {"article_id": identifier(1), "event_id": identifier(2), "type": "tap"}
    result = feedback.ingest_events(conn, "user", {"events": [event, {**event, "duration_seconds": True}, None]})
    assert result == {"inserted": 1, "acknowledged": [identifier(2)], "rejected_indices": [1, 2]}
    assert conn.execute.call_count == 1
    with pytest.raises(ValueError):
        feedback.ingest_events(conn, "user", {"events": [event] * 101})


def test_telemetry_cannot_be_second_explicit_learning_writer():
    conn = Mock()
    conn.transaction.return_value = nullcontext()
    result = feedback.ingest_events(conn, "user", {"events": [{"article_id": identifier(1), "type": "more_like_this"}]})
    assert result["rejected_indices"] == [0]
    conn.execute.assert_not_called()


# --- S10 D: passive engagement (qualified reads, quick-backs) wired through ingest_events ---

VALID_HASH = "a" * 64


class EventDB:
    """Fake DB for ingest_events: one receipted article confirmed against two
    intents, every write recorded so passive-signal wiring is directly
    assertable without a real Postgres connection."""

    def __init__(self, *, receipted=True, intent_ids=None):
        self.receipted = receipted
        self.intent_ids = intent_ids if intent_ids is not None else [identifier(1), identifier(2)]
        self.calls = []

    def transaction(self):
        return nullcontext()

    def execute(self, sql, args=()):
        q = " ".join(sql.split())
        self.calls.append((q, args))
        if q.startswith("SELECT final_position"):
            if not self.receipted:
                return Result(row=None)
            return Result(row={"final_position": 0, "intent_ids": self.intent_ids})
        if q.startswith("INSERT INTO public.reading_events"):
            return Result(row={"id": identifier(66)})
        return Result()

    def engagement_writes(self):
        return [(q, a) for q, a in self.calls if "INSERT INTO public.reader_topic_engagement" in q]

    def exposure_writes(self):
        return [(q, a) for q, a in self.calls if "INSERT INTO public.reader_topic_exposure" in q]


def _event(event_type, **overrides):
    return {"article_id": identifier(10), "event_id": identifier(20), "feed_request_id": identifier(30),
            "position": 0, "type": event_type, **overrides}


def test_qualified_read_bumps_engagement_for_every_confirmed_intent():
    conn = EventDB()
    result = feedback.ingest_events(conn, "user", {"events": [
        _event("read", duration_seconds=30, read_content_hash=VALID_HASH)]})
    assert result["inserted"] == 1
    writes = conn.engagement_writes()
    assert {args[1] for _q, args in writes} == set(conn.intent_ids)
    for _q, args in writes:
        assert args[2] == pytest.approx(feedback._reward.QUALIFIED_READ_BONUS)


def test_unqualified_read_does_not_bump_engagement():
    """No read_content_hash (source-web/preview, or no native body displayed)
    -- the client only sets this for a verified native-body view."""
    conn = EventDB()
    result = feedback.ingest_events(conn, "user", {"events": [_event("read", duration_seconds=30)]})
    assert result["inserted"] == 1
    assert conn.engagement_writes() == []


def test_skip_bumps_engagement_negatively():
    conn = EventDB()
    result = feedback.ingest_events(conn, "user", {"events": [_event("skip")]})
    assert result["inserted"] == 1
    writes = conn.engagement_writes()
    assert {args[1] for _q, args in writes} == set(conn.intent_ids)
    for _q, args in writes:
        assert args[2] == pytest.approx(-feedback._reward.QUICK_BACK_PENALTY)


def test_tap_and_impression_never_bump_engagement():
    for event_type in ("tap", "impression"):
        conn = EventDB()
        result = feedback.ingest_events(conn, "user", {"events": [_event(event_type)]})
        assert result["inserted"] == 1
        assert conn.engagement_writes() == [], f"{event_type} must not bump engagement"


def test_impression_bumps_exposure_not_engagement():
    conn = EventDB()
    feedback.ingest_events(conn, "user", {"events": [_event("impression")]})
    assert conn.engagement_writes() == []
    exposure = conn.exposure_writes()
    assert {args[1] for _q, args in exposure} == set(conn.intent_ids)


def test_unreceipted_event_bumps_nothing():
    """No feed_request_id at all -- delivered is never looked up, so there is
    nothing to attribute a passive signal to."""
    conn = EventDB()
    event = _event("read", duration_seconds=30, read_content_hash=VALID_HASH)
    del event["feed_request_id"]
    feedback.ingest_events(conn, "user", {"events": [event]})
    assert conn.engagement_writes() == []
    assert conn.exposure_writes() == []


def test_passive_signals_never_write_reader_learned_signals():
    """The invariant this whole batch is built around: passive telemetry must
    never become a second writer to the table explicit feedback owns."""
    conn = EventDB()
    feedback.ingest_events(conn, "user", {"events": [
        _event("read", duration_seconds=30, read_content_hash=VALID_HASH),
        _event("skip", article_id=identifier(11), event_id=identifier(21)),
    ]})
    assert not any("reader_learned_signals" in q for q, _a in conn.calls)


class FeedbackDB:
    def __init__(self, receipt=True):
        self.saved, self.writes, self.receipt = None, 0, receipt
    def execute(self, sql, args=()):
        if "SELECT * FROM public.reader_feedback_events" in sql:
            return Result(row=self.saved)
        if "SELECT id,url" in sql:
            return Result(row={"id": identifier(55), "url": "https://news.example/a"})
        if "SELECT intent_ids" in sql:
            return Result(row={"intent_ids": [identifier(1)],
                "intent_semantic_hashes": {identifier(1): intent_semantic_hash(profile()["intents"][0])}}
                if self.receipt else None)
        if "INSERT INTO public.reader_learned_signals" in sql:
            self.writes += 1
        if "INSERT INTO public.reader_feedback_events" in sql:
            self.saved = {"request_hash": args[3], "result": json.loads(args[4])}
        return Result()


def test_feedback_retry_applies_once_and_different_payload_is_rejected(monkeypatch):
    monkeypatch.setattr(repo, "load_reader", lambda *a, **k: snapshot())
    monkeypatch.setattr(repo, "publication_guard", lambda *a, **k: nullcontext())
    conn = FeedbackDB()
    payload = {"event_id": identifier(90), "article_id": identifier(55), "reader_generation": 1,
               "action": "more_like_this", "feed_request_id": identifier(88)}
    result = feedback.submit_feedback(conn, "user", payload)
    assert result == feedback.submit_feedback(conn, "user", payload)
    assert conn.writes == 1 and result["attributed"]
    with pytest.raises(ValueError):
        feedback.submit_feedback(conn, "user", {**payload, "action": "important"})


def test_feedback_missing_receipt_cannot_invent_intent_attribution(monkeypatch):
    monkeypatch.setattr(repo, "load_reader", lambda *a, **k: snapshot())
    monkeypatch.setattr(repo, "publication_guard", lambda *a, **k: nullcontext())
    conn = FeedbackDB(receipt=False)
    result = feedback.submit_feedback(conn, "user", {"event_id": identifier(90), "article_id": identifier(55),
        "reader_generation": 1, "action": "more_like_this", "feed_request_id": identifier(88)})
    assert result["signals_adjusted"] == 0 and conn.writes == 0


def test_delayed_pre_reset_feedback_is_rejected(monkeypatch):
    monkeypatch.setattr(repo, "load_reader", lambda *a, **k: {**snapshot(), "generation": 2})
    monkeypatch.setattr(repo, "publication_guard", lambda *a, **k: nullcontext())
    with pytest.raises(repo.ReaderConflict):
        feedback.submit_feedback(FeedbackDB(), "user", {"event_id": identifier(90), "article_id": identifier(55),
            "reader_generation": 1, "action": "important"})
