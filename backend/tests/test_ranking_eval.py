"""Ranking evaluation denominator, identity and upstream-miss regression tests."""
import copy
import unittest

from app.services.ranking_contract import RankBatch
from app.services.reader_contract import canonical_hash
from app.services.ranking_service import abstain
from evals.ranking import evaluate, RankingLabel
from tests.test_ranking_service import make_request, accept, rejected, INTENT


class RankingEvaluationTests(unittest.TestCase):
    def fixture(self, decisions=('accept', 'reject', 'abstain')):
        req = make_request(len(decisions))
        judgments = [dict(accept=accept, reject=rejected, abstain=abstain)[decision](pack)
                     for decision, pack in zip(decisions, req.evidence)]
        ranked = RankBatch(request_id=req.batch.request_id, context_hash=req.fingerprint,
            recipe_hash=canonical_hash(req.recipe), status='degraded', valid_until=req.batch.valid_until,
            judgments=judgments, ordered_ids=[j.article_id for j in judgments if j.decision == 'accept'],
            diagnostics={'known_cost_usd': .012, 'elapsed_ms': 12.5, 'input_tokens': 100,
                         'output_tokens': 20, 'attempts': 1})
        return req, ranked, [e.article_id for e in req.evidence]

    def test_conditional_and_end_to_end_preserve_upstream_miss(self):
        req, ranked, ids = self.fixture(('accept',))
        labels = {ids[0]: {'grade': 3}, 'missed': {'grade': 3}}
        report = evaluate(req, ranked, labels, full_pool_ids=[*ids, 'missed'])
        self.assertEqual(report['conditional']['known_positive_recall']['value'], 1.)
        self.assertEqual(report['end_to_end']['known_positive_recall']['value'], .5)
        self.assertEqual(report['conditional']['ndcg_at_10'], 1.)
        self.assertLess(report['end_to_end']['ndcg_at_10'], 1.)
        self.assertEqual(len(req.batch.candidates), 1)
        self.assertFalse(report['quality_proven'])

    def test_labels_do_not_implicitly_assert_complete_full_pool(self):
        req, ranked, ids = self.fixture(('accept',))
        report = evaluate(req, ranked, {ids[0]: {'grade': 3}, 'not_retrieved': {'grade': 3}})
        self.assertIsNone(report['end_to_end'])
        self.assertEqual(report['conditional']['universe_count'], 1)

    def test_unknown_labels_remain_unknown_not_irrelevant_or_perfect(self):
        req, ranked, ids = self.fixture(('accept', 'accept'))
        report = evaluate(req, ranked, {ids[0]: {'grade': 3}})
        metrics = report['conditional']
        self.assertEqual(metrics['acceptance_precision'], {'value': 1., 'numerator': 1, 'denominator': 1})
        self.assertEqual(metrics['shown_label_coverage']['value'], .5)
        self.assertIsNone(metrics['ndcg_at_10'])
        self.assertIsNone(metrics['prohibited_rate']['value'])

    def test_empty_denominators_are_undefined(self):
        req, ranked, ids = self.fixture(())
        report = evaluate(req, ranked, {}, full_pool_ids=[])
        for field in ('acceptance_precision', 'known_positive_recall', 'prohibited_rate',
                      'shown_label_coverage', 'relevance_label_coverage'):
            self.assertIsNone(report['conditional'][field]['value'])
        self.assertIsNone(report['conditional']['ndcg_at_10'])
        self.assertIsNone(report['freshness']['mean_hours'])
        self.assertIsNone(report['abstention_coverage']['value'])

    def test_all_zero_truth_has_undefined_ndcg_not_perfect(self):
        req, ranked, ids = self.fixture(('reject',))
        report = evaluate(req, ranked, {ids[0]: {'grade': 0}})
        self.assertIsNone(report['conditional']['ndcg_at_10'])
        self.assertIsNone(report['conditional']['known_positive_recall']['value'])

    def test_abstention_is_not_false_rejection(self):
        req, ranked, ids = self.fixture()
        report = evaluate(req, ranked, {key: {'grade': 3} for key in ids})
        band = report['band_errors']['3']
        self.assertEqual(band['false_reject']['value'], 1/3)
        self.assertEqual(band['abstention']['value'], 1/3)
        self.assertEqual(report['decision_counts'], {'accept': 1, 'reject': 1, 'abstain': 1})

    def test_false_accept_bands_and_prohibited_rate(self):
        req, ranked, ids = self.fixture(('accept', 'accept'))
        report = evaluate(req, ranked, {ids[0]: {'grade': 0, 'prohibited': True},
                                       ids[1]: {'grade': 1, 'prohibited': False}})
        self.assertEqual(report['conditional']['acceptance_precision']['value'], 0)
        self.assertEqual(report['conditional']['prohibited_rate']['value'], .5)
        for grade in ('0', '1'):
            self.assertEqual(report['band_errors'][grade]['false_accept']['value'], 1.)

    def test_final_selection_is_not_base_order(self):
        req, ranked, ids = self.fixture(('accept', 'accept'))
        report = evaluate(req, ranked, {ids[0]: {'grade': 2}, ids[1]: {'grade': 3}},
                          final_ids=[ids[1]], full_pool_ids=ids)
        self.assertEqual(report['conditional']['shown_count'], 2)
        self.assertEqual(report['final_conditional']['shown_count'], 1)
        self.assertEqual(report['end_to_end']['known_positive_recall']['value'], .5)

    def test_final_unknown_or_rejected_or_duplicate_id_rejected(self):
        req, ranked, ids = self.fixture()
        for final in [['foreign'], [ids[1]], [ids[0]]*2]:
            with self.subTest(final=final), self.assertRaises(ValueError):
                evaluate(req, ranked, {}, final_ids=final)

    def test_wrong_identity_or_context_rejected(self):
        req, ranked, _ = self.fixture()
        for field in ('request_id', 'context_hash', 'recipe_hash'):
            with self.subTest(field=field), self.assertRaises(ValueError):
                evaluate(req, ranked.model_copy(update={field: 'other'}), {})

    def test_incomplete_or_duplicate_full_pool_rejected(self):
        req, ranked, ids = self.fixture()
        for pool in [ids[:1], ids+ids]:
            with self.subTest(pool=pool), self.assertRaises(ValueError):
                evaluate(req, ranked, {}, full_pool_ids=pool)

    def test_actual_candidate_decision_set_required(self):
        req, ranked, _ = self.fixture()
        ranked.judgments = ranked.judgments[:1]
        with self.assertRaises(ValueError):
            evaluate(req, ranked, {})

    def test_per_intent_reports_known_opportunity_and_upstream_recall(self):
        req, ranked, ids = self.fixture(('accept',))
        labels = {key: {'grade': 3, 'intent_grades': {INTENT: 3}} for key in [*ids, 'missed']}
        report = evaluate(req, ranked, labels, full_pool_ids=[*ids, 'missed', 'unknown'])
        intent = report['intent_opportunities'][INTENT]
        self.assertEqual(intent['label_coverage']['value'], 2/3)
        self.assertEqual(intent['retrieved_known_positive_recall']['value'], .5)
        self.assertEqual(intent['final_known_positive_recall']['value'], .5)

    def test_slices_include_counts_and_unknown_groups(self):
        req, ranked, ids = self.fixture(('accept', 'accept'))
        req.batch.candidates[1].article.pop('language')
        ranked.context_hash = req.fingerprint
        report = evaluate(req, ranked, {key: {'grade': 3} for key in ids})
        self.assertEqual(report['slices']['language']['unknown']['universe_count'], 1)
        self.assertEqual(report['slices']['source']['publisher']['shown_count'], 2)
        self.assertEqual(report['slices']['evidence_tier']['publisher_analysis']['shown_count'], 2)

    def test_usage_is_observed_not_estimated_and_freshness_frozen(self):
        req, ranked, ids = self.fixture(('accept', 'accept'))
        report = evaluate(req, ranked, {})
        self.assertEqual(report['usage']['known_cost_usd'], .012)
        self.assertEqual(report['usage']['elapsed_ms'], 12.5)
        self.assertEqual(report['freshness']['mean_hours'], .5)
        ranked.diagnostics = {'known_cost_usd': float('nan'), 'elapsed_ms': -1, 'attempts': True}
        self.assertTrue(all(value is None for value in evaluate(req, ranked, {})['usage'].values()))

    def test_baseline_does_not_claim_unknown_policy_safe(self):
        req, ranked, ids = self.fixture(('accept', 'accept', 'accept'))
        report = evaluate(req, ranked, {ids[0]: {'prohibited': False}, ids[1]: {'prohibited': True}})
        baseline = report['policy_labeled_high_recall_baseline']
        self.assertEqual(baseline['ordered_ids'], [ids[0]])
        self.assertEqual(baseline['excluded_unknown_policy_count'], 1)

    def test_invalid_labels_are_rejected_not_coerced(self):
        for value in ['3', True, 3.0, -1, 4, float('nan')]:
            with self.subTest(value=value), self.assertRaises(ValueError):
                RankingLabel(grade=value)
        with self.assertRaises(ValueError):
            RankingLabel(prohibited='false')

    def test_evaluation_does_not_mutate_inputs(self):
        req, ranked, ids = self.fixture()
        labels = {ids[0]: {'grade': 3}}
        before = copy.deepcopy((req.model_dump(), ranked.model_dump(), labels))
        evaluate(req, ranked, labels, full_pool_ids=[*ids, 'missed'])
        self.assertEqual(before, (req.model_dump(), ranked.model_dump(), labels))


if __name__ == '__main__':
    unittest.main()
