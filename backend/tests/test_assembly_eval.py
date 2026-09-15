"""S8 metric denominators and actual-input comparator regression tests."""
from itertools import combinations

import pytest

from app.services.assembly_contract import AssemblyCandidate
from app.services.assembly_service import assemble
from evals.assembly import evaluate
from test_assembly_contract import candidate, request


def proposed(report, cutoff='5'):
    return report['comparisons'][cutoff]['policies']['proposed']


def test_unknown_labels_and_metadata_never_receive_perfect_scores():
    req = request([candidate(), candidate('b', 1)], limit=2)
    report = evaluate(req, assemble(req), {'a': {'grade': 3}})
    metrics = proposed(report)['final_labeled']
    assert metrics['known_relevance_precision'] == {'value': 1.0, 'numerator': 1, 'denominator': 1}
    assert metrics['shown_relevance_label_coverage']['value'] == .5
    assert metrics['read_repeat_rate']['value'] is None
    assert metrics['prohibited_rate']['value'] is None
    assert metrics['duplicate_unit_rate']['value'] is None
    assert proposed(report)['mechanical']['max_publisher_share_known']['value'] is None
    assert proposed(report)['mechanical']['verified_identity_coverage']['value'] == 0
    assert report['quality_proven'] is False


def test_full_universe_misses_remain_misses_without_oracle_injection():
    req = request(limit=1)
    labels = {'a': {'grade': 3}, 'missed': {'grade': 3}}
    result = assemble(req)
    conditional = evaluate(req, result, labels)
    assert proposed(conditional)['end_to_end_labeled'] is None
    assert conditional['ignored_outside_universe_label_count'] == 1
    report = evaluate(req, result, labels, full_pool_ids=['a', 'missed'])
    assert proposed(report)['final_labeled']['known_positive_recall']['value'] == 1
    assert proposed(report)['end_to_end_labeled']['known_positive_recall']['value'] == .5
    assert len(req.candidates) == 1
    assert all('missed' not in value['ordered_ids'] for value in report['comparisons']['5']['policies'].values())


def test_actual_duplicates_read_repeats_and_underfill_comparisons():
    req = request([candidate('read', 0, known_read=True, novelty_key='old'),
        candidate('a', 1, coverage_key='story:x'), candidate('b', 2, coverage_key='story:x'),
        candidate('c', 3, coverage_key='story:y')], limit=3)
    report = evaluate(req, assemble(req))
    policies = report['comparisons']['5']['policies']
    assert policies['accepted_s7_top_k']['ordered_ids'] == ['read', 'a', 'b']
    assert policies['accepted_s7_top_k']['mechanical']['verified_duplicate_unit_rate']['value'] == .5
    assert policies['verified_dedupe_only']['ordered_ids'] == ['read', 'a', 'c']
    assert policies['proposed']['ordered_ids'] == ['a', 'c']
    assert policies['proposed']['mechanical']['shown_known_read_count'] == 0
    assert policies['proposed']['mechanical']['underfill'] == 1
    assert policies['proposed']['mechanical']['opportunity_limited_shortfall_lower_bound'] == 1


def test_external_identity_labels_can_expose_missed_duplicates():
    req = request([candidate(), candidate('b', 1)], limit=2)
    report = evaluate(req, assemble(req), {'a': {'coverage_unit': 'true-story'}, 'b': {'coverage_unit': 'true-story'}})
    assert proposed(report)['final_labeled']['duplicate_unit_rate']['value'] == .5
    assert proposed(report)['mechanical']['verified_duplicate_unit_rate']['value'] is None


def test_external_labels_expose_false_merges_and_false_read_suppression():
    req = request([candidate('a', 0, coverage_key='wrong'), candidate('b', 1, coverage_key='wrong'),
        candidate('read', 2, known_read=True, novelty_key='read')], limit=3)
    report = evaluate(req, assemble(req), {'a': {'coverage_unit': 'original'},
        'b': {'coverage_unit': 'correction'}, 'read': {'identical_read_repeat': False}})
    assert report['identity_validation']['false_merge_pair_rate']['value'] == 1
    assert report['novelty_validation']['false_read_suppression_rate']['value'] == 1


