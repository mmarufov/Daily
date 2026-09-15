"""Offline full-batch S7 handoff and fresh publication-fence contracts."""
from contextlib import contextmanager
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from uuid import UUID

import pytest
from psycopg.pq import TransactionStatus

from app.services import reader_retrieval as retrieval
from app.services import reader_repository
from app.services.reader_contract import ReaderProfile, canonical_hash
from app.services.reader_repository import ReaderConflict
from app.services.retrieval_contract import Candidate, CandidateBatch, Match, RECIPE, article_stamp


NOW = datetime(2026, 9, 7, 12, tzinfo=timezone.utc)
USER = str(UUID(int=10000))
INTENT = str(UUID(int=20000))
CONFIG = {**RECIPE, 'dense_requested': False, 'min_similarity': None, 'ann': False}


def evidence_stamp(current):
    return retrieval._s6_evidence_stamp(current)


class Harness:
    def __init__(self, monkeypatch, count=3, *, derived=False):
        self.profile = ReaderProfile(intents=[{
            'id': INTENT, 'kind': 'topic', 'label': 'Science'}]).model_dump()
        self.snapshot = {'generation': 1, 'revision': 3, 'learning_revision': 2,
            'migration_status': 'ready', 'profile': self.profile}
        self.recipe = {'id': 'recipe'} if derived else None
        self.fresh = {}
        candidates = []
        for index in range(1, count + 1):
            identifier = str(UUID(int=index))
            article = {'id': identifier, 'title': 'Science',
                'url': 'https://publisher.example.com/story/' + identifier,
                'display_content_artifact_id': 10 + index,
                'analysis_content_artifact_id': 20 + index,
                'artifact_content_hash': 'unchanged-display-hash'}
            current = {'input_hash': 'current-input', 'semantic_revision': 1,
                'analysis_eligibility_generation': 2, 'recipe_id': 'recipe',
                'facets': {'result_id': 'facets-result', 'payload': {'topics': []}},
                'embedding': {'result_id': 'embedding-result', 'payload': {'dimensions': 1536}}} if derived else {}
            self.fresh[identifier] = {'article': article, 'current': current, 'policy': {}}
            candidates.append(Candidate(article_id=identifier, allocated_intent_id=INTENT,
                matched_intent_ids=[INTENT], matches=[Match(intent_id=INTENT,
                leg='dense' if derived else 'lexical', variant='exact' if derived else 'strict',
                rank=index, score=.8, query_hash='private-hash',
                recipe_id='recipe' if derived else None, input_hash='current-input' if derived else None)],
                retrieval_score=1 / (60 + index), article_stamp=article_stamp(article),
                evidence_stamp=evidence_stamp(current), policy_evidence={}, article=deepcopy(article)))
        self.batch = CandidateBatch(request_id=str(UUID(int=50000)), user_id=USER,
            generation=1, revision=3, learning_revision=2, reader_hash=canonical_hash(self.profile),
            as_of=NOW, valid_until=NOW + timedelta(minutes=15), retrieval_recipe=canonical_hash(CONFIG),
            configuration=deepcopy(CONFIG), s3_recipe_id='recipe' if derived else None,
            space_id='space' if derived else None, status='complete', candidates=candidates, diagnostics={})
        self.decisions = [{'article_id': item.article_id, 'relevant': True, 'score': float(index)}
                          for index, item in enumerate(candidates)]
        self.in_transaction = False
        self.in_guard = False
        self.guard_seen = None
        self.sql = []
        self.deleted = set()
        self.info = SimpleNamespace(transaction_status=TransactionStatus.IDLE)
        monkeypatch.setattr(reader_repository, 'publication_guard', self.guard)
        monkeypatch.setattr(retrieval, '_s6_recipe', lambda conn: self.recipe)
        monkeypatch.setattr(retrieval, '_s6_hydrate', self.hydrate)
        monkeypatch.setattr(retrieval, 'retrieval_configuration', lambda: deepcopy(CONFIG))

    @contextmanager
    def transaction(self):
        assert not self.in_transaction
        self.in_transaction = True
        try:
            yield
        finally:
            self.in_transaction = False

    @contextmanager
    def guard(self, conn, user_id, expected):
        assert self.in_transaction
        self.guard_seen = (user_id, expected)
        for key in ('generation', 'revision', 'learning_revision'):
            if expected[key] != self.snapshot[key]:
                raise ReaderConflict('reader_changed')
        self.in_guard = True
        try:
            yield self.snapshot
        finally:
            self.in_guard = False

    def execute(self, sql, params=()):
        self.sql.append((sql, params))
        rows = []
        if 'FROM public.articles WHERE' in sql:
            rows = [deepcopy(self.fresh[key]['article']) for key in params[0] if key not in self.deleted]
        elif 'to_regclass' in sql:
            rows = [{'relation': 'understanding_control' if self.recipe else None}]
        return SimpleNamespace(fetchall=lambda: rows, fetchone=lambda: rows[0] if rows else None)

    def hydrate(self, conn, identifiers, recipe):
        assert self.in_guard
        return {key: deepcopy(self.fresh[key]) for key in identifiers if key not in self.deleted}

    def authorize(self, **kwargs):
        return retrieval.authorize_candidate_batch(self, kwargs.pop('user_id', USER), self.batch,
            kwargs.pop('decisions', self.decisions), now=kwargs.pop('now', lambda: NOW), **kwargs)


