"""Pure/control-path checks; these do not substitute for hosted SQL race tests."""
from contextlib import nullcontext
from copy import deepcopy
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from app.services import event_repository as repo


@pytest.mark.parametrize('value', [True, False, None, 'not-money', 'NaN', 'Infinity', -1, '100000000', '1e999'])
def test_invalid_budget_rejected_before_database(value):
    with pytest.raises(ValueError, match='monetary'):
        repo._money(value)


def test_money_rounds_up_not_down():
    assert repo._money('0.000000001') == Decimal('0.00000001')


@pytest.mark.parametrize('request_hash', [None, False, 'g' * 64, 'A' * 64, '1' * 63])
def test_reservation_requires_canonical_request_hash_before_database(request_hash):
    with pytest.raises(ValueError, match='priced request'):
        repo.reserve(None, {}, '0.001', request_hash)


def test_boolean_recipe_version_not_integer_one():
    definition = deepcopy(repo.DEFAULT_RECIPE)
    definition['version'] = True
    with pytest.raises(ValueError, match='recipe definition'):
        repo.register_recipe(None, definition)


@pytest.mark.parametrize('final_update', [None, {'id': 1, 'state': 'running', 'attempts': 2, 'lease_token': 'fresh'}])
def test_claim_returns_only_final_update_not_stale_discovery(final_update):
    # Clock can pass a deadline between candidate selection and final update.
    conn = Mock()
    conn.transaction.side_effect = nullcontext
    conn.execute.side_effect = [
        SimpleNamespace(fetchall=lambda: [{'id': 1, 'attempts': 1, 'definition': {'version': 1}}]),
        SimpleNamespace(fetchone=lambda: final_update),
    ]
    result = repo.claim(conn)
    assert result == ([] if final_update is None else [{**final_update, 'definition': {'version': 1}}])
    assert 'RETURNING *' in conn.execute.call_args.args[0]
