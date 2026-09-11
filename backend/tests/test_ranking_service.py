"""Deterministic S7 proof. No real provider, database, or server is used."""
import asyncio
from contextlib import ExitStack, contextmanager
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch
from uuid import UUID

from app.services import ranking_service as service
from app.services.ranking_contract import (ArticleJudgment, EvidencePack, IntentGrade,
    RankingRequest, RankBatch, validate_judgments)
from app.services.reader_contract import ReaderProfile, canonical_hash
from app.services.retrieval_contract import CandidateBatch, Candidate, Match


NOW = datetime(2026, 9, 8, tzinfo=timezone.utc)
INTENT = str(UUID(int=700))
SECOND = str(UUID(int=701))


def make_request(count=1, *, generic=False):
    profile = ReaderProfile(intents=[] if generic else [
        {'id': INTENT, 'kind': 'topic', 'label': 'Science', 'resolved_id': 'science'}])
    packs = [EvidencePack(article_id=str(UUID(int=i+1)), input_hash='input-' + str(i),
        title='Science discovery', summary='New evidence from scientists.',
        analysis='Publisher-owned analysis.', analysis_allowed=True, tier='publisher_analysis',
        published_at=NOW-timedelta(hours=i), central_ids={'topic_ids': ['science']},
        retrieval_intent_ids=[] if generic else [INTENT]) for i in range(count)]
    batch = CandidateBatch(request_id=str(UUID(int=800)), user_id=str(UUID(int=900)),
        generation=1, revision=1, learning_revision=1, reader_hash=canonical_hash(profile.model_dump()),
        as_of=NOW, valid_until=NOW+timedelta(minutes=15), retrieval_recipe='s6',
        configuration={}, s3_recipe_id=None, space_id=None, status='complete', diagnostics={},
        candidates=[Candidate(article_id=pack.article_id, allocated_intent_id=None if generic else INTENT,
            matched_intent_ids=[] if generic else [INTENT], matches=[Match(
                intent_id=None if generic else INTENT, leg='generic' if generic else 'lexical',
                variant='strict', rank=i+1, score=1., query_hash='query')],
            retrieval_score=.1, article_stamp='stamp', evidence_stamp={}, policy_evidence={},
            article={'id': pack.article_id, 'title': pack.title, 'source_id': 'publisher', 'language': 'en'})
            for i, pack in enumerate(packs)])
    return RankingRequest(batch=batch, profile=profile, evidence=packs)


def accept(pack, *, intent_id=INTENT, grade=2):
    return ArticleJudgment(article_id=pack.article_id, input_hash=pack.input_hash,
        decision='accept', reason='substantive_match', explanation='Substantive evidence.',
        confirmed_intent_ids=[intent_id], grades=[IntentGrade(intent_id=intent_id, grade=grade,
            qualifiers='satisfied', field='title', quote='Science discovery')])


def rejected(pack, *, intent_id=INTENT):
    return ArticleJudgment(article_id=pack.article_id, input_hash=pack.input_hash,
        decision='reject', reason='not_relevant', explanation='Not relevant.',
        confirmed_intent_ids=[], grades=[IntentGrade(intent_id=intent_id, grade=0,
            qualifiers='satisfied', field='title', quote='')])


class FakeProvider:
    def __init__(self, outcome=None, *, max_items=50, fail=None, hang=False):
        self.outcome, self.max_items, self.fail, self.hang = outcome, max_items, fail, hang
        self.calls = []

    def prepare(self, request, packs):
        from app.services.ranking_provider import ProviderFailure
        if len(packs) > self.max_items:
            raise ProviderFailure('input_limit')
        return SimpleNamespace(reserved_usd=.1)

    async def judge(self, request, packs, *, prepared):
        self.calls.append([pack.article_id for pack in packs])
        if self.hang:
            await asyncio.Event().wait()
        if self.fail:
            raise self.fail
        judgments = self.outcome(request, packs) if self.outcome else [accept(pack) for pack in reversed(packs)]
        return SimpleNamespace(judgments=judgments, input_tokens=100, output_tokens=20, usage_usd=.01)


