"""Real S7/S8 pure adapter + mocked publication IO; no provider or database."""
from contextlib import contextmanager
import asyncio
from copy import deepcopy
from datetime import timedelta
import json
from pathlib import Path
import time
from unittest.mock import Mock

import pytest

from app.services import assembly_integration as adapter, ranking_service as ranking
from app.services import ranking_repository, ranking_events, reader_repository, reader_feedback, reader_retrieval
from app.services.assembly_contract import RECIPE
from app.services.event_feed import FeedResult
from app.services.ranking_contract import RankBatch
from app.services.reader_contract import canonical_hash
from tests.test_ranking_service import make_request, accept, NOW
from tests.test_ranking_build import snapshot


def setup_input(count=4):
    request = make_request(count)
    ranked = RankBatch(request_id=request.batch.request_id, context_hash=request.fingerprint,
        recipe_hash=canonical_hash(request.recipe), valid_until=request.batch.valid_until,
        status='complete', judgments=[accept(p) for p in request.evidence],
        ordered_ids=[p.article_id for p in request.evidence])
    manifest = {'as_of': NOW.isoformat(), 'generation': 1, 'history_revision': 0,
        'control': {'recipe': deepcopy(RECIPE), 'epoch': 1, 'recipe_hash': canonical_hash(RECIPE)},
        'candidates': {p.article_id: {'coverage_key': 's3:copy' if i < 3 else None,
            'novelty_key': None, 'known_read': False, 'publisher_id': None, 'topic_ids': []}
            for i, p in enumerate(request.evidence)}}
    return request, ranked, snapshot(request), manifest


def assemble(request, ranked, state, manifest, *, limit=3, critical=None, events=()):
    ordinary = ranking._ordinary(request.batch, ranked, state)
    result = critical or FeedResult(payload={**ordinary, 'articles': []}, decisions=[], major_candidates=[])
    return adapter.assemble(request, ranked, state, ordinary, manifest, result, events, limit=limit)


def test_whole_pool_refills_after_verified_deduplication():
    req, ranked, state, manifest = setup_input()
    final, envelope = assemble(req, ranked, state, manifest)
    assert [a['id'] for a in final['articles']] == [ranked.ordered_ids[0], ranked.ordered_ids[3]]
    assert len(envelope['request']['candidates']) == 4
    assert len(envelope['result']['dispositions']) == 4
    assert [a['delivery_position'] for a in final['articles']] == [0, 1]


def test_same_article_critical_keeps_only_its_own_attribution():
    req, ranked, state, manifest = setup_input()
    first = ranked.ordered_ids[0]
    critical = FeedResult(payload={'articles': [{'id': first, 'event_delivery': {'development_id': 'dev'}}]},
                          decisions=[], major_candidates=[])
    final, envelope = assemble(req, ranked, state, manifest, critical=critical)
    assert final['articles'][0]['_reader_intent_ids'] == ranked.judgments[0].confirmed_intent_ids
    assert envelope['request']['candidates'][0]['origin'] == 'world_critical'


def test_s4_only_card_has_no_invented_s7_match():
    req, ranked, state, manifest = setup_input()
    manifest['candidates']['critical'] = {'coverage_key': None, 'novelty_key': None}
    critical = FeedResult(payload={'articles': [{'id': 'critical', 'event_delivery': {'development_id': 'dev'}}]},
                          decisions=[], major_candidates=[])
    final, envelope = assemble(req, ranked, state, manifest, critical=critical)
    assert final['articles'][0]['id'] == 'critical'
    assert '_reader_intent_ids' not in final['articles'][0]
    candidate = next(c for c in envelope['request']['candidates'] if c['article_id'] == 'critical')
    assert candidate['grade'] == 0 and candidate['intents'] == {}


