"""Offline S7 learning fences; fake database checks are not SQL concurrency proof."""
import json
from contextlib import nullcontext
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from uuid import UUID

import pytest

from app.services import reader_feedback as feedback
from app.services import reader_repository as repository
from app.services.reader_contract import intent_semantic_hash, validate_profile


def uid(number):
    return str(UUID(int=number))


def snapshot():
    return {"generation": 1, "revision": 2, "learning_revision": 3, "migration_status": "ready",
            "profile": validate_profile({"intents": [
                {"id": uid(1), "kind": "topic", "label": "AI regulation"},
                {"id": uid(2), "kind": "entity", "label": "OpenAI"}]})}


class Result:
    def __init__(self, row=None, rows=None):
        self.row, self.rows = row, rows or []

    def fetchone(self):
        return self.row

    def fetchall(self):
        return self.rows


class DB:
    def __init__(self, *, receipt=None, learned=None, exposure=None):
        self.receipt, self.learned = receipt, learned or []
        self.exposure = exposure or []
        self.calls = []

    def transaction(self):
        return nullcontext()

    def execute(self, sql, args=()):
        sql = " ".join(sql.split())
        self.calls.append((sql, args))
        if "SELECT intent_id,semantic_hash,weight" in sql:
            return Result(rows=self.learned)
        if "SELECT topic_key, count FROM public.reader_topic_exposure" in sql:
            return Result(rows=self.exposure)
        if "SELECT intent_ids,intent_semantic_hashes" in sql or "SELECT final_position" in sql:
            return Result(row=self.receipt)
        if "SELECT id,url" in sql:
            return Result(row={"id": uid(10), "url": "https://news.example/article"})
        if "INSERT INTO public.reading_events" in sql:
            return Result(row={"id": uid(40)})
        return Result()


def matching_receipt(state):
    return {"intent_ids": [uid(1)], "intent_semantic_hashes": {
        uid(1): intent_semantic_hash(state["profile"]["intents"][0])}}


def submit(monkeypatch, state, receipt, action="more_like_this"):
    monkeypatch.setattr(repository, "load_reader", lambda *a: state)
    monkeypatch.setattr(repository, "publication_guard", lambda *a: nullcontext())
    db = DB(receipt=receipt)
    response = feedback.submit_feedback(db, uid(99), {"article_id": uid(10), "event_id": uid(11),
        "feed_request_id": uid(12), "reader_generation": 1, "action": action})
    return db, response


@pytest.mark.parametrize("mutation", [
    {"query": "cricket"}, {"qualifiers": ["only research papers"]},
    {"resolved_id": "entity:different"}, {"kind": "place"},
])
def test_reused_intent_uuid_cannot_inherit_receipt_meaning(monkeypatch, mutation):
    state = snapshot()
    receipt = matching_receipt(state)
    state["profile"]["intents"][0].update(mutation)
    db, response = submit(monkeypatch, state, receipt)
    assert response["signals_adjusted"] == 0
    assert not any("INSERT INTO public.reader_learned_signals" in sql for sql, _ in db.calls)


def test_priority_only_edit_preserves_receipt_semantics(monkeypatch):
    state = snapshot()
    receipt = matching_receipt(state)
    state["profile"]["intents"][0]["priority"] = 2.8
    db, response = submit(monkeypatch, state, receipt)
    assert response["signals_adjusted"] == 1
    sql, args = next((sql, args) for sql, args in db.calls if "INSERT INTO public.reader_learned_signals" in sql)
    assert "reader_learned_signals.semantic_hash=EXCLUDED.semantic_hash" in sql
    assert "reader_learned_signals.generation=EXCLUDED.generation" in sql
    # S10 B2: reward_recipe_hash is now the final bound parameter; the receipt's
    # semantic hash is the one before it.
    assert "reward_recipe_hash=EXCLUDED.reward_recipe_hash" in sql
    assert args[-2] == receipt["intent_semantic_hashes"][uid(1)]
    from app.services.reward import reward_recipe_hash
    assert args[-1] == reward_recipe_hash()