class ContractTests(unittest.TestCase):
    def test_exact_candidate_evidence_set(self):
        data = make_request(2).model_dump()
        for packs in [data['evidence'][:1], [data['evidence'][0]]*2,
                      [*data['evidence'], {**data['evidence'][0], 'article_id': 'foreign'}]]:
            with self.subTest(packs=packs), self.assertRaises(ValueError):
                RankingRequest.model_validate({**data, 'evidence': packs})

    def test_wrong_reader_rejected(self):
        data = make_request().model_dump()
        data['profile']['depth'] = 'deep'
        with self.assertRaises(ValueError):
            RankingRequest.model_validate(data)

    def test_nonfinite_and_unbounded_learning_rejected(self):
        for weight in [float('nan'), float('inf'), -1.01, .81]:
            data = make_request().model_dump()
            with self.subTest(weight=weight), self.assertRaises(ValueError):
                RankingRequest.model_validate({**data, 'learned': {INTENT: weight}})

    def test_strict_grade_does_not_coerce(self):
        data = accept(make_request().evidence[0]).model_dump()
        for grade in ['2', True, 2.0, float('nan'), float('inf'), -1, 4]:
            data['grades'][0]['grade'] = grade
            with self.subTest(grade=grade), self.assertRaises(ValueError):
                ArticleJudgment.model_validate(data)

    def test_exact_identity_not_positional(self):
        req = make_request(2)
        judgments = [accept(pack) for pack in req.evidence]
        self.assertEqual(validate_judgments(req, req.evidence, list(reversed(judgments)))[0].article_id,
                         req.evidence[1].article_id)
        for values in [judgments[:1], [judgments[0]]*2,
                       [judgments[0], judgments[1].model_copy(update={'article_id': 'foreign'})]]:
            with self.subTest(values=values), self.assertRaises(ValueError):
                validate_judgments(req, req.evidence, [value.model_dump() for value in values])

    def test_hash_and_quote_must_match_frozen_input(self):
        req = make_request()
        for field, value in [('input_hash', 'other'), ('quote', 'invented evidence')]:
            data = accept(req.evidence[0]).model_dump()
            if field == 'quote':
                data['grades'][0][field] = value
            else:
                data[field] = value
            with self.subTest(field=field), self.assertRaises(ValueError):
                validate_judgments(req, req.evidence, [data])

    def test_positive_requires_quote_and_qualifiers(self):
        req = make_request()
        for field, value in [('quote', ''), ('qualifiers', 'unknown'), ('qualifiers', 'contradicted')]:
            data = accept(req.evidence[0]).model_dump()
            data['grades'][0][field] = value
            with self.subTest(field=field, value=value), self.assertRaises(ValueError):
                validate_judgments(req, req.evidence, [data])

    def test_rejection_requires_all_intents_assessed(self):
        req = make_request()
        req.profile.intents.append(req.profile.intents[0].model_copy(update={'id': SECOND}))
        with self.assertRaises(ValueError):
            validate_judgments(req, req.evidence, [rejected(req.evidence[0])])

    def test_unknown_intent_and_duplicate_attribution_rejected(self):
        req = make_request()
        data = accept(req.evidence[0], intent_id=SECOND).model_dump()
        with self.assertRaises(ValueError):
            validate_judgments(req, req.evidence, [data])
        data = accept(req.evidence[0]).model_dump()
        data['confirmed_intent_ids'] *= 2
        with self.assertRaises(ValueError):
            ArticleJudgment.model_validate(data)

    def test_provider_cannot_use_revoked_or_deterministic_authority(self):
        req = make_request()
        req.evidence[0].analysis_allowed = False
        with self.assertRaises(ValueError):
            validate_judgments(req, req.evidence, [accept(req.evidence[0])], provider=True)
        req.evidence[0].analysis_allowed = True
        data = accept(req.evidence[0]).model_dump()
        data['reason'] = 'central_identity'
        with self.assertRaises(ValueError):
            validate_judgments(req, req.evidence, [data], provider=True)

    def test_rank_order_is_exact_accepted_set(self):
        req = make_request(2)
        data = dict(request_id=req.batch.request_id, context_hash=req.fingerprint,
            recipe_hash=canonical_hash(req.recipe), status='complete', valid_until=req.batch.valid_until,
            judgments=[accept(req.evidence[0]), rejected(req.evidence[1])])
        for ids in [[], [req.evidence[1].article_id], [req.evidence[0].article_id]*2]:
            with self.subTest(ids=ids), self.assertRaises(ValueError):
                RankBatch(**data, ordered_ids=ids)


