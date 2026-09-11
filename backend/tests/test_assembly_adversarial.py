"""Cross-module S8 negative paths using real contracts, with no live IO.

Fakes test orchestration, not PostgreSQL rollback/isolation or semantic accuracy.
"""
import asyncio
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from unittest.mock import Mock

import pytest

from app.services import assembly_repository, ranking_service
from app.services import ranking_repository, reader_feedback, reader_repository, reader_retrieval
from app.services import ranking_provider
from app.services.understanding_contract import build_evidence
from tests.test_assembly_integration import setup_input, assemble
from tests.test_understanding_contract import row, artifact


def native_article():
    article = row()
    body = artifact()
    article.update(presentation_mode='native_full_text', body_state='verified_full',
        display_content_artifact_id=body['id'], display_rights_basis='publisher_permission',
        display_effective_completeness='complete', display_policy_version=1, content_version=1,
        artifact_kind=body['kind'], artifact_origin_url=body['origin_url'],
        artifact_extractor_version=body['extractor_version'], artifact_completeness='complete',
        artifact_confidence=body['confidence'], artifact_content_hash=body['content_hash'])
    return article


def test_actual_s3_manifest_produces_content_proof_not_fixture_only_fields():
    article = native_article()
    bundle = build_evidence(article, artifact())
    current = {'article': article, 'article_id': article['id'], 'state': 'ready',
               'evidence': bundle, 'recipe_id': 's3', 'input_hash': bundle['input_hash']}
    proof = assembly_repository.candidate_evidence(current)
    assert bundle['manifest']['artifact']['text_hash']
    assert bundle['manifest']['artifact']['content_hash']
    assert proof['novelty_key'] and len(proof['novelty_key']) == 64
    assert proof['coverage_key'] is None
    assert proof['identity_verified'] is False
    # Display-only drift cannot fabricate a new content snapshot.
    article.update(image_url='https://publisher.example.com/new-image.jpg', published_at=datetime.now(timezone.utc))
    current['evidence'] = build_evidence(article, artifact())
    assert assembly_repository.candidate_evidence(current)['novelty_key'] == proof['novelty_key']
    current['evidence'] = build_evidence(article, artifact(text='The publisher corrected its original report.'))
    assert assembly_repository.candidate_evidence(current)['novelty_key'] != proof['novelty_key']


@pytest.mark.parametrize('change', [{'article_id': 'wrong-owner'}, {'completeness': 'partial'},
                                   {'is_current': False}, {'analysis_allowed': False}])
def test_real_s3_untrusted_or_incomplete_body_cannot_suppress_read(change):
    article = row()
    current = {'article': article, 'evidence': build_evidence(article, artifact(**change))}
    assert assembly_repository.candidate_evidence(current)['novelty_key'] is None


def test_real_s3_proof_survives_adapter_into_own_article_receipt():
    req, ranked, state, manifest = setup_input(1)
    identity = ranked.ordered_ids[0]
    article = native_article()
    article['id'] = identity
    body = artifact(article_id=identity)
    proof = assembly_repository.candidate_evidence({'article': article, 'article_id': identity,
        'evidence': build_evidence(article, body), 'state': 'ready'})
    manifest['candidates'][identity] = proof
    req.batch.candidates[0].article = article
    ranked.context_hash = req.fingerprint
    final, _ = assemble(req, ranked, state, manifest)
    conn = Mock()
    reader_feedback.record_delivery(conn, req.batch.user_id, req.batch.request_id, state, final['articles'])
    insert = next(call for call in conn.execute.call_args_list if 'INSERT INTO public.reader_delivery_receipts' in call.args[0])
    args = insert.args[1]
    assert args[2] == identity
    assert args[-1] == proof['analysis_content_hash']
    assert args[-2] == proof['novelty_key']
    assert args[-3] == 'article:' + identity
    assert args[-4] == final['articles'][0]['_assembly_recipe']


def test_source_web_read_cannot_acknowledge_an_undisplayed_analysis_body():
    from app.services.article_content import serialize_article
    req, ranked, state, manifest = setup_input(1)
    identity = ranked.ordered_ids[0]
    article = row()
    article['id'] = identity
    current = {'article': article, 'article_id': article['id'], 'state': 'ready',
               'evidence': build_evidence(article, artifact(article_id=identity))}
    assert current['evidence']['evidence_tier'] == 'original_body'
    assert serialize_article(article, include_body=False)['presentation']['mode'] == 'source_web'
    # Repository proof is potential analysis identity; only the adapter can tie
    # it to the actual S2 card/display route before making a delivery receipt.
    manifest['candidates'][identity] = assembly_repository.candidate_evidence(current)
    final, _ = assemble(req, ranked, state, manifest)
    assert final['articles'][0]['_assembly_novelty_key'] is None


@pytest.mark.parametrize('display_hash', [None, '0'*64])
def test_different_or_unproved_native_display_cannot_inherit_analysis_read_history(display_hash):
    req, ranked, state, manifest = setup_input(1)
    identity = ranked.ordered_ids[0]
    article = native_article()
    article['id'] = identity
    proof = assembly_repository.candidate_evidence({'article': article, 'article_id': identity,
        'state': 'ready', 'evidence': build_evidence(article, artifact(article_id=identity))})
    proof['known_read'] = True
    article['artifact_content_hash'] = display_hash
    req.batch.candidates[0].article = article
    ranked.context_hash = req.fingerprint
    manifest['candidates'][identity] = proof
    final, _ = assemble(req, ranked, state, manifest)
    assert [a['id'] for a in final['articles']] == [identity]
    assert final['articles'][0]['_assembly_novelty_key'] is None


