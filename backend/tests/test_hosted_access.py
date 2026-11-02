"""Hosted single-owner boundary, including direct backend access."""

import asyncio
import base64

from ads_optimizer.api import app
from httpx import ASGITransport, AsyncClient


def call(path="/api/v1/workspace", method="GET", headers=None):
    async def run():
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            return await client.request(method, path, headers=headers)

    return asyncio.run(run())


def test_hosted_fails_closed_and_health_remains_available(monkeypatch):
    monkeypatch.setenv("ADS_HOSTED", "1")
    monkeypatch.delenv("ADS_ACCESS_PASSWORD", raising=False)
    assert call().status_code == 503
    assert call("/api/v1/health").status_code == 200


def test_hosted_auth_protects_reads_writes_and_docs(monkeypatch):
    monkeypatch.setenv("ADS_HOSTED", "1")
    password = "fictional-test-password-32-characters-long"
    monkeypatch.setenv("ADS_ACCESS_PASSWORD", password)
    monkeypatch.setenv("ADS_ALLOWED_ORIGINS", "https://black-stone-8p52.vercel.app")
    for path in ["/api/v1/workspace", "/docs", "/openapi.json"]:
        assert call(path).status_code == 401
    assert call(method="PUT").status_code == 401
    auth = "Basic " + base64.b64encode(("owner:" + password).encode()).decode()
    headers = {"Authorization": auth}
    assert call(headers=headers).status_code == 200
    headers["Origin"] = "https://untrusted.example"
    assert call(method="PUT", headers=headers).status_code == 403
    headers["Origin"] = "https://black-stone-8p52.vercel.app"
    assert call(method="PUT", headers=headers).status_code == 405
    headers["sec-fetch-site"] = "cross-site"
    assert call(method="PUT", headers=headers).status_code == 403
