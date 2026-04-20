"""Configure integration tests to run in mock mode with an isolated in-memory job store.

Uses monkeypatch.setenv + importlib.reload so that Pydantic validation runs
normally when settings are re-created — no bypassing of __setattr__.

Every test gets:
- MOCK_MODE=true in env → settings.mock_mode=True → mock providers used
- experience_job.settings patched to the freshly-reloaded settings object
- experience_job._store = fresh InMemoryJobStore() → test isolation, no DB files
"""

import importlib

import pytest

import app.core.config as config_module
import app.jobs.experience_job as ej
from app.jobs.job_store import InMemoryJobStore


@pytest.fixture(autouse=True)
def use_mock_mode(monkeypatch):
    # Set env vars before reloading so Pydantic validation picks them up.
    monkeypatch.setenv("MOCK_MODE", "true")
    monkeypatch.setenv("JOB_STORE_PATH", ":memory:")

    # Reload creates a fresh Settings() that reads the patched env vars.
    importlib.reload(config_module)

    # Patch experience_job's module-level settings reference to the new object
    # so _execute_pipeline sees mock_mode=True at runtime.
    monkeypatch.setattr(ej, "settings", config_module.settings)

    # Fresh in-memory store per test — monkeypatch restores _store=None on teardown.
    monkeypatch.setattr(ej, "_store", InMemoryJobStore())
