"""Test configuration: force deterministic (no-LLM) mode so tests are fast and offline."""
import os
import pytest

# Remove the live API key before any test module is imported so the rate-limiter
# and all llm_available() checks return False throughout the test session.
os.environ.pop("OPENAI_API_KEY", None)


@pytest.fixture(autouse=True)
def _no_live_llm(monkeypatch):
    """config.py reloads .env (override=True) when the package is imported, which restores the key.
    Remove it per test so nothing calls the live provider."""
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
