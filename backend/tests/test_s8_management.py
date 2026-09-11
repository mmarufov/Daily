"""Disconnected S8 control-plane checks; all applied connections are test doubles."""
from contextlib import nullcontext
import json
from pathlib import Path
import subprocess
import sys
from unittest.mock import Mock

import pytest

from app.services import assembly_repository as repository
from app.services.assembly_contract import RECIPE
from scripts import manage_s8_assembly as cli


@pytest.fixture
def recipe_file(tmp_path):
    path = tmp_path / 'assembly.json'
    path.write_text(json.dumps(RECIPE))
    return str(path)


@pytest.fixture(autouse=True)
def no_real_connections(monkeypatch):
    import psycopg
    monkeypatch.setattr(psycopg, 'connect', lambda *a, **kw: pytest.fail('real connection forbidden'))
    monkeypatch.setenv('DATABASE_URL', 'postgresql://never-use-implicit:secret@host/private')


@pytest.mark.parametrize('command', ['status', 'install'])
def test_disconnected_by_default(command, monkeypatch, capsys):
    monkeypatch.setattr(cli, 'execute', lambda *a: pytest.fail('must not execute'))
    assert cli.main([command]) == 0
    assert json.loads(capsys.readouterr().out) == {
        'dry_run': True, 'command': command, 'provider_calls': False, 'activation_changed': False}


def test_configure_dry_run_validates_without_activation(recipe_file, monkeypatch, capsys):
    monkeypatch.setattr(cli, 'execute', lambda *a: pytest.fail('must not execute'))
    assert cli.main(['configure', '--recipe-file', recipe_file, '--approve', '--serve']) == 0
    assert json.loads(capsys.readouterr().out)['activation_changed'] is False


@pytest.mark.parametrize('args', [[], ['--database-env', 'S8_NO_DSN']])
def test_apply_requires_explicit_environment_even_if_database_url_exists(args, monkeypatch, capsys):
    monkeypatch.delenv('S8_NO_DSN', raising=False)
    assert cli.main(['install', '--apply', *args]) == 1
    assert json.loads(capsys.readouterr().err)['error'] == 'explicit_populated_database_env_required'


@pytest.mark.parametrize('value', ['', ' ', '\n'])
def test_empty_named_environment_rejected(value, monkeypatch, capsys):
    monkeypatch.setenv('S8_TEST_DSN', value)
    assert cli.main(['status', '--apply', '--database-env', 'S8_TEST_DSN']) == 1
    assert 'explicit_populated_database_env_required' in capsys.readouterr().err


@pytest.mark.parametrize('args', [
    ['status', '--serve'], ['install', '--approve'], ['status', '--recipe-file', 'x'],
    ['configure'], ['status', '--database-env', ''], ['status', '--database-env', 'X;DROP'],
])
def test_invalid_flags_rejected(args):
    assert cli.main(args) == 1


def test_serve_requires_explicit_approval_before_reading_file(capsys):
    assert cli.main(['configure', '--recipe-file', '/missing/recipe', '--serve']) == 1
    assert json.loads(capsys.readouterr().err)['error'] == 'serving_requires_approval'


@pytest.mark.parametrize('args', [['prune'], ['status', '--provider'], ['status', '--app'],
    ['status', '--daily-usd', '5'], ['status', '--unknown', 'postgresql://private:secret@host/db']])
def test_unknown_or_abbreviated_flags_are_secret_safe(args, capsys):
    with pytest.raises(SystemExit) as error:
        cli.main(args)
    assert error.value.code == 2
    assert json.loads(capsys.readouterr().err) == {'error': 'invalid_arguments'}


@pytest.mark.parametrize('value', [None, {}, {**RECIPE, 'unknown': True},
    {**RECIPE, 'publisher_share': float('nan')}, {**RECIPE, 'source_streak': True}])
def test_invalid_recipe_fails_before_connecting(value, tmp_path, capsys):
    path = tmp_path / 'invalid.json'
    path.write_text(json.dumps(value))
    assert cli.main(['configure', '--recipe-file', str(path), '--apply', '--database-env', 'DATABASE_URL']) == 1
    assert json.loads(capsys.readouterr().err)['error'] == 'ValueError'


def test_duplicate_and_oversized_recipes_rejected(tmp_path, capsys):
    path = tmp_path / 'duplicate.json'
    path.write_text('{"version":"secret", "version":"another-secret"}')
    assert cli.main(['configure', '--recipe-file', str(path)]) == 1
    assert json.loads(capsys.readouterr().err)['error'] == 'duplicate_recipe_key'
    path.write_text(' ' * 65_537)
    assert cli.main(['configure', '--recipe-file', str(path)]) == 1
    assert json.loads(capsys.readouterr().err)['error'] == 'recipe_file_too_large'


