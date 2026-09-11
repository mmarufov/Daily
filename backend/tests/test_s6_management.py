"""Disconnected control-plane tests. These do not claim real query-plan/index proof."""
from contextlib import nullcontext
import json
from unittest.mock import Mock

import pytest

from scripts import manage_s6_retrieval as cli


class Connection:
    autocommit = True

    def __init__(self, indexes=None, relation='r', extension='0.8.0', geometry='vector(1536)'):
        self.indexes = indexes or {}
        self.relation, self.extension, self.geometry = relation, extension, geometry
        self.statements = []

    def transaction(self):
        return nullcontext()

    def execute(self, sql, params=()):
        self.statements.append(sql)
        result = None
        if 'pg_get_indexdef' in sql:
            result = self.indexes.get(params[0])
        elif 'SELECT c.relkind' in sql:
            result = {'relkind': self.relation} if self.relation else None
        elif 'SELECT extversion' in sql:
            result = {'extversion': self.extension} if self.extension else None
        elif 'SELECT format_type' in sql:
            result = {'geometry': self.geometry}
        elif 'SHOW server_version' in sql:
            result = {'server_version': '17.6'}
        elif sql.startswith('CREATE INDEX'):
            spec = next(s for s in (*cli.INDEXES, cli.DENSE) if s.ddl() == sql)
            self.indexes[spec.name] = row(spec)
        elif sql.startswith('DROP INDEX'):
            del self.indexes[sql.rsplit('.', 1)[1]]
        return Mock(fetchone=lambda: result)


def row(spec, valid=True, definition=None):
    return {'valid': valid, 'ready': True, 'unique': False, 'primary': False,
            'table_schema': 'public', 'table_name': spec.relation,
            'definition': definition or spec.ddl().replace(' CONCURRENTLY', '')}


@pytest.mark.parametrize('command', ['status', 'index', 'dense-index'])
def test_default_disconnected(command, monkeypatch, capsys):
    monkeypatch.setattr(cli, 'execute', lambda *a: pytest.fail('must not connect'))
    assert cli.main([command]) == 0
    value = json.loads(capsys.readouterr().out)
    assert value['dry_run'] and value['provider_calls'] is False


@pytest.mark.parametrize('args', [[], ['--database-env', ''], ['--database-env', 'UNKNOWN_S6_DSN']])
def test_apply_requires_explicit_populated_environment(args, monkeypatch, capsys):
    monkeypatch.delenv('UNKNOWN_S6_DSN', raising=False)
    assert cli.main(['index', '--apply', *args]) == 1
    assert 'explicit_populated_database_env_required' in capsys.readouterr().err


def test_database_name_and_repair_arguments_validated():
    assert cli.main(['index', '--database-env', 'X;DROP']) == 1
    assert cli.main(['status', '--repair-invalid']) == 1


def test_indexes_on_real_relations_and_dense_separate():
    conn = Connection()
    result = cli.provision(conn, cli.INDEXES)
    assert all(index['valid'] and index['matches'] for index in result['indexes'])
    ddl = [sql for sql in conn.statements if sql.startswith('CREATE')]
    assert len(ddl) == 3
    assert all('CONCURRENTLY' in sql for sql in ddl)
    assert any('COALESCE(published_at,ingested_at)' in sql for sql in ddl)
    assert any("article_understanding_results USING gin (payload) WHERE stage='facets'" in sql for sql in ddl)
    assert not any('hnsw' in sql or 'articles.embedding' in sql for sql in ddl)
    assert not result['activation_changed'] and not result['ann_activated']


def test_valid_indexes_do_not_rebuild():
    conn = Connection({spec.name: row(spec) for spec in cli.INDEXES})
    cli.provision(conn, cli.INDEXES)
    assert not any(sql.startswith(('CREATE', 'DROP')) for sql in conn.statements)


@pytest.mark.parametrize('relation', [None, 'v', 'p'])
def test_missing_view_partitioned_relation_rejected_before_ddl(relation):
    conn = Connection(relation=relation)
    with pytest.raises(cli.ManagementError, match='base_relation'):
        cli.provision(conn, cli.INDEXES)
    assert not any(sql.startswith(('CREATE', 'DROP')) for sql in conn.statements)


