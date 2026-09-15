"""Offline S6 execution contracts, without provider calls or a database server.

These tests exercise real policy checks, candidate construction, allocation and
refill. SQL snapshot/index/cancellation guarantees have a separate PostgreSQL gate.
"""
from contextlib import nullcontext
from copy import deepcopy
from datetime import datetime, timezone
from types import SimpleNamespace
from uuid import UUID

import pytest
from psycopg.pq import TransactionStatus
from pydantic import ValidationError

from app.services import reader_retrieval as retrieval
from app.services.retrieval_contract import CandidateBatch, RECIPE, RetrievalRequest


USER = str(UUID(int=10000))
NOW = datetime(2026, 9, 7, 12, tzinfo=timezone.utc)


def intent(number=1, **values):
    return {'id': str(UUID(int=number)), 'kind': 'topic', 'label': 'Science',
            'priority': 1.0, **values}


def snapshot(intents=None, **profile):
    return {'generation': 1, 'revision': 3, 'learning_revision': 2,
            'migration_status': 'ready',
            'profile': {'intents': [intent()] if intents is None else intents, **profile}}


def hit(number, **values):
    return {'id': str(UUID(int=number)), 'score': 1.0 / (number + 1), **values}


def policy(kind='lexical', value='blocked', **values):
    return {'id': str(UUID(int=20000)), 'kind': kind, 'value': value, **values}


class Connection:
    def __init__(self):
        self.info = SimpleNamespace(transaction_status=TransactionStatus.IDLE)
        self.sql = []

    def transaction(self):
        return nullcontext()

    def execute(self, sql, params=()):
        self.sql.append((sql, params))
        return SimpleNamespace(fetchone=lambda: None, fetchall=lambda: [])


class Harness:
    def __init__(self, monkeypatch, sources=None, *, recipe=None, vectors=None):
        self.conn = Connection()
        self.sources = sources or {}
        self.articles = {}
        self.current = {}
        self.policies = {}
        self.pages = []
        self.hydrations = []
        self.config = {**RECIPE, 'dense_requested': bool(vectors),
                       'min_similarity': .5 if vectors else None, 'ann': False}
        monkeypatch.setattr(retrieval, '_s6_recipe', lambda conn: recipe)
        monkeypatch.setattr(retrieval, '_s6_vectors',
                            lambda *args: (vectors or {}, 'test-space' if vectors else None))
        monkeypatch.setattr(retrieval, '_s6_page', self.page)
        monkeypatch.setattr(retrieval, '_s6_hydrate', self.hydrate)

    def page(self, conn, state, *, count, **kwargs):
        key = (state['intent'], state['leg'], state['variant'])
        self.pages.append((key, count))
        source = self.sources.get(key, [])
        if isinstance(source, Exception):
            raise source
        offset = 0
        if state.get('cursor'):
            offset = next(i + 1 for i, value in enumerate(source)
                          if str(value['id']) == state['cursor'][1])
        return deepcopy(source[offset:offset + count])

    def hydrate(self, conn, identifiers, recipe):
        self.hydrations.append(list(identifiers))
        return {key: {'article': self.articles.get(key, {
            'id': key, 'title': 'Science report', 'summary': 'Publisher summary',
            'url': 'https://publisher.example.com/story/' + key,
            'ingested_at': NOW, 'published_at': NOW}),
            'current': self.current.get(key, {}),
            'policy': self.policies.get(key, {})} for key in identifiers}

    def run(self, reader=None, **kwargs):
        return retrieval.build_candidate_batch(self.conn, USER, reader or snapshot(),
            as_of=NOW, configuration=self.config, **kwargs)


def lexical(item, rows, variant='strict'):
    return {(item['id'], 'lexical', variant): rows}


def test_zero_requested_candidates_is_empty_not_budget_degradation(monkeypatch):
    harness = Harness(monkeypatch)
    batch = harness.run(limit=0)
    assert batch.status == 'empty'
    assert batch.candidates == []
    assert harness.pages == []


def test_explicit_zero_deadline_is_not_replaced_with_default(monkeypatch):
    harness = Harness(monkeypatch)
    with pytest.raises(retrieval.RetrievalDeadline):
        harness.run(deadline=0, clock=lambda: 0.0)
    assert harness.pages == []


