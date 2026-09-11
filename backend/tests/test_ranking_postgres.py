"""Opt-in S7 SQL contracts on a newly created disposable database only.

Never reads DATABASE_URL or .env. S7_TEST_DATABASE_REQUIRED=1 disallows skips.
The explicit server must permit CREATE DATABASE; these are correctness tests,
not proof of production latency, model quality or compatibility with live data.
"""
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from decimal import Decimal
import os
import secrets
import uuid

import pytest

REQUIRED = os.getenv('S7_TEST_DATABASE_REQUIRED') == '1'
if REQUIRED:
    import psycopg
else:
    psycopg = pytest.importorskip('psycopg')
from psycopg import sql
from psycopg.conninfo import conninfo_to_dict, make_conninfo
from psycopg.rows import dict_row

from app.services import ranking_repository as repository
from app.services.ranking_contract import RECIPE

BASE_URL = os.getenv('S7_TEST_DATABASE_URL')
if REQUIRED and not BASE_URL:
    raise RuntimeError('S7_TEST_DATABASE_REQUIRED=1 requires S7_TEST_DATABASE_URL')
pytestmark = pytest.mark.skipif(not BASE_URL, reason='S7_TEST_DATABASE_URL is not set')
USER, OTHER = (str(uuid.UUID(int=i)) for i in (70001, 70002))
IDENTITY = {'generation': 1, 'revision': 1, 'learning_revision': 1}


@pytest.fixture(scope='session')
def s7_database_url():
    name = f'daily_s7_test_{os.getpid()}_{secrets.token_hex(8)}'
    admin, created = None, False
    try:
        try:
            admin = psycopg.connect(BASE_URL, autocommit=True, connect_timeout=10)
            admin.execute(sql.SQL('CREATE DATABASE {}').format(sql.Identifier(name)))
            created = True
            parameters = conninfo_to_dict(BASE_URL)
            parameters['dbname'] = name
            test_url = make_conninfo(**parameters)
            with psycopg.connect(test_url, autocommit=True, row_factory=dict_row) as conn:
                conn.execute('CREATE TABLE public.users(id uuid PRIMARY KEY, is_deleted boolean DEFAULT false)')
                repository.install_schema(conn)
        except Exception as exc:
            reason = f'S7 PostgreSQL setup unavailable ({type(exc).__name__})'
            if REQUIRED:
                pytest.fail(reason)
            pytest.skip(reason)
        yield test_url
    finally:
        if admin is not None:
            try:
                if created:
                    admin.execute(sql.SQL('DROP DATABASE {} WITH (FORCE)').format(sql.Identifier(name)))
            finally:
                admin.close()


@pytest.fixture
def db(s7_database_url):
    with psycopg.connect(s7_database_url, autocommit=True, row_factory=dict_row) as conn:
        conn.execute('TRUNCATE public.users, public.ranking_control, public.ranking_budget CASCADE')
        conn.execute('INSERT INTO public.ranking_control(singleton) VALUES(true)')
        conn.execute('INSERT INTO public.users(id) VALUES(%s),(%s)', (USER, OTHER))
        yield conn


def enable(db, *, daily='1', account='.5'):
    return repository.configure(db, deepcopy(RECIPE), approved=True, serving=True, provider=True,
                                daily_usd=daily, account_daily_usd=account)


def claim(db, user=USER, identity=IDENTITY):
    result = repository.claim_build(db, user, identity, repository.control(db)['recipe_hash'])
    return {**result, 'build_id': str(result['build_id']), 'token': str(result['token'])}


def reserve(db, build, amount='.1', attempt=1, user=USER):
    return repository.reserve(db, user, build['build_id'], build['token'], attempt, amount)


def publish(db, build, envelope=None):
    return repository.publish(db, USER, build['build_id'], build['token'], IDENTITY,
        envelope or {'rank': {'ordered_ids': ['b', 'a']}, 'final': ['b', 'a']},
        datetime.now(timezone.utc) + timedelta(minutes=1))


def test_install_is_idempotent_zero_spend_and_does_not_reset_approval(db):
    state = repository.control(db)
    assert not state['approved'] and not state['serving'] and not state['provider']
    assert state['daily_usd'] == state['account_daily_usd'] == 0
    configured = enable(db)
    repository.install_schema(db)
    assert repository.control(db) == configured


def test_s9_sequence_survives_result_cleanup_and_advances_only_on_publish(db):
    enable(db)
    first = publish(db, claim(db))
    assert first['publication_sequence'] == 1
    assert repository.latest(db, USER)['publication_sequence'] == 1
    repository.invalidate(db, USER)
    second = publish(db, claim(db))
    assert second['publication_sequence'] == 2
    assert second['created_at'] >= first['created_at']


def test_s9_counter_rolls_back_with_receipt_transaction(db):
    enable(db)
    build = claim(db)
    with pytest.raises(RuntimeError, match='receipt failed'):
        with db.transaction():
            assert publish(db, build)['publication_sequence'] == 1
            raise RuntimeError('receipt failed')
    assert db.execute('SELECT count(*) AS n FROM public.ranking_publication_counters').fetchone()['n'] == 0
    assert repository.latest(db, USER) is None
    assert publish(db, build)['publication_sequence'] == 1


def test_s9_concurrent_same_claim_has_one_publication_sequence(db, s7_database_url):
    enable(db)
    build = claim(db)
    def attempt():
        with psycopg.connect(s7_database_url, autocommit=True, row_factory=dict_row) as conn:
            try:
                return publish(conn, build)['publication_sequence']
            except repository.RankingStoreError:
                return None
    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(lambda _: attempt(), range(2)))
    assert results.count(1) == 1 and results.count(None) == 1
    assert db.execute('SELECT sequence FROM public.ranking_publication_counters WHERE user_id=%s',
                      (USER,)).fetchone()['sequence'] == 1