class RankTests(unittest.IsolatedAsyncioTestCase):
    async def run_provider(self, req, provider, **kwargs):
        self.reservations, self.settlements = [], []
        async def reserve(attempt, amount):
            row = {'attempt': attempt, 'amount': amount}
            self.reservations.append(row)
            return row
        async def settle(row, actual):
            self.settlements.append((row, actual))
        return await service.rank(req, provider=provider, reserve=reserve, settle=settle,
                                  now=lambda: NOW, **kwargs)

    async def test_default_is_zero_spend_and_all_300_ids_abstain(self):
        req = make_request(300)
        result = await service.rank(req, now=lambda: NOW)
        self.assertEqual(len(result.judgments), 300)
        self.assertTrue(all(j.decision == 'abstain' for j in result.judgments))
        self.assertEqual(result.ordered_ids, [])
        self.assertEqual(result.diagnostics['attempts'], 0)
        self.assertEqual(result.status, 'degraded')

    async def test_generic_mode_is_not_personal_relevance(self):
        req = make_request(3, generic=True)
        result = await service.rank(req, now=lambda: NOW)
        self.assertEqual(result.ordered_ids, [e.article_id for e in req.evidence])
        self.assertTrue(all(j.reason == 'generic' and not j.confirmed_intent_ids for j in result.judgments))

    async def test_revoked_never_provider_or_generic(self):
        req = make_request(generic=True)
        req.evidence[0].tier = 'revoked'
        req.evidence[0].analysis_allowed = False
        adapter = FakeProvider()
        result = await self.run_provider(req, adapter)
        self.assertFalse(adapter.calls)
        self.assertEqual(result.judgments[0].reason, 'analysis_revoked')

    async def test_central_identity_requires_explicit_capability_and_no_qualifiers(self):
        req = make_request()
        self.assertEqual(service.baseline(req)[0].decision, 'abstain')
        req.recipe['central_identity'] = True
        self.assertEqual(service.baseline(req)[0].decision, 'accept')
        for change in [{'qualifiers': ['Only direct practical breakthroughs']},
                       {'query': 'Science funding cuts'}]:
            changed = req.model_copy(deep=True)
            for key, value in change.items():
                setattr(changed.profile.intents[0], key, value)
            self.assertEqual(service.baseline(changed)[0].decision, 'abstain')
        req.evidence[0].truncated = True
        self.assertEqual(service.baseline(req)[0].decision, 'abstain')

    async def test_reordered_provider_maps_ids_and_settles_known_cost(self):
        req = make_request(3)
        result = await self.run_provider(req, FakeProvider())
        self.assertEqual(result.ordered_ids, [e.article_id for e in req.evidence])
        self.assertEqual(result.diagnostics['input_tokens'], 100)
        self.assertEqual(result.diagnostics['known_cost_usd'], .01)
        self.assertEqual(len(self.reservations), 1)
        self.assertEqual(self.settlements[0][1], .01)

    async def test_missing_or_duplicate_provider_results_abstain_whole_chunk(self):
        for outcome in [lambda req, packs: [accept(packs[0])],
                        lambda req, packs: [accept(packs[0])]*len(packs)]:
            result = await self.run_provider(make_request(2), FakeProvider(outcome))
            self.assertTrue(all(j.decision == 'abstain' for j in result.judgments))
            self.assertEqual(result.ordered_ids, [])

    async def test_attempt_cap_keeps_remaining_items_explicit(self):
        req = make_request(8)
        adapter = FakeProvider(max_items=1)
        result = await self.run_provider(req, adapter)
        self.assertEqual(len(adapter.calls), 6)
        self.assertEqual(len(result.judgments), 8)
        self.assertEqual(len(result.ordered_ids), 6)
        self.assertTrue(all(j.decision == 'abstain' for j in result.judgments[6:]))

    async def test_denied_budget_never_dispatches(self):
        adapter = FakeProvider()
        async def reserve(*args):
            raise RuntimeError('budget exhausted')
        async def settle(*args):
            self.fail('no reservation to settle')
        result = await service.rank(make_request(), provider=adapter, reserve=reserve, settle=settle,
                                    now=lambda: NOW)
        self.assertFalse(adapter.calls)
        self.assertEqual(result.judgments[0].reason, 'budget_exhausted')

    async def test_expired_deadline_never_spends(self):
        adapter = FakeProvider()
        result = await self.run_provider(make_request(), adapter, deadline=0)
        self.assertFalse(adapter.calls)
        self.assertFalse(self.reservations)
        self.assertEqual(result.judgments[0].reason, 'deadline')

    async def test_stale_future_or_expired_batch_rejected_before_reservation(self):
        from app.services.reader_repository import ReaderConflict
        for status, current in [('stale', NOW), ('complete', NOW-timedelta(seconds=1)),
                                ('complete', NOW+timedelta(minutes=15))]:
            req = make_request()
            req.batch.status = status
            adapter = FakeProvider()
            async def never(*args):
                self.fail('invalid batch reached budget store')
            with self.subTest(status=status, current=current), self.assertRaises(ReaderConflict):
                await service.rank(req, provider=adapter, reserve=never, settle=never, now=lambda: current)
            self.assertFalse(adapter.calls)

    async def test_known_cost_settled_even_when_judgment_validation_fails(self):
        result = await self.run_provider(make_request(2), FakeProvider(lambda req, packs: [accept(packs[0])]))
        self.assertEqual(self.settlements[0][1], .01)
        self.assertEqual(result.diagnostics['known_cost_usd'], .01)
        self.assertEqual(result.ordered_ids, [])

    async def test_timeout_keeps_ambiguous_reservation_and_never_retries(self):
        import time
        adapter = FakeProvider(hang=True)
        result = await self.run_provider(make_request(2), adapter, deadline=time.monotonic()+.025)
        self.assertEqual(len(adapter.calls), 1)
        self.assertFalse(self.settlements)
        self.assertTrue(all(j.reason == 'deadline' for j in result.judgments))

    async def test_cancellation_keeps_reservation(self):
        adapter = FakeProvider(hang=True)
        task = asyncio.create_task(self.run_provider(make_request(), adapter))
        for _ in range(100):
            if adapter.calls:
                break
            await asyncio.sleep(0)
        self.assertTrue(adapter.calls)
        task.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await task
        self.assertEqual(len(self.reservations), 1)
        self.assertFalse(self.settlements)

    async def test_provider_failure_does_not_invent_negative_truth(self):
        from app.services.ranking_provider import ProviderFailure
        adapter = FakeProvider(fail=ProviderFailure('transport_error', ambiguous=True))
        result = await self.run_provider(make_request(3), adapter)
        self.assertTrue(all(j.decision == 'abstain' for j in result.judgments))
        self.assertEqual(len(adapter.calls), 1)
        self.assertFalse(self.settlements)

    async def test_grade_then_priority_then_freshness_not_retrieval_score(self):
        req = make_request(4)
        req.profile.intents.append(req.profile.intents[0].model_copy(update={'id': SECOND, 'priority': 3.0}))
        req.learned = {INTENT: .8, SECOND: -1.0}
        judgments = [accept(req.evidence[0]), accept(req.evidence[1], intent_id=SECOND),
                     accept(req.evidence[2], grade=3), rejected(req.evidence[3])]
        req.batch.candidates[3].retrieval_score = 999999
        self.assertEqual(service.ordered(req, judgments), [req.evidence[i].article_id for i in (2, 1, 0)])

    async def test_same_grade_and_priority_use_stable_id_for_tie(self):
        req = make_request(2)
        req.evidence[1].published_at = req.evidence[0].published_at
        self.assertEqual(service.ordered(req, [accept(e) for e in reversed(req.evidence)]),
                         sorted(e.article_id for e in req.evidence))

    async def test_s6_adapter_never_promotes_rejection_or_abstention(self):
        req = make_request(3)
        result = await self.run_provider(req, FakeProvider(lambda req, packs:
            [accept(packs[0]), rejected(packs[1]), service.abstain(packs[2])]))
        decisions = service._decisions(req.batch, result)
        self.assertEqual([d.relevant for d in decisions], [True, False, False])
        self.assertEqual([d.score for d in decisions], [1., 0., 0.])