def test_status_applied_transaction_is_read_only(monkeypatch):
    conn = Mock()
    conn.transaction.return_value = nullcontext()
    monkeypatch.setattr(repository, 'control', lambda connection: {'epoch': 2})
    value = cli.execute(conn, cli.parser().parse_args(['status']))
    conn.execute.assert_called_once_with('SET TRANSACTION READ ONLY')
    assert value == {'installed': True, 'control': {'epoch': 2}, 'activation_changed': False}


def test_status_uninstalled_is_not_installed(monkeypatch):
    conn = Mock()
    conn.transaction.return_value = nullcontext()
    monkeypatch.setattr(repository, 'control', lambda connection: None)
    assert not cli.execute(conn, cli.parser().parse_args(['status']))['installed']


def test_install_does_not_configure(monkeypatch):
    install = Mock()
    monkeypatch.setattr(repository, 'install_schema', install)
    monkeypatch.setattr(repository, 'configure', lambda *a, **kw: pytest.fail('no activation'))
    conn = object()
    assert cli.execute(conn, cli.parser().parse_args(['install']))['activation_changed'] is False
    install.assert_called_once_with(conn)


def test_explicit_apply_uses_bounded_connection_and_exact_validated_recipe(recipe_file, monkeypatch, capsys):
    import psycopg
    conn = Mock()
    connect = Mock(return_value=nullcontext(conn))
    monkeypatch.setattr(psycopg, 'connect', connect)
    monkeypatch.setenv('S8_EXPLICIT_TARGET', 'postgresql://explicit:secret@host/db')
    configure = Mock(return_value={'epoch': 3, 'serving': True})
    monkeypatch.setattr(repository, 'configure', configure)
    assert cli.main(['configure', '--recipe-file', recipe_file, '--approve', '--serve',
                     '--apply', '--database-env', 'S8_EXPLICIT_TARGET']) == 0
    configure.assert_called_once_with(conn, RECIPE, approved=True, serving=True)
    assert connect.call_args.args == ('postgresql://explicit:secret@host/db',)
    assert connect.call_args.kwargs['autocommit'] is True
    assert connect.call_args.kwargs['connect_timeout'] == 10
    assert 'statement_timeout=30000' in connect.call_args.kwargs['options']
    assert 'lock_timeout=5000' in connect.call_args.kwargs['options']
    assert json.loads(capsys.readouterr().out)['activation_changed'] is True


def test_connection_error_never_echoes_dsn(monkeypatch, capsys):
    import psycopg
    monkeypatch.setenv('S8_EXPLICIT_TARGET', 'postgresql://private:secret@host/db')
    monkeypatch.setattr(psycopg, 'connect', Mock(side_effect=RuntimeError('postgresql://private:secret@host/db')))
    assert cli.main(['status', '--apply', '--database-env', 'S8_EXPLICIT_TARGET']) == 1
    assert json.loads(capsys.readouterr().err) == {'error': 'RuntimeError'}


def test_configure_defaults_to_unapproved_not_serving(recipe_file, monkeypatch, capsys):
    import psycopg
    conn = Mock()
    monkeypatch.setattr(psycopg, 'connect', Mock(return_value=nullcontext(conn)))
    configure = Mock(return_value={'epoch': 4, 'approved': False, 'serving': False})
    monkeypatch.setattr(repository, 'configure', configure)
    assert cli.main(['configure', '--recipe-file', recipe_file, '--apply', '--database-env', 'DATABASE_URL']) == 0
    configure.assert_called_once_with(conn, RECIPE, approved=False, serving=False)


def test_configure_missing_schema_is_not_reported_as_applied(recipe_file, monkeypatch, capsys):
    import psycopg
    monkeypatch.setattr(psycopg, 'connect', Mock(return_value=nullcontext(Mock())))
    monkeypatch.setattr(repository, 'configure', Mock(return_value=None))
    assert cli.main(['configure', '--recipe-file', recipe_file, '--apply', '--database-env', 'DATABASE_URL']) == 1
    assert json.loads(capsys.readouterr().err) == {'error': 'assembly_schema_not_installed'}


@pytest.mark.parametrize('command', ['status', 'install', 'configure'])
def test_script_entry_point_is_cwd_independent_and_disconnected(command, recipe_file, tmp_path):
    args = [sys.executable, str(Path(cli.__file__).resolve()), command]
    if command == 'configure':
        args.extend(['--recipe-file', recipe_file, '--approve', '--serve'])
    completed = subprocess.run(args, cwd=tmp_path, check=True, capture_output=True, text=True, timeout=10)
    assert json.loads(completed.stdout) == {
        'dry_run': True, 'command': command, 'provider_calls': False, 'activation_changed': False}
