"""S7 control-flow contracts; actual locking/SQL is in the opt-in PostgreSQL suite."""
from contextlib import nullcontext
from copy import deepcopy
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from unittest.mock import Mock
import uuid

import pytest

from app.services import ranking_repository as repository
from app.services.ranking_contract import RECIPE as DEFAULT_RECIPE

USER, BUILD, TOKEN, RESERVATION = [str(uuid.UUID(int=i)) for i in range(1, 5)]
IDENTITY = {'generation': 1, 'revision': 1, 'learning_revision': 1}
RECIPE = deepcopy(DEFAULT_RECIPE)


class Connection:
    def __init__(self, *, state=None, claim=None, reservation=None, spent=None):
        self.state = state or {'approved': True, 'provider': True, 'serving': True,
            'recipe_hash': 'recipe', 'epoch': 1, 'daily_usd': Decimal('1'),
            'account_daily_usd': Decimal('0.5')}
        self.claim = claim or {'build_id': BUILD, 'token': TOKEN, 'epoch': 1,
            'recipe_hash': 'recipe', 'live': True, 'published': False,
            'identity_hash': repository._identity(IDENTITY)}
        self.reservation = reservation
        self.spent = spent or []
        self.statements = []

    def transaction(self):
        return nullcontext()

    def execute(self, sql, params=()):
        if sql.startswith('SET LOCAL'):
            return Mock()
        self.statements.append((sql, params))
        row, rows = None, []
        if 'SELECT id FROM public.users' in sql:
            row = {'id': USER}
        elif "to_regclass('public.ranking_control')" in sql:
            row = {'relation': 'ranking_control'}
        elif 'SELECT * FROM public.ranking_control' in sql or 'UPDATE public.ranking_control SET epoch=epoch+1,' in sql:
            row = self.state
        elif 'FROM public.ranking_builds WHERE user_id=%s FOR UPDATE' in sql:
            row = self.claim
        elif ('SELECT * FROM public.ranking_reservations' in sql
              or 'SELECT user_id FROM public.ranking_reservations' in sql):
            row = self.reservation
        elif "AT TIME ZONE 'UTC')::date AS day" in sql:
            row = {'day': date(2026, 9, 8)}
        elif 'SELECT account,committed_usd' in sql:
            rows = self.spent
        elif 'INSERT INTO public.ranking_reservations' in sql:
            row = {'reservation_id': params[0], 'reserved_usd': params[-1]}
        elif 'AS valid' in sql:
            row = {'valid': True}
        elif 'INSERT INTO public.ranking_results' in sql:
            row = {'build_id': BUILD}
        elif 'INSERT INTO public.ranking_publication_counters' in sql:
            row = {'sequence': 1}
        return Mock(fetchone=lambda: row, fetchall=lambda: rows)


@pytest.mark.parametrize('value', [True, False, None, 'nan', 'Infinity', '-1', 1000001, object()])
def test_money_rejects_ambiguous_or_unbounded_values(value):
    with pytest.raises(repository.RankingStoreError):
        repository._money(value)


def test_money_rounds_reservations_up_not_down():
    assert repository._money('0.000000001') == Decimal('0.00000001')


@pytest.mark.parametrize('identity', [{}, [], {'x': float('nan')}, {'x': object()}])
def test_identity_must_be_finite_json(identity):
    with pytest.raises(repository.RankingStoreError):
        repository._identity(identity)


@pytest.mark.parametrize('kwargs', [dict(provider=True), dict(serving=True), dict(approved='true'),
    dict(approved=True, provider=True),
    dict(approved=True, provider=True, daily_usd='1', account_daily_usd='2')])
def test_configure_fails_closed_before_sql(kwargs):
    conn = Connection()
    with pytest.raises(repository.RankingStoreError):
        repository.configure(conn, RECIPE, **kwargs)
    assert not conn.statements


def test_explicit_priced_approval_and_positive_budgets():
    conn = Connection()
    repository.configure(conn, RECIPE, approved=True, provider=True,
                         daily_usd='1', account_daily_usd='0.1')
    assert conn.statements[0][1][-2:] == (Decimal('1'), Decimal('0.1'))


