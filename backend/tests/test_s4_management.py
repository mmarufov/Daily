"""Management commands are explicit, bounded and do not expose credentials."""
from contextlib import nullcontext
import json
from types import SimpleNamespace

import pytest

from scripts import manage_s4_events as cli


RECIPE = "a" * 64
ARTICLE = "00000000-0000-4000-8000-000000000001"


class Connection:
    def __init__(self):
        self.queries = []
    def __enter__(self):
        return self
    def __exit__(self, *args):
        return False
    def transaction(self):
        return nullcontext()
    def execute(self, query, args=None):
        self.queries.append(query)
        if "current_database()" in query:
            row = {"database": "isolated-fixture", "postgres_version": "160000"}
        elif "SELECT * FROM public.event_control" in query:
            row = {"delivery_enabled": True, "daily_budget_usd": "1", "monthly_budget_usd": "10"}
        else:
            row = None
        return SimpleNamespace(fetchone=lambda: row)


@pytest.fixture
def environment(monkeypatch):
    connection = Connection()
    calls = []
    monkeypatch.setenv("S4_TEST_DATABASE", "postgres://secret-user:secret-password@private-host/database")
    monkeypatch.setattr(cli.psycopg, "connect", lambda *args, **kwargs: connection)
    for name in ("ensure_schema", "register_recipe", "set_recipe_enabled", "configure", "set_source",
                 "set_coverage", "replay", "promote", "reconcile"):
        def record(*args, _name=name, **kwargs):
            calls.append((_name, args[1:], kwargs))
            if _name == "reconcile":
                return {"scanned": 0, "inserted": 0, "next_cursor": None}
        monkeypatch.setattr(cli.repo, name, record, raising=False)
    monkeypatch.setattr(cli.repo, "status", lambda conn: {"jobs": [], "control": {"generation": 4}})
    return connection, calls


def invoke(args):
    return cli.main(args + ["--database-env", "S4_TEST_DATABASE"])


@pytest.mark.parametrize("command", ["migrate", "enable", "disable", "configure", "pause", "backfill", "replay", "coverage"])
def test_mutations_default_to_read_only_dry_run(command, environment, capsys):
    args = [command, "--recipe", RECIPE, "--expected-generation", "4", "--job-id", "9", "--reviewed-by", "reviewer"]
    invoke(args)
    connection, calls = environment
    assert calls == []
    assert all(query.startswith("SELECT") or query == "SET TRANSACTION READ ONLY" for query in connection.queries)
    output = json.loads(capsys.readouterr().out)
    assert output["mode"] == "dry_run" and output["expected_generation"] == 4
    assert "secret-password" not in str(output) and "private-host" not in str(output)


def test_status_is_read_only_and_migration_is_explicit(environment, capsys):
    invoke(["status"])
    assert environment[1] == []
    assert json.loads(capsys.readouterr().out)["status"]["control"]["generation"] == 4
    invoke(["migrate", "--apply"])
    assert [item[0] for item in environment[1]] == ["ensure_schema"]


@pytest.mark.parametrize("command", ["enable", "disable"])
def test_recipe_controls_forward_expected_generation(command, environment):
    invoke([command, "--recipe", RECIPE, "--expected-generation", "4", "--apply"])
    assert environment[1] == [("set_recipe_enabled", (RECIPE, command == "enable"), {"expected_generation": 4})]


def test_configure_uses_explicit_budget_strings_and_separate_switches(environment):
    invoke(["configure", "--expected-generation", "4", "--submissions-enabled", "--daily-budget-usd", ".10",
            "--monthly-budget-usd", "2.00", "--apply"])
    assert environment[1][0][2] == {"submissions_enabled": True, "delivery_enabled": False,
        "daily_budget_usd": ".10", "monthly_budget_usd": "2.00", "expected_generation": 4}


def test_pause_preserves_delivery_and_budget_but_cas_fences_the_copy(environment):
    invoke(["pause", "--expected-generation", "4", "--apply"])
    assert environment[1][0][2] == {"submissions_enabled": False, "delivery_enabled": True,
        "daily_budget_usd": "1", "monthly_budget_usd": "10", "expected_generation": 4}


