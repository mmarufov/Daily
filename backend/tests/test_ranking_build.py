"""Offline S7 preparation/build orchestration; no providers, SQL or servers."""
from contextlib import ExitStack
import copy
import unittest
from unittest.mock import Mock, patch

from app.services import ranking_service as service
from app.services import ranking_repository, ranking_provider
from app.services import reader_retrieval, reader_repository, reader_feedback
from app.services.retrieval_contract import article_stamp
from app.services.reader_contract import canonical_hash
from tests.test_ranking_service import make_request, FakeProvider, NOW, INTENT


def snapshot(request):
    return {'profile': request.profile.model_dump(), 'generation': 1, 'revision': 1,
            'learning_revision': 1, 'migration_status': 'ready'}


class PreparationTests(unittest.TestCase):
    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.req = make_request()
        self.snapshot = snapshot(self.req)
        self.conn = Mock()
        self.conn.transaction = lambda: ExitStack()
        self.article = {**self.req.batch.candidates[0].article,
            'summary': 'Publisher summary', 'published_at': NOW,
            'content': 'Untrusted raw display body', 'display_body': 'Display-only text',
            'analysis_text': 'Legacy unvalidated analysis', 'embedding': [1., 0.]}
        self.bundle = {'evidence_tier': 'publisher_analysis',
                       'fields': {'title': 'Science discovery', 'body': 'Verified publisher analysis'}}
        self.row = {'article': self.article, 'current': {'evidence': self.bundle},
                    'policy': {'topic_ids': ['science']}}
        self.stack.enter_context(patch.object(reader_retrieval, '_s6_recipe', return_value=None))
        self.hydrate = self.stack.enter_context(patch.object(reader_retrieval, '_s6_hydrate',
            return_value={self.req.evidence[0].article_id: self.row}))
        self.evidence_stamp = self.stack.enter_context(patch.object(reader_retrieval,
            '_s6_evidence_stamp', return_value={}))
        self.learned = self.stack.enter_context(patch.object(reader_feedback,
            'load_learned_weights', return_value={INTENT: .1}))
        self.freeze()

    def freeze(self):
        candidate = self.req.batch.candidates[0]
        candidate.article = copy.deepcopy(self.article)
        candidate.article_stamp = article_stamp(self.article)

    def prepare(self):
        return service.prepare_request(self.conn, self.req.batch, self.snapshot)

    def test_current_exact_hydration_builds_allowlisted_analysis_and_frozen_learning(self):
        prepared = self.prepare()
        pack = prepared.evidence[0]
        self.assertEqual(pack.analysis, 'Verified publisher analysis')
        self.assertTrue(pack.analysis_allowed)
        self.assertEqual(pack.central_ids['topic_ids'], ['science'])
        self.assertEqual(prepared.learned, {INTENT: .1})
        self.hydrate.assert_called_once_with(self.conn, [pack.article_id], None)
        self.learned.assert_called_once_with(self.conn, self.req.batch.user_id, self.snapshot, as_of=NOW)

    def test_missing_changed_article_or_changed_evidence_cannot_prepare(self):
        from app.services.reader_repository import ReaderConflict
        for mode in ('missing', 'article', 'evidence'):
            with self.subTest(mode=mode):
                self.hydrate.return_value = {self.req.evidence[0].article_id: self.row}
                self.evidence_stamp.return_value = {}
                self.freeze()
                if mode == 'missing':
                    self.hydrate.return_value = {}
                elif mode == 'article':
                    self.article['summary'] += ' changed'
                else:
                    self.evidence_stamp.return_value = {'recipe_id': 'changed'}
                with self.assertRaises(ReaderConflict):
                    self.prepare()
        self.learned.assert_not_called()

    def test_revocation_removes_analysis_even_if_current_bundle_contains_body(self):
        self.article['analysis_revoked'] = True
        self.freeze()
        pack = self.prepare().evidence[0]
        self.assertEqual(pack.analysis, '')
        self.assertEqual(pack.tier, 'revoked')
        self.assertFalse(pack.analysis_allowed)

    def test_s2_and_legacy_raw_body_cannot_become_provider_analysis(self):
        self.row['current'] = {}
        pack = self.prepare().evidence[0]
        self.assertEqual(pack.analysis, '')
        self.assertEqual(pack.title, self.article['title'])
        self.assertNotIn('Untrusted raw', pack.model_dump_json())
        self.assertNotIn('Legacy unvalidated', pack.model_dump_json())

    def test_cache_strips_bodies_and_embedding_without_mutating_retrieval_or_digest(self):
        before = self.req.batch.model_dump()
        prepared = self.prepare()
        candidate = prepared.batch.candidates[0]
        self.assertEqual(candidate.article_stamp, article_stamp(self.article))
        for key in ('content', 'display_body', 'analysis_text', 'embedding'):
            self.assertNotIn(key, candidate.article)
            self.assertIn(key, self.req.batch.candidates[0].article)
        self.assertEqual(self.req.batch.model_dump(), before)
        self.assertEqual(candidate.article['id'], self.article['id'])


class BuildTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.stack.enter_context(patch.dict('os.environ', {
            'S7_SERVING_ENABLED': 'true', 'S5_READER_ENABLED': 'true', 'S6_SERVING_ENABLED': 'true',
            'S7_PROVIDER_ENABLED': 'false', 'S7_BACKGROUND_ENABLED': 'false', 'S7_SHADOW_ENABLED': 'true'}))
        self.req = make_request()
        self.snapshot = snapshot(self.req)
        self.control = {'approved': True, 'serving': True, 'provider': True,
                        'recipe': self.req.recipe, 'recipe_hash': canonical_hash(self.req.recipe)}
        self.conn = Mock()
        self.conn.transaction = lambda: ExitStack()
        self.pool = object()
        self.in_database = False
        self.phases = 0

        async def phase(pool, operation, *, deadline):
            self.assertIs(pool, self.pool)
            self.assertFalse(self.in_database)
            self.in_database = True
            self.phases += 1
            try:
                return operation(self.conn)
            finally:
                self.in_database = False

        real_rank = service.rank
        async def rank(request, **kwargs):
            self.assertFalse(self.in_database)
            return await real_rank(request, now=lambda: NOW, **kwargs)

        self.stack.enter_context(patch.object(service, 'database_phase', side_effect=phase))
        self.stack.enter_context(patch.object(service, 'rank', side_effect=rank))
        self.stack.enter_context(patch.object(reader_repository, 'load_reader', return_value=self.snapshot))
        self.stack.enter_context(patch.object(ranking_repository, 'control', return_value=self.control))
        self.claim = self.stack.enter_context(patch.object(ranking_repository, 'claim_build',
            return_value={'build_id': 'build', 'token': 'owner'}))
        self.retrieve = self.stack.enter_context(patch.object(reader_retrieval, 'build_candidate_batch',
            return_value=self.req.batch))
        self.stack.enter_context(patch.object(service, 'prepare_request', return_value=self.req))
        self.reserve = self.stack.enter_context(patch.object(ranking_repository, 'reserve',
            return_value={'reservation_id': 'reservation'}))
        self.settle = self.stack.enter_context(patch.object(ranking_repository, 'settle'))
        self.release = self.stack.enter_context(patch.object(ranking_repository, 'release_claim'))
        self.publish = self.stack.enter_context(patch.object(service, '_publish',
            return_value={'status': 'ready', 'articles': []}))
        self.factory = self.stack.enter_context(patch.object(ranking_provider, 'RankingProvider'))

    async def build(self, **kwargs):
        return await service.build_feed(self.pool, self.req.batch.user_id, **kwargs)

    async def test_default_flag_never_constructs_provider_or_reserves_spend(self):
        self.assertEqual((await self.build())['status'], 'ready')
        self.factory.assert_not_called()
        self.reserve.assert_not_called()
        self.assertEqual(self.publish.call_args.args[3].diagnostics['attempts'], 0)
        self.release.assert_called_once_with(self.conn, self.req.batch.user_id, 'build', 'owner')

    async def test_provider_runs_outside_database_and_settles_reservation_id(self):
        owner = self
        class CheckedProvider(FakeProvider):
            async def judge(self, *args, **kwargs):
                owner.assertFalse(owner.in_database)
                return await super().judge(*args, **kwargs)
        adapter = CheckedProvider()
        self.factory.return_value = adapter
        with patch.dict('os.environ', {'S7_PROVIDER_ENABLED': 'true'}):
            self.assertEqual((await self.build())['status'], 'ready')
        self.assertEqual(len(adapter.calls), 1)
        self.reserve.assert_called_once_with(self.conn, self.req.batch.user_id, 'build', 'owner', 1, .1)
        self.settle.assert_called_once_with(self.conn, 'reservation', .01)
        self.assertEqual(self.publish.call_args.args[3].ordered_ids, [self.req.evidence[0].article_id])
        self.assertEqual(self.phases, 5)  # preflight, reserve, settle, publish, release

    async def test_background_and_shadow_do_not_inherit_foreground_spend_permission(self):
        with patch.dict('os.environ', {'S7_PROVIDER_ENABLED': 'true'}):
            self.assertEqual((await self.build(background=True))['status'], 'ready')
            self.publish.reset_mock()
            result = await self.build(shadow=True)
        self.factory.assert_not_called()
        self.reserve.assert_not_called()
        self.publish.assert_not_called()
        self.assertEqual(result['provider_calls'], 0)

    async def test_missing_approval_never_claims_retrieves_or_spends(self):
        self.control['approved'] = False
        result = await self.build()
        self.assertEqual(result['status'], 'unavailable')
        self.claim.assert_not_called()
        self.retrieve.assert_not_called()
        self.factory.assert_not_called()
        self.publish.assert_not_called()

    async def test_publication_conflict_returns_needs_build_and_releases_owner_claim(self):
        from app.services.reader_repository import ReaderConflict
        self.publish.side_effect = ReaderConflict('reader_changed')
        self.assertEqual((await self.build())['status'], 'needs_build')
        self.release.assert_called_once_with(self.conn, self.req.batch.user_id, 'build', 'owner')

    async def test_wrong_retrieval_account_cannot_reach_scorer(self):
        batch = self.req.batch.model_copy(update={'user_id': 'wrong-account'})
        self.retrieve.return_value = batch
        self.assertEqual((await self.build())['status'], 'needs_build')
        self.factory.assert_not_called()
        self.reserve.assert_not_called()
        self.publish.assert_not_called()