def test_configure_does_not_guess_pricing_or_model():
    for recipe in ({'model': repository.SUPPORTED_MODEL}, {**RECIPE, 'model': 'newest-model'},
                   {**RECIPE, 'pricing': {'input_usd_per_million': '.01', 'output_usd_per_million': '.01'}}):
        with pytest.raises(repository.RankingStoreError):
            repository.configure(Connection(), recipe, approved=True, provider=True,
                                 daily_usd='1', account_daily_usd='0.1')


@pytest.mark.parametrize('change', [
    {'rubric': 'unreviewed'}, {'ordering': 'random'}, {'max_attempts': 7},
    {'max_input_tokens': 12001}, {'max_output_tokens': 6001},
    {'deadline_seconds': 21}, {'max_attempts': True},
])
def test_approval_rejects_unsupported_recipe_even_without_provider(change):
    conn = Connection()
    with pytest.raises(repository.RankingStoreError, match='unsupported_recipe'):
        repository.configure(conn, {**deepcopy(RECIPE), **change}, approved=True,
                             serving=True)
    assert not conn.statements


def test_disabled_unapproved_recipe_can_be_saved_for_explicit_later_approval():
    conn = Connection()
    repository.configure(conn, {'proposal': 'unapproved'})
    assert conn.statements[0][1][2:5] == (False, False, False)


def test_claim_sql_does_not_steal_live_changed_identity():
    conn = Connection()
    repository.claim_build(conn, USER, IDENTITY, 'recipe')
    sql = conn.statements[-1][0]
    assert 'ranking_builds.expires_at<=clock_timestamp() OR ranking_builds.published' in sql
    assert 'OR ranking_builds.epoch' not in sql
    assert conn.statements[0][0].endswith('FOR SHARE')


@pytest.mark.parametrize('seconds', [0, 31, 1.5, True])
def test_invalid_lease(seconds):
    with pytest.raises(repository.RankingStoreError):
        repository.claim_build(Connection(), USER, IDENTITY, 'recipe', lease_seconds=seconds)


def test_reserve_serializes_global_control_before_claim_and_counters():
    conn = Connection()
    row = repository.reserve(conn, USER, BUILD, TOKEN, 1, '0.1')
    assert row['reserved_usd'] == Decimal('0.1')
    assert 'public.users' in conn.statements[0][0] and 'FOR SHARE' in conn.statements[0][0]
    assert 'FOR UPDATE' in conn.statements[1][0]
    assert 'ranking_control' in conn.statements[1][0]
    assert 'ranking_builds' in conn.statements[2][0]
    assert sum('INSERT INTO public.ranking_budget' in sql for sql, _ in conn.statements) == 2


@pytest.mark.parametrize('account,amount', [('*', '0.95'), (USER, '0.45')])
def test_global_and_account_reservation_caps(account, amount):
    conn = Connection(spent=[{'account': account, 'committed_usd': Decimal(amount)}])
    with pytest.raises(repository.RankingStoreError, match='budget_exhausted'):
        repository.reserve(conn, USER, BUILD, TOKEN, 1, '0.1')
    assert not any('INSERT' in sql for sql, _ in conn.statements)


@pytest.mark.parametrize('change', [{'live': False}, {'published': True}, {'epoch': 2}, {'token': USER}])
def test_stale_claim_cannot_spend(change):
    conn = Connection()
    conn.claim.update(change)
    with pytest.raises(repository.RankingStoreError, match='stale_claim'):
        repository.reserve(conn, USER, BUILD, TOKEN, 1, '0.1')


def reservation(**extra):
    return {'reservation_id': RESERVATION, 'user_id': USER, 'build_id': BUILD,
        'day': date(2026, 9, 8), 'reserved_usd': Decimal('0.1'), 'actual_usd': None, **extra}


def test_same_attempt_reservation_is_idempotent_and_conflicts_rejected():
    conn = Connection(reservation=reservation())
    assert repository.reserve(conn, USER, BUILD, TOKEN, 1, '0.1') == conn.reservation
    assert not any('INSERT' in sql for sql, _ in conn.statements)
    with pytest.raises(repository.RankingStoreError, match='reservation_reused'):
        repository.reserve(conn, USER, BUILD, TOKEN, 1, '0.2')


