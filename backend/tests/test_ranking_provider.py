"""Offline S7 wire, spending and lifecycle boundaries. No real provider calls."""
import asyncio
import copy
import importlib
import json
import sys
import types
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import patch
from uuid import UUID

# Other historical test modules install a deliberately tiny httpx stand-in.
existing = sys.modules.get('httpx')
if not isinstance(existing, types.ModuleType) or not getattr(existing, '__spec__', None):
    sys.modules.pop('httpx', None)
httpx = importlib.import_module('httpx')

from app.services import ranking_provider as provider
from app.services.ranking_contract import EvidencePack, RankingRequest
from app.services.reader_contract import ReaderProfile, canonical_hash
from app.services.retrieval_contract import CandidateBatch, Candidate, Match

INTENT = str(UUID(int=700))
NOW = datetime(2026, 9, 8, tzinfo=timezone.utc)


def request(count=1):
    profile = ReaderProfile(intents=[{'id': INTENT, 'kind': 'topic', 'label': 'Science'}])
    packs = [EvidencePack(article_id=str(UUID(int=i + 1)), input_hash='hash-' + str(i),
        title='Science discovery', summary='Scientists discovered a new technique.',
        analysis_allowed=True, tier='publisher_analysis') for i in range(count)]
    batch = CandidateBatch(request_id=str(UUID(int=800)), user_id=str(UUID(int=900)),
        generation=1, revision=1, learning_revision=1, reader_hash=canonical_hash(profile.model_dump()),
        as_of=NOW, valid_until=NOW + timedelta(minutes=15), retrieval_recipe='s6',
        configuration={}, s3_recipe_id=None, space_id=None, status='complete', diagnostics={},
        candidates=[Candidate(article_id=e.article_id, allocated_intent_id=INTENT,
            matched_intent_ids=[INTENT], matches=[Match(intent_id=INTENT, leg='lexical',
                variant='strict', rank=i + 1, score=1., query_hash='q')],
            retrieval_score=.1, article_stamp='stamp', evidence_stamp={}, policy_evidence={},
            article={'id': e.article_id, 'secret_not_for_provider': 'private'}) for i, e in enumerate(packs)])
    return RankingRequest(batch=batch, profile=profile, evidence=packs)


def judgment(pack):
    return {'article_id': pack.article_id, 'input_hash': pack.input_hash, 'decision': 'accept',
        'reason': 'substantive_match', 'explanation': 'Science discovery is substantive.',
        'confirmed_intent_ids': [INTENT], 'grades': [{'intent_id': INTENT, 'grade': 2,
            'qualifiers': 'satisfied', 'field': 'title', 'quote': 'Science discovery'}]}


def response(req):
    return {'id': 'chatcmpl-offline', 'model': req.recipe['model'],
        'usage': {'prompt_tokens': 500, 'completion_tokens': 200},
        'choices': [{'index': 0, 'finish_reason': 'stop', 'message': {
            'role': 'assistant', 'refusal': None,
            'content': json.dumps({'judgments': [judgment(e) for e in req.evidence]})}}]}


class RankingProviderTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        # Another test can import the adapter before this module replaces the
        # historical httpx stub. Bind real MockTransport support for this test
        # without leaking a module-global patch to other suites.
        transport = patch.object(provider, 'httpx', httpx)
        transport.start()
        self.addCleanup(transport.stop)
        self.flag = patch.dict('os.environ', {'S7_PROVIDER_ENABLED': 'true'})
        self.flag.start()
        self.addCleanup(self.flag.stop)
        self.req = request()
        self.calls = []

    def adapter(self, data=None, *, handler=None, raw=None, status=200, tokenizer=None):
        def default(call):
            self.calls.append(call)
            kwargs = {'content': raw} if raw is not None else {'json': data or response(self.req)}
            return httpx.Response(status, headers={'x-request-id': 'req-offline'}, **kwargs)
        client = httpx.AsyncClient(transport=httpx.MockTransport(handler or default))
        self.addAsyncCleanup(client.aclose)
        return provider.RankingProvider('sk-offline', client=client,
            tokenizer=tokenizer or (lambda value, model: 100))

    async def check_failure(self, adapter, kind=None):
        with self.assertRaises(provider.ProviderFailure) as caught:
            await adapter.judge(self.req, self.req.evidence)
        if kind:
            self.assertEqual(caught.exception.kind, kind)
        return caught.exception

    async def test_valid_exact_id_schema_grounding_and_usage(self):
        adapter = self.adapter()
        prepared = adapter.prepare(self.req, self.req.evidence)
        result = await adapter.judge(self.req, self.req.evidence, prepared=prepared)
        self.assertEqual(result.judgments[0].article_id, self.req.evidence[0].article_id)
        self.assertEqual(result.input_tokens, 500)
        self.assertAlmostEqual(result.usage_usd, .00052)
        self.assertAlmostEqual(prepared.reserved_usd, .0144)
        sent = json.loads(self.calls[0].content)
        self.assertEqual(str(self.calls[0].url), provider.API_ROOT + '/chat/completions')
        self.assertNotIn('tools', sent)
        self.assertNotIn('private', sent['messages'][1]['content'])
        self.assertIn('untrusted', sent['messages'][0]['content'])
        self.assertTrue(sent['response_format']['json_schema']['strict'])
        self.assertFalse(sent['response_format']['json_schema']['schema']['additionalProperties'])

    async def test_schema_requires_every_field_recursively(self):
        def check(node):
            if isinstance(node, dict):
                self.assertNotIn('default', node)
                if node.get('type') == 'object':
                    self.assertEqual(set(node['required']), set(node['properties']))
                    self.assertIs(node['additionalProperties'], False)
                for value in node.values():
                    check(value)
            elif isinstance(node, list):
                for value in node:
                    check(value)
        check(provider._schema())

    async def test_unrelated_profile_context_is_not_sent(self):
        self.req.profile.context = 'private unrelated context'
        self.req.batch.reader_hash = canonical_hash(self.req.profile.model_dump())
        prepared = self.adapter().prepare(self.req, self.req.evidence)
        self.assertNotIn('private unrelated context', json.dumps(prepared.payload))

    async def test_unpriced_or_mismatched_recipe_cannot_spend(self):
        for pricing in (None, {}, {'input_usd_per_million': .01, 'output_usd_per_million': .01},
                        {'input_usd_per_million': True, 'output_usd_per_million': 1.6}):
            self.req.recipe['pricing'] = pricing
            with self.assertRaises(provider.ProviderFailure) as caught:
                self.adapter().prepare(self.req, self.req.evidence)
            self.assertEqual(caught.exception.kind, 'unsupported_pricing')
        self.assertFalse(self.calls)

    async def test_reordered_outputs_map_by_identity(self):
        self.req = request(3)
        data = response(self.req)
        data['choices'][0]['message']['content'] = json.dumps({'judgments':
            list(reversed([judgment(e) for e in self.req.evidence]))})
        result = await self.adapter(data).judge(self.req, self.req.evidence)
        self.assertEqual([j.article_id for j in result.judgments],
            list(reversed([e.article_id for e in self.req.evidence])))

    async def test_disabled_never_calls_transport(self):
        with patch.dict('os.environ', {'S7_PROVIDER_ENABLED': 'false'}):
            await self.check_failure(self.adapter(), 'provider_disabled')
        self.assertFalse(self.calls)

    async def test_missing_key_never_calls_transport(self):
        adapter = self.adapter()
        adapter._api_key = None
        with patch.dict('os.environ', {'OPENAI_API_KEY': ''}):
            await self.check_failure(adapter, 'missing_api_key')
        self.assertFalse(self.calls)

    async def test_unknown_model_rejected_before_network(self):
        self.req.recipe['model'] = 'latest'
        await self.check_failure(self.adapter(), 'unsupported_model')
        self.assertFalse(self.calls)

    async def test_nonintegral_and_raised_caps_fail_before_network(self):
        for field, value in [('max_input_tokens', True), ('max_input_tokens', 12001),
                             ('max_output_tokens', 6001), ('max_output_tokens', 1.5),
                             ('deadline_seconds', float('nan')), ('deadline_seconds', 21)]:
            self.req = request()
            self.req.recipe[field] = value
            with self.subTest(field=field, value=value):
                await self.check_failure(self.adapter())
        self.assertFalse(self.calls)

    async def test_revoked_analysis_stays_off_provider(self):
        self.req.evidence[0].analysis_allowed = False
        await self.check_failure(self.adapter(), 'analysis_revoked')
        self.assertFalse(self.calls)

    async def test_changed_prepared_context_rejected_before_spend(self):
        adapter = self.adapter()
        prepared = adapter.prepare(self.req, self.req.evidence)
        prepared.payload['messages'][0]['content'] = 'forged'
        with self.assertRaises(provider.ProviderFailure) as caught:
            await adapter.judge(self.req, self.req.evidence, prepared=prepared)
        self.assertEqual(caught.exception.kind, 'prepared_context_changed')
        self.assertFalse(self.calls)

    async def test_foreign_missing_and_duplicate_article_ids(self):
        original = judgment(self.req.evidence[0])
        for items in [[], [original, original], [{**original, 'article_id': str(UUID(int=333))}]]:
            data = response(self.req)
            data['choices'][0]['message']['content'] = json.dumps({'judgments': items})
            failure = await self.check_failure(self.adapter(data), 'invalid_output')
            self.assertIsNotNone(failure.usage_usd)

    async def test_wrong_evidence_hash_and_invented_quote(self):
        for mutate in ['hash', 'quote']:
            value = judgment(self.req.evidence[0])
            if mutate == 'hash':
                value['input_hash'] = 'wrong'
            else:
                value['grades'][0]['quote'] = 'unsupported facts'
            data = response(self.req)
            data['choices'][0]['message']['content'] = json.dumps({'judgments': [value]})
            await self.check_failure(self.adapter(data), 'invalid_output')

    async def test_string_and_boolean_grades_cannot_coerce(self):
        for grade in ['2', True, 'NaN', 2.0]:
            value = judgment(self.req.evidence[0])
            value['grades'][0]['grade'] = grade
            data = response(self.req)
            data['choices'][0]['message']['content'] = json.dumps({'judgments': [value]})
            await self.check_failure(self.adapter(data), 'invalid_output')

    async def test_semantic_reason_must_match_decision(self):
        value = judgment(self.req.evidence[0])
        value['reason'] = 'provider_unavailable'
        data = response(self.req)
        data['choices'][0]['message']['content'] = json.dumps({'judgments': [value]})
        await self.check_failure(self.adapter(data), 'invalid_output')

    async def test_refusal_and_incomplete_output_keep_known_cost(self):
        for case in ['refusal', 'length']:
            data = response(self.req)
            if case == 'refusal':
                data['choices'][0]['message']['refusal'] = 'No'
            else:
                data['choices'][0]['finish_reason'] = 'length'
            failure = await self.check_failure(self.adapter(data),
                'refusal' if case == 'refusal' else 'incomplete_response')
            self.assertEqual(failure.request_id, 'req-offline')
            self.assertGreater(failure.usage_usd, 0)

    async def test_duplicate_keys_nan_utf16_and_invalid_utf8(self):
        for raw in [b'{"usage":{},"usage":{}}', b'{"n":NaN}', b'{"n":1e9999}',
                    b'\xff', json.dumps(response(self.req)).encode('utf-16')]:
            failure = await self.check_failure(self.adapter(raw=raw), 'invalid_response')
            self.assertTrue(failure.ambiguous)

    async def test_nested_duplicate_keys_and_surrogate_are_not_salvaged(self):
        for content in ['{"judgments":[],"judgments":[]}', '{"judgments":NaN}',
                        '{"judgments":[],"extra":"\\ud800"}']:
            data = response(self.req)
            data['choices'][0]['message']['content'] = content
            failure = await self.check_failure(self.adapter(data), 'invalid_output')
            self.assertGreater(failure.usage_usd, 0)

    async def test_malformed_usage_does_not_free_ambiguous_spend(self):
        for usage in [None, {}, {'prompt_tokens': True, 'completion_tokens': 1},
                      {'prompt_tokens': 1, 'completion_tokens': '1'}]:
            data = response(self.req)
            data['usage'] = usage
            failure = await self.check_failure(self.adapter(data))
            self.assertTrue(failure.ambiguous)
            self.assertIsNone(failure.usage_usd)

    async def test_usage_above_cap_is_recorded_but_not_accepted(self):
        data = response(self.req)
        data['usage']['prompt_tokens'] = 12001
        failure = await self.check_failure(self.adapter(data), 'usage_exceeds_limits')
        self.assertGreater(failure.usage_usd, 0)

    async def test_oversized_response_is_bounded(self):
        failure = await self.check_failure(self.adapter(raw=b'x' * (provider.MAX_RESPONSE_BYTES + 1)),
                                          'response_too_large')
        self.assertTrue(failure.ambiguous)

    async def test_http_429_and_500_have_no_automatic_retries(self):
        for status in [429, 500]:
            before = len(self.calls)
            failure = await self.check_failure(self.adapter(status=status), 'http_' + str(status))
            self.assertEqual(len(self.calls), before + 1)
            self.assertEqual(failure.ambiguous, status == 500)

    async def test_two_global_operations_and_cancel_release_admission(self):
        entered, release = asyncio.Event(), asyncio.Event()
        active = []
        async def handler(call):
            active.append(call)
            if len(active) == 2:
                entered.set()
            await release.wait()
            return httpx.Response(200, json=response(self.req), headers={'x-request-id': 'req-offline'})
        first, second = self.adapter(handler=handler), self.adapter(handler=handler)
        tasks = [asyncio.create_task(a.judge(self.req, self.req.evidence)) for a in [first, second]]
        try:
            await asyncio.wait_for(entered.wait(), 1)
            await self.check_failure(self.adapter(), 'provider_busy')
            self.assertFalse(self.calls)
            tasks[0].cancel()
            with self.assertRaises(asyncio.CancelledError):
                await tasks[0]
            await self.adapter().judge(self.req, self.req.evidence)
        finally:
            release.set()
            await asyncio.gather(*tasks, return_exceptions=True)

    async def test_wall_timeout_is_ambiguous_and_slot_is_reusable(self):
        async def handler(call):
            await asyncio.Event().wait()
        self.req.recipe['deadline_seconds'] = .01
        failure = await self.check_failure(self.adapter(handler=handler), 'transport_ambiguous')
        self.assertTrue(failure.ambiguous)
        self.req.recipe['deadline_seconds'] = 20.
        await self.adapter().judge(self.req, self.req.evidence)

    async def test_request_mutation_after_send_cannot_rewrite_validation(self):
        original = response(self.req)
        async def handler(call):
            self.req.evidence[0].title = 'Changed'
            self.req.profile.intents.clear()
            return httpx.Response(200, json=original, headers={'x-request-id': 'req-offline'})
        outcome = await self.adapter(handler=handler).judge(self.req, self.req.evidence)
        self.assertEqual(outcome.judgments[0].decision, 'accept')

    def test_packing_preserves_every_id_and_respects_article_limit(self):
        req = request(101)
        batches = provider.pack_batches(req, req.evidence, provider=self.adapter())
        self.assertEqual([len(b) for b in batches], [50, 50, 1])
        self.assertEqual([e.article_id for b in batches for e in b], [e.article_id for e in req.evidence])
        self.assertFalse(self.calls)

    def test_token_packing_refills_without_dropping_overflow(self):
        req = request(6)
        def count(value, model):
            payload = json.loads(value)
            size = len(json.loads(payload['messages'][1]['content'])['evidence'])
            return 3000 * size
        batches = provider.pack_batches(req, req.evidence, provider=self.adapter(tokenizer=count))
        self.assertEqual([len(b) for b in batches], [3, 3])

    def test_oversized_singleton_is_explicit_failure(self):
        adapter = self.adapter(tokenizer=lambda value, model: 12000)
        with self.assertRaises(provider.ProviderFailure) as caught:
            provider.pack_batches(self.req, self.req.evidence, provider=adapter)
        self.assertEqual(caught.exception.kind, 'input_too_large')
        self.assertFalse(self.calls)

    def test_duplicate_or_foreign_evidence_never_prepares(self):
        adapter = self.adapter()
        foreign = self.req.evidence[0].model_copy(update={'input_hash': 'other'})
        for packs in [[foreign], self.req.evidence * 2]:
            with self.assertRaises(provider.ProviderFailure) as caught:
                adapter.prepare(self.req, packs)
            self.assertEqual(caught.exception.kind, 'invalid_evidence')

    def test_invalid_tokenizer_and_empty_batch_fail_closed(self):
        for count in [True, -1, 1.5]:
            with self.assertRaises(provider.ProviderFailure):
                self.adapter(tokenizer=lambda value, model: count).prepare(self.req, self.req.evidence)
        with self.assertRaises(provider.ProviderFailure):
            self.adapter().prepare(self.req, [])

    def test_empty_packing_has_no_side_effects(self):
        self.assertEqual(provider.pack_batches(self.req, [], provider=self.adapter()), [])
        self.assertFalse(self.calls)
