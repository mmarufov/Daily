"""Synthetic assembly invariants, not semantic-quality or deployment evidence."""
from itertools import permutations
from time import perf_counter

from app.services.assembly_contract import AssemblyCandidate, RECIPE, validate_result
from app.services.assembly_service import assemble
from test_assembly_contract import candidate, request


def ordinary(article_id, ordinal, *, grade=3, intents=None, **values):
    return AssemblyCandidate(article_id=article_id, ordinal=ordinal, grade=grade,
        intents={'science': 1.0} if intents is None else intents, **values)


def dispositions(result):
    return {d.article_id: d.reason for d in result.dispositions}


def test_whole_pool_refills_after_equivalent_copies():
    req = request([candidate(str(i), i, coverage_key='story:one' if i < 4 else f'story:{i}')
                   for i in range(7)], limit=3)
    result = assemble(req)
    assert result.ordered_ids == ['0', '4', '5']
    assert dispositions(result)['3'] == 'equivalent_copy'
    assert dispositions(result)['6'] == 'capacity'


def test_unknown_identity_is_never_inferred_from_metadata_or_equal_content_keys():
    result = assemble(request([candidate('a', 0, novelty_key='same'),
                               candidate('b', 1, novelty_key='same')]))
    assert result.ordered_ids == ['a', 'b']
    assert result.diagnostics['unknown_identity_count'] == 2


def test_verified_namespaces_do_not_collapse_broad_events_and_developments():
    result = assemble(request([candidate('a', 0, coverage_key='event:1'),
                               candidate('b', 1, coverage_key='development:1')]))
    assert result.ordered_ids == ['a', 'b']


def test_stronger_own_grade_wins_equivalent_representative():
    result = assemble(request([ordinary('weak', 0, grade=2, coverage_key='story:1'),
                               candidate('strong', 1, coverage_key='story:1')]))
    assert result.ordered_ids == ['strong']
    assert result.dispositions[0].equivalent_to == 'strong'


def test_blocked_or_read_copy_cannot_destroy_eligible_representative():
    result = assemble(request([candidate('blocked', 0, eligible=False, coverage_key='story:1'),
        candidate('read', 1, known_read=True, novelty_key='content:old', coverage_key='story:1'),
        candidate('eligible', 2, coverage_key='story:1')]))
    assert result.ordered_ids == ['eligible']
    assert dispositions(result) == {'blocked': 'policy_stale', 'read': 'known_read_repeat', 'eligible': 'selected'}


def test_image_title_and_body_are_not_selection_inputs():
    assert not {'title', 'image_url', 'content', 'source_quality'} & AssemblyCandidate.model_fields.keys()


def test_grade_protection_overrides_interest_and_publisher_diversity():
    values = [ordinary('weak', 0, grade=2, intents={'art': 3.0}, publisher_id='other')]
    values += [ordinary(str(i), i+1, publisher_id='same') for i in range(4)]
    result = assemble(request(values, limit=3))
    assert result.ordered_ids == ['0', '1', '2']
    assert result.diagnostics['relaxations']


def test_priority_weighted_fair_schedule_and_shared_attribution_count_once():
    values = [ordinary(f's{i}', i, intents={'science': 2.0}) for i in range(4)]
    values += [ordinary(f'a{i}', i+4, intents={'art': 1.0}) for i in range(3)]
    result = assemble(request(values, limit=6))
    assert [s.scheduled_intent_id for s in result.selections] == ['science', 'art', 'science', 'science', 'art', 'science']
    shared = ordinary('shared', 0, intents={'science': 1.0, 'art': 1.0})
    result = assemble(request([shared, ordinary('s', 1), ordinary('a', 2, intents={'art': 1.0})]))
    assert sum(result.diagnostics['intent_service_counts'].values()) == 3
    assert result.selections[0].intents == {'science': 1.0, 'art': 1.0}


def test_publisher_alternative_representative_retained_until_selection():
    result = assemble(request([candidate('first', 0, publisher_id='p1'),
        candidate('copy1', 1, publisher_id='p1', coverage_key='story:2'),
        candidate('copy2', 2, publisher_id='p2', coverage_key='story:2')], limit=2))
    assert result.ordered_ids == ['first', 'copy2']


