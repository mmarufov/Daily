"""Validation and summarisation for the Phase 7.2 crash-report ingest.

Everything in a report except the account it arrives on is device-controlled,
so the interesting cases are all adversarial: oversized payloads, a wrong
device clock, an OS reporting a diagnostic kind this build has never heard of,
and the retry that must not double-count a crash. The storage half runs against
a real server in `test_client_diagnostics_postgres.py`.
"""
import importlib
import sys
import uuid
from datetime import datetime, timedelta, timezone

import pytest

import tests._app_stubs  # noqa: F401


def _module(name):
    """Resolve `app.*` at call time; see test_account_lifecycle._module."""
    return sys.modules.get(name) or importlib.import_module(name)


@pytest.fixture()
def diagnostics():
    return _module("app.services.client_diagnostics")


def _report(**overrides):
    base = {
        "report_id": str(uuid.uuid4()),
        "captured_at": "2026-09-12T10:00:00Z",
        "app_version": "1.0",
        "build_number": "42",
        "os_version": "Version 26.0",
        "kinds": ["crash"],
        "payload": '{"crashDiagnostics":[]}',
        "truncated": False,
    }
    base.update(overrides)
    return base


class RecordingConn:
    """Accepts the INSERT and reports a stored row unless told otherwise."""

    def __init__(self, *, conflicts=()):
        self.executed = []
        self.conflicts = set(conflicts)

    def execute(self, query, params=None):
        self.executed.append((" ".join(query.split()), params))
        report_id = str(params[0]) if params else None
        return _Result(None if report_id in self.conflicts else {"report_id": report_id})

    def transaction(self):
        return _Noop()


class _Result:
    def __init__(self, row):
        self._row = row

    def fetchone(self):
        return self._row


class _Noop:
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


class TestBatchShape:
    def test_a_batch_must_be_a_list_of_reports(self, diagnostics):
        for body in ({}, {"reports": None}, {"reports": []}, {"reports": "x"}, []):
            with pytest.raises(diagnostics.DiagnosticsRejected):
                diagnostics.ingest(RecordingConn(), str(uuid.uuid4()), body)

    def test_an_oversized_batch_is_rejected(self, diagnostics):
        body = {"reports": [_report() for _ in range(diagnostics.MAX_REPORTS_PER_REQUEST + 1)]}
        with pytest.raises(diagnostics.DiagnosticsRejected):
            diagnostics.ingest(RecordingConn(), str(uuid.uuid4()), body)

    def test_one_bad_report_rejects_the_whole_batch_before_any_write(self, diagnostics):
        """Parse everything first: a half-stored batch would make the client's
        retry ambiguous, and it has no way to report which half landed."""
        conn = RecordingConn()
        body = {"reports": [_report(), _report(payload="")]}
        with pytest.raises(diagnostics.DiagnosticsRejected):
            diagnostics.ingest(conn, str(uuid.uuid4()), body)
        assert conn.executed == []


class TestFieldValidation:
    @pytest.mark.parametrize("field", ["app_version", "build_number", "os_version"])
    def test_labels_are_required_and_bounded(self, diagnostics, field):
        for bad in (None, "", "   ", 7, "x" * (diagnostics.MAX_LABEL_CHARS + 1)):
            with pytest.raises(diagnostics.DiagnosticsRejected):
                diagnostics.ingest(RecordingConn(), str(uuid.uuid4()),
                                   {"reports": [_report(**{field: bad})]})

    def test_report_id_must_be_a_uuid(self, diagnostics):
        for bad in (None, "", "not-a-uuid", 12):
            with pytest.raises(diagnostics.DiagnosticsRejected):
                diagnostics.ingest(RecordingConn(), str(uuid.uuid4()),
                                   {"reports": [_report(report_id=bad)]})

    def test_payload_must_be_a_non_empty_bounded_string(self, diagnostics):
        for bad in (None, "", {}, "x" * (diagnostics.MAX_PAYLOAD_CHARS + 1)):
            with pytest.raises(diagnostics.DiagnosticsRejected):
                diagnostics.ingest(RecordingConn(), str(uuid.uuid4()),
                                   {"reports": [_report(payload=bad)]})

    def test_a_payload_at_the_limit_is_accepted(self, diagnostics):
        """The client caps itself just under this; an off-by-one here would
        silently 422 exactly the biggest (most interesting) crash reports."""
        conn = RecordingConn()
        body = {"reports": [_report(payload="x" * diagnostics.MAX_PAYLOAD_CHARS)]}
        assert diagnostics.ingest(conn, str(uuid.uuid4()), body)["stored"] == 1

    def test_kinds_must_be_a_bounded_non_empty_list(self, diagnostics):
        for bad in (None, [], "crash", ["crash"] * 9, [""], [1]):
            with pytest.raises(diagnostics.DiagnosticsRejected):
                diagnostics.ingest(RecordingConn(), str(uuid.uuid4()),
                                   {"reports": [_report(kinds=bad)]})

    def test_an_unrecognised_kind_is_bucketed_rather_than_rejected(self, diagnostics):
        """A future OS reporting something this build has never heard of must
        not cost us the report; the original label survives in the payload."""
        conn = RecordingConn()
        diagnostics.ingest(conn, str(uuid.uuid4()),
                           {"reports": [_report(kinds=["crash", "neural_engine_fault"])]})
        stored_kinds = conn.executed[0][1][6]
        assert stored_kinds == '["crash", "unknown"]'

    def test_kinds_are_deduplicated_and_ordered(self, diagnostics):
        conn = RecordingConn()
        diagnostics.ingest(conn, str(uuid.uuid4()),
                           {"reports": [_report(kinds=["hang", "crash", "hang"])]})
        assert conn.executed[0][1][6] == '["crash", "hang"]'