def test_ranker_receives_all_300_candidates_without_prefilter_or_legacy_cap(monkeypatch):
    harness = Harness(monkeypatch, 300)
    seen = []
    def scorer(batch):
        assert not harness.in_guard and not harness.in_transaction
        seen.extend(item.article_id for item in batch.candidates)
        return list(reversed(harness.decisions))
    decisions = retrieval.rank_candidate_batch(harness.batch, scorer)
    assert len(seen) == len(decisions) == 300
    assert set(seen) == {item.article_id for item in harness.batch.candidates}
    assert not harness.sql


def test_ranker_mutation_cannot_change_authorization_stamps_or_original_candidates(monkeypatch):
    harness = Harness(monkeypatch)
    before = harness.batch.model_dump()
    def scorer(batch):
        batch.candidates[0].article['title'] = 'Injected'
        batch.candidates[0].article_stamp = 'forged'
        batch.configuration['version'] = 'forged'
        batch.candidates.clear()
        return harness.decisions
    retrieval.rank_candidate_batch(harness.batch, scorer)
    assert harness.batch.model_dump() == before


@pytest.mark.parametrize('mutation', ['duplicate', 'foreign', 'incomplete', 'missing-score',
    'string-score', 'nan', 'infinite', 'string-relevant', 'extra-field'])
def test_malformed_ranker_verdicts_rejected(monkeypatch, mutation):
    harness = Harness(monkeypatch)
    verdicts = deepcopy(harness.decisions)
    if mutation == 'duplicate':
        verdicts[1] = deepcopy(verdicts[0])
    elif mutation == 'foreign':
        verdicts[0]['article_id'] = str(UUID(int=90000))
    elif mutation == 'incomplete':
        verdicts.pop()
    elif mutation == 'missing-score':
        del verdicts[0]['score']
    elif mutation == 'string-score':
        verdicts[0]['score'] = '1.0'
    elif mutation == 'nan':
        verdicts[0]['score'] = float('nan')
    elif mutation == 'infinite':
        verdicts[0]['score'] = float('inf')
    elif mutation == 'string-relevant':
        verdicts[0]['relevant'] = 'true'
    else:
        verdicts[0]['reason'] = 'Uncontracted field'
    with pytest.raises(ValueError):
        retrieval.rank_candidate_batch(harness.batch, lambda batch: verdicts)


def test_stale_batch_never_reaches_scorer(monkeypatch):
    harness = Harness(monkeypatch)
    harness.batch.status = 'stale'
    def scorer(batch):
        pytest.fail('Stale batch reached scorer')
    with pytest.raises(ValueError, match='stale'):
        retrieval.rank_candidate_batch(harness.batch, scorer)


def test_success_yields_only_accepted_score_sorted_candidates_inside_guard(monkeypatch):
    harness = Harness(monkeypatch)
    harness.decisions[1]['relevant'] = False
    with harness.authorize() as candidates:
        assert harness.in_guard and harness.in_transaction
        assert [item.article_id for item in candidates] == [str(UUID(int=3)), str(UUID(int=1))]
        assert candidates[0].matched_intent_ids == [INTENT]
    assert not harness.in_guard and not harness.in_transaction
    assert harness.guard_seen[0] == USER
    assert harness.guard_seen[1]['learning_revision'] == 2
    assert any('article_content_artifacts' in sql and 'FOR SHARE' in sql for sql, _ in harness.sql)


