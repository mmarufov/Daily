"""Final endpoint adapter invariants; no hosted/database proof is implied."""
from contextlib import contextmanager
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import Mock
import uuid

import pytest

from app.services import event_integration as integration

USER = '11111111-1111-1111-1111-111111111111'
ARTICLE = '22222222-2222-2222-2222-222222222222'
OTHER = '33333333-3333-3333-3333-333333333333'


class Connection:
    autocommit = True
    info = SimpleNamespace(transaction_status=0)

    def __init__(self, *, hidden_error=False, delivery=True, articles=(), topic_recipe=True,
                 receipt_error=False, seen=(), hidden=None):
        self.sql = []
        self.parameters = []
        self.hidden_error, self.delivery = hidden_error, delivery
        self.inside = False
        self.articles, self.topic_recipe = list(articles), topic_recipe
        self.receipt_error, self.seen = receipt_error, list(seen)
        self.hidden = [{'article_id': 'hidden'}] if hidden is None else hidden
        self.transaction_count = 0

    @contextmanager
    def transaction(self):
        self.inside = True
        self.transaction_count += 1
        try:
            yield
        finally:
            self.inside = False

    def execute(self, sql, parameters=None):
        self.sql.append(sql)
        self.parameters.append(parameters)
        if 'reading_events' in sql and self.hidden_error:
            raise RuntimeError('private database error must not escape')
        if 'INSERT INTO public.event_delivery_receipts' in sql and self.receipt_error:
            raise RuntimeError('private receipt error must not escape')
        one = {'delivery_enabled': self.delivery} if 'event_control' in sql else {'time': datetime.now(timezone.utc)}
        if 'JOIN public.understanding_recipes' in sql:
            one = {'id': 'approved-s3'} if self.topic_recipe else None
        rows = []
        if 'SELECT DISTINCT article_id' in sql:
            rows = self.hidden
        elif 'WITH RECURSIVE seen' in sql:
            rows = self.seen
        elif 'SELECT a.* FROM public.articles' in sql:
            rows = self.articles
        return SimpleNamespace(fetchone=lambda: one, fetchall=lambda: rows)


@pytest.fixture
def wiring(monkeypatch):
    monkeypatch.setenv('S4_CONSUMERS_ENABLED', 'true')
    # S4 priority is only composed onto an edition something will receipt and
    # the client can echo back -- otherwise its "already knew" suppression is
    # decorative. See `_delivery_is_attributable` and the tests below.
    monkeypatch.setenv('S5_READER_ENABLED', 'true')
    from app.services import feed_service
    monkeypatch.setattr(feed_service, '_load_user_preferences_full', lambda *a: ('profile', {}, {}, None, None))
    monkeypatch.setattr(feed_service, '_build_preference_profile', lambda *a, **k: 'profile')
    monkeypatch.setattr(feed_service, '_score_candidate', lambda article, profile: (0, '', article.get('excluded', False)))
    return feed_service


@pytest.mark.parametrize('capability', [None, '', 'true', '0', True])
def test_old_client_never_queries_S4(monkeypatch, capability):
    monkeypatch.setenv('S4_CONSUMERS_ENABLED', 'true')
    result = {'status': 'needs_discovery', 'articles': []}
    assert integration.compose_feed(None, USER, result, capability=capability) is result


def test_feature_disabled_never_touches_database(monkeypatch):
    monkeypatch.delenv('S4_CONSUMERS_ENABLED', raising=False)
    result = {'status': 'ready', 'articles': [{'id': 'ordinary'}]}
    assert integration.compose_feed(None, USER, result, capability='1') is result


def test_no_active_sources_can_reach_final_event_composition(wiring, monkeypatch):
    conn = Connection()
    result = {'status': 'needs_discovery', 'articles': []}
    def load(connection, *, in_snapshot):
        assert connection.inside and in_snapshot is True
        return ['authorized-candidate']
    monkeypatch.setattr(integration.repo, 'load_candidates', load)
    def compose(ordinary, candidates, policy, *, now, limit, hard_allowed):
        assert conn.inside
        assert ordinary is result and candidates == ['authorized-candidate']
        assert policy.blocked_article_ids == frozenset({'hidden'})
        assert hard_allowed({'id': 'unsubscribed-source'})
        assert not hard_allowed({'id': 'hidden'})
        assert not hard_allowed({'id': 'excluded', 'excluded': True})
        assert not hard_allowed({'id': 'revoked', 'analysis_revoked': True})
        return SimpleNamespace(payload={'status': 'ready', 'articles': [{'id': 'event'}]}, decisions=[], major_candidates=[])
    monkeypatch.setattr(integration, 'apply_event_feed', compose)
    assert integration.compose_feed(conn, USER, result, capability='1')['articles'] == [{'id': 'event'}]
    assert conn.sql[0] == 'SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY'


