"""BC-3: optional login-free public demo mode for the hosted deployment.

ADS_PUBLIC_DEMO=1 (user-requested 2026-11-02) removes Basic auth but keeps the
origin/CSRF guard and request limits, and refuses destructive or secret-changing
writes so anonymous visitors cannot delete the shared workspace or set API keys.
Without the flag, hosted mode still requires the owner password (unchanged).
"""

from ads_optimizer.api import app
from fastapi.testclient import TestClient

ORIGIN = {"origin": "http://127.0.0.1:3000"}


def hosted(monkeypatch, tmp_path, public):
    monkeypatch.setenv("ADS_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("ADS_HOSTED", "1")
    monkeypatch.delenv("ADS_ACCESS_PASSWORD", raising=False)
    if public:
        monkeypatch.setenv("ADS_PUBLIC_DEMO", "1")
    else:
        monkeypatch.delenv("ADS_PUBLIC_DEMO", raising=False)
    return TestClient(app)


def test_hosted_without_flag_still_requires_configured_auth(monkeypatch, tmp_path):
    client = hosted(monkeypatch, tmp_path, public=False)
    assert client.get("/api/v1/workspace").status_code == 503


def test_public_demo_allows_reads_and_safe_writes(monkeypatch, tmp_path):
    client = hosted(monkeypatch, tmp_path, public=True)
    assert client.get("/api/v1/workspace").status_code == 200
    created = client.post(
        "/api/v1/datasets/generate", json={"rows": 100, "seed": 1}, headers=ORIGIN
    )
    assert created.status_code == 201
    assert client.get("/api/v1/workspace").json()["dataset_count"] == 1


def test_public_demo_refuses_deletes_and_key_changes(monkeypatch, tmp_path):
    client = hosted(monkeypatch, tmp_path, public=True)
    dataset = client.post(
        "/api/v1/datasets/generate", json={"rows": 100, "seed": 1}, headers=ORIGIN
    ).json()
    deleted = client.delete(f"/api/v1/datasets/{dataset['id']}", headers=ORIGIN)
    assert deleted.status_code == 403 and "public demo" in deleted.json()["detail"]
    key = client.put("/api/v1/ai/key", json={"api_key": "nvapi-" + "x" * 30}, headers=ORIGIN)
    assert key.status_code == 403
    assert client.get("/api/v1/workspace").json()["dataset_count"] == 1


def test_public_demo_keeps_cross_site_write_guard(monkeypatch, tmp_path):
    client = hosted(monkeypatch, tmp_path, public=True)
    blocked = client.post(
        "/api/v1/datasets/generate", json={}, headers={"origin": "https://evil.example"}
    )
    assert blocked.status_code == 403
