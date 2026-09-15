"""S8 contract tests, using no provider or database."""
from copy import deepcopy
from datetime import datetime, timedelta, timezone

import pytest

from app.services.assembly_contract import (AssemblyCandidate, AssemblyRequest, RECIPE,
                                          validate_recipe, validate_result)
from app.services.assembly_service import assemble


NOW = datetime(2026, 9, 9, tzinfo=timezone.utc)


def candidate(article_id='a', ordinal=0, **values):
    return AssemblyCandidate(article_id=article_id, ordinal=ordinal, grade=3,
                             intents={'science': 1.0}, **values)


def request(candidates=None, **values):
    return AssemblyRequest(user_id='account', request_id='edition', ranking_context_hash='ranking',
        ranking_recipe_hash='s7', generation=1, revision=1, history_revision=0,
        as_of=NOW, valid_until=NOW + timedelta(minutes=15), limit=values.pop('limit', 10),
        candidates=candidates if candidates is not None else [candidate()], **values)


@pytest.mark.parametrize('field,value', [('source_streak', True), ('source_streak', '2'),
    ('source_streak', 0), ('source_streak', 101), ('history_retention_days', 31),
    ('history_retention_days', 0), ('topic_share', True), ('publisher_share', float('nan')),
    ('topic_share', float('inf')), ('publisher_share', .09), ('publisher_share', 1.01),
    ('s3_membership_enabled', 1), ('version', 'future'), ('ordering', 'random')])
def test_recipe_rejects_unsupported_or_unsafe_values(field, value):
    with pytest.raises(ValueError):
        validate_recipe({**RECIPE, field: value})


def test_recipe_exact_schema_and_detached_copy():
    for value in [{}, {**RECIPE, 'unknown': 1}, None]:
        with pytest.raises(ValueError):
            validate_recipe(value)
    value = validate_recipe(RECIPE)
    value['source_streak'] = 8
    assert RECIPE['source_streak'] == 2


@pytest.mark.parametrize('field,value', [('grade', True), ('grade', '3'), ('grade', 1),
    ('ordinal', -1), ('ordinal', True), ('ordinal', 302), ('article_id', ''),
    ('intents', {'science': float('nan')}), ('intents', {'science': True}),
    ('intents', {'science': .01}), ('intents', {}), ('authorized', 'true'),
    ('known_read', True), ('topic_ids', ['science', 'science'])])
def test_candidate_rejects_incoherent_features(field, value):
    with pytest.raises(ValueError):
        AssemblyCandidate.model_validate({**candidate().model_dump(), field: value})


def test_generic_and_critical_do_not_fabricate_personal_attribution():
    assert AssemblyCandidate(article_id='g', ordinal=0, grade=0).intents == {}
    with pytest.raises(ValueError):
        AssemblyCandidate(article_id='g', ordinal=0, grade=0, intents={'science': 1.0})
    assert not AssemblyCandidate(article_id='c', ordinal=0, grade=0, origin='world_critical').authorized


def test_request_identity_bounds_and_rank_ordinals():
    for values in [[candidate(), candidate()], [candidate(), candidate('b')],
                   [candidate(str(i), min(i, 301)) for i in range(301)],
                   [candidate(str(i), i, origin='world_critical') for i in range(3)]]:
        with pytest.raises(ValueError):
            request(values)
    # Separate S4 and S7 ordinal spaces are deliberate.
    request([candidate(), candidate('c', origin='world_critical', authorized=True)])


@pytest.mark.parametrize('limit', [0, 101, True, '10'])
def test_request_capacity_is_strict(limit):
    with pytest.raises(ValueError):
        request(limit=limit)


def test_request_temporal_and_priority_coherence():
    data = request().model_dump()
    for overrides in [{'as_of': NOW.replace(tzinfo=None)}, {'valid_until': NOW},
                      {'history_revision': -1}, {'assembly_epoch': 0}]:
        with pytest.raises(ValueError):
            AssemblyRequest.model_validate({**data, **overrides})
    second = candidate('b', 1).model_copy(update={'intents': {'science': 2.0}})
    with pytest.raises(ValueError):
        request([candidate(), second])


def test_fingerprint_is_permutation_invariant_but_tracks_all_dependencies():
    first = request([candidate(topic_ids=['a', 'b']), candidate('b', 1)])
    second = request([candidate('b', 1), candidate(topic_ids=['b', 'a'])])
    assert first.fingerprint == second.fingerprint
    for overrides in [{'history_revision': 1}, {'assembly_epoch': 2},
                      {'dependencies': {'unselected_member': 'changed'}}]:
        assert first.fingerprint != AssemblyRequest.model_validate({**first.model_dump(), **overrides}).fingerprint


@pytest.mark.parametrize('field,value', [('context_hash', 'wrong'), ('history_revision', 1),
    ('assembly_epoch', 2), ('recipe_hash', 'wrong'), ('dependencies', {'changed': True})])
def test_result_cannot_be_replayed_against_other_snapshot(field, value):
    req = request()
    result = assemble(req).model_dump()
    with pytest.raises(ValueError):
        validate_result(req, {**result, field: value})


def test_result_cannot_forge_attribution_position_origin_or_omissions():
    req = request([candidate(), candidate('b', 1)], limit=1)
    result = assemble(req).model_dump()
    for field, value in [('grade', 2), ('intents', {'forged': 1.0}), ('origin', 'world_critical'),
                         ('final_position', 1), ('coverage_key', 'invented'), ('scheduled_intent_id', None)]:
        changed = deepcopy(result)
        changed['selections'][0][field] = value
        with pytest.raises(ValueError):
            validate_result(req, changed)
    changed = deepcopy(result)
    changed['dispositions'][1]['reason'] = 'known_read_repeat'
    with pytest.raises(ValueError):
        validate_result(req, changed)
    changed = deepcopy(result)
    changed['dispositions'].pop()
    with pytest.raises(ValueError):
        validate_result(req, changed)


def test_selector_revalidates_model_copy_bypass():
    req = request().model_copy(update={'limit': 1000})
    with pytest.raises(ValueError):
        assemble(req)


def test_validated_result_cannot_hide_fillable_opportunities():
    req = request(limit=2)
    result = assemble(req).model_dump()
    result['selections'] = []
    result['ordered_ids'] = []
    result['dispositions'][0]['reason'] = 'capacity'
    with pytest.raises(ValueError):
        validate_result(req, result)