def test_single_lexical_leg_can_supply_full_300_without_legacy_cap(monkeypatch):
    harness = Harness(monkeypatch, lexical(intent(), [hit(i) for i in range(1, 601)]))
    batch = harness.run()
    assert len(batch.candidates) == 300
    assert batch.status == 'complete'
    assert batch.diagnostics['stop_reason'] == 'target_reached'
    assert batch.diagnostics['unique_examined'] == 300
    assert all(len(chunk) <= 300 for chunk in harness.hydrations)
    assert not any('relevant' in item.article for item in batch.candidates)
    assert any('REPEATABLE READ READ ONLY' in sql for sql, _ in harness.conn.sql)


def test_denied_first_page_refills_before_applying_candidate_quota(monkeypatch):
    harness = Harness(monkeypatch, lexical(intent(), [hit(i) for i in range(1, 351)]))
    for i in range(1, 301):
        identifier = str(UUID(int=i))
        harness.articles[identifier] = {'id': identifier, 'title': 'blocked',
            'url': 'https://publisher.example.com/story'}
    batch = harness.run(snapshot(policies=[policy()]), limit=50)
    assert {item.article_id for item in batch.candidates} == {str(UUID(int=i)) for i in range(301, 351)}
    assert batch.diagnostics['rounds'] == 2
    assert batch.diagnostics['rejected']['policy_denied'] == 300
    assert batch.diagnostics['unique_examined'] == 350


def test_equal_intents_receive_equal_disjoint_allocations(monkeypatch):
    left, right = intent(1), intent(2, label='Culture')
    sources = {**lexical(left, [hit(i) for i in range(1, 301)]),
               **lexical(right, [hit(i) for i in range(1001, 1301)])}
    batch = Harness(monkeypatch, sources).run(snapshot([left, right]), limit=100)
    assert sum(item.allocated_intent_id == left['id'] for item in batch.candidates) == 50
    assert sum(item.allocated_intent_id == right['id'] for item in batch.candidates) == 50


def test_priority_weights_allocate_actual_supply_without_starving_small_interest(monkeypatch):
    left, right = intent(1, priority=3.0), intent(2, label='Culture')
    sources = {**lexical(left, [hit(i) for i in range(1, 301)]),
               **lexical(right, [hit(i) for i in range(1001, 1301)])}
    batch = Harness(monkeypatch, sources).run(snapshot([left, right]), limit=40)
    assert sum(item.allocated_intent_id == left['id'] for item in batch.candidates) == 30
    assert sum(item.allocated_intent_id == right['id'] for item in batch.candidates) == 10


def test_shared_candidates_deduplicate_but_retain_all_matching_attribution(monkeypatch):
    left, right = intent(1), intent(2, label='Culture')
    rows = [hit(i) for i in range(1, 101)]
    batch = Harness(monkeypatch, {**lexical(left, rows), **lexical(right, rows)}).run(
        snapshot([left, right]), limit=100)
    assert len(batch.candidates) == len({item.article_id for item in batch.candidates}) == 100
    assert all(item.matched_intent_ids == [left['id'], right['id']] for item in batch.candidates)
    assert all(item.allocated_intent_id in item.matched_intent_ids for item in batch.candidates)
    assert batch.diagnostics['unique_examined'] == 100


def test_strict_and_label_are_one_fusion_family_and_mark_unresolved_qualifiers(monkeypatch):
    item = intent(query='Science climate')
    rows = [hit(1)]
    sources = {**lexical(item, rows), **lexical(item, rows, 'label')}
    batch = Harness(monkeypatch, sources).run(snapshot([item]))
    candidate = batch.candidates[0]
    assert candidate.retrieval_score == pytest.approx(1 / 61)
    assert {match.variant for match in candidate.matches} == {'strict', 'label'}
    assert {match.variant: match.unresolved_qualifiers for match in candidate.matches} == {
        'strict': False, 'label': True}


def test_identity_available_independently_of_dense_enabled(monkeypatch):
    item = intent(kind='entity', resolved_id='entity:apple')
    row = hit(1, input_hash='current-hash', semantic_revision=2, analysis_eligibility_generation=3)
    harness = Harness(monkeypatch, {(item['id'], 'identity', 'entity'): [row]},
                      recipe={'id': 'recipe'})
    harness.current[row['id']] = {'facets': {'entities': []}, 'input_hash': 'current-hash',
        'semantic_revision': 2, 'analysis_eligibility_generation': 3, 'recipe_id': 'recipe'}
    harness.policies[row['id']] = {'entity_ids': ['entity:apple']}
    batch = harness.run(snapshot([item]))
    assert len(batch.candidates) == 1
    assert batch.candidates[0].matches[0].leg == 'identity'
    assert any(leg['leg'] == 'dense' and leg['status'] == 'disabled'
               for leg in batch.diagnostics['legs'])


