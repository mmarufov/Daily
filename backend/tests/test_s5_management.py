"""Offline control-plane checks; dry runs must never open a connection."""
from contextlib import nullcontext
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from scripts import manage_s5_reader as cli


@pytest.mark.parametrize('command', ['migrate', 'index', 'cleanup', 'status', 'pause'])
def test_default_is_disconnected_dry_run(command, monkeypatch, capsys):
    monkeypatch.delenv('DATABASE_URL', raising=False)
    assert cli.main([command]) == 0
    assert '"dry_run": true' in capsys.readouterr().out


@pytest.mark.parametrize('values', [[], ['--daily-global-tokens', '100', '--daily-user-tokens', '0'],
    ['--daily-global-tokens', '10', '--daily-user-tokens', '20']])
def test_budget_needs_explicit_positive_bounded_values(values):
    assert cli.main(['budget', *values]) == 1


def test_budget_and_pause_do_not_enable_delivery():
    conn = Mock()
    conn.transaction.return_value = nullcontext()
    cli.execute(conn, SimpleNamespace(command='budget', daily_global_tokens=100, daily_user_tokens=10))
    sql, values = conn.execute.call_args.args
    assert 'reader_embedding_control' in sql and values == (100, 10)
    assert 'semantic' not in sql and 'understanding_control' not in sql
    cli.execute(conn, SimpleNamespace(command='pause'))
    assert 'enabled=false' in conn.execute.call_args.args[0]