def test_critical_slots_are_not_fabricated_personal_quality():
    req = request([candidate(), AssemblyCandidate(article_id='critical', ordinal=0,
        grade=0, origin='world_critical', authorized=True)], limit=2)
    report = evaluate(req, assemble(req), {'a': {'grade': 3}, 'critical': {'grade': 0}})
    assert proposed(report)['final_labeled']['known_relevance_precision']['value'] == .5
    assert proposed(report)['ordinary_labeled']['known_relevance_precision']['value'] == 1
    assert proposed(report)['mechanical']['critical_slots'] == 1
    for policy in report['comparisons']['5']['policies'].values():
        assert policy['ordered_ids'][0] == 'critical'


def test_publishers_topics_and_streaks_have_explicit_known_denominators():
    req = request([candidate('a', 0, publisher_id='p', topic_ids=['science']),
        candidate('b', 1, publisher_id='p', topic_ids=['science']), candidate('c', 2)], limit=3)
    metrics = proposed(evaluate(req, assemble(req)))['mechanical']
    assert metrics['max_publisher_share_known']['value'] == 1
    assert metrics['publisher_metadata_coverage']['value'] == 2/3
    assert metrics['max_central_topic_share_known']['value'] == 1
    assert metrics['topic_metadata_coverage']['value'] == 2/3
    assert metrics['max_observed_source_streak'] == 2
    assert metrics['ordinary_grade_displacement'] == 0


def test_empty_universes_have_no_division_by_zero_or_fake_precision():
    req = request([], limit=5)
    metrics = proposed(evaluate(req, assemble(req), full_pool_ids=[]))
    assert metrics['mechanical']['underfill'] == 5
    assert metrics['mechanical']['available_intent_coverage']['value'] is None
    assert metrics['final_labeled']['known_positive_recall']['value'] is None


@pytest.mark.parametrize('pool', [[], ['a', 'a'], ['foreign']])
def test_full_universe_requires_actual_unique_candidates(pool):
    req = request()
    with pytest.raises(ValueError):
        evaluate(req, assemble(req), full_pool_ids=pool)


@pytest.mark.parametrize('cutoffs', [(0,), (101,), (True,), ('5',), (5, 5)])
def test_cutoffs_are_bounded_and_not_coerced(cutoffs):
    req = request()
    with pytest.raises(ValueError):
        evaluate(req, assemble(req), cutoffs=cutoffs)


def test_evaluation_rejects_result_from_another_dependency_snapshot():
    req = request()
    result = assemble(req).model_copy(update={'history_revision': 20})
    with pytest.raises(ValueError):
        evaluate(req, result)


def test_prefix_evaluation_does_not_claim_unbuilt_larger_edition():
    req = request([candidate(str(i), i) for i in range(8)], limit=2)
    report = evaluate(req, assemble(req))
    assert report['comparisons']['50']['effective_capacity'] == 2
    assert len(proposed(report, '50')['ordered_ids']) == 2


def test_small_exhaustive_identity_capacity_oracle_without_runtime_solver():
    # Enumerate feasible subsets solely as a tiny offline identity/refill oracle.
    # This does not assert globally optimal relevance-variety scheduling.
    values = [candidate('a', 0, coverage_key='story:1'), candidate('b', 1, coverage_key='story:1'),
              candidate('c', 2, coverage_key='story:2'), candidate('d', 3),
              candidate('read', 4, known_read=True, novelty_key='read')]
    for limit in range(1, 6):
        req = request(values, limit=limit)
        feasible = []
        for size in range(limit+1):
            for subset in combinations(values, size):
                units = [c.coverage_key for c in subset if c.coverage_key is not None]
                if not any(c.known_read or not c.eligible for c in subset) and len(units) == len(set(units)):
                    feasible.append(subset)
        assert len(assemble(req).ordered_ids) == max(map(len, feasible))
