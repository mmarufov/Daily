"""Offline S5 embedding lifecycle and per-interest retrieval contracts.

No API requests or database services. SQL transaction/concurrency behavior still
requires the opt-in hosted PostgreSQL gate before activation.
"""
import asyncio
from contextlib import contextmanager, nullcontext
from copy import deepcopy
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

import pytest

from app.services import reader_worker as worker
from app.services import reader_retrieval as retrieval
from app.services.understanding_contract import DEFAULT_RECIPE
from app.services.understanding_provider import ProviderFailure


def intent(identifier='a', **values):
    return {'id': identifier, 'label': 'Новости Таджикистана', 'query': 'Новости Таджикистана',
            'priority': 1, 'kind': 'topic', **values}


def snapshot(item=None, **values):
    return {'generation': 1, 'revision': 1, 'learning_revision': 1,
            'profile': {'intents': [item or intent()]}, **values}


def job():
    return {'id': 1, 'user_id': 'user', 'generation': 1, 'intent_id': 'a',
            'semantic_hash': worker.semantic_hash(intent()), 'space_id': worker.space_id(DEFAULT_RECIPE),
            'recipe_id': 'recipe', 'lease_token': 'token'}


def test_space_identity_excludes_facets_but_includes_geometry():
    original = worker.space_id(DEFAULT_RECIPE)
    assert worker.space_id({**DEFAULT_RECIPE, 'prompt_version': 'new-facets'}) == original
    for key in ('embedding_model', 'input_version', 'query_recipe', 'document_recipe'):
        assert worker.space_id({**DEFAULT_RECIPE, key: 'different'}) != original
    with pytest.raises(ValueError):
        worker.space_id({**DEFAULT_RECIPE, 'dimensions': 3072})


def test_query_hash_preserves_unicode_and_ignores_priority_and_biography():
    original = intent(query=' cafe\u0301   Москва ')
    assert worker.intent_query(original) == 'café Москва'
    assert worker.semantic_hash(original) == worker.semantic_hash({**original, 'query': 'café Москва', 'priority': 2})
    assert worker.semantic_hash(original) != worker.semantic_hash(intent(query='cafe Moscow'))
    with pytest.raises(ValueError):
        worker.intent_query(intent(query='a' * 281))


@pytest.mark.parametrize('change', ['reset', 'edit', 'delete', 'recipe', 'expired'])
def test_stale_work_cannot_match(change):
    reader = snapshot()
    recipe = {'id': 'recipe', 'definition': deepcopy(DEFAULT_RECIPE)}
    if change == 'reset':
        reader['generation'] = 2
    elif change == 'edit':
        reader['profile']['intents'][0]['query'] = 'Other interest'
    elif change == 'delete':
        reader['profile']['intents'] = []
    elif change == 'recipe':
        recipe['id'] = 'new-recipe'
    else:
        reader['profile']['intents'][0]['expires_at'] = '2020-01-01T00:00:00Z'
    assert not worker.job_matches(job(), reader, recipe)


def test_priority_edit_and_learning_changes_reuse_same_vector():
    reader = snapshot(intent(priority=3), revision=10, learning_revision=30)
    assert worker.job_matches(job(), reader, {'id': 'recipe', 'definition': DEFAULT_RECIPE})


def test_expiry_is_checked_without_a_mutation():
    reader = snapshot(intent(expires_at='2026-09-07T12:00:00Z'))
    assert len(worker.active_intents(reader, now=datetime(2026, 9, 7, 11, tzinfo=timezone.utc))) == 1
    assert worker.active_intents(reader, now=datetime(2026, 9, 7, 12, tzinfo=timezone.utc)) == []
    with pytest.raises(ValueError):
        worker.active_intents(snapshot(intent(expires_at='2026-09-07T12:00:00')))


def test_disabled_worker_has_no_db_or_provider_work(monkeypatch):
    monkeypatch.delenv('S5_WORKER_ENABLED', raising=False)
    service = worker.ReaderWorker(None, Mock())
    service.db = AsyncMock()
    assert asyncio.run(service.tick()) == 0
    service.db.assert_not_awaited()
    assert worker.claim(Mock()) == []
    assert worker.reconcile(Mock()) is None


def test_prepare_budget_pause_does_not_call_provider():
    provider = SimpleNamespace(query_embedding=AsyncMock())
    service = worker.ReaderWorker(None, provider)
    service.db = AsyncMock(return_value=None)
    asyncio.run(service.process(job()))
    provider.query_embedding.assert_not_awaited()


