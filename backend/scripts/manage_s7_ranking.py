#!/usr/bin/env python3
"""Explicit S7 administration, disconnected unless --apply and named database env.

Schema installation defaults to zero spend and no serving. Configuring approval,
prices or activation is an explicit operator action, not part of app startup.
"""
import argparse
import json
import os
from pathlib import Path
import re
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def parser():
    result = argparse.ArgumentParser(description=__doc__)
    result.add_argument('command', choices=('status', 'install', 'configure', 'prune'))
    result.add_argument('--apply', action='store_true')
    result.add_argument('--database-env')
    result.add_argument('--recipe-file')
    result.add_argument('--approve', action='store_true')
    result.add_argument('--serve', action='store_true')
    result.add_argument('--provider', action='store_true')
    result.add_argument('--daily-usd', default='0')
    result.add_argument('--account-daily-usd', default='0')
    return result


def execute(conn, args):
    from app.services import ranking_repository as repository
    if args.command == 'install':
        repository.install_schema(conn)
        return {'installed': True, 'activation_changed': False}
    if args.command == 'status':
        with conn.transaction():
            conn.execute('SET TRANSACTION READ ONLY')
            state = repository.control(conn)
            delivery_ready = conn.execute("""SELECT
                to_regclass('public.ranking_publication_counters') IS NOT NULL
                AND EXISTS(SELECT 1 FROM information_schema.columns
                  WHERE table_schema='public' AND table_name='ranking_results'
                    AND column_name='publication_sequence') AS ready""").fetchone()['ready']
        return {'installed': state is not None, 'control': state, 'activation_changed': False,
                'delivery_schema_ready': delivery_ready}
    if args.command == 'configure':
        recipe = json.loads(Path(args.recipe_file).read_text())
        state = repository.configure(conn, recipe, approved=args.approve,
            serving=args.serve, provider=args.provider, daily_usd=args.daily_usd,
            account_daily_usd=args.account_daily_usd)
        return {'control': state, 'activation_changed': True}
    repository.prune(conn)
    return {'pruned': True, 'activation_changed': False}


def main(argv=None):
    args = parser().parse_args(argv)
    try:
        if args.database_env and not re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]*', args.database_env):
            raise ValueError('invalid_database_environment_variable_name')
        if args.command != 'configure' and (args.recipe_file or args.approve or args.serve
                or args.provider or args.daily_usd != '0' or args.account_daily_usd != '0'):
            raise ValueError('configuration_flags_require_configure')
        if args.command == 'configure' and not args.recipe_file:
            raise ValueError('explicit_recipe_file_required')
        if not args.apply:
            print(json.dumps({'dry_run': True, 'command': args.command,
                              'provider_calls': False, 'activation_changed': False}))
            return 0
        if not args.database_env or not os.environ.get(args.database_env):
            raise ValueError('explicit_populated_database_env_required')
        import psycopg
        from psycopg.rows import dict_row
        with psycopg.connect(os.environ[args.database_env], autocommit=True, row_factory=dict_row,
                connect_timeout=10, options='-c statement_timeout=30000 -c lock_timeout=5000') as conn:
            result = execute(conn, args)
        print(json.dumps({**result, 'provider_calls': False}, default=str))
        return 0
    except Exception as exc:
        # Never print provider/account inputs, arbitrary exception messages or DSNs.
        safe_codes = {'invalid_database_environment_variable_name',
                      'configuration_flags_require_configure', 'explicit_recipe_file_required',
                      'explicit_populated_database_env_required'}
        code = str(exc) if type(exc) is ValueError and str(exc) in safe_codes else type(exc).__name__
        print(json.dumps({'error': code}), file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
