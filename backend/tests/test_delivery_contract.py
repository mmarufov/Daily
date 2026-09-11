"""S9 deterministic wire/lifetime contracts. No hosted database or provider."""
import asyncio
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from unittest.mock import Mock
import uuid

import pytest

from app.services import delivery_contract as delivery
from app.services import ranking_service as ranking
from app.services import ranking_repository as repository
from tests.test_ranking_integration import api

NOW = datetime(2026, 9, 9, 12, tzinfo=timezone.utc)
REQUEST = str(uuid.UUID(int=9))
IDENTITY = {'reader_generation': 1, 'reader_revision': 2}


def publication(**changes):
    return {'publication_sequence': 3, 'created_at': NOW-timedelta(seconds=30),
            'expires_at': NOW+timedelta(minutes=5), **changes}


def test_publication_revalidation_never_renews_deadline_or_identity():
    first = delivery.metadata(publication(), REQUEST, IDENTITY, now=NOW)
    second = delivery.metadata(publication(), REQUEST, IDENTITY, now=NOW+timedelta(seconds=5))
    assert first['sequence'] == 3 and first['edition_id'] == REQUEST
    assert first['valid_until'] == second['valid_until']
    assert {k:v for k,v in first.items() if k != 'validated_at'} == {
        k:v for k,v in second.items() if k != 'validated_at'}


@pytest.mark.parametrize('sequence', [None, 0, -1, True, 2.5, '3', delivery.MAX_SEQUENCE+1])
def test_publication_sequence_is_strict(sequence):
    with pytest.raises(ValueError):
        delivery.metadata(publication(publication_sequence=sequence), REQUEST, IDENTITY, now=NOW)


@pytest.mark.parametrize('changes', [
    {'created_at': NOW+timedelta(seconds=1)}, {'expires_at': NOW},
    {'expires_at': NOW+timedelta(minutes=16)}, {'created_at': NOW.replace(tzinfo=None)}])
def test_publication_rejects_invalid_lifetimes(changes):
    with pytest.raises(ValueError):
        delivery.metadata(publication(**changes), REQUEST, IDENTITY, now=NOW)


def test_legacy_negotiation_omits_new_contract_without_mutating_result():
    result = {'status':'ready', 'articles':[], 'delivery':{'sequence':3}, 'reason':'example'}
    assert delivery.negotiated(result, None) == {'status':'ready', 'articles':[]}
    assert 'delivery' in result


@pytest.mark.parametrize('status', ['building', 'unavailable', 'needs_build', 'needs_reader_review'])
def test_failure_contract_has_machine_reason(status):
    result = delivery.negotiated({'status':status,'articles':[]}, '1')
    assert result['reason']
    if status in {'building', 'unavailable'}:
        assert result['retry_after_seconds'] == 5


def native():
    return {'presentation': {'mode':'native_full_text','body':'verified publisher body',
                              'provenance': {'policy_version':2}}}


@pytest.mark.parametrize('seconds', [None, 0, -1, True, '300', 86401])
def test_offline_rights_are_default_deny(seconds):
    result = delivery.native_lease(native(), policy={'display_policy':'native_full_text',
        'version':2,'offline_cache_seconds':seconds}, now=NOW)
    assert result['presentation']['offline_valid_until'] is None


def test_native_policy_grant_is_bounded_and_version_bound():
    policy = {'display_policy':'native_full_text','version':2,'offline_cache_seconds':600}
    result = delivery.native_lease(native(), policy=policy, now=NOW)
    assert result['presentation']['offline_valid_until'] == (NOW+timedelta(minutes=10)).isoformat()
    assert result['presentation']['validated_at'] == NOW.isoformat()
    assert 'offline_valid_until' not in native()['presentation']
    for changed in ({**policy, 'version':3}, {**policy, 'display_policy':'source_only'}):
        assert delivery.native_lease(native(), policy=changed, now=NOW)['presentation']['offline_valid_until'] is None


def test_cache_database_failure_is_not_a_build_request(monkeypatch):
    monkeypatch.setenv('S7_SERVING_ENABLED','true')
    monkeypatch.setenv('S5_READER_ENABLED','true')
    monkeypatch.setenv('S6_SERVING_ENABLED','true')
    monkeypatch.setattr(repository,'latest',Mock(side_effect=RuntimeError('database unavailable')))
    assert ranking.cached_feed(None, REQUEST, delivery_version='1')['status'] == 'unavailable'
    assert ranking.cached_feed(None, REQUEST)['status'] == 'needs_build'