def test_expired_semantic_rank_is_not_reused_despite_recent_edition_timestamp(monkeypatch):
    req, ranked, state, _ = setup_input(1)
    expired = datetime.now(timezone.utc)-timedelta(seconds=1)
    req.batch.as_of = expired-timedelta(minutes=15)
    req.batch.valid_until = expired
    ranked.context_hash = req.fingerprint
    ranked.valid_until = expired
    control = {'recipe': req.recipe, 'recipe_hash': ranked.recipe_hash, 'epoch': 1}
    stored = {'identity': ranking_service.identity(state, req.recipe), 'epoch': 1,
        'created_at': datetime.now(timezone.utc), 'expires_at': datetime.now(timezone.utc)+timedelta(minutes=10),
        'envelope': {'request': req.model_dump(mode='json'), 'ranked': ranked.model_dump(mode='json')}}
    monkeypatch.setattr(ranking_repository, 'latest_rank', Mock(return_value=stored))
    authorize = Mock(side_effect=AssertionError('Expired semantics cannot be authorized/replayed'))
    monkeypatch.setattr(reader_retrieval, 'authorize_candidate_batch', authorize)
    assert ranking_service._reuse_rank(Mock(), req.batch.user_id, state, control) is None
    authorize.assert_not_called()


def test_history_only_build_reuse_cannot_construct_provider_or_retrieve_again(monkeypatch):
    req, ranked, state, _ = setup_input(1)
    conn = Mock()
    @contextmanager
    def transaction():
        yield
    conn.transaction = transaction
    for name in ('S5_READER_ENABLED', 'S6_SERVING_ENABLED', 'S7_SERVING_ENABLED',
                 'S8_SERVING_ENABLED', 'S7_PROVIDER_ENABLED'):
        monkeypatch.setenv(name, 'true')
    control = {'recipe': req.recipe, 'recipe_hash': ranked.recipe_hash,
               'epoch': 1, 'approved': True, 'serving': True, 'provider': True}
    async def database_phase(pool, operation, **kwargs):
        return operation(conn)
    monkeypatch.setattr(ranking_service, 'database_phase', database_phase)
    monkeypatch.setattr(reader_repository, 'load_reader', Mock(return_value=state))
    monkeypatch.setattr(ranking_repository, 'control', Mock(return_value=control))
    monkeypatch.setattr(assembly_repository, 'control', Mock(return_value={'approved': True, 'serving': True}))
    monkeypatch.setattr(ranking_repository, 'claim_build', Mock(return_value={'build_id': 'build', 'token': 'token'}))
    monkeypatch.setattr(ranking_repository, 'release_claim', Mock())
    monkeypatch.setattr(ranking_service, '_reuse_rank', Mock(return_value=(req, ranked)))
    forbidden = Mock(side_effect=AssertionError('History-only rebuild must reuse fresh authorized semantic judgments'))
    monkeypatch.setattr(reader_retrieval, 'build_candidate_batch', forbidden)
    monkeypatch.setattr(ranking_service, 'prepare_request', forbidden)
    monkeypatch.setattr(ranking_service, 'rank', forbidden)
    monkeypatch.setattr(ranking_provider, 'RankingProvider', forbidden)
    publish = Mock(return_value={'status': 'ready', 'articles': [], 'feed_request_id': 'new-edition'})
    monkeypatch.setattr(ranking_service, '_publish', publish)
    result = asyncio.run(ranking_service.build_feed(object(), req.batch.user_id))
    assert result['feed_request_id'] == 'new-edition'
    assert publish.call_args.args[2] is req and publish.call_args.args[3] is ranked
    forbidden.assert_not_called()


def test_unapproved_s8_fails_before_provider_retrieval_or_rank_reuse(monkeypatch):
    req, ranked, state, _ = setup_input(1)
    conn = Mock()
    @contextmanager
    def transaction():
        yield
    conn.transaction = transaction
    for name in ('S5_READER_ENABLED', 'S6_SERVING_ENABLED', 'S7_SERVING_ENABLED', 'S8_SERVING_ENABLED'):
        monkeypatch.setenv(name, 'true')
    async def database_phase(pool, operation, **kwargs):
        return operation(conn)
    monkeypatch.setattr(ranking_service, 'database_phase', database_phase)
    monkeypatch.setattr(reader_repository, 'load_reader', Mock(return_value=state))
    monkeypatch.setattr(ranking_repository, 'control', Mock(return_value={
        'approved': True, 'serving': True, 'recipe': req.recipe, 'recipe_hash': ranked.recipe_hash}))
    monkeypatch.setattr(ranking_repository, 'claim_build', Mock(return_value={'build_id': 'build', 'token': 'token'}))
    monkeypatch.setattr(ranking_repository, 'release_claim', Mock())
    monkeypatch.setattr(assembly_repository, 'control', Mock(return_value={'approved': False, 'serving': False}))
    forbidden = Mock(side_effect=AssertionError('No work is admitted without assembly approval'))
    monkeypatch.setattr(ranking_service, '_reuse_rank', forbidden)
    monkeypatch.setattr(reader_retrieval, 'build_candidate_batch', forbidden)
    monkeypatch.setattr(ranking_provider, 'RankingProvider', forbidden)
    assert asyncio.run(ranking_service.build_feed(object(), req.batch.user_id))['status'] == 'needs_build'
    forbidden.assert_not_called()
