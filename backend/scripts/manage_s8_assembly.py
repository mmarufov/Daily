#!/usr/bin/env python3
"""Explicit S8 administration: disconnected unless --apply and a named DSN env.

Dry-run configure validates only a local recipe. Installation does not approve or
activate assembly. No provider, model, spend, pruning or implicit DATABASE_URL.
"""
import argparse
import json
import os
from pathlib import Path
import re
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


class SafeParser(argparse.ArgumentParser):
    def error(self, message):
        # argparse's default includes unknown argument values, which may be DSNs.
        self.exit(2, json.dumps({'error': 'invalid_arguments'}) + '\n')


def parser():
    result = SafeParser(description=__doc__, allow_abbrev=False)
    result.add_argument('command', choices=('status', 'install', 'configure'))
    result.add_argument('--apply', action='store_true')
    result.add_argument('--database-env')
    result.add_argument('--recipe-file')
    result.add_argument('--approve', action='store_true')
    result.add_argument('--serve', action='store_true')
    return result


def _unique_object(pairs):
    value = {}
    for key, item in pairs:
        if key in value:
            raise ValueError('duplicate_recipe_key')
        value[key] = item
    return value


def load_recipe(path):
    from app.services.assembly_contract import validate_recipe
    with Path(path).open('rb') as source:
        data = source.read(65_537)
    if len(data) > 65_536:
        raise ValueError('recipe_file_too_large')
    return validate_recipe(json.loads(data, object_pairs_hook=_unique_object))


def execute(conn, args):
    from app.services import assembly_repository as repository
    if args.command == 'install':
        repository.install_schema(conn)
        return {'installed': True, 'activation_changed': False}
    if args.command == 'status':
        with conn.transaction():
            conn.execute('SET TRANSACTION READ ONLY')
            state = repository.control(conn)
        return {'installed': state is not None, 'control': state, 'activation_changed': False}
    state = repository.configure(conn, args.validated_recipe, approved=args.approve, serving=args.serve)
    if state is None:
        raise ValueError('assembly_schema_not_installed')
    return {'control': state, 'activation_changed': True}


def main(argv=None):
    args = parser().parse_args(argv)
    try:
        if args.database_env is not None and not re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]*', args.database_env):
            raise ValueError('invalid_database_environment_variable_name')
        if args.command != 'configure' and (args.recipe_file is not None or args.approve or args.serve):
            raise ValueError('configuration_flags_require_configure')
        if args.command == 'configure':
            if not args.recipe_file:
                raise ValueError('explicit_recipe_file_required')
            if args.serve and not args.approve:
                raise ValueError('serving_requires_approval')
            # Validate before any connection; reuse the same value, not a changed file.
            args.validated_recipe = load_recipe(args.recipe_file)
        if not args.apply:
            print(json.dumps({'dry_run': True, 'command': args.command,
                              'provider_calls': False, 'activation_changed': False}))
            return 0
        if not args.database_env or not os.environ.get(args.database_env, '').strip():
            raise ValueError('explicit_populated_database_env_required')
        import psycopg
        from psycopg.rows import dict_row
        with psycopg.connect(os.environ[args.database_env], autocommit=True, row_factory=dict_row,
                connect_timeout=10, options='-c statement_timeout=30000 -c lock_timeout=5000') as conn:
            result = execute(conn, args)
        print(json.dumps({**result, 'provider_calls': False}, default=str))
        return 0
    except Exception as exc:
        # Neither arbitrary error strings nor connection/provider/account inputs are safe.
        safe_codes = {'invalid_database_environment_variable_name',
                      'configuration_flags_require_configure', 'explicit_recipe_file_required',
                      'explicit_populated_database_env_required', 'serving_requires_approval',
                      'duplicate_recipe_key', 'recipe_file_too_large', 'assembly_schema_not_installed'}
        code = str(exc) if type(exc) is ValueError and str(exc) in safe_codes else type(exc).__name__
        print(json.dumps({'error': code}), file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