def test_interrupted_build_requires_explicit_repair():
    spec = cli.INDEXES[1]
    conn = Connection({spec.name: row(spec, valid=False)})
    with pytest.raises(cli.ManagementError, match='rerun_with_repair_invalid'):
        cli.provision(conn, (spec,))
    cli.provision(conn, (spec,), repair=True)
    assert f'DROP INDEX CONCURRENTLY public.{spec.name}' in conn.statements
    assert conn.indexes[spec.name]['valid']


def test_S5_owned_invalid_index_never_dropped():
    spec = cli.INDEXES[0]
    conn = Connection({spec.name: row(spec, valid=False)})
    with pytest.raises(cli.ManagementError, match='S5_operator_repair'):
        cli.provision(conn, (spec,), repair=True)
    assert not any(sql.startswith('DROP') for sql in conn.statements)


def test_wrong_existing_definition_never_dropped_even_repair():
    spec = cli.INDEXES[1]
    conn = Connection({spec.name: row(spec, valid=False, definition=spec.ddl().replace('DESC', 'ASC'))})
    with pytest.raises(cli.ManagementError, match='definition_mismatch'):
        cli.provision(conn, (spec,), repair=True)
    assert not any(sql.startswith('DROP') for sql in conn.statements)


def test_catalog_deparse_matches_lexical_but_wrong_literal_does_not():
    spec = cli.INDEXES[0]
    definition = ("CREATE INDEX reader_article_lexical ON public.articles USING gin "
                  "(to_tsvector('simple'::regconfig, ((COALESCE(title, ''::text) || ' '::text) "
                  "|| COALESCE(summary, ''::text))))")
    conn = Connection({spec.name: row(spec, definition=definition)})
    assert cli.index_state(conn, spec)['matches']
    conn.indexes[spec.name]['definition'] = definition.replace("' '::text", "''::text")
    assert not cli.index_state(conn, spec)['matches']


@pytest.mark.parametrize('extension,geometry', [(None, 'vector(1536)'), ('0.4.4', 'vector(1536)'),
                                               ('0.8.0', 'vector(768)')])
def test_dense_requires_actual_server_extension_and_geometry(extension, geometry):
    conn = Connection(extension=extension, geometry=geometry)
    with pytest.raises(cli.ManagementError):
        cli.provision(conn, (cli.DENSE,))
    assert not any(sql.startswith('CREATE') for sql in conn.statements)


def test_dense_is_partial_S3_cosine_and_does_not_activate():
    conn = Connection()
    result = cli.provision(conn, (cli.DENSE,))
    ddl = next(sql for sql in conn.statements if sql.startswith('CREATE'))
    assert "article_understanding_results USING hnsw (embedding vector_cosine_ops) WHERE stage='embedding'" in ddl
    assert not result['ann_activated']
    assert not any(sql.startswith('UPDATE') for sql in conn.statements)


def test_predicate_literal_case_is_not_normalized():
    spec = cli.INDEXES[2]
    conn = Connection({spec.name: row(spec, definition=spec.ddl().replace("'facets'", "'FACETS'"))})
    assert not cli.index_state(conn, spec)['matches']


def test_status_distinguishes_versions_without_reading_profiles(monkeypatch):
    monkeypatch.setattr(cli, 'version', lambda package: '0.3.6')
    conn = Connection()
    result = cli.status(conn)
    assert result['vector_server_extension_version'] == '0.8.0'
    assert result['pgvector_python_package_version'] == '0.3.6'
    assert result['postgresql_server_version'] == '17.6'
    assert not any('reader_profiles' in sql for sql in conn.statements)
    assert 'SET TRANSACTION READ ONLY' in conn.statements


def test_connection_failure_does_not_expose_dsn(monkeypatch, capsys):
    import psycopg
    monkeypatch.setenv('S6_TEST_DSN', 'postgres://secret:password@private-host/db')
    monkeypatch.setattr(psycopg, 'connect', Mock(side_effect=RuntimeError('secret password private-host')))
    assert cli.main(['status', '--database-env', 'S6_TEST_DSN', '--apply']) == 1
    assert json.loads(capsys.readouterr().err) == {'error': 'RuntimeError'}


def test_concurrent_ddl_rejects_transactional_connection():
    conn = Connection()
    conn.autocommit = False
    with pytest.raises(cli.ManagementError, match='autocommit'):
        cli.provision(conn, cli.INDEXES)
    assert not conn.statements