@pytest.mark.parametrize('field', ['input_hash', 'semantic_revision', 'analysis_eligibility_generation'])
def test_stale_derived_match_cannot_survive_current_evidence_fence(monkeypatch, field):
    item = intent(kind='entity', resolved_id='entity:apple')
    row = hit(1, input_hash='current-hash', semantic_revision=2, analysis_eligibility_generation=3)
    harness = Harness(monkeypatch, {(item['id'], 'identity', 'entity'): [row]}, recipe={'id': 'recipe'})
    harness.current[row['id']] = {**row, 'facets': {'entities': []}, field: 'changed'}
    harness.policies[row['id']] = {'entity_ids': ['entity:apple']}
    batch = harness.run(snapshot([item]))
    assert not batch.candidates
    assert batch.diagnostics['rejected']['stale_or_unresolved_evidence'] == 1


def test_ordinary_lexical_metadata_does_not_require_analysis_permission(monkeypatch):
    harness = Harness(monkeypatch, lexical(intent(), [hit(1)]))
    harness.current[str(UUID(int=1))] = {'state': 'ineligible'}
    batch = harness.run()
    assert len(batch.candidates) == 1
    assert batch.candidates[0].matches[0].leg == 'lexical'


@pytest.mark.parametrize('profile', [
    {'languages': ['en']},
    {'policies': [policy('subject', 'energy', scope='sector')]},
    {'policies': [policy('subject', 'entity:apple', scope='entity')]},
])
def test_unknown_hard_policy_evidence_fails_closed(monkeypatch, profile):
    batch = Harness(monkeypatch, lexical(intent(), [hit(1)])).run(snapshot(**profile))
    assert not batch.candidates
    assert batch.diagnostics['rejected']['policy_unknown'] == 1
    assert batch.status == 'degraded'


def test_known_empty_subject_evidence_allows_unrelated_story(monkeypatch):
    harness = Harness(monkeypatch, lexical(intent(), [hit(1)]))
    harness.policies[str(UUID(int=1))] = {'entity_ids': []}
    batch = harness.run(snapshot(policies=[policy('subject', 'entity:apple', scope='entity')]))
    assert len(batch.candidates) == 1


def test_unavailable_display_is_not_a_candidate(monkeypatch):
    harness = Harness(monkeypatch, lexical(intent(), [hit(1)]))
    harness.articles[str(UUID(int=1))] = {'id': str(UUID(int=1)), 'title': 'Story', 'url': None}
    batch = harness.run()
    assert not batch.candidates
    assert batch.diagnostics['rejected']['display_unavailable'] == 1


@pytest.mark.parametrize('error,status', [(RuntimeError('unavailable'), 'failed'),
                                        (TimeoutError(), 'timed_out')])
def test_failed_leg_does_not_discard_other_intent_supply(monkeypatch, error, status):
    left, right = intent(1), intent(2, label='Culture')
    sources = {**lexical(left, error), **lexical(right, [hit(1001)])}
    batch = Harness(monkeypatch, sources).run(snapshot([left, right]))
    assert len(batch.candidates) == 1
    assert batch.status == 'degraded'
    assert any(leg['intent_id'] == left['id'] and leg['status'] == status
               for leg in batch.diagnostics['legs'])


def test_refill_has_three_round_bound_even_when_nothing_passes_policy(monkeypatch):
    harness = Harness(monkeypatch, lexical(intent(), [hit(i) for i in range(1, 2001)]))
    batch = harness.run(snapshot(policies=[policy(value='Science')]))
    assert not batch.candidates
    assert batch.status == 'degraded'
    assert batch.diagnostics['rounds'] == 3
    assert len(harness.pages) == 3
    assert batch.diagnostics['stop_reason'] == 'round_budget'
    assert batch.diagnostics['unique_examined'] == 900


def test_unique_budget_is_global_across_intents_and_rounds(monkeypatch):
    items = [intent(i) for i in range(1, 9)]
    sources = {}
    for index, item in enumerate(items):
        sources.update(lexical(item, [hit(index * 1000 + i) for i in range(1, 1000)]))
    harness = Harness(monkeypatch, sources)
    batch = harness.run(snapshot(items, policies=[policy(value='Science')]))
    assert batch.diagnostics['unique_examined'] <= 2400
    assert sum(len(chunk) for chunk in harness.hydrations) <= 2400
    assert batch.diagnostics['rows_returned'] <= 7200
    assert batch.diagnostics['rounds'] <= 3
    assert batch.status == 'degraded'


