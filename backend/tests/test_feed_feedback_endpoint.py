"""S10 A1/A5: regression tests for the legacy `/feed/feedback` endpoint.

Locks down three fixes: article_id is UUID-validated before any DB write (was
an unhandled 500 on bad input); a retried/duplicate action does not re-apply
learned-weight deltas (was unconditional, so retaps compounded the weight);
hide_source suppresses the specific article, not only future ones from its
source. See docs/stages/s10-learning-audit.md L1/L4/L5/L7 and
docs/stages/s10-implementation-plan.md batch A.
"""
import asyncio
import uuid

import pytest
import tests._app_stubs  # noqa: F401
from app import main


class FakeCursor:
    """Minimal cursor: scripted SELECT results, a settable rowcount, recorded writes."""

    def __init__(self, store):
        self.store = store
        self.rowcount = 0
        self._rows = []

    def execute(self, query, params=None):
        q = " ".join(query.split())
        self.store["executed"].append((q, params))
        self._rows = []
        if q.startswith("SELECT feed_request_id FROM public.user_feed_cache"):
            row = self.store.get("cached_receipt")
            self._rows = [row] if row else []
        elif q.startswith("INSERT INTO public.reading_events"):
            self.rowcount = self.store.get("insert_rowcount", 1)
            self.store["last_insert_params"] = params
            # hide_source's INSERT embeds the event_type as a SQL literal
            # (VALUES (%s, %s, 'hide_source', %s, %s)); the general branch
            # parameterizes it (VALUES (%s, %s, %s, %s, %s)).
            self.store["last_insert_event_type"] = (
                "hide_source" if "'hide_source'" in q else (params[2] if len(params) > 2 else None)
            )
        elif q.startswith("UPDATE public.user_sources"):
            self.store["hide_source_update_params"] = params

    def fetchone(self):
        return self._rows[0] if self._rows else None

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


class FakeConn:
    def __init__(self, *, cached_receipt=None, insert_rowcount=1):
        self.store = {
            "executed": [],
            "cached_receipt": cached_receipt,
            "insert_rowcount": insert_rowcount,
        }

    def cursor(self):
        return FakeCursor(self.store)

    def writes(self):
        return [(q, p) for q, p in self.store["executed"] if q.startswith(("INSERT", "UPDATE"))]


def _auth(monkeypatch, user_id="11111111-1111-1111-1111-111111111111"):
    monkeypatch.setattr(main, "_require_auth", lambda value: "token")
    monkeypatch.setattr(main, "_get_user_id_from_token", lambda *a: user_id)
    monkeypatch.setattr(main, "_clear_user_feed_cache", lambda *a, **kw: None)
    from app.services import reader_integration
    monkeypatch.setattr(reader_integration, "enabled", lambda: False)


def _call(conn, payload):
    return asyncio.run(main.submit_feed_feedback(payload=payload, Authorization="token", conn=conn))


class TestValidation:
    def test_non_uuid_article_id_is_a_clean_400_not_a_500(self, monkeypatch):
        _auth(monkeypatch)
        conn = FakeConn()
        with pytest.raises(main.HTTPException) as error:
            _call(conn, {"article_id": "not-a-uuid", "action": "not_relevant"})
        assert error.value.status_code == 400
        assert conn.writes() == []

    def test_missing_article_id_is_a_400(self, monkeypatch):
        _auth(monkeypatch)
        conn = FakeConn()
        with pytest.raises(main.HTTPException) as error:
            _call(conn, {"action": "not_relevant"})
        assert error.value.status_code == 400

    def test_invalid_action_is_a_400(self, monkeypatch):
        _auth(monkeypatch)
        conn = FakeConn()
        with pytest.raises(main.HTTPException) as error:
            _call(conn, {"article_id": str(uuid.uuid4()), "action": "shrug"})
        assert error.value.status_code == 400


class TestIdempotency:
    def test_new_event_applies_feedback(self, monkeypatch):
        _auth(monkeypatch)
        from app.services import feedback_signals
        applied = monkeypatch.setattr(feedback_signals, "apply_feedback", lambda *a, **kw: 3)
        conn = FakeConn(insert_rowcount=1)
        result = _call(conn, {"article_id": str(uuid.uuid4()), "action": "not_relevant"})
        assert result == {"status": "ok", "action": "not_relevant", "signals_adjusted": 3}

    def test_duplicate_event_does_not_reapply_feedback(self, monkeypatch):
        """The dedup INSERT reported no new row (ON CONFLICT fired) -- a retry
        must not call apply_feedback again, or the weight compounds per retap."""
        _auth(monkeypatch)
        from app.services import feedback_signals
        calls = []
        monkeypatch.setattr(feedback_signals, "apply_feedback",
                             lambda *a, **kw: calls.append(1) or 3)
        conn = FakeConn(insert_rowcount=0)
        result = _call(conn, {"article_id": str(uuid.uuid4()), "action": "not_relevant"})
        assert calls == []
        assert result == {"status": "ok", "action": "not_relevant", "signals_adjusted": 0}


class TestReceiptAttribution:
    def test_cached_receipt_overrides_client_supplied_feed_request_id(self, monkeypatch):
        """The server's own record of what it served outranks a client claim."""
        _auth(monkeypatch)
        real_receipt = str(uuid.uuid4())
        conn = FakeConn(cached_receipt={"feed_request_id": real_receipt}, insert_rowcount=1)
        _call(conn, {"article_id": str(uuid.uuid4()), "action": "less_like_this",
                     "feed_request_id": "client-claimed-stale-id"})
        used = conn.store["last_insert_params"][3]
        assert str(used) == real_receipt

    def test_falls_back_to_client_value_when_nothing_cached(self, monkeypatch):
        """Feedback on an article outside the current cache (e.g. a bookmark)
        still records whatever the client sent, matching prior behavior."""
        _auth(monkeypatch)
        conn = FakeConn(cached_receipt=None, insert_rowcount=1)
        client_value = str(uuid.uuid4())
        _call(conn, {"article_id": str(uuid.uuid4()), "action": "less_like_this",
                     "feed_request_id": client_value})
        used = conn.store["last_insert_params"][3]
        assert used == client_value


class TestHideSourceSuppression:
    def test_hides_the_specific_article_not_only_future_ones(self, monkeypatch):
        """S10 A5: hide_source must also record a suppression event for the
        exact article, or it reappears until the source's other articles age out."""
        _auth(monkeypatch)
        conn = FakeConn()
        result = _call(conn, {"article_id": str(uuid.uuid4()), "action": "hide_source"})
        assert result == {"status": "ok", "action": "hide_source"}
        assert conn.store.get("hide_source_update_params") is not None
        assert conn.store.get("last_insert_event_type") == "hide_source"
