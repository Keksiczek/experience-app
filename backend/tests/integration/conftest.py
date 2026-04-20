"""Configure integration tests to run in mock mode with an isolated in-memory job store.

Every test gets:
- settings.mock_mode = True  →  _execute_pipeline uses mock providers, no live HTTP
- experience_job._store = fresh InMemoryJobStore()  →  test isolation, no DB files
"""

import pytest

from app.core.config import settings as _settings
from app.jobs import experience_job
from app.jobs.job_store import InMemoryJobStore


@pytest.fixture(autouse=True)
def _use_mock_mode():
    orig_mock = _settings.mock_mode
    orig_store = experience_job._store

    object.__setattr__(_settings, "mock_mode", True)
    experience_job._store = InMemoryJobStore()

    yield

    object.__setattr__(_settings, "mock_mode", orig_mock)
    experience_job._store = orig_store