def test_deadline_stops_before_processing_late_page(monkeypatch):
    harness = Harness(monkeypatch, lexical(intent(), [hit(1)]))
    now = [0.0]
    original = harness.page
    def late_page(*args, **kwargs):
        result = original(*args, **kwargs)
        now[0] = 3.0
        return result
    monkeypatch.setattr(retrieval, '_s6_page', late_page)
    batch = harness.run(clock=lambda: now[0])
    assert not batch.candidates
    assert batch.status == 'degraded'
    assert batch.diagnostics['stop_reason'] == 'deadline'
    assert len(harness.pages) == 1


def test_empty_reader_uses_explicit_generic_provenance(monkeypatch):
    batch = Harness(monkeypatch, {(None, 'generic', 'recent'): [hit(1)]}).run(snapshot([]))
    assert len(batch.candidates) == 1
    candidate = batch.candidates[0]
    assert candidate.allocated_intent_id is None
    assert candidate.matched_intent_ids == []
    assert candidate.matches[0].leg == 'generic'


def test_expired_intent_is_not_queried_and_active_expiry_bounds_batch(monkeypatch):
    expired = intent(1, expires_at='2026-09-07T11:59:59Z')
    active = intent(2, expires_at='2026-09-07T12:03:00Z')
    harness = Harness(monkeypatch, lexical(active, [hit(1)]))
    batch = harness.run(snapshot([expired, active]))
    assert all(key[0] == active['id'] for key, _ in harness.pages)
    assert batch.valid_until == datetime(2026, 9, 7, 12, 3, tzinfo=timezone.utc)


def test_nonidle_connection_and_unreviewed_reader_rejected_before_sql(monkeypatch):
    harness = Harness(monkeypatch)
    harness.conn.info.transaction_status = TransactionStatus.INTRANS
    with pytest.raises(ValueError, match='idle'):
        harness.run()
    assert not harness.conn.sql
    reader = snapshot()
    reader['migration_status'] = 'needs_review'
    with pytest.raises(ValueError, match='review'):
        harness.run(reader)
    assert not harness.conn.sql


@pytest.mark.parametrize('limit', [-1, 301, True, '300'])
def test_candidate_limit_is_strictly_bounded(monkeypatch, limit):
    with pytest.raises(ValidationError):
        Harness(monkeypatch).run(limit=limit)


def test_contract_rejects_duplicates_and_forged_attribution(monkeypatch):
    batch = Harness(monkeypatch, lexical(intent(), [hit(1)])).run()
    data = batch.model_dump()
    data['candidates'] *= 2
    with pytest.raises(ValidationError, match='duplicate'):
        CandidateBatch.model_validate(data)
    data = batch.model_dump()
    data['candidates'][0]['allocated_intent_id'] = str(UUID(int=999))
    with pytest.raises(ValidationError, match='attribution'):
        CandidateBatch.model_validate(data)


def test_request_rejects_naive_time():
    reader = snapshot()
    with pytest.raises(ValidationError, match='timezone'):
        RetrievalRequest(user_id=USER, generation=1, revision=1, learning_revision=1,
                         profile=reader['profile'], as_of=NOW.replace(tzinfo=None))


def test_dense_is_default_off_and_threshold_requires_explicit_finite_setting(monkeypatch):
    monkeypatch.delenv('S6_DENSE_ENABLED', raising=False)
    monkeypatch.delenv('S6_ANN_ENABLED', raising=False)
    assert retrieval.retrieval_configuration()['dense_requested'] is False
    monkeypatch.setenv('S6_DENSE_ENABLED', 'true')
    for raw in ('nan', 'inf', '-0.1', '1.1', 'not-a-number'):
        monkeypatch.setenv('S6_MIN_SIMILARITY', raw)
        assert retrieval.retrieval_configuration()['min_similarity'] is None
    monkeypatch.setenv('S6_MIN_SIMILARITY', '.6')
    assert retrieval.retrieval_configuration()['min_similarity'] == .6


def test_below_threshold_dense_hits_count_toward_unique_budget_without_hydration(monkeypatch):
    item = intent()
    rows = [hit(i, score=.2) for i in range(1, 401)]
    harness = Harness(monkeypatch, {(item['id'], 'dense', 'exact'): rows},
                      recipe={'id': 'recipe'}, vectors={item['id']: [1.0]})
    batch = harness.run()
    assert not batch.candidates
    assert batch.diagnostics['unique_examined'] == 400
    assert batch.diagnostics['rows_returned'] == 400
    assert harness.hydrations == []


