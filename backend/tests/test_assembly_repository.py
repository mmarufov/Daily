"""Offline S8 evidence/history contracts; fakes do not prove PostgreSQL locking."""
from contextlib import contextmanager
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from uuid import UUID

import pytest

from app.services import assembly_repository as repo
from app.services import reader_feedback, reader_repository, reader_retrieval, understanding_repository
from app.services.assembly_contract import RECIPE
from app.services.reader_contract import canonical_hash


def uid(number):
    return str(UUID(int=number))


NOW = datetime(2026, 9, 9, tzinfo=timezone.utc)
USER, ARTICLE, EDITION, EVENT = map(uid, (100, 1, 200, 300))
SNAPSHOT = {"generation": 1, "revision": 2, "learning_revision": 3,
            "profile": {"intents": []}}


class Result:
    def __init__(self, row=None, rows=()):
        self.row, self.rows = row, list(rows)

    def fetchone(self):
        return self.row

    def fetchall(self):
        return self.rows


class DB:
    def __init__(self):
        self.calls = []
        self.control = {"epoch": 1, "approved": True, "serving": True,
                        "recipe": deepcopy(RECIPE), "recipe_hash": canonical_hash(RECIPE)}
        self.memberships, self.clusters = [], []
        self.revision, self.known, self.reads, self.events = 0, set(), set(), set()
        self.generation = 1
        self.delivered = {"final_position": 3, "generation": 1,
            "assembly_recipe": canonical_hash(RECIPE), "coverage_key": "article:" + ARTICLE,
            "novelty_key": "a" * 64, "assembly_content_hash": "b" * 64}

    @contextmanager
    def transaction(self):
        yield

    def execute(self, sql, args=()):
        sql = " ".join(sql.split())
        self.calls.append((sql, args))
        if "to_regclass('public.assembly_control')" in sql:
            return Result({"relation": "assembly_control"})
        if "SELECT * FROM public.assembly_control" in sql:
            return Result(deepcopy(self.control))
        if "SELECT * FROM public.story_memberships" in sql:
            return Result(rows=deepcopy(self.memberships))
        if "SELECT id,recipe_id,version FROM public.story_clusters" in sql:
            return Result(rows=deepcopy(self.clusters))
        if "SELECT revision FROM public.reader_edition_state" in sql:
            return Result({"revision": self.revision})
        if "SELECT novelty_key FROM public.reader_edition_reads" in sql:
            return Result(rows=[{"novelty_key": key} for key in self.known])
        if "SELECT id FROM public.users" in sql:
            return Result({"id": USER})
        if "SELECT * FROM public.reader_profiles" in sql:
            return Result({"generation": self.generation})
        if sql.startswith("SELECT final_position"):
            return Result(deepcopy(self.delivered))
        if "INSERT INTO public.reading_events" in sql:
            event_id = args[5]
            if event_id in self.events:
                return Result()
            self.events.add(event_id)
            return Result({"id": len(self.events)})
        if "INSERT INTO public.reader_edition_reads" in sql:
            key = args[1], args[2]
            if key in self.reads:
                return Result()
            self.reads.add(key)
            return Result({"novelty_key": args[2]})
        if "INSERT INTO public.reader_edition_state" in sql:
            self.revision += 1
        return Result()


def current(*, complete=True):
    return {"article_id": ARTICLE, "article": {"id": ARTICLE,
            "url": "https://www.news.example/report?edition=7", "image_url": "before"},
            "recipe_id": "s3-approved", "input_hash": "input", "state": "ready",
            "policy_evidence": {"topic_ids": ["technology"]},
            "evidence": {"sufficient": True, "evidence_tier": "original_body", "manifest": {
                "analysis_allowed": True, "truncated": False,
                "artifact": {"completeness": "complete" if complete else "partial", "text_hash": "body"},
                "field_hashes": {"title": "title", "summary": "summary", "body": "body"}}}}


def membership():
    return {"article_id": ARTICLE, "recipe_id": "s3-approved", "cluster_id": uid(8),
            "input_hash": "input", "semantic_revision": 1, "eligibility_generation": 1,
            "version": 1, "reason": "singleton_insufficient_or_ambiguous"}


def hydration(monkeypatch, db, *, member=False, evidence=None):
    row = evidence or current()
    monkeypatch.setattr(reader_retrieval, "_s6_recipe", lambda conn: {"id": "s3-approved"})
    if member:
        db.control["recipe"]["s3_membership_enabled"] = True
        db.control["recipe_hash"] = canonical_hash(db.control["recipe"])
        db.memberships = [membership()]
        db.clusters = [{"id": uid(8), "recipe_id": "s3-approved", "version": 3}]
        row["membership"] = deepcopy(db.memberships[0])
    monkeypatch.setattr(understanding_repository, "load_current_batch",
                        lambda conn, ids, recipe_id, **kw: {ARTICLE: deepcopy(row)})
    return repo.hydrate(db, USER, SNAPSHOT, [ARTICLE], db.control["recipe"], as_of=NOW)


