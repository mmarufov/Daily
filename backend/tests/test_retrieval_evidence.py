"""Offline batch/single S3 parity and fail-closed S6 policy projection tests."""
from copy import deepcopy
import hashlib
from uuid import UUID

import pytest

from app.services.article_content import EXTRACTOR_VERSION
from app.services.understanding_contract import TOPIC_IDS, build_evidence
from app.services.understanding_repository import load_current, load_current_batch, policy_evidence


ARTICLE_ID = str(UUID(int=1))


def article(identifier=ARTICLE_ID):
    return dict(id=identifier, title='Apple develops a new product.', summary='Product news.',
        url='https://publisher.example.com/story', source_name='Publisher', semantic_revision=3,
        analysis_eligibility_generation=2, analysis_content_artifact_id=42)


def artifact(identifier=ARTICLE_ID):
    text = 'Apple develops a new product. This story is not sponsored.'
    return dict(id=42, article_id=identifier, version=1, kind='origin_extract',
        origin_url='https://publisher.example.com/story', method='trafilatura',
        extractor_version=EXTRACTOR_VERSION, completeness='complete', confidence=.95,
        is_current=True, text=text, content_hash=hashlib.sha256(text.encode()).hexdigest())


def card(bundle):
    return dict(article_id=bundle['article_id'], input_hash=bundle['input_hash'],
        kind='unknown', kind_evidence=[], topics=[], entities=[], places=[],
        commercial=dict(value='unknown', subtype=None, evidence=[]), about=None,
        about_evidence=[], event_hints=[], abstentions=[dict(field=field,
        reason='insufficient_evidence') for field in
        ('kind', 'topics', 'entities', 'places', 'commercial', 'about', 'event_hints')])


def span(bundle, quote='Apple'):
    start = bundle['fields']['title'].index(quote)
    return dict(field='title', start=start, end=start + len(quote), quote=quote)


class Rows:
    def __init__(self, values):
        self.values = deepcopy(values)

    def fetchone(self):
        return self.values[0] if self.values else None

    def fetchall(self):
        return self.values


class Connection:
    """Models SQL read boundaries; does not emulate PostgreSQL guarantees."""
    def __init__(self, count=1, mutate=None, stages=('facets', 'embedding')):
        self.articles = {str(UUID(int=i)): article(str(UUID(int=i))) for i in range(1, count + 1)}
        self.artifacts = {key: artifact(key) for key in self.articles}
        self.bundles = {key: build_evidence(value, self.artifacts[key]) for key, value in self.articles.items()}
        self.results = [dict(article_id=key, input_hash=bundle['input_hash'],
            semantic_revision=3, analysis_eligibility_generation=2, recipe_id='recipe',
            stage=stage, result_id=f'{key}:{stage}',
            payload=card(bundle) if stage == 'facets' else {'dimensions': 1536})
            for key, bundle in self.bundles.items() for stage in stages]
        self.calls = []
        self.mutate = mutate
        self.enabled = True
        self.serving = 'recipe'

    def execute(self, sql, params=()):
        self.calls.append(sql)
        if 'SELECT serving_recipe' in sql:
            return Rows([dict(serving_recipe=self.serving)])
        if 'SELECT enabled' in sql:
            return Rows([dict(enabled=self.enabled)])
        if 'FROM public.article_understanding_current' in sql:
            result = Rows(self.results)
            if self.mutate:
                self.mutate(self)
                self.mutate = None
            return result
        if 'FROM public.story_memberships' in sql:
            return Rows([])
        if 'to_jsonb(c)' in sql:
            return Rows([dict(value, _selected_artifact=self.artifacts.get(key))
                         for key, value in self.articles.items() if key in params[0]])
        if 'FROM public.articles WHERE id=' in sql:
            return Rows([self.articles[params[0]]] if params[0] in self.articles else [])
        if 'FROM public.article_content_artifacts' in sql:
            return Rows([self.artifacts[params[1]]] if params[1] in self.artifacts else [])
        raise AssertionError(sql)


@pytest.mark.parametrize('stages,state', [
    ((), 'pending'), (('facets',), 'partial'), (('embedding',), 'partial'),
    (('facets', 'embedding'), 'ready'),
])
def test_batch_parity_with_single_current_validator(stages, state):
    single = load_current(Connection(stages=stages), ARTICLE_ID)
    batch = load_current_batch(Connection(stages=stages), [ARTICLE_ID])[ARTICLE_ID]
    assert batch['state'] == state
    assert {key: batch[key] for key in single} == single
    assert batch['article']['id'] == ARTICLE_ID


def test_three_hundred_articles_use_constant_queries_without_membership_reads():
    conn = Connection(300)
    result = load_current_batch(conn, conn.articles)
    assert len(result) == 300
    assert all(value['state'] == 'ready' for value in result.values())
    assert len(conn.calls) == 6
    assert not any('story_memberships' in sql for sql in conn.calls)


def test_membership_is_an_explicit_optional_batched_read():
    conn = Connection(3)
    load_current_batch(conn, conn.articles, include_membership=True)
    assert sum('story_memberships' in sql for sql in conn.calls) == 1