def test_vector_setup_failure_degrades_but_retains_lexical_candidates(monkeypatch):
    harness = Harness(monkeypatch, lexical(intent(), [hit(1)]),
                      recipe={'id': 'recipe'}, vectors={intent()['id']: [1.0]})
    def failure(*args):
        raise ValueError('unsupported cached embedding geometry')
    monkeypatch.setattr(retrieval, '_s6_vectors', failure)
    batch = harness.run()
    assert len(batch.candidates) == 1
    assert batch.status == 'degraded'
    assert batch.diagnostics['vector_setup'] == 'unavailable'


def test_dense_and_lexical_add_independent_families_with_preserved_provenance(monkeypatch):
    item = intent()
    row = hit(1, score=.8, input_hash='current-hash', semantic_revision=2,
              analysis_eligibility_generation=3)
    harness = Harness(monkeypatch, {**lexical(item, [row]),
        (item['id'], 'dense', 'exact'): [row]}, recipe={'id': 'recipe'},
        vectors={item['id']: [1.0]})
    harness.current[row['id']] = {**row, 'embedding': {'dimensions': 1536}, 'recipe_id': 'recipe'}
    batch = harness.run()
    candidate = batch.candidates[0]
    assert {match.leg for match in candidate.matches} == {'lexical', 'dense'}
    assert candidate.retrieval_score == pytest.approx(2 / 61)
    assert batch.diagnostics['unique_examined'] == 1
    assert batch.diagnostics['rows_returned'] == 2
    dense = next(match for match in candidate.matches if match.leg == 'dense')
    assert dense.input_hash == 'current-hash'
    assert dense.recipe_id == 'recipe'


@pytest.mark.parametrize('change', [{'text': 'Corrected private artifact text'},
    {'is_current': False}, {'completeness': 'partial'}, {'content_hash': 'corrected-hash'}])
def test_hydration_fences_display_artifact_state_without_retaining_private_json(monkeypatch, change):
    from app.services import understanding_repository
    from app.services.retrieval_contract import article_stamp
    identifier = str(UUID(int=1))
    artifact = {'id': 42, 'article_id': identifier, 'text': 'Original private artifact text',
        'content_hash': 'original-hash', 'is_current': True, 'completeness': 'complete'}
    row = {'id': identifier, 'title': 'Science', 'url': 'https://publisher.example.com/story',
        'display_content_artifact_id': 42, '_s6_display_artifact': artifact}
    calls = []
    def execute(sql, params):
        calls.append((sql, params))
        return SimpleNamespace(fetchall=lambda: [deepcopy(row)])
    def no_s3(*args, **kwargs):
        pytest.fail('No serving recipe must not load S3 results')
    monkeypatch.setattr(understanding_repository, 'load_current_batch', no_s3)
    conn = SimpleNamespace(execute=execute)
    before = retrieval._s6_hydrate(conn, [identifier], None)[identifier]
    row['_s6_display_artifact'].update(change)
    after = retrieval._s6_hydrate(conn, [identifier], None)[identifier]
    assert before['article']['artifact_state_stamp'] != after['article']['artifact_state_stamp']
    assert article_stamp(before['article']) != article_stamp(after['article'])
    for hydrated in (before, after):
        assert '_s6_display_artifact' not in hydrated['article']
        assert 'text' not in hydrated['article']
        assert 'private artifact text' not in str(hydrated)
        assert hydrated['current'] == {}
    assert all('to_jsonb(artifact) AS _s6_display_artifact' in sql for sql, _ in calls)
    assert all(params == ([UUID(identifier)],) for _, params in calls)
    if 'content_hash' not in change:
        assert row['_s6_display_artifact']['content_hash'] == 'original-hash'


def test_hydration_without_selected_display_artifact_has_explicit_empty_stamp(monkeypatch):
    from app.services import understanding_repository
    identifier = str(UUID(int=1))
    row = {'id': identifier, 'title': 'Science', '_s6_display_artifact': None}
    conn = SimpleNamespace(execute=lambda *args: SimpleNamespace(fetchall=lambda: [row]))
    def no_s3(*args, **kwargs):
        pytest.fail('Unexpected S3 lookup without a serving recipe')
    monkeypatch.setattr(understanding_repository, 'load_current_batch', no_s3)
    value = retrieval._s6_hydrate(conn, [identifier], None)[identifier]
    assert value['article']['artifact_state_stamp'] is None
    assert '_s6_display_artifact' not in value['article']
    assert all(value['policy'][key] is None for key in (
        'topic_ids', 'entity_ids', 'place_ids', 'sector_ids', 'language', 'content_language'))