def test_hydration_is_readonly_coherent_and_explicitly_unknown(monkeypatch):
    db = DB()
    result = hydration(monkeypatch, db)
    assert db.calls[0][0] == "SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY"
    candidate = result["candidates"][ARTICLE]
    assert not candidate["identity_verified"] and candidate["coverage_key"] is None
    assert candidate["publisher_id"] == "news.example" and candidate["topic_ids"] == ["technology"]
    assert result["history_revision"] == 0 and result["control"]["epoch"] == 1
    assert not any(sql.startswith(("INSERT", "DELETE", "UPDATE")) for sql, _ in db.calls)


def test_verified_s3_identity_accepts_original_singleton_member_reason(monkeypatch):
    result = hydration(monkeypatch, DB(), member=True)
    candidate = result["candidates"][ARTICLE]
    assert candidate["identity_verified"]
    assert candidate["coverage_key"] == "s3:s3-approved:" + uid(8)
    assert candidate["membership_stamp"]["cluster"]["version"] == 3


@pytest.mark.parametrize("change", ["absent", "stale", "wrong_recipe", "disabled"])
def test_unvalidated_membership_cannot_create_identity(change):
    row = current()
    member = membership()
    row["membership"] = deepcopy(member)
    cluster = {"id": uid(8), "recipe_id": "s3-approved", "version": 1}
    if change == "absent":
        row["membership"] = None
    elif change == "stale":
        row["state"] = "stale"
    elif change == "wrong_recipe":
        cluster["recipe_id"] = "wrong"
    result = repo.candidate_evidence(row, membership=member, cluster=cluster,
                                     membership_enabled=change != "disabled")
    assert not result["identity_verified"] and result["coverage_key"] is None


@pytest.mark.parametrize("change", ["partial", "title_only", "revoked", "truncated", "missing"])
def test_uncertain_body_cannot_hard_suppress_read(change):
    row = current(complete=change != "partial")
    if change == "title_only":
        row["evidence"]["evidence_tier"] = "title_only"
    elif change == "revoked":
        row["evidence"]["manifest"]["analysis_allowed"] = False
    elif change == "truncated":
        row["evidence"]["manifest"]["truncated"] = True
    elif change == "missing":
        row["evidence"] = None
    assert repo.candidate_evidence(row)["novelty_key"] is None


def test_novelty_ignores_metadata_and_versions_but_tracks_supported_content():
    row = current()
    before = repo.candidate_evidence(row)["novelty_key"]
    row["article"].update(image_url="new", published_at=NOW.isoformat(), semantic_revision=12)
    row["input_hash"] = "metadata changed"
    row["evidence"]["manifest"]["artifact"].update(id="new", version=99)
    assert repo.candidate_evidence(row)["novelty_key"] == before
    row["evidence"]["manifest"]["field_hashes"]["body"] = "corrected supported body"
    assert repo.candidate_evidence(row)["novelty_key"] != before


@pytest.mark.parametrize("mutation", ["history", "epoch", "disabled", "membership_insert", "cluster"])
def test_fresh_validation_rejects_every_selection_dependency_change(monkeypatch, mutation):
    db = DB()
    expected = hydration(monkeypatch, db, member=mutation in {"membership_insert", "cluster"})
    if mutation == "history":
        db.revision += 1
    elif mutation == "epoch":
        db.control["epoch"] += 2  # Disable/re-enable same recipe is not the same authority.
    elif mutation == "disabled":
        db.control["serving"] = False
    elif mutation == "membership_insert":
        db.memberships[0]["version"] += 1
    elif mutation == "cluster":
        db.clusters[0]["version"] += 1
    with pytest.raises(repo.AssemblyStoreError):
        repo.validate(db, USER, SNAPSHOT, expected)


def test_validation_locks_members_before_clusters_before_control(monkeypatch):
    db = DB()
    expected = hydration(monkeypatch, db, member=True)
    db.calls.clear()
    assert repo.validate(db, USER, SNAPSHOT, expected) == expected
    locking = [sql for sql, _ in db.calls if "FOR SHARE" in sql]
    assert "story_memberships" in locking[0] and "story_clusters" in locking[1]
    assert "assembly_control" in locking[-1]


def test_missing_membership_presence_is_a_frozen_dependency(monkeypatch):
    db = DB()
    db.control["recipe"]["s3_membership_enabled"] = True
    db.control["recipe_hash"] = canonical_hash(db.control["recipe"])
    expected = hydration(monkeypatch, db)
    assert expected["candidates"][ARTICLE]["membership_stamp"]["membership"] is None
    db.memberships = [membership()]
    db.clusters = [{"id": uid(8), "recipe_id": "s3-approved", "version": 1}]
    with pytest.raises(repo.AssemblyStoreError, match="dependencies_changed"):
        repo.validate(db, USER, SNAPSHOT, expected)


def test_hydration_rejects_unbounded_candidate_union():
    db = DB()
    with pytest.raises(repo.AssemblyStoreError, match="article_limit"):
        repo.hydrate(db, USER, SNAPSHOT, [uid(value) for value in range(601)], RECIPE, as_of=NOW)