def test_equal_scores_are_ordered_by_stable_article_identity(monkeypatch):
    harness = Harness(monkeypatch)
    verdicts = [{**value, 'score': 1.0} for value in reversed(harness.decisions)]
    with harness.authorize(decisions=verdicts) as candidates:
        assert [item.article_id for item in candidates] == [str(UUID(int=i)) for i in range(1, 4)]


def test_wrong_account_rejected_before_database_work(monkeypatch):
    harness = Harness(monkeypatch)
    with pytest.raises(ReaderConflict, match='account_mismatch'), harness.authorize(user_id=str(UUID(int=9))):
        pytest.fail('Wrong account authorized')
    assert not harness.sql


@pytest.mark.parametrize('field', ['generation', 'revision', 'learning_revision'])
def test_reader_revision_fence_passes_all_generations_to_publication_guard(monkeypatch, field):
    harness = Harness(monkeypatch)
    harness.snapshot[field] += 1
    with pytest.raises(ReaderConflict, match='reader_changed'), harness.authorize():
        pytest.fail('Changed reader authorized')


@pytest.mark.parametrize('mutation', ['profile', 'migration'])
def test_changed_profile_hash_or_migration_state_rejected(monkeypatch, mutation):
    harness = Harness(monkeypatch)
    if mutation == 'profile':
        harness.snapshot['profile']['depth'] = 'deep'
    else:
        harness.snapshot['migration_status'] = 'needs_review'
    with pytest.raises(ReaderConflict, match='reader_changed'), harness.authorize():
        pytest.fail('Changed profile authorized')


def test_changed_runtime_configuration_rejected_before_guard(monkeypatch):
    harness = Harness(monkeypatch)
    monkeypatch.setattr(retrieval, 'retrieval_configuration', lambda: {**CONFIG, 'ann': True})
    with pytest.raises(ReaderConflict, match='configuration_changed'), harness.authorize():
        pytest.fail('Changed configuration authorized')
    assert harness.guard_seen is None


@pytest.mark.parametrize('mutation', ['changed', 'disabled'])
def test_changed_or_disabled_serving_recipe_rejected(monkeypatch, mutation):
    harness = Harness(monkeypatch, derived=True)
    harness.recipe = {'id': 'different-recipe'} if mutation == 'changed' else None
    with pytest.raises(ReaderConflict, match='recipe_changed'), harness.authorize():
        pytest.fail('Changed recipe authorized')


@pytest.mark.parametrize('when', [NOW - timedelta(seconds=1), NOW + timedelta(minutes=15),
    NOW + timedelta(hours=1), NOW.replace(tzinfo=None)])
def test_invalid_publication_time_rejected_before_guard(monkeypatch, when):
    harness = Harness(monkeypatch)
    with pytest.raises(ReaderConflict, match='expired'), harness.authorize(now=lambda: when):
        pytest.fail('Expired or invalid batch authorized')
    assert harness.guard_seen is None


def test_expiry_while_waiting_for_locks_rechecked_before_yield(monkeypatch):
    harness = Harness(monkeypatch)
    times = iter([NOW, NOW, NOW + timedelta(minutes=15)])
    with pytest.raises(ReaderConflict, match='expired'), harness.authorize(now=lambda: next(times)):
        pytest.fail('Batch expired under lock authorized')
    assert harness.guard_seen is not None
    assert not harness.in_guard


def test_expiry_during_synchronous_consumer_work_rejects_commit(monkeypatch):
    harness = Harness(monkeypatch)
    value = [NOW]
    with pytest.raises(ReaderConflict, match='expired'):
        with harness.authorize(now=lambda: value[0]):
            value[0] = NOW + timedelta(minutes=15)
    assert not harness.in_guard and not harness.in_transaction


@pytest.mark.parametrize('field', ['title', 'url', 'artifact_content_hash', 'display_content_artifact_id'])
def test_article_or_display_artifact_correction_rejected(monkeypatch, field):
    harness = Harness(monkeypatch)
    harness.fresh[str(UUID(int=1))]['article'][field] = 999 if field == 'display_content_artifact_id' else 'changed'
    with pytest.raises(ReaderConflict, match='article_changed'), harness.authorize():
        pytest.fail('Changed article authorized')