def test_feedback_invalidates_old_ranking_claim_after_learning_revision(monkeypatch):
    invalidations = []
    def invalidate(conn, user):
        assert "learning_revision=learning_revision+1" in conn.calls[-1][0]
        invalidations.append(user)
    monkeypatch.setattr(repository, "_invalidate", invalidate)
    state = snapshot()
    submit(monkeypatch, state, matching_receipt(state))
    assert invalidations == [uid(99)]


@pytest.mark.parametrize("receipt", [None, {"intent_ids": [uid(1)]},
    {"intent_ids": [uid(1)], "intent_semantic_hashes": {}},
    {"intent_ids": [uid(1)], "intent_semantic_hashes": {uid(1): "wrong"}},
    {"intent_ids": [uid(1)], "intent_semantic_hashes": []},
])
def test_missing_semantic_proof_does_not_learn(monkeypatch, receipt):
    db, response = submit(monkeypatch, snapshot(), receipt)
    assert response["signals_adjusted"] == 0
    assert not any("INSERT INTO public.reader_learned_signals" in sql for sql, _ in db.calls)


def test_legacy_receipt_keeps_exact_article_feedback(monkeypatch):
    mutations = []
    monkeypatch.setattr(repository, "mutate_reader", lambda conn, user, payload: mutations.append(payload))
    _, response = submit(monkeypatch, snapshot(), {"intent_ids": [uid(1)]}, action="not_relevant")
    assert response["signals_adjusted"] == 0 and response["attributed"]
    assert mutations[0]["patch"]["policies"][-1]["kind"] == "article"
    assert mutations[0]["patch"]["policies"][-1]["value"] == uid(10)


def test_only_confirmed_receipt_intents_are_updated(monkeypatch):
    state = snapshot()
    receipt = matching_receipt(state)
    receipt["intent_semantic_hashes"][uid(2)] = intent_semantic_hash(state["profile"]["intents"][1])
    db, response = submit(monkeypatch, state, receipt)
    writes = [args for sql, args in db.calls if "INSERT INTO public.reader_learned_signals" in sql]
    assert response["signals_adjusted"] == 1 and writes[0][1] == uid(1)