def test_unapproved_s3_uses_ordinary_metadata_without_s3_tables(monkeypatch):
    db = DB()
    monkeypatch.setattr(reader_retrieval, "_s6_recipe", lambda conn: None)
    monkeypatch.setattr(reader_retrieval, "_s6_hydrate", lambda conn, ids, recipe: {
        ARTICLE: {"article": {"id": ARTICLE, "url": "https://news.example/x"},
                  "policy": {"topic_ids": None}}})
    monkeypatch.setattr(understanding_repository, "load_current_batch",
                        lambda *a, **kw: pytest.fail("must not load unsupported S3"))
    result = repo.hydrate(db, USER, SNAPSHOT, [ARTICLE], RECIPE, as_of=NOW)
    item = result["candidates"][ARTICLE]
    assert item["coverage_key"] is None and item["novelty_key"] is None
    assert item["publisher_id"] == "news.example" and item["topic_ids"] is None


def test_history_query_is_account_generation_keys_and_frozen_retention_bounded(monkeypatch):
    db = DB()
    key = repo.candidate_evidence(current())["novelty_key"]
    db.known.add(key)
    result = hydration(monkeypatch, db)
    assert result["candidates"][ARTICLE]["known_read"]
    sql, args = next(call for call in db.calls if "SELECT novelty_key" in call[0])
    assert "user_id=%s AND generation=%s AND novelty_key=ANY" in sql
    assert args == (USER, 1, [key], NOW - timedelta(days=30), NOW)


def event(**overrides):
    return {"article_id": ARTICLE, "type": "read", "event_id": EVENT,
            "feed_request_id": EDITION, "position": 3, "duration_seconds": 8,
            "read_content_hash": "b" * 64, **overrides}


def test_new_receipted_read_locks_reader_before_article_and_increments_once():
    db = DB()
    first = reader_feedback.ingest_events(db, USER, {"events": [event()]})
    replay = reader_feedback.ingest_events(db, USER, {"events": [event()]})
    another = reader_feedback.ingest_events(db, USER, {"events": [event(event_id=uid(301))]})
    assert first["inserted"] == another["inserted"] == 1 and replay["inserted"] == 0
    assert db.revision == 1
    sqls = [sql for sql, _ in db.calls]
    guard = next(index for index, sql in enumerate(sqls) if "reader_profiles" in sql)
    article_write = next(index for index, sql in enumerate(sqls) if "INSERT INTO public.reading_events" in sql)
    assert "FOR UPDATE" in sqls[guard] and guard < article_write
    assert not any("learning_revision=" in sql for sql in sqls)


@pytest.mark.parametrize("overrides", [{"type": "impression"}, {"type": "tap"}, {"position": None},
    {"position": 0}, {"feed_request_id": None}, {"event_id": None},
    {"read_content_hash": None}, {"read_content_hash": "c" * 64}, {"read_content_hash": "not-a-hash"}])
def test_non_attributed_events_never_churn_history(overrides):
    db = DB()
    reader_feedback.ingest_events(db, USER, {"events": [event(**overrides)]})
    assert db.revision == 0 and not db.reads


def test_old_generation_receipt_after_reset_never_repopulates_history():
    db = DB()
    db.generation = 2
    reader_feedback.ingest_events(db, USER, {"events": [event()]})
    assert db.revision == 0


def test_missing_or_unproved_receipt_never_populates_history():
    for proof in (None, {"final_position": 3, "generation": 1}):
        db = DB()
        db.delivered = proof
        reader_feedback.ingest_events(db, USER, {"events": [event()]})
        assert db.revision == 0


def test_receipts_keep_original_positions_and_only_explicit_assembly_proof():
    db = DB()
    reader_feedback.record_delivery(db, USER, EDITION, SNAPSHOT, [
        {"id": ARTICLE, "delivery_position": 7, "_assembly_recipe": canonical_hash(RECIPE),
         "_assembly_coverage_unit": "article:" + ARTICLE, "_assembly_novelty_key": "a" * 64,
         "_assembly_content_hash": "b" * 64}])
    sql, args = db.calls[0]
    assert "assembly_recipe,coverage_key,novelty_key" in sql
    assert args[9] == 7 and args[-2:] == ("a" * 64, "b" * 64)


@pytest.mark.parametrize("content_hash", [None, "x" * 64, True, "short"])
def test_novelty_receipt_without_valid_display_content_hash_fails_before_writes(content_hash):
    db = DB()
    with pytest.raises(ValueError, match="assembly receipt proof"):
        reader_feedback.record_delivery(db, USER, EDITION, SNAPSHOT, [
            {"id": ARTICLE, "_assembly_recipe": canonical_hash(RECIPE),
             "_assembly_coverage_unit": "article:" + ARTICLE,
             "_assembly_novelty_key": "a" * 64, "_assembly_content_hash": content_hash}])
    assert not db.calls


@pytest.mark.parametrize("position", [-1, True, 10001, "2"])
def test_invalid_receipt_positions_fail_before_any_write(position):
    db = DB()
    with pytest.raises(ValueError):
        reader_feedback.record_delivery(db, USER, EDITION, SNAPSHOT,
                                       [{"id": ARTICLE, "delivery_position": position}])
    assert not db.calls