def test_live_claim_cannot_be_stolen_by_new_identity_and_stale_owner_cannot_publish(db):
    enable(db)
    first = claim(db)
    assert repository.claim_build(db, USER, {'revision': 2}, repository.control(db)['recipe_hash']) is None
    db.execute("UPDATE public.ranking_builds SET expires_at=clock_timestamp()-interval '1 second'")
    second = claim(db)
    with pytest.raises(repository.RankingStoreError, match='stale_claim'):
        publish(db, first)
    assert publish(db, second)
    assert repository.latest(db, USER)['envelope']['final'] == ['b', 'a']


def test_epoch_change_and_invalidation_make_publication_and_cache_unavailable(db):
    enable(db)
    first = claim(db)
    publish(db, first)
    enable(db)
    assert repository.latest(db, USER) is None
    with pytest.raises(repository.RankingStoreError, match='stale_claim'):
        publish(db, first)
    repository.invalidate(db, USER)
    assert repository.latest(db, USER) is None
    assert db.execute('SELECT count(*) AS n FROM public.ranking_builds').fetchone()['n'] == 0


def test_envelope_and_receipt_failure_roll_back_together(db):
    enable(db)
    build = claim(db)
    with pytest.raises(RuntimeError, match='receipt failed'):
        with db.transaction():
            publish(db, build)
            raise RuntimeError('receipt failed')
    assert repository.latest(db, USER) is None
    assert not db.execute('SELECT published FROM public.ranking_builds').fetchone()['published']


def test_global_reservations_are_serialized_across_connections(db, s7_database_url):
    enable(db, daily='.15', account='.15')
    builds = {USER: claim(db), OTHER: claim(db, OTHER)}
    def spend(user):
        with psycopg.connect(s7_database_url, autocommit=True, row_factory=dict_row) as conn:
            try:
                return reserve(conn, builds[user], user=user)
            except repository.RankingStoreError as exc:
                assert str(exc) == 'budget_exhausted'
                return None
    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(spend, (USER, OTHER)))
    assert sum(result is not None for result in results) == 1
    assert db.execute("SELECT committed_usd FROM public.ranking_budget WHERE account='*'").fetchone()['committed_usd'] == Decimal('.1')


def test_settlement_idempotent_after_claim_expiry_and_overrun_fences_work(db):
    enable(db)
    build = claim(db)
    reserved = reserve(db, build)
    again = reserve(db, build)
    assert again['reservation_id'] == reserved['reservation_id']
    db.execute("UPDATE public.ranking_builds SET expires_at=clock_timestamp()-interval '1 second'")
    settled = repository.settle(db, reserved['reservation_id'], '.2')
    assert settled['overrun']
    assert repository.settle(db, reserved['reservation_id'], '.2')['overrun']
    state = repository.control(db)
    assert not state['provider'] and not state['serving']
    assert db.execute("SELECT committed_usd FROM public.ranking_budget WHERE account='*'").fetchone()['committed_usd'] == Decimal('.2')


def test_account_delete_retains_global_spend_but_cleans_private_state(db):
    enable(db)
    build = claim(db)
    reserve(db, build)
    publish(db, build)
    db.execute('DELETE FROM public.users WHERE id=%s', (USER,))
    for table in ('ranking_builds', 'ranking_results', 'ranking_reservations'):
        assert db.execute(sql.SQL('SELECT count(*) AS n FROM public.{}').format(sql.Identifier(table))).fetchone()['n'] == 0
    rows = db.execute('SELECT account,committed_usd FROM public.ranking_budget').fetchall()
    assert rows == [{'account': '*', 'committed_usd': Decimal('.1')}]


def test_reservation_waits_on_user_before_control_and_times_out_bounded(db, s7_database_url):
    enable(db)
    build = claim(db)
    with psycopg.connect(s7_database_url, autocommit=True, row_factory=dict_row) as owner:
        with owner.transaction():
            owner.execute('SELECT id FROM public.users WHERE id=%s FOR UPDATE', (USER,))
            with pytest.raises(psycopg.errors.LockNotAvailable):
                reserve(db, build)
            # A failed admission did not retain a control lock or change totals.
            owner.execute("SET LOCAL lock_timeout='100ms'")
            owner.execute('SELECT singleton FROM public.ranking_control FOR UPDATE')
    assert db.execute('SELECT count(*) AS n FROM public.ranking_reservations').fetchone()['n'] == 0


def test_settlement_waits_on_user_before_control_and_retains_reservation(db, s7_database_url):
    enable(db)
    build = claim(db)
    reserved = reserve(db, build)
    with psycopg.connect(s7_database_url, autocommit=True, row_factory=dict_row) as owner:
        with owner.transaction():
            owner.execute('SELECT id FROM public.users WHERE id=%s FOR UPDATE', (USER,))
            with pytest.raises(psycopg.errors.LockNotAvailable):
                repository.settle(db, reserved['reservation_id'], '.04')
            owner.execute("SET LOCAL lock_timeout='100ms'")
            owner.execute('SELECT singleton FROM public.ranking_control FOR UPDATE')
    row = db.execute('SELECT actual_usd FROM public.ranking_reservations').fetchone()
    assert row['actual_usd'] is None
    assert db.execute("SELECT committed_usd FROM public.ranking_budget WHERE account='*'").fetchone()['committed_usd'] == Decimal('.1')


def test_unsupported_approval_does_not_change_epoch_or_enable_serving(db):
    before = repository.control(db)
    with pytest.raises(repository.RankingStoreError, match='unsupported_recipe'):
        repository.configure(db, {**deepcopy(RECIPE), 'max_attempts': 7},
                             approved=True, serving=True)
    assert repository.control(db) == before
