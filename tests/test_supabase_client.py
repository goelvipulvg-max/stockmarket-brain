import pytest
from unittest.mock import patch, MagicMock

pytestmark = pytest.mark.usefixtures("clean_supabase_module")


def test_get_client_raises_if_url_empty(monkeypatch):
    monkeypatch.setenv("SUPABASE_URL", "")
    monkeypatch.setenv("SUPABASE_SERVICE_ROLE_KEY", "test-key")
    from utils.supabase_client import get_client
    with pytest.raises(ValueError, match="SUPABASE_URL"):
        get_client()


def test_get_client_raises_if_key_empty(monkeypatch):
    monkeypatch.setenv("SUPABASE_URL", "https://test.supabase.co")
    monkeypatch.setenv("SUPABASE_SERVICE_ROLE_KEY", "")
    from utils.supabase_client import get_client
    with pytest.raises(ValueError, match="SUPABASE_SERVICE_ROLE_KEY"):
        get_client()


def test_get_client_calls_create_client(monkeypatch):
    monkeypatch.setenv("SUPABASE_URL", "https://test.supabase.co")
    monkeypatch.setenv("SUPABASE_SERVICE_ROLE_KEY", "test-key")
    mock_client = MagicMock()
    with patch("utils.supabase_client.create_client", return_value=mock_client) as m:
        from utils.supabase_client import get_client
        result = get_client()
    assert result is mock_client
    m.assert_called_once_with("https://test.supabase.co", "test-key")
