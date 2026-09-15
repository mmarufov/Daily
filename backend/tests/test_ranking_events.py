"""Offline S7/S4 publication adapter checks; no provider or hosted SQL calls."""
from copy import deepcopy
from datetime import datetime
from uuid import UUID

import pytest

from app.services import event_repository as repo, ranking_events as events, reader_retrieval
from app.services.event_contract import dependency_digest
from app.services.reader_contract import validate_profile
from app.services.reader_repository import ReaderConflict
from test_event_contract import assessment
from test_event_consumers import NOW, candidate, ordinary


def event():
    value = candidate()
    value['snapshot']['event_id'] = str(UUID(int=1))
    value['development_id'] = str(UUID(int=2))
    for index, (evidence, representative) in enumerate(zip(value['snapshot']['evidence'], value['representatives']), 3):
        identifier = str(UUID(int=index))
        evidence['dependency']['article_id'] = identifier
        representative.update(development_id=value['development_id'])
        representative['article'].update(id=identifier, url='https://example.com/report', language='en',
                                         source_name='Publisher', summary='Report', analysis_revoked=False)
    value['snapshot']['dependency_digest'] = dependency_digest(value['snapshot']['evidence'])
    value['assessment'] = assessment(value['snapshot'], tier='world_critical')
    return value


class Rows:
    def __init__(self, rows):
        self.rows = rows

    def fetchall(self):
        return self.rows

    def fetchone(self):
        return self.rows[0] if self.rows else None


class Connection:
    def __init__(self, value):
        self.value = value
        self.queries = []
        self.now = datetime.fromisoformat(NOW)
        self.version = 1
        self.members = True
        self.hidden = []
        self.seen = []
        self.changed_article = False

    def execute(self, query, params=None):
        self.queries.append(query)
        assert not any(word in query.upper() for word in ('INSERT ', 'UPDATE ', 'DELETE '))
        value = self.value
        if 'SELECT clock_timestamp()' in query:
            return Rows([{'time': self.now}])
        if 'FROM public.event_developments' in query:
            return Rows([{'id': UUID(value['development_id']), 'event_id': UUID(value['snapshot']['event_id']),
                          'version': self.version}])
        if 'FROM public.event_evidence' in query:
            return Rows([{'article_id': rep['article']['id'], 'payload': {
                'role': rep['role'], 'dependency': {'source_id': rep['source_id']}}}
                for rep in value['representatives']] if self.members else [])
        if 'FROM public.articles a LEFT JOIN' in query:
            row = deepcopy(next(rep['article'] for rep in value['representatives'] if rep['article']['id'] == params[0]))
            if self.changed_article:
                row['title'] = 'Corrected report'
            return Rows([row])
        if 'SELECT DISTINCT article_id FROM public.reading_events' in query:
            return Rows(self.hidden)
        if 'WITH RECURSIVE' in query:
            return Rows(self.seen)
        if 'FROM public.events WHERE' in query:
            return Rows([{'id': UUID(value['snapshot']['event_id'])}])
        raise AssertionError(query)


@pytest.fixture
def harness(monkeypatch):
    value = event()
    conn = Connection(value)
    current = {'current_assessment': value['assessment_id'], 'lifecycle': 'active'}
    recipe = {'id': value['snapshot']['recipe_id'], 'approved': True,
              'definition': {'maximum_observation_lag_seconds': 3600}}
    control = {'delivery_enabled': True, 'serving_recipe': recipe['id']}
    monkeypatch.setattr(repo, '_controls', lambda *a, **k: ({}, control, recipe, {}))
    monkeypatch.setattr(repo, '_validate_dependencies', lambda *a: current)
    monkeypatch.setattr(reader_retrieval, '_s6_recipe', lambda *a: {})
    fresh = {rep['article']['id']: {'policy': {'topic_ids': [], 'place_ids': [], 'entity_ids': [], 'sector_ids': []}}
             for rep in value['representatives']}
    monkeypatch.setattr(reader_retrieval, '_s6_hydrate', lambda *a: fresh)
    return conn, value, current, recipe, fresh


def compose(harness, profile=None):
    conn, value, *_ = harness
    return events.compose(conn, str(UUID(int=100)), {'status': 'ready', 'articles': [ordinary()], 'article_count': 1},
                          [value], profile or validate_profile({}), limit=5)


@pytest.mark.parametrize('capability,flag', [(None, 'true'), ('0', 'true'), ('1', 'false'), ('1', '')])
def test_disabled_or_unsupported_never_reads_events(monkeypatch, capability, flag):
    monkeypatch.setenv('S4_CONSUMERS_ENABLED', flag)
    monkeypatch.setattr(repo, 'load_candidates', lambda *a: pytest.fail('unexpected event read'))
    assert events.prepare(None, capability) == []


def test_empty_events_do_not_access_connection():
    result = {'articles': [ordinary()]}
    assert events.compose(None, 'user', result, [], {}, limit=5) is result
    events.lock_sources(None, [])