def test_public_card_has_complete_immutable_receipt_context():
    req, ranked, state, manifest = setup_input()
    final, _ = assemble(req, ranked, state, manifest)
    public = ranking._public(final, req.batch.request_id)
    for position, article in enumerate(public['articles']):
        assert article['reader_generation'] == article['reader_revision'] == 1
        assert article['feed_request_id'] == public['feed_request_id']
        assert article['delivery_position'] == position
        assert not any(key.startswith('_') for key in article)
    filtered = {**final, 'articles': final['articles'][1:]}
    assert ranking._public(filtered, req.batch.request_id)['articles'][0]['delivery_position'] == 1


def test_swift_shared_fixture_is_exact_backend_public_serialization():
    fixture = json.loads((Path(__file__).resolve().parents[2] /
                          'DailyTests/Fixtures/s8-edition.json').read_text())
    private = {**fixture, 'articles': [{key: value for key, value in article.items()
        if key not in {'reader_generation', 'reader_revision', 'feed_request_id'}}
        for article in fixture['articles']]}
    assert ranking._public(private, fixture['feed_request_id']) == fixture


@pytest.fixture
def publication(monkeypatch):
    from app.services import assembly_repository
    req, ranked, state, manifest = setup_input()
    for flag in ('S5_READER_ENABLED', 'S6_SERVING_ENABLED', 'S7_SERVING_ENABLED', 'S8_SERVING_ENABLED'):
        monkeypatch.setenv(flag, 'true')
    conn = Mock()
    @contextmanager
    def transaction():
        yield
    conn.transaction = transaction
    monkeypatch.setattr(reader_retrieval, 'authorize_candidate_batch', lambda *a, **k: transaction())
    monkeypatch.setattr(reader_repository, 'load_reader', Mock(return_value=state))
    monkeypatch.setattr(ranking_events, 'prepare', Mock(return_value=[]))
    monkeypatch.setattr(adapter, 'prepare', Mock(return_value=manifest))
    monkeypatch.setattr(assembly_repository, 'validate', Mock())
    monkeypatch.setattr(ranking_repository, 'control', Mock(return_value={
        'serving': True, 'epoch': 1, 'recipe_hash': ranked.recipe_hash}))
    monkeypatch.setattr(ranking_repository, 'publish', Mock(return_value=True))
    monkeypatch.setattr(reader_feedback, 'record_delivery', Mock())
    monkeypatch.setattr(ranking, '_event_receipts', Mock())
    monkeypatch.setattr(ranking, '_check_expiry', Mock())
    claim = {'build_id': 'build', 'token': 'token'}
    public = ranking._publish(conn, req.batch.user_id, req, ranked, state, claim, 3, None, time.monotonic()+10)
    envelope = ranking_repository.publish.call_args.args[5]
    monkeypatch.setattr(ranking_repository, 'latest', Mock(return_value={
        'envelope': envelope, 'identity': ranking.identity(state, req.recipe), 'epoch': 1}))
    reader_feedback.record_delivery.reset_mock()
    return conn, req, ranked, state, manifest, envelope, public


def test_cache_returns_immutable_prefix_without_reassembly_or_new_receipts(publication, monkeypatch):
    conn, req, _, _, _, envelope, original = publication
    monkeypatch.setattr(adapter, 'assemble', Mock(side_effect=AssertionError('GET must not assemble')))
    actual = ranking.cached_feed(conn, req.batch.user_id, limit=1)
    assert actual['feed_request_id'] == original['feed_request_id']
    assert actual['articles'] == original['articles'][:1]
    reader_feedback.record_delivery.assert_not_called()


def test_history_conflict_never_reorders_cached_edition(publication, monkeypatch):
    from app.services import assembly_repository
    conn, req, *_ = publication
    monkeypatch.setattr(assembly_repository, 'validate', Mock(side_effect=reader_repository.ReaderConflict('history_changed')))
    assert ranking.cached_feed(conn, req.batch.user_id, limit=1)['status'] == 'needs_build'
    reader_feedback.record_delivery.assert_not_called()


def test_disabling_assembly_does_not_downgrade_same_edition(publication, monkeypatch):
    conn, req, *_ = publication
    monkeypatch.setenv('S8_SERVING_ENABLED', 'false')
    assert ranking.cached_feed(conn, req.batch.user_id, limit=1)['status'] == 'needs_build'