def test_batch_bounds_are_checked_before_sql():
    conn = Connection()
    assert load_current_batch(conn, []) == {}
    with pytest.raises(ValueError, match='300'):
        load_current_batch(conn, [ARTICLE_ID] * 301)
    assert conn.calls == []


@pytest.mark.parametrize('mutation', [
    lambda c: c.articles[ARTICLE_ID].update(semantic_revision=4),
    lambda c: c.articles[ARTICLE_ID].update(analysis_eligibility_generation=3),
    lambda c: c.articles[ARTICLE_ID].update(analysis_revoked=True),
    lambda c: c.articles[ARTICLE_ID].update(summary='Corrected without revision trigger'),
    lambda c: c.artifacts[ARTICLE_ID].update(is_current=False),
    lambda c: c.artifacts[ARTICLE_ID].update(text='Edited in place'),
    lambda c: c.articles.pop(ARTICLE_ID),
])
def test_recheck_rejects_article_and_in_place_artifact_edits(mutation):
    single = load_current(Connection(mutate=mutation), ARTICLE_ID)
    batch = load_current_batch(Connection(mutate=mutation), [ARTICLE_ID])[ARTICLE_ID]
    assert single['state'] == batch['state'] == 'stale'
    assert batch['facets'] is batch['embedding'] is None


@pytest.mark.parametrize('field,value', [
    ('input_hash', 'old'), ('semantic_revision', 2),
    ('analysis_eligibility_generation', 1), ('recipe_id', 'old'),
])
def test_current_results_must_match_all_fences(field, value):
    conn = Connection()
    for result in conn.results:
        result[field] = value
    assert load_current_batch(conn, [ARTICLE_ID])[ARTICLE_ID]['state'] == 'pending'


@pytest.mark.parametrize('mutation', [lambda c: setattr(c, 'enabled', False),
                                    lambda c: setattr(c, 'serving', 'new')])
def test_recipe_disable_or_serving_promotion_invalidates_default_cohort(mutation):
    result = load_current_batch(Connection(mutate=mutation), [ARTICLE_ID])[ARTICLE_ID]
    assert result['state'] == 'disabled'
    assert result['facets'] is result['embedding'] is None


def test_s3_disabled_preserves_article_metadata_without_inventing_policy_evidence():
    conn = Connection()
    conn.serving = None
    value = load_current_batch(conn, [ARTICLE_ID])[ARTICLE_ID]
    assert value['article']['title'] == article()['title']
    assert value['state'] == 'disabled'
    assert value['policy_evidence']['topic_ids'] is None


def current():
    return load_current_batch(Connection(), [ARTICLE_ID])[ARTICLE_ID]


def test_empty_and_abstained_fields_are_unknown_not_known_absent():
    value = policy_evidence(current())
    assert value['topic_ids'] is value['entity_ids'] is value['place_ids'] is None
    assert value['_policy_evidence_states']['topic'] == 'abstained'
    assert value['sector_ids'] is value['language'] is None


@pytest.mark.parametrize('role,expected', [('primary', True), ('secondary', True), ('mentioned', False)])
def test_topics_project_only_validated_central_roles(role, expected):
    value = current()
    payload = value['facets']['payload']
    payload['abstentions'] = [item for item in payload['abstentions'] if item['field'] != 'topics']
    topic = next(iter(TOPIC_IDS))
    payload['topics'] = [dict(topic_id=topic, role=role, evidence=[span(value['evidence'])])]
    projected = policy_evidence(value)
    assert projected['topic_ids'] == ([topic] if expected else [])


def test_unresolved_central_entity_is_unknown_but_incidental_mention_is_not_aboutness():
    value = current()
    payload = value['facets']['payload']
    payload['abstentions'] = [item for item in payload['abstentions'] if item['field'] != 'entities']
    payload['entities'] = [dict(mention='Apple', entity_type='organization', role='subject',
        resolved_id=None, resolution='unresolved', evidence=[span(value['evidence'])])]
    assert policy_evidence(value)['_policy_evidence_states']['entity'] == 'unresolved'
    payload['entities'][0]['role'] = 'mentioned'
    assert policy_evidence(value)['entity_ids'] == []


def test_corrupted_card_evidence_is_never_policy_proof():
    value = current()
    value['facets']['payload']['input_hash'] = 'not-current'
    assert policy_evidence(value)['_policy_evidence_states']['topic'] == 'invalid_facets'


def test_truncated_input_never_proves_subject_absence():
    value = current()
    value['evidence']['manifest']['truncated'] = True
    assert policy_evidence(value)['_policy_evidence_states']['topic'] == 'truncated'


def test_full_field_capacity_does_not_claim_exhaustive_subject_coverage():
    value = current()
    payload = value['facets']['payload']
    payload['abstentions'] = [item for item in payload['abstentions'] if item['field'] != 'topics']
    payload['topics'] = [dict(topic_id=topic, role='primary', evidence=[span(value['evidence'])])
                         for topic in sorted(TOPIC_IDS)[:12]]
    assert policy_evidence(value)['_policy_evidence_states']['topic'] == 'possibly_truncated'