class TestTimestamps:
    def test_a_naive_timestamp_is_read_as_utc(self, diagnostics):
        conn = RecordingConn()
        diagnostics.ingest(conn, str(uuid.uuid4()),
                           {"reports": [_report(captured_at="2026-09-12T10:00:00")]})
        assert conn.executed[0][1][2].tzinfo is not None

    def test_a_future_timestamp_is_clamped_not_rejected(self, diagnostics):
        """Device clocks are wrong in both directions. A crash report with a bad
        timestamp is still a crash report."""
        conn = RecordingConn()
        ahead = (datetime.now(timezone.utc) + timedelta(days=3650)).isoformat()
        diagnostics.ingest(conn, str(uuid.uuid4()), {"reports": [_report(captured_at=ahead)]})
        assert conn.executed[0][1][2] <= datetime.now(timezone.utc)

    def test_an_unparseable_timestamp_is_rejected(self, diagnostics):
        for bad in (None, "", "yesterday", 17):
            with pytest.raises(diagnostics.DiagnosticsRejected):
                diagnostics.ingest(RecordingConn(), str(uuid.uuid4()),
                                   {"reports": [_report(captured_at=bad)]})


class TestIdempotency:
    def test_a_retried_report_is_accepted_but_not_stored_twice(self, diagnostics):
        """`DiagnosticsService.flush` retries a batch whose response was lost.
        Double-counting one crash as two would misreport a build's stability."""
        report = _report()
        conn = RecordingConn(conflicts=[report["report_id"]])
        assert diagnostics.ingest(conn, str(uuid.uuid4()), {"reports": [report]}) == {
            "accepted": 1, "stored": 0
        }

    def test_the_insert_is_conflict_tolerant(self, diagnostics):
        conn = RecordingConn()
        diagnostics.ingest(conn, str(uuid.uuid4()), {"reports": [_report()]})
        assert "ON CONFLICT (report_id) DO NOTHING" in conn.executed[0][0]


class TestBounds:
    def test_client_and_server_payload_caps_agree(self):
        """The iOS client truncates at its own ceiling; if the server's were
        lower, every truncated report would still 422."""
        from pathlib import Path

        swift = Path(__file__).resolve().parents[2] / "Daily/Services/DiagnosticsService.swift"
        source = swift.read_text()
        diagnostics = _module("app.services.client_diagnostics")
        assert f"maxPayloadBytes = {diagnostics.MAX_PAYLOAD_CHARS:_}" in source
        assert f"maxLabelCharacters = {diagnostics.MAX_LABEL_CHARS}" in source

    def test_a_full_batch_still_fits_under_the_request_body_limit(self, diagnostics):
        """main.py's middleware returns 413 above 1MB, and the client treats a
        413 as permanent -- so a batch that overruns the cap doesn't just fail,
        it discards up to five crash reports. The client therefore batches by
        total payload size, not just count; this pins the two ends together."""
        from pathlib import Path

        swift = Path(__file__).resolve().parents[2] / "Daily/Services/DiagnosticsService.swift"
        source = swift.read_text()
        assert f"maxReportsPerRequest = {diagnostics.MAX_REPORTS_PER_REQUEST}" in source
        assert "maxRequestPayloadBytes = 800_000" in source
        assert 800_000 < 1_048_576, "the client's per-request budget must stay under the 413 cap"
        assert diagnostics.MAX_PAYLOAD_CHARS < 800_000, (
            "a single maximum payload has to fit in one request on its own"
        )