@pytest.mark.parametrize("args", [
    ["configure", "--submissions-enabled", "--expected-generation", "4"],
    ["configure", "--expected-generation", "4", "--daily-budget-usd", "nan"],
    ["configure", "--expected-generation", "4", "--daily-budget-usd", "-1"],
    ["configure"], ["enable", "--recipe", RECIPE], ["disable", "--expected-generation", "4"],
    ["backfill", "--recipe", RECIPE, "--max-rows", "10001"],
    ["backfill", "--recipe", RECIPE, "--after", "bad"],
    ["replay", "--expected-generation", "4", "--job-id", "0"],
    ["coverage", "--expected-generation", "4", "--verified", "--reviewed-by", "operator"],
    ["coverage", "--expected-generation", "4", "--observed-through", "2026-09-06", "--reviewed-by", "operator"],
    ["status", "--database-env", "postgres://password@example.com"],
])
def test_invalid_or_underspecified_command_does_not_connect_or_mutate(args, monkeypatch):
    monkeypatch.setattr(cli.psycopg, "connect", lambda *args, **kwargs: pytest.fail("must validate before connection"))
    with pytest.raises(ValueError):
        cli.main(args)


def test_backfill_is_bounded_and_preserves_cursor_for_resume(environment, monkeypatch, capsys):
    observed = []
    def reconcile(conn, recipe, *, limit, after):
        observed.append((limit, after))
        return {"scanned": limit, "inserted": limit, "next_cursor": ARTICLE if after is None else "00000000-0000-4000-8000-000000000002"}
    monkeypatch.setattr(cli.repo, "reconcile", reconcile)
    invoke(["backfill", "--recipe", RECIPE, "--max-rows", "125", "--apply"])
    assert observed == [(100, None), (25, ARTICLE)]
    assert json.loads(capsys.readouterr().out)["outcome"]["scanned"] == 125


def test_replay_never_resets_attempts_it_calls_repository_reconciliation(environment):
    invoke(["replay", "--job-id", "12", "--expected-generation", "4", "--apply"])
    assert environment[1] == [("replay", (12,), {"expected_generation": 4})]


def test_verified_coverage_requires_an_explicit_reviewed_watermark(environment):
    invoke(["coverage", "--expected-generation", "4", "--observed-through", "2026-09-06T12:00:00Z",
            "--verified", "--reviewed-by", "coverage-monitor", "--apply"])
    assert environment[1][0][2] == {"observed_through": "2026-09-06T12:00:00Z", "verified": True,
                                   "expected_generation": 4, "reviewed_by": "coverage-monitor"}


def test_register_requires_complete_explicit_recipe_and_starts_disabled(environment, monkeypatch):
    definition = dict(cli.repo.DEFAULT_RECIPE, s3_recipe_id="s3-reviewed-recipe")
    monkeypatch.setattr(cli, "_json_file", lambda path: definition)
    invoke(["register", "--recipe-file", "fixture.json", "--apply"])
    assert environment[1] == [("register_recipe", (definition,), {"enabled": False})]


def test_promotion_forwards_three_independent_reviewed_artifacts_without_manufacturing_flags(environment, monkeypatch):
    docs = {"report.json": {"quality_gates_passed": False}, "bindings.json": {"binding": "frozen"},
            "ops.json": {"s1_s2_s3_verified": False}}
    monkeypatch.setattr(cli, "_json_file", lambda path: docs[str(path)])
    invoke(["promote", "--recipe", RECIPE, "--expected-generation", "4", "--report", "report.json",
            "--bindings", "bindings.json", "--operations", "ops.json", "--apply"])
    assert environment[1] == [("promote", (RECIPE,), {"report": docs["report.json"],
        "expected_bindings": docs["bindings.json"], "operations": docs["ops.json"], "expected_generation": 4})]
    assert docs["report.json"]["quality_gates_passed"] is False  # Real repository must reject.


def test_json_duplicate_keys_and_nonfinite_constants_rejected(monkeypatch):
    class Document:
        def __init__(self, text): self.text = text
        def stat(self): return SimpleNamespace(st_size=len(self.text))
        def read_text(self): return self.text
    for text in ('{"x": 1, "x": 2}', '{"budget": NaN}', '[]'):
        with pytest.raises(ValueError):
            cli._json_file(Document(text))


def test_top_level_error_never_prints_driver_credentials(monkeypatch, capsys):
    def failure(argv):
        raise RuntimeError("postgres://secret-user:secret-password@private-host")
    monkeypatch.setattr(cli, "main", failure)
    assert cli.run(["status"]) == 1
    output = capsys.readouterr()
    assert "secret" not in output.err and "private-host" not in output.err
    assert json.loads(output.err)["error"] == "RuntimeError"
