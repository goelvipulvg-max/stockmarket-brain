import sys
import pytest
from unittest.mock import patch


def pytest_configure(config):
    """Register custom markers so -m integration filters cleanly (no warnings)."""
    config.addinivalue_line(
        "markers",
        "integration: hits the real DB / external services; run with -m integration",
    )


@pytest.fixture
def clean_supabase_module():
    """Remove supabase_client from sys.modules and mock load_dotenv before each test.

    This ensures that:
    1. Module is freshly imported each test (clean slate)
    2. load_dotenv doesn't override monkeypatched env vars
    3. Tests can isolate environment changes
    """
    if 'utils.supabase_client' in sys.modules:
        del sys.modules['utils.supabase_client']

    # Mock load_dotenv so it doesn't override monkeypatched env vars at import time
    with patch('dotenv.load_dotenv'):
        yield

    if 'utils.supabase_client' in sys.modules:
        del sys.modules['utils.supabase_client']