def test_failed_hide_lookup_never_means_no_exclusions(wiring, monkeypatch, caplog):
    conn = Connection(hidden_error=True)
    load = Mock()
    monkeypatch.setattr(integration.repo, 'load_candidates', load)
    result = {'status': 'ready', 'articles': [{'id': 'ordinary'}]}
    assert integration.compose_feed(conn, USER, result, capability='1') is result
    load.assert_not_called()
    assert 'private database error' not in caplog.text


def test_database_delivery_switch_blocks_warm_feature(wiring, monkeypatch):
    conn = Connection(delivery=False)
    load = Mock()
    monkeypatch.setattr(integration.repo, 'load_candidates', load)
    result = {'status': 'ready', 'articles': []}
    assert integration.compose_feed(conn, USER, result, capability='1') is result
    load.assert_not_called()


def test_existing_transaction_cannot_supply_a_mixed_authorization(wiring):
    conn = Connection()
    conn.autocommit = False
    result = {'status': 'ready', 'articles': []}
    assert integration.compose_feed(conn, USER, result, capability='1') is result
    assert conn.sql == []


def test_invalid_explicit_profile_fails_closed(wiring, monkeypatch):
    monkeypatch.setattr(wiring, '_load_user_preferences_full', lambda *a: ('profile', {}, {'blocked_source_ids': 'not-list'}, None, None))
    result = {'status': 'ready', 'articles': []}
    load = Mock()
    monkeypatch.setattr(integration.repo, 'load_candidates', load)
    assert integration.compose_feed(Connection(), USER, result, capability='1') is result
    load.assert_not_called()


def public_article(identifier=ARTICLE):
    return {'id': identifier, 'title': 'Previously serialized source title', 'source': 'Publisher',
            'presentation': {'mode': 'source_web', 'original_url': 'https://example.com/report'},
            'relevant': True, 'relevance_score': .7}


def raw_article(identifier=ARTICLE, **changes):
    return {'id': uuid.UUID(identifier), 'title': 'Current title', 'summary': 'Current summary',
            'source_name': 'Publisher', 'canonical_source_domain': 'publisher.example',
            'content': 'PRIVATE ANALYSIS BODY', **changes}


def set_policy(wiring, monkeypatch, **settings):
    monkeypatch.setattr(wiring, '_load_user_preferences_full', lambda *a: ('profile', {}, settings, None, None))


def test_ordinary_policy_reauthorization_uses_current_raw_metadata_and_preserves_public_fields(wiring, monkeypatch):
    conn = Connection(articles=[raw_article(ARTICLE, excluded=True), raw_article(OTHER)])
    monkeypatch.setattr(integration.repo, 'load_candidates', lambda *a, **k: [])
    original = {'status': 'ready', 'articles': [public_article(), public_article(OTHER)], 'article_count': 2}
    output = integration.compose_feed(conn, USER, original, capability='1')
    assert output['articles'] == [public_article(OTHER)]
    assert output['article_count'] == 1
    assert original['article_count'] == 2 and len(original['articles']) == 2
    assert 'PRIVATE' not in str(output)
    query = next(i for i, sql in enumerate(conn.sql) if 'SELECT a.* FROM public.articles' in sql)
    assert conn.parameters[query] == ([uuid.UUID(ARTICLE), uuid.UUID(OTHER)],)


def test_exclusion_committed_between_ordinary_build_and_compose_removes_old_public_article(wiring, monkeypatch):
    monkeypatch.setattr(wiring, '_score_candidate', lambda article, profile: (0, '', 'excluded-new' in article['title']))
    conn = Connection(articles=[raw_article(title='excluded-new topic')])
    monkeypatch.setattr(integration.repo, 'load_candidates', lambda *a, **k: [])
    result = {'status': 'ready', 'articles': [public_article()]}
    output = integration.compose_feed(conn, USER, result, capability='1')
    assert output['articles'] == [] and output['status'] == 'needs_build'


@pytest.mark.parametrize('source', ['publisher.example', 'publisher-id'])
def test_ordinary_source_blocks_use_canonical_current_identity_not_public_display_name(wiring, monkeypatch, source):
    set_policy(wiring, monkeypatch, blocked_source_ids=[source])
    conn = Connection(articles=[raw_article(source_id='publisher-id')])
    monkeypatch.setattr(integration.repo, 'load_candidates', lambda *a, **k: [])
    output = integration.compose_feed(conn, USER, {'status': 'ready', 'articles': [public_article()]}, capability='1')
    assert output['articles'] == []