class PublicationTests(unittest.TestCase):
    """Exercise orchestration boundaries with fakes, not PostgreSQL isolation."""

    def setUp(self):
        from app.services import ranking_repository, ranking_events
        from app.services import reader_retrieval, reader_repository, reader_feedback
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.clock = self.stack.enter_context(patch.object(service, 'datetime', wraps=datetime))
        self.clock.now.return_value = NOW
        self.stack.enter_context(patch.dict('os.environ', {
            'S7_SERVING_ENABLED': 'true', 'S5_READER_ENABLED': 'true', 'S6_SERVING_ENABLED': 'true'}))
        self.req = make_request(3)
        self.snapshot = {'profile': self.req.profile.model_dump(), 'generation': 1,
                         'revision': 1, 'learning_revision': 1}
        self.ranked = RankBatch(request_id=self.req.batch.request_id,
            context_hash=self.req.fingerprint, recipe_hash=canonical_hash(self.req.recipe),
            status='complete', valid_until=self.req.batch.valid_until,
            judgments=[accept(p) for p in self.req.evidence],
            ordered_ids=[p.article_id for p in self.req.evidence])
        self.conn = Mock()
        self.conn.transaction = lambda: ExitStack()
        self.claim = {'build_id': 'build', 'token': 'token'}
        self.in_guard = False
        self.guard_aborted = False

        @contextmanager
        def guard(*args, **kwargs):
            self.in_guard = True
            try:
                yield
            except Exception:
                self.guard_aborted = True
                raise
            finally:
                self.in_guard = False

        self.guard = self.stack.enter_context(patch.object(reader_retrieval,
            'authorize_candidate_batch', side_effect=guard))
        self.control = self.stack.enter_context(patch.object(ranking_repository, 'control',
            return_value={'serving': True, 'recipe_hash': self.ranked.recipe_hash, 'epoch': 1}))
        self.publish = self.stack.enter_context(patch.object(ranking_repository, 'publish', return_value=True))
        self.latest = self.stack.enter_context(patch.object(ranking_repository, 'latest'))
        self.load_reader = self.stack.enter_context(patch.object(reader_repository, 'load_reader', return_value=self.snapshot))
        self.receipts = self.stack.enter_context(patch.object(reader_feedback, 'record_delivery'))
        self.event_receipts = self.stack.enter_context(patch.object(service, '_event_receipts'))
        self.stack.enter_context(patch.object(ranking_events, 'prepare', return_value=[]))
        self.stack.enter_context(patch.object(ranking_events, 'article_ids', return_value=[]))
        # Keep S2/S4 algorithms outside this unit: change order as an actual final
        # assembler would, and keep private learning provenance until serialization.
        self.ordinary = {'status': 'ready', 'article_count': 3, 'articles': [
            {'id': p.article_id, '_reader_intent_ids': [INTENT], '_ranking_recipe': self.ranked.recipe_hash}
            for p in self.req.evidence]}
        self.stack.enter_context(patch.object(service, '_ordinary', return_value=self.ordinary))
        self.final = {**self.ordinary, 'articles': list(reversed(self.ordinary['articles']))}
        self.compose = self.stack.enter_context(patch.object(service, '_compose', return_value=self.final))

    def do_publish(self):
        import time
        return service._publish(self.conn, self.req.batch.user_id, self.req, self.ranked,
                                self.snapshot, self.claim, 3, None, time.monotonic()+10)

    def cache(self):
        self.do_publish()
        args = self.publish.call_args.args
        self.latest.return_value = {'identity': args[4], 'envelope': args[5], 'epoch': 1}
        self.receipts.reset_mock()
        self.event_receipts.reset_mock()
        return args[5]

    def test_atomic_publication_uses_final_order_and_receipts_inside_guard(self):
        self.publish.side_effect = lambda *args: self.assertTrue(self.in_guard) or True
        self.receipts.side_effect = lambda *args: self.assertTrue(self.in_guard)
        self.event_receipts.side_effect = lambda *args: self.assertTrue(self.in_guard)
        result = self.do_publish()
        ids = [p.article_id for p in reversed(self.req.evidence)]
        self.assertEqual([a['id'] for a in result['articles']], ids)
        self.assertEqual([a['id'] for a in self.publish.call_args.args[5]['final']['articles']], ids)
        self.assertEqual([a['id'] for a in self.receipts.call_args.args[4]], ids)
        self.assertEqual(self.publish.call_args.args[6], self.ranked.valid_until)
        self.assertFalse(any(k.startswith('_') for a in result['articles'] for k in a))
        self.assertTrue(all(a['feed_request_id'] == result['feed_request_id'] for a in result['articles']))

    def test_cas_failure_cannot_write_delivery_receipts(self):
        from app.services.reader_repository import ReaderConflict
        self.publish.return_value = False
        with self.assertRaises(ReaderConflict):
            self.do_publish()
        self.receipts.assert_not_called()
        self.event_receipts.assert_not_called()

    def test_expiry_after_receipts_raises_inside_guard_instead_of_returning_feed(self):
        from app.services.reader_repository import ReaderConflict
        def advance_after_receipts(*args):
            self.assertTrue(self.in_guard)
            self.clock.now.return_value = self.ranked.valid_until
        self.receipts.side_effect = advance_after_receipts
        with self.assertRaisesRegex(ReaderConflict, 'ranking_delivery_expired'):
            self.do_publish()
        self.publish.assert_called_once()
        self.receipts.assert_called_once()
        self.assertTrue(self.guard_aborted)
        self.assertFalse(self.in_guard)

    def test_cached_expiry_after_receipts_returns_no_stale_articles(self):
        self.cache()
        self.receipts.side_effect = lambda *args: setattr(self.clock.now, 'return_value', self.ranked.valid_until)
        result = service.cached_feed(self.conn, self.req.batch.user_id, limit=3)
        self.assertEqual(result, {'status': 'needs_build', 'articles': [], 'article_count': 0})
        self.receipts.assert_called_once()
        self.assertTrue(self.guard_aborted)

    def test_current_evidence_conflict_stops_composition_and_publish(self):
        from app.services.reader_repository import ReaderConflict
        self.guard.side_effect = ReaderConflict('retrieval_evidence_changed')
        with self.assertRaises(ReaderConflict):
            self.do_publish()
        self.compose.assert_not_called()
        self.publish.assert_not_called()
        self.receipts.assert_not_called()

    def test_changed_recipe_stops_publication(self):
        from app.services.reader_repository import ReaderConflict
        self.control.return_value['recipe_hash'] = 'changed'
        with self.assertRaises(ReaderConflict):
            self.do_publish()
        self.publish.assert_not_called()
        self.receipts.assert_not_called()

    def test_rank_context_change_stops_before_article_locks(self):
        self.ranked.context_hash = 'changed'
        with self.assertRaises(ValueError):
            self.do_publish()
        self.guard.assert_not_called()
        self.publish.assert_not_called()

    def test_provider_free_cache_preserves_final_order_and_records_only_slice(self):
        envelope = self.cache()
        result = service.cached_feed(self.conn, self.req.batch.user_id, limit=2)
        expected = envelope['final']['articles'][:2]
        self.assertEqual([a['id'] for a in result['articles']], [a['id'] for a in expected])
        self.assertEqual(self.receipts.call_args.args[4], expected)
        self.assertEqual(result['article_count'], 2)
        self.assertEqual(result['feed_request_id'], envelope['request_id'])
        self.event_receipts.assert_not_called()

    def test_internal_ordinary_reuse_revalidates_capable_edition_then_removes_priority(self):
        from app.services import ranking_events
        self.final['articles'][0]['event_delivery'] = {
            'valid_until': (NOW+timedelta(minutes=5)).isoformat()}
        envelope = self.cache()
        envelope['capability'] = '1'
        self.compose.reset_mock()
        # Ordinary public reads retain the exact client capability gate.
        self.assertEqual(service.cached_feed(self.conn, self.req.batch.user_id, limit=2)['status'], 'needs_build')
        self.compose.assert_not_called()
        result = service.cached_feed(self.conn, self.req.batch.user_id, limit=2, ordinary_only=True)
        expected = envelope['final']['articles'][1:]
        self.assertEqual([a['id'] for a in result['articles']], [a['id'] for a in expected])
        self.assertFalse(any(a.get('event_delivery') for a in result['articles']))
        self.assertEqual(result['feed_request_id'], envelope['request_id'])
        self.assertEqual(self.receipts.call_args.args[4], expected)
        ranking_events.prepare.assert_called_with(self.conn, '1')
        self.assertEqual(self.compose.call_args.args[3:5], ('1', 3))

    def test_internal_large_limit_reuses_only_stored_edition_without_rebuilding(self):
        envelope = self.cache()
        self.assertEqual(service.cached_feed(self.conn, self.req.batch.user_id, limit=50)['status'], 'needs_build')
        self.compose.reset_mock()
        result = service.cached_feed(self.conn, self.req.batch.user_id, limit=50, ordinary_only=True)
        self.assertEqual([a['id'] for a in result['articles']],
                         [a['id'] for a in envelope['final']['articles']])
        self.assertEqual(result['article_count'], 3)
        self.assertEqual(result['feed_request_id'], envelope['request_id'])
        self.assertEqual(self.compose.call_args.args[4], 3)
        # A larger requested slice never changes the frozen edition capacity.
        self.assertEqual(envelope['limit'], 3)

    def test_cache_recomposition_drift_requests_build_instead_of_resorting(self):
        self.cache()
        self.compose.return_value = self.ordinary
        result = service.cached_feed(self.conn, self.req.batch.user_id, limit=3)
        self.assertEqual(result['status'], 'needs_build')
        self.assertEqual(result['articles'], [])
        self.receipts.assert_not_called()

    def test_cache_identity_capacity_or_capability_mismatch_fail_closed(self):
        self.cache()
        for kwargs in ({'limit': 4}, {'limit': 3, 'capability': '1'}):
            with self.subTest(kwargs=kwargs):
                self.assertEqual(service.cached_feed(self.conn, self.req.batch.user_id, **kwargs)['status'], 'needs_build')
        self.snapshot['learning_revision'] += 1
        self.assertEqual(service.cached_feed(self.conn, self.req.batch.user_id, limit=3)['status'], 'needs_build')
        self.receipts.assert_not_called()

    def test_cache_storage_failure_never_falls_back_to_legacy(self):
        self.latest.side_effect = RuntimeError('storage unavailable')
        result = service.cached_feed(self.conn, self.req.batch.user_id, limit=3)
        self.assertEqual(result, {'status': 'needs_build', 'articles': [], 'article_count': 0})
        self.compose.assert_not_called()
        self.receipts.assert_not_called()

    def test_control_epoch_change_invalidates_cache_even_with_same_recipe(self):
        self.cache()
        self.control.return_value['epoch'] = 2
        result = service.cached_feed(self.conn, self.req.batch.user_id, limit=3)
        self.assertEqual(result['status'], 'needs_build')
        self.receipts.assert_not_called()

    def test_disable_switch_prevents_cached_read(self):
        with patch.dict('os.environ', {'S7_SERVING_ENABLED': 'false'}):
            self.assertEqual(service.cached_feed(self.conn, self.req.batch.user_id, limit=3)['status'], 'needs_build')
        self.latest.assert_not_called()