def test_settlement_after_claim_expired_still_records_actual_charge():
    conn = Connection(reservation=reservation())
    conn.claim['live'] = False
    result = repository.settle(conn, RESERVATION, '0.04')
    assert not result['overrun']
    updates = [params for sql, params in conn.statements if 'UPDATE public.ranking_budget' in sql]
    assert len(updates) == 2 and updates[0][0] == Decimal('-0.06')
    assert not any('ranking_builds' in sql for sql, _ in conn.statements)
    assert 'SELECT user_id' in conn.statements[0][0]
    assert 'public.users' in conn.statements[1][0] and 'FOR SHARE' in conn.statements[1][0]
    assert 'ranking_control' in conn.statements[2][0]
    assert 'ranking_reservations' in conn.statements[3][0] and 'FOR UPDATE' in conn.statements[3][0]


def test_deleted_reservation_cannot_release_global_spend():
    conn = Connection()
    with pytest.raises(repository.RankingStoreError, match='reservation_missing'):
        repository.settle(conn, RESERVATION, '0')
    assert not any('UPDATE' in sql for sql, _ in conn.statements)


def test_settlement_overrun_is_recorded_and_disables_admission_without_rollback():
    conn = Connection(reservation=reservation())
    assert repository.settle(conn, RESERVATION, '0.2')['overrun']
    assert any('provider=false,serving=false' in sql for sql, _ in conn.statements)


def test_settlement_idempotency():
    conn = Connection(reservation=reservation(actual_usd=Decimal('0.04')))
    repository.settle(conn, RESERVATION, '0.04')
    assert not any('UPDATE public.' in sql for sql, _ in conn.statements)
    with pytest.raises(repository.RankingStoreError, match='settlement_conflict'):
        repository.settle(conn, RESERVATION, '0.05')


def test_publish_one_json_envelope_with_claim_compare_and_swap():
    conn = Connection()
    expiry = datetime.now(timezone.utc)+timedelta(minutes=1)
    assert repository.publish(conn, USER, BUILD, TOKEN, IDENTITY, {'ordered_ids': [USER]}, expiry)
    sql = next(sql for sql, _ in conn.statements if 'INSERT INTO public.ranking_results' in sql)
    assert 'ON CONFLICT(user_id) DO UPDATE' in sql
    assert 'expires_at>clock_timestamp() AND NOT published' in sql
    assert not any('DELETE' in sql for sql, _ in conn.statements)


def test_publish_different_identity_fails():
    with pytest.raises(repository.RankingStoreError, match='identity_changed'):
        repository.publish(Connection(), USER, BUILD, TOKEN, {'generation': 2}, {}, datetime.now(timezone.utc))


def test_publish_cannot_use_approved_but_disabled_control():
    conn = Connection()
    conn.state['serving'] = False
    with pytest.raises(repository.RankingStoreError, match='serving_disabled'):
        repository.publish(conn, USER, BUILD, TOKEN, IDENTITY, {}, datetime.now(timezone.utc))


def test_transactions_bound_lock_and_statement_waits():
    conn = Mock()
    conn.transaction.return_value = nullcontext()
    with repository._transaction(conn):
        pass
    assert [call.args[0] for call in conn.execute.call_args_list] == [
        "SET LOCAL statement_timeout = '2000ms'", "SET LOCAL lock_timeout = '100ms'"]


@pytest.mark.parametrize('lock', [False, True])
def test_control_can_hold_shared_configuration_fence_in_publication(lock):
    conn = Connection()
    assert repository.control(conn, lock=lock) == conn.state
    assert conn.statements[-1][0].endswith('FOR SHARE') is lock


def test_invalidate_and_release_never_refund_spend():
    conn = Connection()
    repository.invalidate(conn, USER)
    repository.release_claim(conn, USER, BUILD, TOKEN)
    assert all('ranking_budget' not in sql and 'ranking_reservations' not in sql for sql, _ in conn.statements)
    assert 'build_id=%s AND token=%s' in conn.statements[-1][0]


def test_pruning_bounded_and_retains_today_ambiguous_spend():
    conn = Connection()
    repository.prune(conn)
    deletes = [sql for sql, _ in conn.statements if sql.startswith('DELETE')]
    assert len(deletes) == 4
    assert all('LIMIT %s' in sql for sql in deletes)
    assert "interval '30 days'" in deletes[0]
    assert 'ranking_builds' in deletes[2] and 'ranking_results' in deletes[3]