@pytest.mark.parametrize('card,approved,allowed', [
    ({'state': 'ready', 'facets': {'payload': {'topics': [{'topic_id': 'blocked'}]}}}, True, False),
    ({'state': 'ready', 'facets': {'payload': {'topics': [{'topic_id': 'allowed'}]}}}, True, True),
    ({'state': 'pending'}, True, False),
    ({'state': 'ready', 'facets': {'payload': {'topics': []}}}, False, False),
    ({'state': 'ready', 'facets': {'payload': {'topics': [{'topic_id': True}]}}}, True, False),
])
def test_ordinary_hard_topics_require_current_approved_topic_card(wiring, monkeypatch, card, approved, allowed):
    set_policy(wiring, monkeypatch, blocked_topic_ids=['blocked'])
    conn = Connection(articles=[raw_article()], topic_recipe=approved)
    monkeypatch.setattr(integration.repo, 'load_candidates', lambda *a, **k: [])
    lookup = Mock(return_value=card)
    monkeypatch.setattr(integration.repo.s3, 'load_current', lookup)
    output = integration.compose_feed(conn, USER, {'status': 'ready', 'articles': [public_article()]}, capability='1')
    assert bool(output['articles']) is allowed
    if approved:
        lookup.assert_called_once_with(conn, uuid.UUID(ARTICLE), 'approved-s3')
    else:
        lookup.assert_not_called()


def test_ordinary_without_hard_topics_does_not_require_s3_or_analysis_permission(wiring, monkeypatch):
    conn = Connection(articles=[raw_article(analysis_revoked=True)])
    monkeypatch.setattr(integration.repo, 'load_candidates', lambda *a, **k: [])
    lookup = Mock(side_effect=AssertionError('ordinary news does not require S3'))
    monkeypatch.setattr(integration.repo.s3, 'load_current', lookup)
    result = {'status': 'ready', 'articles': [public_article()]}
    assert integration.compose_feed(conn, USER, result, capability='1')['articles'] == result['articles']
    lookup.assert_not_called()


def test_missing_article_and_malformed_id_fail_closed_without_db_row_leak(wiring, monkeypatch):
    conn = Connection(articles=[])
    monkeypatch.setattr(integration.repo, 'load_candidates', lambda *a, **k: [])
    result = {'status': 'ready', 'articles': [public_article(), {'id': 'invalid'}]}
    assert integration.compose_feed(conn, USER, result, capability='1')['articles'] == []


def test_later_s4_failure_cannot_resurrect_rejected_ordinary_row(wiring, monkeypatch):
    conn = Connection(articles=[raw_article(excluded=True)])
    monkeypatch.setattr(integration.repo, 'load_candidates', Mock(side_effect=RuntimeError('unavailable')))
    output = integration.compose_feed(conn, USER, {'status': 'ready', 'articles': [public_article()]}, capability='1')
    assert output['articles'] == []


def priority_article():
    return {'id': ARTICLE, 'event_delivery': {
        'event_id': OTHER, 'development_id': '44444444-4444-4444-4444-444444444444',
        'development_version': 2, 'assessment_id': '55555555-5555-5555-5555-555555555555',
        'valid_until': '2026-09-06T15:00:00Z'}}


def test_delivery_receipt_has_exact_versions_account_request_and_no_read_ack(wiring, monkeypatch):
    conn = Connection()
    monkeypatch.setattr(integration.repo, 'load_candidates', lambda *a, **k: [])
    monkeypatch.setattr(integration, 'apply_event_feed', lambda *a, **k: SimpleNamespace(
        payload={'status': 'ready', 'articles': [priority_article()]}, decisions=[], major_candidates=[]))
    output = integration.compose_feed(conn, USER, {'status': 'needs_discovery', 'articles': []}, capability='1')
    writes = [(sql, params) for sql, params in zip(conn.sql, conn.parameters) if 'INSERT INTO' in sql]
    assert len(writes) == 1 and 'event_delivery_receipts' in writes[0][0]
    values = writes[0][1]
    assert values[0] == uuid.UUID(USER) and values[1] == uuid.UUID(output['feed_request_id'])
    assert values[2] == uuid.UUID(ARTICLE) and values[5] == 2
    assert conn.transaction_count == 2
    assert not any('INSERT INTO public.reading_events' in sql for sql in conn.sql)


def test_receipt_write_failure_returns_only_reauthorized_ordinary(wiring, monkeypatch, caplog):
    conn = Connection(articles=[raw_article(excluded=True), raw_article(OTHER)], receipt_error=True)
    monkeypatch.setattr(integration.repo, 'load_candidates', lambda *a, **k: [])
    monkeypatch.setattr(integration, 'apply_event_feed', lambda *a, **k: SimpleNamespace(
        payload={'status': 'ready', 'articles': [priority_article()]}, decisions=[], major_candidates=[]))
    output = integration.compose_feed(conn, USER, {'status': 'ready', 'articles': [public_article(), public_article(OTHER)]}, capability='1')
    assert output['articles'] == [public_article(OTHER)]
    assert 'event_delivery' not in str(output) and 'private receipt error' not in caplog.text


@pytest.mark.parametrize('limit', [0, 101, 200, True, -1, '10'])
def test_composition_limits_match_selector_contract_before_db_access(wiring, limit):
    conn = Connection()
    with pytest.raises(ValueError):
        integration.compose_feed(conn, USER, {'status': 'ready', 'articles': []}, capability='1', limit=limit)
    assert conn.sql == []