class DatabasePhaseTests(unittest.IsolatedAsyncioTestCase):
    async def test_connections_are_owned_and_closed_in_worker_thread(self):
        import threading
        import time
        main_thread = threading.get_ident()
        events = []

        @contextmanager
        def connection(**kwargs):
            events.append(('open', threading.get_ident()))
            try:
                yield object()
            finally:
                events.append(('close', threading.get_ident()))

        def operation(conn):
            events.append(('query', threading.get_ident()))
            return 42

        result = await service.database_phase(SimpleNamespace(connection=connection), operation,
                                             deadline=time.monotonic()+2)
        self.assertEqual(result, 42)
        self.assertEqual([e[0] for e in events], ['open', 'query', 'close'])
        self.assertEqual(len({e[1] for e in events}), 1)
        self.assertNotEqual(events[0][1], main_thread)

    async def test_cancelled_waiter_does_not_release_or_reuse_live_worker_slot(self):
        import threading
        import time
        entered, release, closed = threading.Event(), threading.Event(), threading.Event()
        slots = threading.BoundedSemaphore(1)

        @contextmanager
        def connection(**kwargs):
            try:
                yield object()
            finally:
                closed.set()

        def operation(conn):
            entered.set()
            release.wait(timeout=2)

        pool = SimpleNamespace(connection=connection)
        with patch.object(service, '_DB_SLOTS', slots):
            task = asyncio.create_task(service.database_phase(pool, operation, deadline=time.monotonic()+2))
            try:
                self.assertTrue(await asyncio.to_thread(entered.wait, 1))
                task.cancel()
                with self.assertRaises(asyncio.CancelledError):
                    await task
                self.assertFalse(closed.is_set())
                with self.assertRaisesRegex(RuntimeError, 'ranking_database_busy'):
                    await service.database_phase(pool, lambda conn: self.fail('live slot reused'),
                                                 deadline=time.monotonic()+2)
            finally:
                release.set()
                self.assertTrue(await asyncio.to_thread(closed.wait, 1))
                # Wait for work()'s finally after the connection context exits.
                self.assertTrue(await asyncio.to_thread(slots.acquire, True, 1))
                slots.release()

    async def test_expired_phase_does_not_acquire_database_connection(self):
        pool = SimpleNamespace(connection=Mock())
        with self.assertRaises(TimeoutError):
            await service.database_phase(pool, lambda conn: self.fail('expired operation ran'), deadline=0)
        pool.connection.assert_not_called()


if __name__ == '__main__':
    unittest.main()
