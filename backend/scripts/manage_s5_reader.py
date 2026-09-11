#!/usr/bin/env python3
"""Explicit S5 schema/budget operations. Dry-run by default; no provider calls.

Use --apply to execute against the named database environment variable. This tool
never enables semantic delivery or starts a worker. Install S1-S3 schemas first.
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
    result.add_argument('command', choices=('migrate', 'index', 'cleanup', 'status', 'budget', 'pause'))
    result.add_argument('--database-env', default='DATABASE_URL')
    result.add_argument('--apply', action='store_true')
    result.add_argument('--daily-global-tokens', type=int)
    result.add_argument('--daily-user-tokens', type=int)
    return result


def execute(conn, args):
    if args.command == 'index':
        # Deliberately outside a transaction; run separately from schema migration
        # to avoid blocking article writes while building the corpus index.
        conn.execute("""CREATE INDEX CONCURRENTLY IF NOT EXISTS reader_article_lexical
            ON public.articles USING gin
            (to_tsvector('simple',COALESCE(title,'')||' '||COALESCE(summary,'')))""")
        return {'lexical_index_requested': True}
    if args.command == 'cleanup':
        removed = {}
        # Bounded sweeps; schedule repeatedly to cover inactive readers too.
        with conn.transaction():
            for table, days in (('reader_operations', 7), ('reader_proposals', 1),
                                ('reader_feedback_events', 30), ('reader_delivery_receipts', 30)):
                result = conn.execute(f'''DELETE FROM public.{table} WHERE ctid IN
                    (SELECT ctid FROM public.{table} WHERE created_at < now()-(%s*interval '1 day')
                     LIMIT 1000 FOR UPDATE SKIP LOCKED)''', (days,))
                removed[table] = result.rowcount
            for table in ('reader_embedding_user_spend', 'reader_embedding_global_spend'):
                result = conn.execute(f'''DELETE FROM public.{table} WHERE ctid IN
                    (SELECT ctid FROM public.{table} WHERE day < (now() AT TIME ZONE 'UTC')::date-90
                     LIMIT 1000 FOR UPDATE SKIP LOCKED)''')
                removed[table] = result.rowcount
        return {'removed': removed}
    if args.command == 'migrate':
        from app.services import reader_repository, reader_feedback, reader_worker
        with conn.transaction():
            reader_repository.install_schema(conn)
            reader_feedback.install_schema(conn)
            reader_worker.install_schema(conn)
        return {'schema_installed': True, 'activation_changed': False}
    if args.command == 'status':
        with conn.transaction():
            conn.execute('SET TRANSACTION READ ONLY')
            control = conn.execute('SELECT * FROM public.reader_embedding_control').fetchone()
            profiles = conn.execute('''SELECT migration_status,count(*) AS count
                FROM public.reader_profiles GROUP BY migration_status''').fetchall()
            jobs = conn.execute('''SELECT state,count(*) AS count FROM public.reader_embedding_jobs
                GROUP BY state''').fetchall()
        return {'embedding_control': control, 'profiles': profiles, 'jobs': jobs}
    with conn.transaction():
        if args.command == 'pause':
            conn.execute('UPDATE public.reader_embedding_control SET enabled=false')
        else:
            conn.execute('''UPDATE public.reader_embedding_control SET enabled=true,
                daily_global_tokens=%s,daily_user_tokens=%s''',
                (args.daily_global_tokens, args.daily_user_tokens))
    return {'embedding_work_enabled': args.command == 'budget'}


def main(argv=None):
    args = parser().parse_args(argv)
    try:
        if not re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]*', args.database_env):
            raise ValueError('database environment variable name required')
        if args.command == 'budget' and not (
            args.daily_user_tokens is not None and args.daily_global_tokens is not None
            and 0 < args.daily_user_tokens <= args.daily_global_tokens <= 1_000_000_000
        ):
            raise ValueError('explicit bounded positive user and global budgets required')
        if not args.apply:
            print(json.dumps({'dry_run': True, 'command': args.command, 'provider_calls': False}))
            return 0
        import psycopg
        from psycopg.rows import dict_row
        with psycopg.connect(os.environ[args.database_env], autocommit=True, row_factory=dict_row,
                connect_timeout=10, options='-c statement_timeout=30000 -c lock_timeout=5000') as conn:
            result = execute(conn, args)
        print(json.dumps(result, default=str))
        return 0
    except Exception as exc:
        # Driver messages may include credentials or private query parameters.
        print(json.dumps({'error': type(exc).__name__}), file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
