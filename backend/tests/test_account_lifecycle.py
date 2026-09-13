"""Offline tests for the Phase 7.1 account-lifecycle endpoints and wiring.

The real proof that deletion is *complete* needs a live server and lives in
`test_account_lifecycle_postgres.py`. What is checked here is everything that
doesn't: the endpoints' contracts, that a failed purge is not surfaced to the
caller as an error, that the auth chokepoint and the background loops now all
exclude deleted accounts, and that the maintenance loop is actually started.
"""
import asyncio
import importlib
import inspect
import sys
import uuid

import pytest

import tests._app_stubs  # noqa: F401

USER_ID = "11111111-1111-1111-1111-111111111111"


def _module(name):
    """Resolve `app.*` at call time, never at import time.

    `test_app_middleware.py` evicts and re-imports every `app.*` module during
    collection so it can exercise the real FastAPI instead of the stub. A
    module-level `from app import main` here would bind the pre-eviction object
    while the endpoint under test resolves the post-eviction one, so patches
    would land on a module nobody calls -- passing alone, failing in the full
    suite. See tasks/lessons.md, "A test suite with no conftest.py has
    order-dependent behaviour".
    """
    return sys.modules.get(name) or importlib.import_module(name)


@pytest.fixture()
def main():
    return _module("app.main")


@pytest.fixture()
def lifecycle():
    return _module("app.services.account_lifecycle")


class FakeCursor:
    def __init__(self, store):
        self.store = store
        self.rowcount = 0
        self._rows = []

    def execute(self, query, params=None):
        self.store["executed"].append((" ".join(query.split()), params))
        self._rows = []

    def fetchone(self):
        return self._rows[0] if self._rows else None

    def fetchall(self):
        return list(self._rows)

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


class FakeConn:
    def __init__(self, **store):
        self.store = {"executed": [], **store}

    def cursor(self):
        return FakeCursor(self.store)


def _auth(monkeypatch, main, user_id=USER_ID):
    monkeypatch.setattr(main, "_require_auth", lambda value: "token")
    monkeypatch.setattr(main, "_get_user_id_from_token", lambda *a: user_id)


def _source_of(obj) -> str:
    return " ".join(inspect.getsource(obj).split())


class TestSessionRevocationEndpoints:
    def test_sign_out_revokes_exactly_this_token(self, monkeypatch, main, lifecycle):
        _auth(monkeypatch, main)
        seen = []

        def revoke(conn, token):
            seen.append(token)
            return True

        monkeypatch.setattr(lifecycle, "revoke_session", revoke)
        result = asyncio.run(main.revoke_current_session(Authorization="Bearer abc", conn=FakeConn()))
        assert result == {"revoked": True}
        assert seen == ["token"]

    def test_signing_out_an_already_dead_token_is_not_an_error(self, monkeypatch, main, lifecycle):
        """A client retrying sign-out after a flaky network must not see a 4xx --
        it would have to special-case an outcome that is already what it wanted."""
        _auth(monkeypatch, main)
        monkeypatch.setattr(lifecycle, "revoke_session", lambda conn, token: False)
        assert asyncio.run(
            main.revoke_current_session(Authorization="Bearer abc", conn=FakeConn())
        ) == {"revoked": False}

    def test_sign_out_requires_a_bearer_token(self, main):
        with pytest.raises(main.HTTPException) as error:
            asyncio.run(main.revoke_current_session(Authorization=None, conn=FakeConn()))
        assert error.value.status_code == 401

    def test_sign_out_everywhere_reports_how_many_sessions_died(self, monkeypatch, main, lifecycle):
        _auth(monkeypatch, main)
        monkeypatch.setattr(lifecycle, "revoke_all_sessions", lambda conn, uid: 3)
        assert asyncio.run(
            main.revoke_all_user_sessions(Authorization="Bearer abc", conn=FakeConn())
        ) == {"revoked": 3}


