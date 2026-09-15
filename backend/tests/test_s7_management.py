import json
from pathlib import Path
import subprocess
import sys
import pytest

from scripts import manage_s7_ranking as cli


@pytest.mark.parametrize('command', ['status', 'install', 'prune'])
def test_disconnected_by_default(command, monkeypatch, capsys):
    monkeypatch.setattr(cli, 'execute', lambda *a: pytest.fail('must not connect'))
    assert cli.main([command]) == 0
    result = json.loads(capsys.readouterr().out)
    assert result['dry_run'] and not result['provider_calls'] and not result['activation_changed']


def test_configure_dry_run_does_not_read_recipe_or_enable(monkeypatch, capsys):
    monkeypatch.setattr(cli, 'execute', lambda *a: pytest.fail('must not connect'))
    assert cli.main(['configure', '--recipe-file', '/missing/recipe', '--approve', '--serve']) == 0
    assert json.loads(capsys.readouterr().out)['activation_changed'] is False


@pytest.mark.parametrize('args', [[], ['--database-env', ''], ['--database-env', 'S7_NO_DSN']])
def test_explicit_database_required(args, monkeypatch, capsys):
    monkeypatch.delenv('S7_NO_DSN', raising=False)
    assert cli.main(['install', '--apply', *args]) == 1
    assert 'explicit_populated_database_env_required' in capsys.readouterr().err


@pytest.mark.parametrize('args', [ ['status', '--serve'], ['install', '--provider'],
    ['configure'], ['status', '--database-env', 'SECRET;bad']])
def test_invalid_management_arguments(args):
    assert cli.main(args) == 1


def test_script_entry_point_does_not_depend_on_current_directory(tmp_path):
    completed = subprocess.run([sys.executable, str(Path(cli.__file__).resolve()), 'status'],
                               cwd=tmp_path, check=True, capture_output=True, text=True,
                               timeout=10)
    assert json.loads(completed.stdout) == {
        'dry_run': True, 'command': 'status', 'provider_calls': False,
        'activation_changed': False,
    }
