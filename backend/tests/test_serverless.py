"""Cold-invocation persistence and fail-closed hosting boundaries."""

import asyncio
import base64
import io
import zipfile
from pathlib import Path

import psycopg
import pytest
from ads_optimizer.api import app
from ads_optimizer.domain import DomainError
from ads_optimizer.hosting.workspace import pack, request_root, unpack
from httpx import ASGITransport, AsyncClient

PASSWORD = "fictional-hosting-test-password-at-least-32"
AUTH = {"Authorization": "Basic " + base64.b64encode(("owner:" + PASSWORD).encode()).decode()}


def call(method, path, **kwargs):
    async def run():
        async with AsyncClient(transport=ASGITransport(app=app), base_url="https://test") as client:
            return await client.request(method, path, headers=AUTH, **kwargs)

    return asyncio.run(run())


class Database:
    """Transaction double: UPDATE publishes only on successful context exit."""

    payload = b""
    fail_update = False

    async def connect(self, *args, **kwargs):
        return Connection(self)


class Connection:
    def __init__(self, database):
        self.database = database
        self.payload = database.payload

    async def __aenter__(self):
        return self

    async def __aexit__(self, kind, value, trace):
        if kind is None:
            self.database.payload = self.payload

    def cursor(self):
        return self

    async def execute(self, sql, parameters=None):
        if sql.startswith("UPDATE"):
            if self.database.fail_update:
                raise psycopg.OperationalError("fictional storage failure")
            self.payload = parameters[0]

    async def fetchone(self):
        return (self.payload,)


@pytest.fixture
def hosted(monkeypatch):
    monkeypatch.setenv("ADS_SERVERLESS", "1")
    monkeypatch.setenv("ADS_ACCESS_PASSWORD", PASSWORD)
    monkeypatch.setenv("ADS_DATABASE_URL", "postgresql://fictional.invalid/test")
    database = Database()
    monkeypatch.setattr(psycopg.AsyncConnection, "connect", database.connect)
    app.dependency_overrides.clear()
    return database


def test_cold_invocations_restore_campaigns_and_export(hosted):
    response = call("POST", "/api/v1/datasets/generate", json={"rows": 100})
    assert response.status_code == 201
    assert request_root.get() is None
    assert hosted.payload
    state = call("GET", "/api/v1/workspace").json()
    assert state["dataset_count"] == 1
    assert state["hosting_notice"]
    assert not next(c for c in state["capabilities"] if c["id"] == "benchmarking")["available"]
    selected = state["selected_dataset_id"]
    export = call("GET", f"/api/v1/datasets/{selected}/export")
    assert export.status_code == 200 and "campaign" in export.text
    # Every request has a newly-created scratch directory, including streaming reads.
    result = call("GET", "/api/v1/workspace")
    assert result.json()["selected_dataset_id"] == selected


def test_storage_failure_never_returns_success_or_publishes_partial_state(hosted):
    hosted.fail_update = True
    response = call("POST", "/api/v1/datasets/generate", json={"rows": 100})
    assert response.status_code == 503
    assert "fictional storage failure" not in response.text
    assert hosted.payload == b""
    assert request_root.get() is None
    hosted.fail_update = False
    assert call("GET", "/api/v1/workspace").json()["dataset_count"] == 0


def test_failed_action_does_not_change_saved_workspace(hosted):
    call("POST", "/api/v1/datasets/generate", json={"rows": 100})
    original = hosted.payload
    assert (
        call("PUT", "/api/v1/workspace/dataset", json={"dataset_id": "missing"}).status_code == 404
    )
    assert hosted.payload == original


def test_missing_storage_fails_closed_but_health_works(hosted, monkeypatch):
    monkeypatch.delenv("ADS_DATABASE_URL")
    monkeypatch.delenv("POSTGRES_URL", raising=False)
    monkeypatch.delenv("DATABASE_URL", raising=False)
    assert call("GET", "/api/v1/workspace").status_code == 503
    assert call("GET", "/api/v1/health").status_code == 200


def test_hosted_lab_cannot_start_detached_worker(hosted, monkeypatch):
    import subprocess

    monkeypatch.setattr(subprocess, "Popen", lambda *a, **k: pytest.fail("detached worker"))
    response = call("POST", "/api/v1/lab/jobs", json={})
    assert response.status_code == 409
    assert "local app" in response.text


def test_archive_round_trip_and_traversal_rejection(tmp_path):
    root = tmp_path / "original"
    root.mkdir()
    (root / "catalog.sqlite").write_bytes(b"fictional-state")
    restored = tmp_path / "restored"
    restored.mkdir()
    unpack(pack(root), restored)
    assert (restored / "catalog.sqlite").read_bytes() == b"fictional-state"
    unsafe = io.BytesIO()
    with zipfile.ZipFile(unsafe, "w") as archive:
        archive.writestr("../escape", "unsafe")
    with pytest.raises(DomainError, match="restored"):
        unpack(unsafe.getvalue(), restored)
    assert not (tmp_path / "escape").exists()
    with pytest.raises(DomainError, match="restored"):
        unpack(b"corrupted", restored)


def test_workspace_size_limit_and_symlinks(tmp_path, monkeypatch):
    import ads_optimizer.hosting.workspace as storage

    (tmp_path / "data").write_bytes(b"12345")
    monkeypatch.setattr(storage, "MAX_STATE_BYTES", 4)
    with pytest.raises(DomainError, match="exceeds"):
        pack(tmp_path)
    (tmp_path / "link").symlink_to(Path("data"))
    with pytest.raises(DomainError, match="links"):
        pack(tmp_path)


def test_hosted_training_finishes_before_response_and_survives_restore(hosted, monkeypatch):
    import subprocess

    monkeypatch.setattr(subprocess, "Popen", lambda *a, **k: pytest.fail("detached worker"))
    dataset = call("POST", "/api/v1/datasets/generate", json={"rows": 1000}).json()
    response = call(
        "POST", "/api/v1/ml/jobs", json={"dataset_id": dataset["id"], "as_of_date": "2026-04-15"}
    )
    assert response.status_code == 202
    job = response.json()
    assert job["status"] == "succeeded", job["message"]
    restored = call("GET", "/api/v1/ml/jobs/" + job["id"]).json()
    assert restored["status"] == "succeeded"
    assert restored["result"]["algorithm"] == "XGBoost"
