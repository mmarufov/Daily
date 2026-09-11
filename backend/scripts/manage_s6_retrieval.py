#!/usr/bin/env python3
"""Explicit S6 index operations. Every command is disconnected until --apply.

Example: manage_s6_retrieval.py index --database-env RETRIEVAL_DATABASE_URL --apply
No schema installation, provider calls, retrieval activation or ANN activation.
"""
import argparse
from dataclasses import dataclass
from importlib.metadata import PackageNotFoundError, version
import json
import os
import re
import sys


@dataclass(frozen=True)
class Index:
    name: str
    relation: str
    method: str
    expression: str
    predicate: str = ''
    owned: bool = True

    def ddl(self):
        where = f' WHERE {self.predicate}' if self.predicate else ''
        return (f'CREATE INDEX CONCURRENTLY {self.name} ON public.{self.relation} '
                f'USING {self.method} ({self.expression}){where}')


INDEXES = (
    # Reuse the S5-owned expression; S6 must never drop another stage's index.
    Index('reader_article_lexical', 'articles', 'gin',
          "to_tsvector('simple',COALESCE(title,'')||' '||COALESCE(summary,''))", owned=False),
    Index('s6_article_time', 'articles', 'btree', 'COALESCE(published_at,ingested_at) DESC,id'),
    Index('s6_current_facets', 'article_understanding_results', 'gin', 'payload', "stage='facets'"),
)
DENSE = Index('s6_result_embedding_hnsw', 'article_understanding_results', 'hnsw',
              'embedding vector_cosine_ops', "stage='embedding'")


class ManagementError(Exception):
    """Only controlled codes and static index names may leave the tool."""
    def __init__(self, code, index=None):
        self.code, self.index = code, index
        super().__init__(code)


def parser():
    result = argparse.ArgumentParser(description=__doc__)
    result.add_argument('command', choices=('status', 'index', 'dense-index'))
    result.add_argument('--apply', action='store_true')
    result.add_argument('--database-env', help='Explicit environment variable containing the target DSN')
    result.add_argument('--repair-invalid', action='store_true',
                        help='Rebuild invalid S6-owned indexes only; never repairs definition mismatches')
    return result


def _normalized_definition(value):
    # Compare the exact fixed expressions while tolerating PostgreSQL deparse
    # parentheses, regconfig/text casts and schema qualification. These recipes
    # contain no arithmetic whose precedence could be changed by parentheses.
    # Preserve quoted whitespace: the lexical separator must stay a literal space.
    parts = re.split(r"('(?:[^']|'')*')", value)
    def unquoted(part):
        part = re.sub(r'::(?:regconfig|text)\b', '', part.lower())
        part = part.replace('public.', '').replace(' concurrently ', ' ')
        return re.sub(r'[\s()]', '', part)
    return ''.join(part if i % 2 else unquoted(part) for i, part in enumerate(parts))


def index_state(conn, spec):
    row = conn.execute('''SELECT i.indisvalid AS valid,i.indisready AS ready,
        i.indisunique AS unique, i.indisprimary AS primary,
        ns.nspname AS table_schema,t.relname AS table_name,
        pg_get_indexdef(c.oid) AS definition
        FROM pg_catalog.pg_class c
        JOIN pg_catalog.pg_namespace n ON n.oid=c.relnamespace
        LEFT JOIN pg_catalog.pg_index i ON i.indexrelid=c.oid
        LEFT JOIN pg_catalog.pg_class t ON t.oid=i.indrelid
        LEFT JOIN pg_catalog.pg_namespace ns ON ns.oid=t.relnamespace
        WHERE n.nspname='public' AND c.relname=%s''', (spec.name,)).fetchone()
    if row is None:
        return {'name': spec.name, 'exists': False, 'valid': False, 'matches': False}
    expected = spec.ddl().replace(' CONCURRENTLY', '')
    matches = (row['table_schema'] == 'public' and row['table_name'] == spec.relation
               and not row['unique'] and not row['primary']
               and _normalized_definition(row['definition'] or '') == _normalized_definition(expected))
    # Index definitions contain column names/expressions only, not reader rows.
    return {'name': spec.name, 'exists': True, 'valid': bool(row['valid'] and row['ready']),
            'matches': matches, 'definition': row['definition']}


def _require_relation(conn, spec):
    row = conn.execute('''SELECT c.relkind FROM pg_catalog.pg_class c
        JOIN pg_catalog.pg_namespace n ON n.oid=c.relnamespace
        WHERE n.nspname='public' AND c.relname=%s''', (spec.relation,)).fetchone()
    if not row or row['relkind'] != 'r':
        raise ManagementError('base_relation_missing_or_unsupported_install_S1_S3_first', spec.name)


