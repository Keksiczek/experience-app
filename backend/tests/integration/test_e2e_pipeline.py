"""End-to-end integration tests for the experience pipeline.

All tests run in mock mode (no live HTTP requests). The conftest.py
autouse fixture sets MOCK_MODE=true and provides an isolated InMemoryJobStore.

Test A  — happy path: Horní Slezsko, abandoned_industrial
Test C  — degradation: Kazakhstan, remote_landscape (too few places → graceful fail)
Test D  — GET /experiences listing: submit 2 jobs, verify both appear in summary list
"""

import asyncio

import pytest
from httpx import ASGITransport, AsyncClient

from app.main import app
from app.models.experience import JobStatus

_MAX_POLL_S = 10.0
_POLL_INTERVAL_S = 0.05


async def _wait_for_completion(client: AsyncClient, job_id: str) -> dict:
    """Poll GET /experiences/{job_id} until the job leaves pending/running."""
    iterations = int(_MAX_POLL_S / _POLL_INTERVAL_S)
    data: dict = {}
    for _ in range(iterations):
        await asyncio.sleep(_POLL_INTERVAL_S)
        resp = await client.get(f"/experiences/{job_id}")
        assert resp.status_code == 200, f"Unexpected status {resp.status_code}"
        data = resp.json()
        if data.get("job_status") not in (JobStatus.PENDING.value, JobStatus.RUNNING.value):
            return data
    return data


@pytest.mark.asyncio
async def test_happy_path_silesia():
    """Test A — pipeline succeeds with ≥3 valid stops for Horní Slezsko."""
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        # 1. Submit job
        resp = await client.post(
            "/experiences",
            json={"prompt": "opuštěné průmyslové oblasti v Horním Slezsku"},
        )
        assert resp.status_code == 202, f"Expected 202, got {resp.status_code}"
        body = resp.json()
        assert "job_id" in body
        assert body["status"] == "pending"
        job_id = body["job_id"]

        # 2. Poll until done
        data = await _wait_for_completion(client, job_id)

        # 3. Assert completion
        assert data["job_status"] in (
            JobStatus.COMPLETED.value,
            JobStatus.COMPLETED_WITH_WARNINGS.value,
        ), (
            f"Expected completed, got job_status={data['job_status']!r}  "
            f"error_code={data.get('error_code')!r}  "
            f"error_message={data.get('error_message')!r}"
        )

        stops = data["stops"]
        assert len(stops) >= 3, f"Expected ≥3 stops, got {len(stops)}"

        for stop in stops:
            assert stop["lat"] != 0.0, f"Stop {stop['id']} has zero lat"
            assert stop["lon"] != 0.0, f"Stop {stop['id']} has zero lon"
            assert stop["name"], f"Stop {stop['id']} has empty name"
            assert stop["why_here"], f"Stop {stop['id']} has empty why_here"
            assert stop["fallback_level"], f"Stop {stop['id']} missing fallback_level"

        metadata = data.get("generation_metadata") or {}
        assert isinstance(metadata.get("warnings", []), list), "warnings must be a list"


@pytest.mark.asyncio
async def test_degradation_kazakhstan():
    """Test C — pipeline handles Kazakhstan gracefully: either ≥2 stops or FAILED with error_code.

    The mock Overpass returns nothing for remote_landscape mode, so the pipeline
    is expected to fail with error_code='too_few_places' (or similar). The key
    invariant is: no unhandled exception (no HTTP 500).
    """
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        resp = await client.post(
            "/experiences",
            json={"prompt": "remote wilderness v Kazachstánu"},
        )
        assert resp.status_code == 202, f"Expected 202, got {resp.status_code}"
        job_id = resp.json()["job_id"]

        data = await _wait_for_completion(client, job_id)

        status = data["job_status"]

        if status == JobStatus.FAILED.value:
            error_code = data.get("error_code")
            assert error_code, (
                f"FAILED job must carry a meaningful error_code, got: {data!r}"
            )
        else:
            assert status in (
                JobStatus.COMPLETED.value,
                JobStatus.COMPLETED_WITH_WARNINGS.value,
            ), f"Unexpected job_status: {status!r}"
            assert len(data["stops"]) >= 2, (
                f"If pipeline succeeds for Kazakhstan it must have ≥2 stops, "
                f"got {len(data['stops'])}"
            )


@pytest.mark.asyncio
async def test_list_experiences():
    """Test D — GET /experiences returns ExperienceSummary for submitted jobs.

    Submits 2 jobs, waits for both to reach a terminal state, then asserts
    both appear in the listing with correct structure.
    """
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        # 1. Submit 2 jobs (same mock data, different prompts are fine)
        prompts = [
            "opuštěné průmyslové oblasti v Horním Slezsku",
            "průmyslové ruiny Slezsko",
        ]
        job_ids: list[str] = []
        for prompt in prompts:
            resp = await client.post("/experiences", json={"prompt": prompt})
            assert resp.status_code == 202, f"Expected 202, got {resp.status_code}"
            job_ids.append(resp.json()["job_id"])

        # 2. Wait for both to reach a terminal state
        for job_id in job_ids:
            await _wait_for_completion(client, job_id)

        # 3. GET /experiences listing
        resp = await client.get("/experiences?limit=10")
        assert resp.status_code == 200, f"Expected 200, got {resp.status_code}"
        items = resp.json()

        assert isinstance(items, list), "Response must be a list"
        assert len(items) >= 2, f"Expected ≥2 items, got {len(items)}"

        # Both submitted jobs must appear in the listing
        listed_ids = {item["job_id"] for item in items}
        for jid in job_ids:
            assert jid in listed_ids, f"Job {jid!r} missing from listing"

        # Every summary must have the required fields with correct types
        valid_statuses = {s.value for s in JobStatus}
        for item in items:
            assert item["job_id"], "job_id must be non-empty"
            assert item["job_status"] in valid_statuses, (
                f"Invalid job_status: {item['job_status']!r}"
            )
            assert isinstance(item["prompt"], str) and item["prompt"], "prompt must be non-empty str"
            assert isinstance(item["stop_count"], int), "stop_count must be int"
            assert isinstance(item["quality_flags"], list), "quality_flags must be list"