def test_worker_calls_only_query_and_does_not_hold_connection():
    provider = SimpleNamespace(query_embedding=AsyncMock(return_value=SimpleNamespace(payload={'vector': [1]})))
    service = worker.ReaderWorker(None, provider)
    calls = []
    async def database(function, *args, **kwargs):
        calls.append(function.__name__)
        return {'query': 'private intent only', 'definition': DEFAULT_RECIPE, 'attempt': 1} if function is worker.prepare else True
    service.db = database
    asyncio.run(service.process(job()))
    assert calls == ['prepare', 'publish']
    provider.query_embedding.assert_awaited_once_with('private intent only', DEFAULT_RECIPE)


@pytest.mark.parametrize('error,retryable', [(ProviderFailure('timeout', retryable=True, ambiguous=True), True),
                                           (ProviderFailure('refusal'), False), (TimeoutError(), True)])
def test_failed_provider_is_bounded_and_never_publishes(error, retryable):
    provider = SimpleNamespace(query_embedding=AsyncMock(side_effect=error))
    service = worker.ReaderWorker(None, provider)
    calls = []
    async def database(function, *args, **kwargs):
        calls.append((function.__name__, kwargs))
        return {'query': 'private', 'definition': DEFAULT_RECIPE, 'attempt': 2} if function is worker.prepare else True
    service.db = database
    asyncio.run(service.process(job()))
    assert [call[0] for call in calls] == ['prepare', 'fail']
    assert calls[-1][1] == {'retryable': retryable, 'code': 'provider_failure', 'attempt': 2}


def test_cancelled_request_keeps_reservation_for_lease_recovery():
    provider = SimpleNamespace(query_embedding=AsyncMock(side_effect=asyncio.CancelledError()))
    service = worker.ReaderWorker(None, provider)
    service.db = AsyncMock(return_value={'query': 'private', 'definition': DEFAULT_RECIPE, 'attempt': 1})
    with pytest.raises(asyncio.CancelledError):
        asyncio.run(service.process(job()))
    assert service.db.await_count == 1


def test_failed_final_lease_fence_rolls_back_insert(monkeypatch):
    monkeypatch.setenv('S5_WORKER_ENABLED', 'true')
    calls = []
    @contextmanager
    def transaction():
        try:
            yield
        except Exception:
            calls.append('rollback')
            raise
        else:
            calls.append('commit')
    def execute(sql, params=None):
        if 'public.users' in sql:
            return SimpleNamespace(fetchone=lambda: {'id': 'user'})
        if 'reader_profiles' in sql:
            return SimpleNamespace(fetchone=lambda: snapshot())
        if 'reader_embedding_control' in sql:
            return SimpleNamespace(fetchone=lambda: {'enabled': True})
        if 'INSERT INTO' in sql:
            calls.append('insert')
        return SimpleNamespace(rowcount=0)
    conn = SimpleNamespace(transaction=transaction, execute=execute)
    with patch.object(worker, 'serving_recipe', return_value={'id': 'recipe', 'definition': DEFAULT_RECIPE}), \
         patch.object(worker, 'validate_embedding', return_value=[1]):
        assert not worker.publish(conn, job(), [1])
    assert calls == ['insert', 'rollback']


def test_worker_skips_deleted_accounts_before_locking_reader():
    conn = Mock()
    conn.execute.return_value.fetchone.return_value = None
    assert worker._current_reader(conn, 'user') is None
    assert conn.execute.call_count == 1
    assert 'is_deleted' in conn.execute.call_args.args[0]


def test_worker_requires_reviewed_profile_under_authority_lock_order():
    conn = Mock()
    conn.execute.side_effect = [SimpleNamespace(fetchone=lambda: {'id': 'user'}),
                               SimpleNamespace(fetchone=lambda: None)]
    assert worker._current_reader(conn, 'user') is None
    first, second = [call.args[0] for call in conn.execute.call_args_list]
    assert 'public.users' in first and 'FOR SHARE' in first
    assert "migration_status='ready'" in second and 'FOR UPDATE' in second


def test_three_unrelated_interests_survive_union_and_deduplication():
    def rows(prefix, count):
        return retrieval.fuse_intent_legs({'lexical': [{'id': f'{prefix}{i}'} for i in range(count)]})
    groups = [(intent('a', priority=3), rows('ai', 100)), (intent('b'), rows('local', 2)),
              (intent('c'), rows('space', 2))]
    assert [row['id'] for row in retrieval.balanced_union(groups, limit=3)] == ['ai0', 'local0', 'space0']
    assert len(retrieval.balanced_union(groups, limit=10)) == 10