def test_deleted_candidate_rejects_whole_batch_instead_of_silent_partial_publish(monkeypatch):
    harness = Harness(monkeypatch)
    harness.deleted.add(str(UUID(int=1)))
    with pytest.raises(ReaderConflict, match='article_deleted'), harness.authorize():
        pytest.fail('Deleted article authorized')


@pytest.mark.parametrize('field', ['input_hash', 'semantic_revision', 'analysis_eligibility_generation'])
def test_current_evidence_revision_change_rejected(monkeypatch, field):
    harness = Harness(monkeypatch, derived=True)
    harness.fresh[str(UUID(int=1))]['current'][field] = 'changed'
    with pytest.raises(ReaderConflict, match='evidence_changed'), harness.authorize():
        pytest.fail('Changed evidence authorized')


def test_policy_projection_change_rejected(monkeypatch):
    harness = Harness(monkeypatch)
    harness.fresh[str(UUID(int=1))]['policy'] = {'topic_ids': ['health']}
    with pytest.raises(ReaderConflict, match='evidence_changed'), harness.authorize():
        pytest.fail('Changed policy evidence authorized')


def test_removed_derived_stage_rejected_even_without_revision_change(monkeypatch):
    harness = Harness(monkeypatch, derived=True)
    del harness.fresh[str(UUID(int=1))]['current']['embedding']
    with pytest.raises(ReaderConflict, match='evidence_changed'), harness.authorize():
        pytest.fail('Removed derived stage authorized')


@pytest.mark.parametrize('stage', ['facets', 'embedding'])
def test_in_place_result_payload_correction_rejected_without_revision_change(monkeypatch, stage):
    harness = Harness(monkeypatch, derived=True)
    harness.fresh[str(UUID(int=1))]['current'][stage]['payload']['changed'] = True
    with pytest.raises(ReaderConflict, match='evidence_changed'), harness.authorize():
        pytest.fail('Corrected result authorized under stale evidence stamp')


def test_authorization_revalidates_decisions_before_locking(monkeypatch):
    harness = Harness(monkeypatch)
    with pytest.raises(ValueError), harness.authorize(decisions=[]):
        pytest.fail('Incomplete ranking authorized')
    assert not harness.sql


def test_publication_requires_exclusive_idle_connection(monkeypatch):
    harness = Harness(monkeypatch)
    harness.info.transaction_status = TransactionStatus.INTRANS
    with pytest.raises(ValueError, match='idle'), harness.authorize():
        pytest.fail('Nonexclusive connection authorized')
    assert not harness.sql


def test_fresh_policy_eligibility_is_rechecked_not_just_stamped(monkeypatch):
    harness = Harness(monkeypatch)
    monkeypatch.setattr(retrieval, '_s6_eligibility', lambda request, row: 'policy_unknown')
    with pytest.raises(ReaderConflict, match='policy_changed'), harness.authorize():
        pytest.fail('Unknown fresh policy authorized')


def test_successful_derived_batch_locks_current_recipe_and_results(monkeypatch):
    harness = Harness(monkeypatch, derived=True)
    with harness.authorize() as candidates:
        assert len(candidates) == 3
        assert harness.in_guard
    for relation in ('understanding_control', 'understanding_recipes', 'article_understanding_results'):
        assert any(relation in sql and 'FOR SHARE' in sql for sql, _ in harness.sql)


def test_recipe_disabled_while_waiting_for_recipe_lock_rejected(monkeypatch):
    harness = Harness(monkeypatch, derived=True)
    recipes = iter([{'id': 'recipe'}, None])
    monkeypatch.setattr(retrieval, '_s6_recipe', lambda conn: next(recipes))
    with pytest.raises(ReaderConflict, match='recipe_changed'), harness.authorize():
        pytest.fail('Recipe disabled during lock wait authorized')


def test_exception_in_publication_consumer_unwinds_guard_and_transaction(monkeypatch):
    harness = Harness(monkeypatch)
    with pytest.raises(RuntimeError, match='receipt write failed'):
        with harness.authorize():
            assert harness.in_guard
            raise RuntimeError('receipt write failed')
    assert not harness.in_guard and not harness.in_transaction