def test_prepare_bounds_union_lock_set(monkeypatch):
    monkeypatch.setenv('S4_CONSUMERS_ENABLED', 'true')
    values = [event() for _ in range(3)]
    for index, value in enumerate(values):
        value['representatives'] = []
        value['snapshot']['evidence'] = [{'dependency': {'article_id': str(UUID(int=1000 + index * 128 + n))}}
                                         for n in range(128)]
    monkeypatch.setattr(repo, 'load_candidates', lambda *a: values)
    assert events.prepare(None, '1') == []


def test_representative_must_belong_to_locked_dependencies():
    value = event()
    value['representatives'][0]['article']['id'] = str(UUID(int=999))
    with pytest.raises(ReaderConflict, match='not_in_snapshot'):
        events.article_ids([value])


@pytest.mark.parametrize('part', ['candidates', 'evidence', 'representatives'])
def test_each_dependency_collection_is_bounded(part):
    value = event()
    values = [value]
    if part == 'candidates':
        values *= 129
    elif part == 'evidence':
        value['snapshot']['evidence'] *= 65
    else:
        value['representatives'] *= 65
    with pytest.raises(ReaderConflict, match='unbounded'):
        events.article_ids(values)


@pytest.mark.parametrize('failure', [None, 'missing', 'moved', 'disabled', 'unapproved', 'changed_recipe'])
def test_source_and_control_locks_fail_closed(monkeypatch, failure):
    value = event()
    recipe = {'id': value['snapshot']['recipe_id'], 'approved': failure != 'unapproved'}
    control = {'delivery_enabled': failure != 'disabled',
               'serving_recipe': 'changed' if failure == 'changed_recipe' else recipe['id']}
    locked = []
    def controls(*args, **kwargs):
        assert kwargs == {'lock': True}
        locked.append('controls')
        return {}, control, recipe, {}
    monkeypatch.setattr(repo, '_controls', controls)
    class Sources:
        def execute(self, sql, params):
            if 'article_source_policies' in sql:
                locked.append('policies')
                return Rows([])
            rows = [{'id': str(index), 'source_domain': 'example.com'}
                    for index, _ in enumerate(events.article_ids([value]))]
            if failure == 'missing':
                rows.pop()
            if 'FOR SHARE' in sql:
                locked.append('sources')
                if failure == 'moved':
                    rows[0]['source_domain'] = 'changed.example.com'
            return Rows(rows)
    if failure:
        with pytest.raises(ReaderConflict):
            events.lock_sources(Sources(), [value])
    else:
        events.lock_sources(Sources(), [value])
        assert locked == ['controls', 'policies', 'sources']


def test_success_uses_current_policy_and_never_writes_receipts(harness):
    output = compose(harness)
    assert output['article_count'] == 2
    assert output['articles'][0]['event_delivery']['development_version'] == 1
    assert output['articles'][-1] == ordinary()
    assert all('event_delivery_receipts' not in query or 'JOIN' in query for query in harness[0].queries)


@pytest.mark.parametrize('changed', ['assessment', 'lifecycle', 'development', 'membership', 'representative'])
def test_changed_publication_dependencies_abort(harness, changed):
    conn, value, current, *_ = harness
    if changed == 'assessment':
        current['current_assessment'] = 'replaced'
    elif changed == 'lifecycle':
        current['lifecycle'] = 'retired'
    elif changed == 'development':
        conn.version = 2
    elif changed == 'membership':
        conn.members = False
    else:
        conn.changed_article = True
    with pytest.raises(ReaderConflict):
        compose(harness)


def test_expired_assessment_aborts(harness):
    harness[0].now = datetime.fromisoformat(harness[1]['assessment']['valid_until'])
    with pytest.raises(ValueError):
        compose(harness)


def test_expired_observation_aborts(harness):
    harness[3]['definition']['maximum_observation_lag_seconds'] = 0
    with pytest.raises(ReaderConflict, match='coverage_expired'):
        compose(harness)


def test_subject_unknown_fails_closed_in_canonical_policy(harness):
    profile = validate_profile({'policies': [{'id': str(UUID(int=999)), 'kind': 'subject', 'scope': 'topic', 'value': 'blocked-topic'}]})
    for value in harness[4].values():
        value['policy']['topic_ids'] = None
    assert compose(harness, profile)['articles'] == [ordinary()]


def test_explicit_canonical_publisher_rule_is_applied(harness):
    profile = validate_profile({'policies': [{'id': str(UUID(int=999)), 'kind': 'publisher', 'value': 'example.com'}]})
    assert compose(harness, profile)['articles'] == [ordinary()]


def test_reader_hide_and_seen_suppress_priority(harness):
    conn, value, *_ = harness
    conn.hidden = [{'article_id': rep['article']['id']} for rep in value['representatives']]
    assert compose(harness)['articles'] == [ordinary()]
    conn.hidden = []
    conn.seen = [{'development_id': value['development_id'], 'development_version': 1}]
    assert compose(harness)['articles'] == [ordinary()]


def test_display_stamp_normalizes_only_timestamp_values():
    now = datetime.fromisoformat(NOW)
    assert events._display_stamp({'published_at': now}) == events._display_stamp({'published_at': NOW})
    assert events._display_stamp({'published_at': NOW}) == events._display_stamp({'published_at': str(now)})
    assert events._display_stamp({'title': '2026-09-06 12:01:00+00:00'}) != events._display_stamp({'title': NOW})