def test_sparse_variety_targets_relax_and_do_not_underfill():
    req = request([candidate(str(i), i, publisher_id='same', topic_ids=['same']) for i in range(6)], limit=6)
    result = assemble(req)
    assert result.ordered_ids == [str(i) for i in range(6)]
    assert result.diagnostics['shortfall'] == 0
    assert result.diagnostics['relaxations'][-1]['constraints'] == ['central_topic', 'publisher_share', 'source_streak']


def test_unknown_metadata_does_not_receive_new_publisher_reward():
    result = assemble(request([candidate('first', 0, publisher_id='p1'),
        candidate('unknown', 1), candidate('new', 2, publisher_id='p2')], limit=3))
    assert result.ordered_ids[:2] == ['first', 'new']


def test_critical_reserved_only_with_own_authorization_and_bounded_capacity():
    critical = AssemblyCandidate(article_id='critical', ordinal=0, grade=0,
        origin='world_critical', authorized=True, coverage_key='development:x')
    result = assemble(request([candidate('a'), critical], limit=1))
    assert result.ordered_ids == ['critical']
    assert result.selections[0].intents == {}
    assert result.diagnostics['intent_service_counts'] == {}
    unauthorized = critical.model_copy(update={'authorized': False})
    result = assemble(request([candidate('a'), unauthorized], limit=1))
    assert result.ordered_ids == ['a']
    assert dispositions(result)['critical'] == 'critical_unauthorized'


def test_priority_equivalence_refills_from_full_ordinary_pool():
    critical = AssemblyCandidate(article_id='critical', ordinal=0, grade=0,
        origin='world_critical', authorized=True, coverage_key='development:x')
    result = assemble(request([critical, candidate('copy', 0, coverage_key='development:x'),
                               candidate('other', 1)], limit=2))
    assert result.ordered_ids == ['critical', 'other']


def test_critical_overflow_and_known_read_priority_are_explicit():
    critical = [AssemblyCandidate(article_id=str(i), ordinal=i, grade=0,
        origin='world_critical', authorized=True) for i in range(2)]
    result = assemble(request(critical, limit=1))
    assert dispositions(result) == {'0': 'selected', '1': 'critical_overflow'}
    critical[0] = critical[0].model_copy(update={'known_read': True, 'novelty_key': 'same'})
    result = assemble(request(critical, limit=1))
    assert result.ordered_ids == ['1']


def test_generic_mode_preserves_neutral_attribution():
    result = assemble(request([ordinary(str(i), i, grade=0, intents={}) for i in range(3)]))
    assert result.ordered_ids == ['0', '1', '2']
    assert all(s.scheduled_intent_id is None for s in result.selections)


def test_deterministic_under_input_permutations():
    values = [candidate('a', 0, publisher_id='p1'), candidate('b', 1, publisher_id='p2'),
              candidate('c', 2, coverage_key='story:x'), candidate('d', 3, coverage_key='story:x')]
    expected = assemble(request(values, limit=3)).model_dump()
    for permutation in permutations(values):
        assert assemble(request(list(permutation), limit=3)).model_dump() == expected


def test_ineligible_addition_does_not_change_selected_order():
    values = [candidate('a', 1), candidate('b', 2)]
    baseline = assemble(request(values, limit=2))
    changed = assemble(request([candidate('blocked', 0, eligible=False), *values], limit=2))
    assert changed.ordered_ids == baseline.ordered_ids


def test_empty_and_all_known_read_are_legitimate_shortfalls():
    for values in [[], [candidate(known_read=True, novelty_key='read')]]:
        result = assemble(request(values, limit=5))
        assert result.ordered_ids == []
        assert result.diagnostics['shortfall'] == 5


def test_max_bound_is_valid_deterministic_and_does_not_mutate_request():
    values = [candidate(str(i), i, publisher_id=f'p{i % 7}', topic_ids=[f't{i % 5}']) for i in range(300)]
    req = request(values, limit=100)
    before = req.model_dump()
    started = perf_counter()
    result = assemble(req)
    elapsed = perf_counter()-started
    assert len(result.ordered_ids) == 100
    assert len(result.dispositions) == 300
    assert req.model_dump() == before
    assert validate_result(req, result).model_dump() == result.model_dump()
    # A coarse runaway guard only, not a serving latency benchmark.
    assert elapsed < 5