def test_rank_reuse_independent_of_assembly_expiry(publication, monkeypatch):
    conn, req, ranked, state, _, envelope, _ = publication
    monkeypatch.setattr(ranking_repository, 'latest_rank', Mock(return_value={
        'envelope': envelope, 'identity': ranking.identity(state, req.recipe), 'epoch': 1,
        'expires_at': NOW-timedelta(seconds=1)}))
    control = {'recipe': req.recipe, 'recipe_hash': ranked.recipe_hash, 'epoch': 1}
    request, reused = ranking._reuse_rank(conn, req.batch.user_id, state, control)
    assert reused == ranked and request == req
    # Reader or recipe drift cannot reuse a prior semantic judgment.
    assert ranking._reuse_rank(conn, req.batch.user_id, {**state, 'revision': 2}, control) is None


def test_rank_reuse_reauthorizes_all_ordinary_candidates(publication, monkeypatch):
    conn, req, ranked, state, _, envelope, _ = publication
    monkeypatch.setattr(ranking_repository, 'latest_rank', Mock(return_value={
        'envelope': envelope, 'identity': ranking.identity(state, req.recipe), 'epoch': 1}))
    monkeypatch.setattr(reader_retrieval, 'authorize_candidate_batch',
                        Mock(side_effect=reader_repository.ReaderConflict('article_changed')))
    assert ranking._reuse_rank(conn, req.batch.user_id, state,
        {'recipe': req.recipe, 'recipe_hash': ranked.recipe_hash, 'epoch': 1}) is None


def test_explicit_history_only_build_never_retrieves_or_calls_ranker(publication, monkeypatch):
    from app.services import assembly_repository
    conn, req, ranked, state, manifest, envelope, previous = publication
    control = {'recipe': req.recipe, 'recipe_hash': ranked.recipe_hash, 'epoch': 1,
               'approved': True, 'serving': True, 'provider': True}
    monkeypatch.setattr(ranking_repository, 'control', Mock(return_value=control))
    monkeypatch.setattr(assembly_repository, 'control', Mock(return_value={
        **manifest['control'], 'approved': True, 'serving': True}))
    monkeypatch.setattr(ranking_repository, 'claim_build', Mock(return_value={'build_id': 'build', 'token': 'token'}))
    monkeypatch.setattr(ranking_repository, 'release_claim', Mock())
    monkeypatch.setattr(ranking_repository, 'latest_rank', Mock(return_value={
        'envelope': envelope, 'identity': ranking.identity(state, req.recipe), 'epoch': 1}))
    monkeypatch.setattr(reader_retrieval, 'build_candidate_batch', Mock(side_effect=AssertionError('no new retrieval')))
    monkeypatch.setattr(ranking, 'rank', Mock(side_effect=AssertionError('no new judgment')))
    async def phase(pool, operation, *, deadline):
        return operation(conn)
    monkeypatch.setattr(ranking, 'database_phase', phase)
    monkeypatch.setenv('S7_PROVIDER_ENABLED', 'true')
    # Simulate an acknowledged history revision; semantic RankBatch remains valid.
    manifest['history_revision'] += 1
    actual = asyncio.run(ranking.build_feed(object(), req.batch.user_id, limit=3))
    assert actual['status'] == 'ready'
    assert actual['feed_request_id'] != previous['feed_request_id']
    ranking.rank.assert_not_called()
    reader_retrieval.build_candidate_batch.assert_not_called()
    ranking_repository.release_claim.assert_called_once()


@pytest.mark.parametrize('field', ['delivery_position', '_reader_intent_ids', 'title'])
def test_corrupt_cached_card_cannot_change_attribution_or_display(publication, field):
    conn, req, _, _, _, envelope, _ = publication
    envelope['final']['articles'][0][field] = 99 if field == 'delivery_position' else 'forged'
    assert ranking.cached_feed(conn, req.batch.user_id, limit=1)['status'] == 'needs_build'
