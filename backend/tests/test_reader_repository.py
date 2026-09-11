"""Offline transaction protocol tests; not a PostgreSQL concurrency substitute."""
from contextlib import contextmanager
from copy import deepcopy
from uuid import uuid4

import pytest

from app.services.reader_contract import validate_profile
from app.services.reader_repository import ReaderConflict, ReaderNotFound, get_operation, load_reader, mutate_reader, publication_guard, reset_learning


class Result:
    def __init__(self, row=None):
        self.row = row
    def fetchone(self):
        return deepcopy(self.row)


class Connection:
    def __init__(self):
        self.profile = {"profile": validate_profile({}), "revision": 1, "learning_revision": 1, "generation": 1, "migration_status": "ready"}
        self.operations, self.jobs, self.sql = {}, [], []
        self.user_exists = True
        self.fail_on = None
        self.depth = 0

    @contextmanager
    def transaction(self):
        before = deepcopy((self.profile, self.operations, self.jobs))
        self.depth += 1
        try:
            yield
        except Exception:
            self.profile, self.operations, self.jobs = before
            raise
        finally:
            self.depth -= 1

    def execute(self, sql, args=()):
        assert self.depth, "all repository statements require an explicit transaction"
        sql = " ".join(sql.split())
        self.sql.append(sql)
        if self.fail_on and self.fail_on in sql:
            raise RuntimeError("injected database failure")
        if sql.startswith("SELECT id FROM public.users"):
            return Result({"id": "u"} if self.user_exists else None)
        if sql.startswith("SELECT user_id FROM public.reader_profiles"):
            return Result({"user_id": "u"} if self.profile else None)
        if sql.startswith("SELECT * FROM public.reader_profiles"):
            return Result(self.profile)
        if sql.startswith("SELECT request_hash,result"):
            return Result(self.operations.get(args[1]))
        if sql.startswith("SELECT to_regclass"):
            # This S5-only fixture predates the optional S7 installation.
            return Result({"relation": None if args[0] == "public.ranking_builds" else args[0]})
        if sql.startswith("UPDATE public.reader_profiles SET profile"):
            self.profile.update(profile=args[0].obj, revision=args[2], migration_status=args[3])
        if sql.startswith("UPDATE public.reader_profiles SET generation"):
            self.profile.update(generation=args[0], learning_revision=args[1])
        if sql.startswith("INSERT INTO public.reader_operations"):
            self.operations[args[1]] = {"request_hash": args[2], "result": args[4].obj}
        if sql.startswith("INSERT INTO public.reader_jobs"):
            self.jobs.append(args[:4])
        if sql.startswith("DELETE FROM public.reader_jobs"):
            self.jobs = []
        return Result()


def command(**patch):
    return {"operation_id": str(uuid4()), "base_generation": 1, "base_revision": 1, "patch": patch}


def test_commit_retry_and_receipt_does_not_misrepresent_current_state():
    conn = Connection()
    first = command(context="first")
    assert mutate_reader(conn, "u", first)["revision"] == 2
    second = {**command(context="second"), "base_revision": 2}
    assert mutate_reader(conn, "u", second)["revision"] == 3
    replay = mutate_reader(conn, "u", first)
    assert replay["replayed"] and replay["revision"] == 2 and replay["current"]["revision"] == 3
    assert get_operation(conn, "u", first["operation_id"])["current"]["profile"]["context"] == "second"


def test_id_reuse_and_stale_edit_rejected():
    conn, request = Connection(), command(context="one")
    mutate_reader(conn, "u", request)
    with pytest.raises(ReaderConflict, match="operation_id_reused"):
        mutate_reader(conn, "u", {**request, "patch": {"context": "two"}})
    with pytest.raises(ReaderConflict, match="reader_changed"):
        mutate_reader(conn, "u", command(context="two"))


def test_failure_between_profile_and_receipt_rolls_back():
    conn = Connection()
    conn.fail_on = "INSERT INTO public.reader_operations"
    with pytest.raises(RuntimeError):
        mutate_reader(conn, "u", command(context="never committed"))
    assert conn.profile["revision"] == 1 and not conn.operations
    assert conn.profile["profile"]["context"] == ""


def test_noop_and_priority_edits_do_not_queue_paid_work():
    conn = Connection()
    assert mutate_reader(conn, "u", command())["revision"] == 1
    assert not conn.jobs
    item = {"id": str(uuid4()), "kind": "topic", "label": "AI"}
    mutate_reader(conn, "u", command(intents=[item]))
    assert {job[-1] for job in conn.jobs} == {"embeddings", "source_reconcile"}
    conn.jobs.clear()
    mutate_reader(conn, "u", {**command(intents=[{**item, "priority": 2.0}]), "base_revision": 2})
    assert not conn.jobs


def test_reset_epoch_fences_old_work_and_is_idempotent():
    conn = Connection()
    request = command()
    result = reset_learning(conn, "u", request)
    assert result["generation"] == 2 and result["learning_revision"] == 2
    assert reset_learning(conn, "u", request)["generation"] == 2
    with pytest.raises(ReaderConflict, match="reader_changed"):
        mutate_reader(conn, "u", command(context="stale"))
    assert any("DELETE FROM public.reading_events" in sql for sql in conn.sql)
    assert any("DELETE FROM public.interest_suggestions" in sql for sql in conn.sql)
    # S10 A3: user_feedback_signals must be cleared on reset too, with the same
    # cast strategy as the other two tables now that it's not a special case.
    signal_deletes = [sql for sql in conn.sql if "DELETE FROM public.user_feedback_signals" in sql]
    assert signal_deletes
    for sql in signal_deletes + [s for s in conn.sql if "DELETE FROM public.reading_events" in s
                                  or "DELETE FROM public.interest_suggestions" in s]:
        assert "user_id::text=%s" in sql
        assert "::uuid" not in sql


def test_publication_holds_transaction_and_rejects_every_revision_dimension():
    conn = Connection()
    snapshot = load_reader(conn, "u")
    with publication_guard(conn, "u", snapshot) as allowed:
        assert allowed and conn.depth == 1
    for key in ("generation", "revision", "learning_revision"):
        with pytest.raises(ReaderConflict, match="reader_changed"):
            with publication_guard(conn, "u", {**snapshot, key: 100}):
                pytest.fail("stale publication entered critical section")


def test_deleted_user_cannot_recreate_reader():
    conn = Connection()
    conn.user_exists = False
    with pytest.raises(ReaderNotFound):
        load_reader(conn, "u")


def test_unreviewed_migration_needs_explicit_confirmation():
    conn = Connection()
    conn.profile["migration_status"] = "needs_review"
    with pytest.raises(ReaderConflict, match="migration_review_required"):
        mutate_reader(conn, "u", command(context="draft"))
    assert mutate_reader(conn, "u", {**command(), "confirm_migration": True})["migration_status"] == "ready"