def test_expired_intent_does_not_learn_from_old_receipt(monkeypatch):
    state = snapshot()
    receipt = matching_receipt(state)
    state["profile"]["intents"][0]["expires_at"] = (datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat()
    _, response = submit(monkeypatch, state, receipt)
    assert response["signals_adjusted"] == 0


@pytest.mark.parametrize("changed,expected", [(False, 0.4), (True, None)])
def test_learned_weights_use_semantic_hash_and_frozen_time(changed, expected):
    state = snapshot()
    now = datetime.now(timezone.utc)
    row = {"intent_id": uid(1), "semantic_hash": intent_semantic_hash(state["profile"]["intents"][0]),
           "weight": 0.8, "updated_at": now - timedelta(days=30)}
    if changed:
        state["profile"]["intents"][0]["query"] = "New meaning"
    else:
        state["profile"]["intents"][0]["priority"] = 3.0
    weights = feedback.load_learned_weights(DB(learned=[row]), uid(99), state, as_of=now)
    assert weights.get(uid(1)) == expected


@pytest.mark.parametrize("weight,semantic", [(float("nan"), True), (float("inf"), True),
    (True, True), ("0.8", True), (0.8, False)])
def test_bad_or_unproven_learned_weight_is_ignored(weight, semantic):
    state = snapshot()
    row = {"intent_id": uid(1), "weight": weight, "updated_at": datetime.now(timezone.utc)}
    if semantic:
        row["semantic_hash"] = intent_semantic_hash(state["profile"]["intents"][0])
    assert feedback.load_learned_weights(DB(learned=[row]), uid(99), state) == {}


# --- S10 D: repeated-impression discount ---

def test_bump_topic_exposure_upserts_with_the_documented_window_shape():
    db = DB()
    feedback._bump_topic_exposure(db, uid(99), uid(1))
    sql, args = db.calls[-1]
    assert "INSERT INTO public.reader_topic_exposure" in sql
    assert "ON CONFLICT (user_id, topic_key) DO UPDATE" in sql
    assert "interval '14 days'" in sql
    assert args == (uid(99), uid(1))


def test_bump_topic_exposure_is_best_effort_on_a_missing_table():
    class Broken:
        def execute(self, *a, **kw):
            raise RuntimeError("relation does not exist")
    feedback._bump_topic_exposure(Broken(), uid(99), uid(1))  # must not raise


def test_load_topic_exposure_parses_rows():
    db = DB(exposure=[{"topic_key": uid(1), "count": 7}, {"topic_key": uid(2), "count": 0}])
    assert feedback.load_topic_exposure(db, uid(99)) == {uid(1): 7, uid(2): 0}


def test_load_topic_exposure_drops_malformed_rows_and_survives_missing_table():
    db = DB(exposure=[{"topic_key": uid(1), "count": "not-a-number"}, {"topic_key": uid(2), "count": -1}])
    assert feedback.load_topic_exposure(db, uid(99)) == {}

    class Broken:
        def execute(self, *a, **kw):
            raise RuntimeError("relation does not exist")
    assert feedback.load_topic_exposure(Broken(), uid(99)) == {}


def test_discount_applies_to_an_intent_with_no_explicit_feedback_at_all():
    """The primary case Lee et al. 2014 targets: shown often, engaged with
    never. No reader_learned_signals row exists for this intent at all."""
    state = snapshot()
    db = DB(learned=[], exposure=[{"topic_key": uid(1), "count": 50}])
    weights = feedback.load_learned_weights(db, uid(99), state)
    assert weights[uid(1)] == -feedback._reward.IMPRESSION_DISCOUNT_CAP
    # The un-exposed intent in the same profile is untouched.
    assert uid(2) not in weights


def test_discount_composes_with_an_existing_explicit_weight():
    state = snapshot()
    now = datetime.now(timezone.utc)
    row = {"intent_id": uid(1), "semantic_hash": intent_semantic_hash(state["profile"]["intents"][0]),
           "weight": 0.5, "updated_at": now}
    db = DB(learned=[row], exposure=[{"topic_key": uid(1), "count": 50}])
    weights = feedback.load_learned_weights(db, uid(99), state, as_of=now)
    assert weights[uid(1)] == pytest.approx(0.5 - feedback._reward.IMPRESSION_DISCOUNT_CAP)


def test_no_exposure_rows_means_no_discount_and_no_new_keys():
    state = snapshot()
    db = DB(learned=[], exposure=[])
    assert feedback.load_learned_weights(db, uid(99), state) == {}


def test_discount_is_not_applied_to_a_stale_no_longer_active_intent():
    """Exposure rows can outlive an intent the reader removed; only currently
    active intents (from _intent_semantics) may gain a discount-only entry."""
    state = snapshot()
    stale_id = uid(999)
    db = DB(learned=[], exposure=[{"topic_key": stale_id, "count": 50}])
    weights = feedback.load_learned_weights(db, uid(99), state)
    assert stale_id not in weights


def test_below_threshold_exposure_yields_no_discount():
    state = snapshot()
    db = DB(learned=[], exposure=[{"topic_key": uid(1), "count": feedback._reward.IMPRESSION_DISCOUNT_THRESHOLD}])
    assert feedback.load_learned_weights(db, uid(99), state) == {}


def test_final_receipts_bind_order_recipe_learning_evidence_and_confirmed_semantics():
    state, db = snapshot(), DB()
    articles = [{"id": uid(20), "_reader_intent_ids": [uid(2)], "_ranking_recipe": "s7-recipe-v1",
                 "_ranking_evidence_stamp": {"article": "hash-20"}},
                {"id": uid(10), "_reader_intent_ids": [], "_ranking_recipe": "s7-recipe-v1",
                 "_ranking_evidence_stamp": "hash-10"}]
    original = deepcopy(articles)
    feedback.record_delivery(db, uid(99), uid(12), state, articles)
    writes = [args for sql, args in db.calls if "INSERT INTO public.reader_delivery_receipts" in sql]
    assert [args[2] for args in writes] == [uid(20), uid(10)]
    assert [args[9] for args in writes] == [0, 1]
    assert writes[0][7:9] == (3, "s7-recipe-v1")
    assert json.loads(writes[0][10]) == {"article": "hash-20"}
    assert json.loads(writes[0][11]) == {uid(2): intent_semantic_hash(state["profile"]["intents"][1])}
    assert json.loads(writes[1][11]) == {}
    assert articles == original


def test_new_legacy_receipts_cannot_turn_retrieval_matches_into_confirmed_learning():
    db = DB()
    feedback.record_delivery(db, uid(99), uid(12), snapshot(), [{"id": uid(20), "_reader_intent_ids": [uid(1)]}])
    args = db.calls[0][1]
    assert json.loads(args[6]) == [uid(1)] and json.loads(args[11]) == {}


@pytest.mark.parametrize("articles", [
    [{"id": uid(20)}, {"id": uid(20)}],
    [{"id": uid(20), "_reader_intent_ids": [uid(40)]}],
    [{"id": uid(20), "_ranking_recipe": 1}],
    [{"id": uid(20), "_ranking_evidence_stamp": float("nan")}],
    [{"id": uid(20), "_ranking_evidence_stamp": "x" * 17000}],
])
def test_invalid_receipt_set_is_rejected_before_any_write(articles):
    db = DB()
    with pytest.raises(ValueError):
        feedback.record_delivery(db, uid(99), uid(12), snapshot(), articles)
    assert not db.calls


@pytest.mark.parametrize("receipt,position,valid", [
    (None, None, False), ({"final_position": 3}, 2, False),
    ({"final_position": 3}, 3, True), ({"final_position": None}, None, True),
])
def test_passive_receipted_event_requires_own_article_request_and_position(receipt, position, valid):
    db = DB(receipt=receipt)
    result = feedback.ingest_events(db, uid(99), {"events": [{"type": "tap", "article_id": uid(10),
        "event_id": uid(30), "feed_request_id": uid(12), "position": position}]})
    assert result["inserted"] == int(valid)
    assert result["rejected_indices"] == ([] if valid else [0])
    sql, args = db.calls[0]
    assert "user_id=%s AND feed_request_id=%s AND article_id=%s" in sql
    assert args == (uid(99), uid(12), uid(10))
    assert not any("reader_learned_signals" in sql for sql, _ in db.calls)
    if valid:
        assert "r.user_id=%s AND r.feed_request_id=%s AND r.article_id=a.id" in db.calls[1][0]


def test_unreceipted_legacy_telemetry_stays_nonlearning():
    db = DB()
    result = feedback.ingest_events(db, uid(99), {"events": [{"type": "read", "article_id": uid(10)}]})
    assert result["inserted"] == 1
    assert len(db.calls) == 1 and "INSERT INTO public.reading_events" in db.calls[0][0]


@pytest.mark.parametrize("installed", [True, False])
def test_reader_invalidation_includes_optional_ranking_claims_and_results(monkeypatch, installed):
    from app.services import ranking_repository
    calls = []
    monkeypatch.setattr(ranking_repository, "invalidate", lambda conn, user: calls.append((conn, user)))

    class InstalledDB(DB):
        def execute(self, sql, args=()):
            result = super().execute(sql, args)
            if "to_regclass" in sql:
                return Result(row={"relation": "public.ranking_builds" if installed and args[0] == "public.ranking_builds" else None})
            return result

    db = InstalledDB()
    repository._invalidate(db, uid(99))
    assert calls == ([(db, uid(99))] if installed else [])
