"""Offline lifecycle checks; database races are tested separately on PostgreSQL."""
import asyncio
import importlib
import sys
import types
from types import SimpleNamespace
from unittest import IsolatedAsyncioTestCase, TestCase
from unittest.mock import AsyncMock, Mock, patch

existing = sys.modules.get('httpx')
if not isinstance(existing, types.ModuleType) or not getattr(existing, '__spec__', None):
    sys.modules.pop('httpx', None)
importlib.import_module('httpx')

from app.services import understanding_repository as repo
from app.services.understanding_provider import ProviderFailure
from app.services.understanding_worker import UnderstandingWorker


class WorkerTests(IsolatedAsyncioTestCase):
    def setUp(self):
        self.job = {'id': 1, 'stage': 'facets', 'attempts': 1, 'definition': {}}
        self.bundle = {'input_hash': 'revision-one'}
        self.provider = SimpleNamespace(estimate_usd=Mock(return_value=.02),
            generate=AsyncMock(return_value=SimpleNamespace(payload={}, usage_usd=.01, request_id='request-1')))
        self.worker = UnderstandingWorker(None, self.provider)
        self.calls = []
        self.results = {'prepare': self.bundle, 'reserve': 'reservation', 'publish': True}

        async def database(function, *args, **kwargs):
            self.calls.append((function.__name__, args, kwargs))
            return self.results.get(function.__name__)
        self.worker.db = database

    async def test_charge_settles_before_publication(self):
        await self.worker.process(self.job)
        self.assertEqual([c[0] for c in self.calls], ['prepare', 'reserve', 'settle', 'publish'])
        self.assertEqual(self.calls[2][1], ('reservation', .01))

    async def test_budget_pause_has_no_request_and_refunds_attempt(self):
        self.results['reserve'] = None
        await self.worker.process(self.job)
        self.provider.generate.assert_not_awaited()
        self.assertEqual([c[0] for c in self.calls], ['prepare', 'reserve', 'defer_without_attempt'])

    async def test_stale_preparation_has_no_charge(self):
        self.results['prepare'] = None
        await self.worker.process(self.job)
        self.provider.generate.assert_not_awaited()
        self.assertEqual([c[0] for c in self.calls], ['prepare'])

    async def test_ambiguous_request_retains_reservation(self):
        self.provider.generate.side_effect = ProviderFailure('timeout', retryable=True, ambiguous=True)
        await self.worker.process(self.job)
        self.assertEqual([c[0] for c in self.calls], ['prepare', 'reserve', 'fail'])

    async def test_known_rejection_releases_reservation(self):
        self.provider.generate.side_effect = ProviderFailure('rejected', retryable=False)
        await self.worker.process(self.job)
        self.assertEqual(self.calls[-2][1], ('reservation', 0))
        self.assertFalse(self.calls[-1][2]['retryable'])

    async def test_invalid_output_keeps_actual_provider_charge(self):
        self.provider.generate.side_effect = ProviderFailure('invalid_output', usage_usd=.015)
        await self.worker.process(self.job)
        self.assertEqual(self.calls[-2][1], ('reservation', .015))
        self.assertNotIn('publish', [c[0] for c in self.calls])

    async def test_cancellation_does_not_release_ambiguous_charge(self):
        self.provider.generate.side_effect = asyncio.CancelledError()
        with self.assertRaises(asyncio.CancelledError):
            await self.worker.process(self.job)
        self.assertEqual([c[0] for c in self.calls], ['prepare', 'reserve'])

    async def test_successful_but_stale_output_still_charged(self):
        self.results['publish'] = False
        await self.worker.process(self.job)
        self.assertEqual([c[0] for c in self.calls], ['prepare', 'reserve', 'settle', 'publish'])

    async def test_shutdown_cancels_active_work(self):
        started = asyncio.Event()
        cancelled = asyncio.Event()

        async def blocked_tick():
            started.set()
            try:
                await asyncio.Event().wait()
            finally:
                cancelled.set()
        self.worker.tick = blocked_tick
        running = asyncio.create_task(self.worker.run())
        await asyncio.wait_for(started.wait(), 1)
        self.worker.stop.set()
        await asyncio.wait_for(running, 1)
        self.assertTrue(cancelled.is_set())

    async def test_fresh_and_backfill_each_get_claim_capacity(self):
        self.results['claim'] = []
        for _ in range(4):
            await self.worker.tick()
        first_claims = [call for call in self.calls if call[0] == 'claim'][::2]
        self.assertEqual([call[2]['fresh'] for call in first_claims], [True, True, True, False])


class PublicationFenceTests(TestCase):
    def test_expired_final_write_aborts_transaction_before_returning_false(self):
        events = []

        class Transaction:
            def __enter__(self):
                events.append('begin')
            def __exit__(self, kind, value, traceback):
                events.append('rollback' if kind else 'commit')

        conn = SimpleNamespace(execute=Mock(return_value=SimpleNamespace(rowcount=0)))

        @repo.lease_fenced
        def publish():
            with Transaction():
                repo.finish_publication(conn, {'id': 1, 'lease_token': 'old'})
            return True

        self.assertFalse(publish())
        self.assertEqual(events, ['begin', 'rollback'])
        self.assertIn('clock_timestamp()', conn.execute.call_args[0][0])

    def test_money_rejects_unknown_or_nonfinite_and_rounds_up(self):
        for value in ('NaN', 'Infinity', '-1'):
            with self.assertRaises(ValueError):
                repo._money(value)
        self.assertEqual(str(repo._money('0.000000001')), '1E-8')


class CurrentResultTests(TestCase):
    def load(self, *, latest=None, enabled=True, stages=('facets', 'embedding')):
        bundle = {'input_hash': 'hash', 'semantic_revision': 1,
                  'analysis_eligibility_generation': 1}
        results = [{'stage': stage} for stage in stages]

        def execute(query, args):
            if 'article_understanding_current' in query:
                return SimpleNamespace(fetchall=lambda: results)
            if 'story_memberships' in query:
                return SimpleNamespace(fetchone=lambda: {'cluster_id': 'cluster'})
            return SimpleNamespace(fetchone=lambda: {'enabled': enabled})
        with patch.object(repo, 'evidence_for_article', side_effect=[bundle, latest or bundle]):
            return repo.load_current(SimpleNamespace(execute=execute), 'article', 'recipe')

    def test_disabled_recipe_cannot_expose_current_results(self):
        self.assertEqual(self.load(enabled=False), {'state': 'disabled'})

    def test_partial_understanding_never_exposes_old_membership(self):
        current = self.load(stages=('facets',))
        self.assertEqual(current['state'], 'partial')
        self.assertIsNone(current['membership'])

    def test_mid_read_revision_or_eligibility_change_is_stale(self):
        for field in ('semantic_revision', 'analysis_eligibility_generation'):
            latest = {'input_hash': 'hash', 'semantic_revision': 1,
                      'analysis_eligibility_generation': 1, field: 2}
            self.assertEqual(self.load(latest=latest), {'state': 'stale'})

    def test_current_ready_results_include_membership(self):
        current = self.load()
        self.assertEqual(current['state'], 'ready')
        self.assertEqual(current['membership'], {'cluster_id': 'cluster'})