def test_duplicate_article_keeps_all_intents_and_evidence_without_private_query():
    groups = [(intent('a'), retrieval.fuse_intent_legs({'semantic': [{'id': 'same'}]})),
              (intent('b'), retrieval.fuse_intent_legs({'lexical': [{'id': 'same'}, {'id': 'other'}]}))]
    result = retrieval.balanced_union(groups, limit=2)
    assert result[0]['_reader_intent_ids'] == ['a', 'b']
    assert result[0]['_reader_match_kinds'] == ['lexical', 'semantic']
    assert not result[0]['_reader_semantic_only']
    assert 'query' not in result[0] and 'label' not in result[0]


def test_rrf_does_not_turn_similarity_into_probability():
    result = retrieval.fuse_intent_legs({'semantic': [{'id': 'a', 'similarity': .8}, {'id': 'b', 'similarity': .79}]})
    assert result[0]['_reader_score'] == 1 / 61
    assert result[0]['_reader_semantic_only']
    assert result[1]['_reader_score'] == 1 / 62


@pytest.mark.parametrize('threshold', [None, 'NaN', 'inf', '-.1', '1.1', 'bogus'])
def test_missing_or_bad_semantic_threshold_abstains(monkeypatch, threshold):
    monkeypatch.setenv('S5_SEMANTIC_ENABLED', 'true')
    if threshold is None:
        monkeypatch.delenv('S5_SEMANTIC_MIN_SIMILARITY', raising=False)
    else:
        monkeypatch.setenv('S5_SEMANTIC_MIN_SIMILARITY', threshold)
    assert retrieval.semantic_threshold() is None


def test_lexical_mode_never_touches_s3_or_embeddings(monkeypatch):
    monkeypatch.delenv('S5_SEMANTIC_ENABLED', raising=False)
    conn = SimpleNamespace(transaction=lambda: nullcontext(), execute=Mock())
    with patch.object(retrieval, 'lexical_rows', return_value=[{'id': 'local'}]) as lexical:
        result = retrieval.build_reader_candidates(conn, 'user', snapshot(), limit=5)
    assert result[0]['_reader_intent_ids'] == ['a']
    conn.execute.assert_not_called()
    lexical.assert_called_once()


def test_semantic_only_synonym_survives_without_legacy_keyword_gate(monkeypatch):
    monkeypatch.setenv('S5_SEMANTIC_ENABLED', 'true')
    monkeypatch.setenv('S5_SEMANTIC_MIN_SIMILARITY', '.7')
    conn = SimpleNamespace(transaction=lambda: nullcontext(), execute=Mock())
    recipe = {'id': 'recipe', 'definition': DEFAULT_RECIPE}
    with patch.object(retrieval, '_recipe_or_none', return_value=recipe), \
         patch.object(retrieval, 'lexical_rows', return_value=[]), \
         patch.object(retrieval, 'identity_rows', return_value=[]), \
         patch.object(retrieval, 'cached_vector', return_value=[1]), \
         patch.object(retrieval, 'semantic_rows', return_value=[
             {'id': 'synonym', 'title': 'Dushanbe developments', 'similarity': .8},
             {'id': 'weak', 'similarity': .5}]):
        result = retrieval.build_reader_candidates(conn, 'user', snapshot())
    assert [row['id'] for row in result] == ['synonym']
    assert result[0]['_reader_semantic_only']
    assert result[0]['_reader_intent_ids'] == ['a']


def test_vector_lookup_is_tenant_generation_intent_hash_and_space_scoped():
    conn = SimpleNamespace(execute=Mock(return_value=SimpleNamespace(fetchone=lambda: {'embedding': '[1,0]'})))
    result = retrieval.cached_vector(conn, 'reader-a', snapshot(), intent(), {'definition': DEFAULT_RECIPE})
    assert result == [1, 0]
    sql, args = conn.execute.call_args.args
    assert args == ('reader-a', 1, 'a', worker.semantic_hash(intent()), worker.space_id(DEFAULT_RECIPE))
    assert all(term in sql for term in ('user_id=%s', 'generation=%s', 'intent_id=%s', 'semantic_hash=%s', 'space_id=%s'))


def test_lexical_query_uses_unicode_simple_dictionary_and_parameters():
    conn = SimpleNamespace(execute=Mock(return_value=SimpleNamespace(fetchall=lambda: [])))
    retrieval.lexical_rows(conn, intent(query="Новости'; DROP TABLE users; --"))
    sql, args = conn.execute.call_args.args
    assert "plainto_tsquery('simple',%s)" in sql
    assert 'DROP TABLE' not in sql
    assert args[0] == "Новости'; DROP TABLE users; --"