def test_same_sequence_never_returns_different_limit_projection(monkeypatch):
    monkeypatch.setenv('S7_SERVING_ENABLED','true')
    monkeypatch.setenv('S5_READER_ENABLED','true')
    monkeypatch.setenv('S6_SERVING_ENABLED','true')
    monkeypatch.setattr(repository,'latest',lambda *a: {'envelope':{'limit':50}})
    assert ranking.cached_feed(None, REQUEST, limit=10, delivery_version='1')['status'] == 'needs_build'


def test_detail_auth_and_hydration_share_worker_owned_connection(monkeypatch):
    from app import main
    from app.services import feed_service
    import threading
    event_thread = threading.get_ident()
    events = []

    class Connection:
        @contextmanager
        def transaction(self):
            yield
        @contextmanager
        def cursor(self):
            yield self
        def execute(self, sql):
            events.append(sql)

    connection = Connection()
    class Pool:
        borrowed = 0
        @contextmanager
        def connection(self, **kwargs):
            assert threading.get_ident() != event_thread
            self.borrowed += 1
            try:
                yield connection
            finally:
                self.borrowed -= 1

    pool = Pool()
    monkeypatch.setattr(main,'pool',pool)
    monkeypatch.setattr(main,'_require_auth',lambda token:'token')
    def authenticate(conn, token):
        assert pool.borrowed == 1 and conn is connection
        events.append('authenticated')
        return REQUEST
    def hydrate(article_id, conn, **kwargs):
        assert threading.get_ident() != event_thread and pool.borrowed == 1
        assert events[-1] == 'authenticated' and kwargs == {'delivery_version':'1'}
        return {'id':article_id}
    monkeypatch.setattr(main,'_get_user_id_from_token',authenticate)
    monkeypatch.setattr(feed_service,'get_article_by_id_sync',hydrate)
    assert asyncio.run(main.get_feed_article(REQUEST, Authorization='Bearer token', delivery_version='1')) == {'id':REQUEST}
    assert pool.borrowed == 0


def test_detail_rejected_auth_never_hydrates(monkeypatch):
    from app import main
    from app.services import feed_service
    monkeypatch.setattr(main,'_require_auth',Mock(side_effect=main.HTTPException(401,'Unauthorized')))
    hydrate = Mock()
    monkeypatch.setattr(feed_service,'get_article_by_id_sync',hydrate)
    with pytest.raises(main.HTTPException) as error:
        asyncio.run(main.get_feed_article(REQUEST, Authorization=None))
    assert error.value.status_code == 401
    hydrate.assert_not_called()


@pytest.mark.parametrize('version', [None, '1'])
def test_feed_negotiation_keeps_existing_capabilities_independent(api, monkeypatch, version):
    result = {'status':'ready','articles':[], 'delivery':delivery.metadata(publication(),REQUEST,IDENTITY,now=NOW)}
    def cached(conn, user_id, **kwargs):
        assert kwargs.get('delivery_version') == version
        assert kwargs['capability'] is None
        return result
    monkeypatch.setattr(ranking,'cached_feed',cached)
    output = asyncio.run(api.get_feed(Authorization='Bearer token', conn=None, limit=50,
        event_expiry=None, edition_version='1', delivery_version=version))
    assert ('delivery' in output) == (version == '1')
    assert output['articles'] == []


def test_feed_database_slot_exhaustion_is_retryable_not_build(api, monkeypatch):
    async def unavailable(*args, **kwargs):
        raise RuntimeError('ranking_database_busy')
    monkeypatch.setattr(ranking,'database_phase',unavailable)
    result = asyncio.run(api._s7_feed(REQUEST,limit=50,capability=None,delivery_version='1'))
    assert result['status'] == 'unavailable' and result['retry_after_seconds'] == 5


def test_personalized_http_responses_are_never_shared_cached():
    from app import main
    from types import SimpleNamespace
    request = SimpleNamespace(headers={}, url=SimpleNamespace(path='/feed/abc'),method='GET')
    response = SimpleNamespace(headers={'content-length':'23'},status_code=200)
    async def next_handler(request):
        return response
    actual = asyncio.run(main._security_headers(request,next_handler))
    assert actual.headers['Cache-Control'] == 'private, no-store'


@pytest.mark.parametrize('seconds', [False,-1,86401,1.5])
def test_policy_api_rejects_invalid_offline_grants_before_database(seconds):
    from app.services.article_content import set_source_policy
    with pytest.raises(ValueError,match='offline cache'):
        set_source_policy(object(),source_domain='example.com',display_policy='native_full_text',
            allowed_artifact_kinds=['origin_extract'],publisher_feed_full_text=False,
            rights_basis='publisher_permission',access_hint='open',reviewed_by='reviewer',
            offline_cache_seconds=seconds)