def _require_dense(conn):
    ext = conn.execute("SELECT extversion FROM pg_catalog.pg_extension WHERE extname='vector'").fetchone()
    match = re.match(r'^(\d+)\.(\d+)\.(\d+)', ext['extversion']) if ext else None
    if not match or tuple(map(int, match.groups())) < (0, 5, 0):
        raise ManagementError('server_vector_extension_0_5_or_newer_required', DENSE.name)
    row = conn.execute('''SELECT format_type(a.atttypid,a.atttypmod) AS geometry
        FROM pg_catalog.pg_attribute a WHERE a.attrelid=to_regclass('public.article_understanding_results')
        AND a.attname='embedding' AND NOT a.attisdropped''').fetchone()
    if not row or row['geometry'] != 'vector(1536)':
        raise ManagementError('S3_embedding_geometry_must_be_vector_1536', DENSE.name)


def provision(conn, specs, repair=False):
    if not conn.autocommit:
        raise ManagementError('concurrent_indexes_require_autocommit')
    # Validate the entire requested set before starting any DDL.
    states = []
    for spec in specs:
        _require_relation(conn, spec)
        if spec == DENSE:
            _require_dense(conn)
        state = index_state(conn, spec)
        if state['exists'] and not state['matches']:
            raise ManagementError('index_definition_mismatch_manual_resolution_required', spec.name)
        if state['exists'] and not state['valid']:
            if not spec.owned:
                raise ManagementError('invalid_S5_index_requires_S5_operator_repair', spec.name)
            if not repair:
                raise ManagementError('invalid_index_rerun_with_repair_invalid', spec.name)
        states.append(state)
    results = []
    for spec, state in zip(specs, states):
        if state['exists'] and not state['valid']:
            # Name is selected exclusively from the fixed S6-owned registry.
            conn.execute(f'DROP INDEX CONCURRENTLY public.{spec.name}')
        if not state['exists'] or not state['valid']:
            conn.execute(spec.ddl())
        verified = index_state(conn, spec)
        if not verified['valid'] or not verified['matches']:
            raise ManagementError('index_post_build_validation_failed', spec.name)
        results.append(verified)
    return {'indexes': results, 'activation_changed': False, 'ann_activated': False}


def status(conn):
    with conn.transaction():
        conn.execute('SET TRANSACTION READ ONLY')
        postgres = conn.execute('SHOW server_version').fetchone()['server_version']
        ext = conn.execute("SELECT extversion FROM pg_catalog.pg_extension WHERE extname='vector'").fetchone()
        states = [index_state(conn, spec) for spec in (*INDEXES, DENSE)]
    try:
        python_vector = version('pgvector')
    except PackageNotFoundError:
        python_vector = None
    return {'postgresql_server_version': postgres,
            'vector_server_extension_version': ext['extversion'] if ext else None,
            'pgvector_python_package_version': python_vector, 'indexes': states,
            'activation_changed': False, 'ann_activated': False}


def execute(conn, args):
    if args.command == 'status':
        return status(conn)
    return provision(conn, INDEXES if args.command == 'index' else (DENSE,), args.repair_invalid)


def main(argv=None):
    args = parser().parse_args(argv)
    try:
        if args.database_env and not re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]*', args.database_env):
            raise ManagementError('invalid_database_environment_variable_name')
        if args.repair_invalid and args.command == 'status':
            raise ManagementError('repair_requires_index_command')
        if not args.apply:
            specs = INDEXES if args.command == 'index' else (DENSE,) if args.command == 'dense-index' else ()
            print(json.dumps({'dry_run': True, 'command': args.command,
                              'planned_indexes': [spec.name for spec in specs],
                              'provider_calls': False, 'activation_changed': False}))
            return 0
        if not args.database_env or not os.environ.get(args.database_env):
            raise ManagementError('explicit_populated_database_env_required')
        import psycopg
        from psycopg.rows import dict_row
        with psycopg.connect(os.environ[args.database_env], autocommit=True, row_factory=dict_row,
                connect_timeout=10, options='-c statement_timeout=300000 -c lock_timeout=5000') as conn:
            result = execute(conn, args)
        print(json.dumps(result, default=str))
        return 0
    except Exception as exc:
        # Database failures can echo DSNs, SQL parameters or credentials.
        error = {'error': exc.code if isinstance(exc, ManagementError) else type(exc).__name__}
        if isinstance(exc, ManagementError) and exc.index:
            error['index'] = exc.index
        print(json.dumps(error), file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