class TestDeletionEndpoint:
    def test_deleting_reports_both_steps(self, monkeypatch, main, lifecycle):
        _auth(monkeypatch, main)
        monkeypatch.setattr(lifecycle, "soft_delete_account", lambda conn, uid: True)
        monkeypatch.setattr(lifecycle, "purge_account", lambda conn, uid: True)
        assert asyncio.run(
            main.delete_user_account(Authorization="Bearer abc", conn=FakeConn())
        ) == {"deleted": True, "purged": True}

    def test_a_failing_purge_still_reports_the_account_deleted(self, monkeypatch, main, lifecycle):
        """Step 1 committed, so the account really is gone from the reader's point
        of view. Raising here would invite a retry that can only re-run a no-op,
        and would tell the reader their deletion failed when it did not."""
        _auth(monkeypatch, main)
        monkeypatch.setattr(lifecycle, "soft_delete_account", lambda conn, uid: True)

        def boom(conn, uid):
            raise RuntimeError("lock timeout")

        monkeypatch.setattr(lifecycle, "purge_account", boom)
        assert asyncio.run(
            main.delete_user_account(Authorization="Bearer abc", conn=FakeConn())
        ) == {"deleted": True, "purged": False}

    def test_deleting_twice_is_idempotent(self, monkeypatch, main, lifecycle):
        _auth(monkeypatch, main)
        monkeypatch.setattr(lifecycle, "soft_delete_account", lambda conn, uid: False)
        monkeypatch.setattr(lifecycle, "purge_account", lambda conn, uid: False)
        assert asyncio.run(
            main.delete_user_account(Authorization="Bearer abc", conn=FakeConn())
        ) == {"deleted": False, "purged": False}

    def test_deletion_requires_a_bearer_token(self, main):
        with pytest.raises(main.HTTPException) as error:
            asyncio.run(main.delete_user_account(Authorization=None, conn=FakeConn()))
        assert error.value.status_code == 401


class TestDeletedAccountsAreExcludedEverywhere:
    """`is_deleted` had five readers and no writer. Now that it has one, every
    path that resolves or enumerates accounts has to honour it -- otherwise a
    tombstone keeps authenticating, keeps getting feeds built, and keeps
    costing money."""

    def test_token_resolution_filters_deleted_accounts(self, main):
        assert "NOT COALESCE(u.is_deleted, false)" in _source_of(main._get_user_id_from_token)

    def test_me_filters_deleted_accounts(self, main):
        assert "NOT COALESCE(u.is_deleted, false)" in _source_of(main.me)

    def test_per_user_refresh_skips_deleted_accounts(self, main):
        assert "NOT COALESCE(u.is_deleted, false)" in _source_of(main._active_users_with_sources)

    def test_background_ranking_refresh_skips_deleted_accounts(self, main):
        assert "NOT COALESCE(is_deleted, false)" in _source_of(main._refresh_s7_background)


class TestMaintenanceLoopWiring:
    def test_the_loop_has_its_own_advisory_lock_key(self, main):
        """Every background loop elects independently; a shared key would make
        two loops fight over one leadership token."""
        assert "account_maintenance" in main._LOCK_KEYS
        assert len(set(main._LOCK_KEYS.values())) == len(main._LOCK_KEYS)

    def test_lifespan_starts_and_cancels_the_loop(self, main):
        source = _source_of(main.lifespan)
        assert "_account_maintenance_loop()" in source
        assert "account_task" in source

    def test_purge_pending_isolates_one_bad_account_from_the_batch(self, monkeypatch, lifecycle):
        ids = [str(uuid.uuid4()) for _ in range(3)]
        monkeypatch.setattr(lifecycle, "pending_purge_ids", lambda conn, limit=50: ids)
        attempted = []

        def purge(conn, account_id):
            attempted.append(account_id)
            if account_id == ids[1]:
                raise RuntimeError("contended")
            return True

        monkeypatch.setattr(lifecycle, "purge_account", purge)
        assert lifecycle.purge_pending_accounts(FakeConn()) == 2
        assert attempted == ids


class TestPurgeCoversUnlinkedTables:
    def test_the_known_orphans_are_listed(self, lifecycle):
        """feed_build_log has no FK at all; ranking_budget is keyed by a text
        account column and is otherwise covered only by a trigger that exists
        solely on databases where the optional S7 schema was installed."""
        assert dict(lifecycle._ORPHAN_USER_TABLES) == {
            "feed_build_log": "user_id",
            "ranking_budget": "account",
        }

    def test_orphan_table_names_are_static_identifiers(self, lifecycle):
        """These names are concatenated into SQL, so they must never be able to
        carry anything but a bare identifier."""
        for table, column in lifecycle._ORPHAN_USER_TABLES:
            assert table.replace("_", "").isalnum()
            assert column.replace("_", "").isalnum()
