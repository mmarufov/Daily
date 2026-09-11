"""Small API-boundary checks; no product server or outbound work."""
import asyncio
from unittest.mock import Mock

import pytest
import tests._app_stubs  # noqa: F401
from app import main


@pytest.mark.parametrize('endpoint', ['build_feed', 'get_feed', 'refresh_feed'])
@pytest.mark.parametrize('limit', [0, -1, 101, 200, True])
def test_invalid_edition_size_is_client_error_before_pipeline(monkeypatch, endpoint, limit):
    monkeypatch.setattr(main, '_require_auth', lambda value: 'token')
    monkeypatch.setattr(main, '_get_user_id_from_token', lambda *args: 'user')
    schema = Mock()
    monkeypatch.setattr(main, '_ensure_tables', schema)
    with pytest.raises(main.HTTPException) as error:
        asyncio.run(getattr(main, endpoint)(Authorization='token', limit=limit, conn=None, event_expiry='1'))
    assert error.value.status_code == 422
    schema.assert_not_called()
