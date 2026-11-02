"""Provider contracts, secret handling and source-bound approval without live calls."""

import asyncio
import io
import json
import stat
import urllib.error
from datetime import date

import pytest
from ads_optimizer.ai import nvidia
from ads_optimizer.ai.service import ExplanationInput, explain, preview
from ads_optimizer.api import app
from ads_optimizer.domain import DomainError
from ads_optimizer.optimization.contracts import PlanConfig
from ads_optimizer.optimization.service import create_plan
from httpx import ASGITransport, AsyncClient
from test_optimization import saved_model

KEY = "nvapi-" + "synthetic-test-only-key" * 2


@pytest.fixture(autouse=True)
def no_real_provider(monkeypatch):
    monkeypatch.delenv("NVIDIA_API_KEY", raising=False)
    nvidia._verification.clear()

    def blocked(*args, **kwargs):
        pytest.fail("Tests must never contact NVIDIA")

    monkeypatch.setattr(nvidia.urllib.request, "build_opener", blocked)


def request(method, path, body=None):
    async def run():
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            return await client.request(method, "/api/v1/ai" + path, json=body)

    return asyncio.run(run())


def source(seed=46):
    async def run():
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            result = await client.post(
                "/api/v1/datasets/generate",
                json={
                    "name": "DO NOT SEND: customer@example.com",
                    "rows": 1000,
                    "seed": seed,
                },
            )
            assert result.status_code == 201
            return result.json()

    return asyncio.run(run())


def provider(
    monkeypatch,
    *,
    text="This simulated report describes observed performance.",
    error=None,
    raw=None,
):
    requests = []

    class Reply(io.BytesIO):
        pass

    class Opener:
        def open(self, req, timeout):
            requests.append((req, timeout))
            if error:
                raise error
            body = (
                raw
                if raw is not None
                else json.dumps(
                    {
                        "choices": [
                            {
                                "message": {
                                    "content": text,
                                    "reasoning_content": "PRIVATE REASONING NEVER DISPLAYED",
                                }
                            }
                        ]
                    }
                ).encode()
            )
            return Reply(body)

    monkeypatch.setattr(nvidia.urllib.request, "build_opener", lambda *args: Opener())
    return requests


def test_private_key_lifecycle_and_truthful_status(isolated_repository):
    repo = isolated_repository
    assert not request("GET", "/status").json()["configured"]
    result = request("PUT", "/key", {"api_key": KEY})
    assert result.status_code == 200
    assert result.json()["configured"] and not result.json()["verified"]
    assert KEY not in result.text and KEY not in request("GET", "/status").text
    assert stat.S_IMODE(nvidia.key_path(repo).stat().st_mode) == 0o600
    assert stat.S_IMODE(nvidia.key_path(repo).parent.stat().st_mode) == 0o700
    assert nvidia.key_path(repo).read_text() == KEY
    assert request("DELETE", "/key").json()["key_source"] == "missing"
    assert not nvidia.key_path(repo).exists()


def test_key_validation_and_environment_management(isolated_repository, monkeypatch):
    invalid = "private-invalid-secret"
    result = request("PUT", "/key", {"api_key": invalid})
    assert result.status_code == 422 and invalid not in result.text
    result = request("PUT", "/key", {"api_key": {"secret": KEY}})
    assert result.status_code == 422 and KEY not in result.text
    monkeypatch.setenv("NVIDIA_API_KEY", KEY)
    assert request("GET", "/status").json()["key_source"] == "environment"
    assert request("PUT", "/key", {"api_key": KEY}).status_code == 422
    assert request("DELETE", "/key").status_code == 422
    assert not nvidia.key_path(isolated_repository).exists()


def test_connection_test_is_explicit_bounded_and_never_returns_reasoning(
    isolated_repository, monkeypatch
):
    request("PUT", "/key", {"api_key": KEY})
    calls = provider(monkeypatch)
    result = request("POST", "/test", {})
    assert result.status_code == 200 and result.json()["verified"]
    req, timeout = calls[0]
    assert req.full_url == nvidia.ENDPOINT and timeout == 30
    assert req.headers["Authorization"] == "Bearer " + KEY
    body = json.loads(req.data)
    assert body["model"] == nvidia.MODEL and body["max_tokens"] == 900
    assert body["stream"] is False and body["chat_template_kwargs"]["enable_thinking"] is False
    assert "No report data" in body["messages"][1]["content"]
    assert KEY not in result.text and "PRIVATE REASONING" not in result.text
    assert request("GET", "/status").json()["checked_at"]
    assert len(calls) == 1  # reading status never contacts the provider


@pytest.mark.parametrize("code,expected", [(401, 422), (403, 422), (429, 429), (500, 502)])
def test_provider_failures_are_sanitized_and_not_connected(
    isolated_repository, monkeypatch, code, expected
):
    request("PUT", "/key", {"api_key": KEY})
    provider(
        monkeypatch,
        error=urllib.error.HTTPError(nvidia.ENDPOINT, code, KEY, {}, io.BytesIO(KEY.encode())),
    )
    result = request("POST", "/test", {})
    assert result.status_code == expected and KEY not in result.text
    state = request("GET", "/status")
    assert not state.json()["verified"] and KEY not in state.text
    assert not nvidia._call_lock.locked()


@pytest.mark.parametrize("raw", [b"not json", b"{}", b"x" * (nvidia.MAX_RESPONSE + 1)])
def test_invalid_or_oversized_provider_response_is_recoverable(
    isolated_repository, monkeypatch, raw
):
    request("PUT", "/key", {"api_key": KEY})
    provider(monkeypatch, raw=raw)
    assert request("POST", "/test", {}).status_code == 502
    provider(monkeypatch)
    assert request("POST", "/test", {}).status_code == 200


def test_timeout_redirect_and_concurrent_request_are_bounded(isolated_repository, monkeypatch):
    request("PUT", "/key", {"api_key": KEY})
    provider(monkeypatch, error=TimeoutError(KEY))
    result = request("POST", "/test", {})
    assert result.status_code == 504 and KEY not in result.text
    with pytest.raises(DomainError):
        nvidia.NoRedirect().redirect_request(None, None, 302, "", {}, "https://other.example")
    nvidia._call_lock.acquire()
    try:
        assert request("POST", "/test", {}).status_code == 429
    finally:
        nvidia._call_lock.release()


def test_allowlisted_summary_excludes_names_rows_and_secrets(isolated_repository):
    source()
    report = preview(isolated_repository, "performance")
    encoded = json.dumps(report["summary"])
    assert "customer@example.com" not in encoded and "Campaign 001" not in encoded
    assert "campaign_id" not in encoded and "filename" not in encoded
    assert report["summary"]["is_synthetic"] and report["local_reference"]["totals"]["rows"] == 1000
    assert len(report["summary"]["platform_observations"]) == 5
    assert all(report["summary"]["synthetic_components"].values())
    assert not any(character.isdigit() for character in encoded)
    assert request("GET", "/summary?kind=model").status_code == 422
    assert request("GET", "/summary?kind=budget").status_code == 422


def test_source_bound_approval_blocks_changed_selection_before_network(isolated_repository):
    source()
    snapshot = preview(isolated_repository, "performance")
    body = {"kind": "performance", "summary_sha256": snapshot["summary_sha256"]}
    assert request("POST", "/explain", body).status_code == 422
    isolated_repository.select(None)
    assert request("POST", "/explain", {**body, "approved": True}).status_code == 422
    source(seed=47)
    result = request("POST", "/explain", {**body, "approved": True})
    assert result.status_code == 409


def test_explanation_contains_only_final_text_and_rejects_numeric_claims(
    isolated_repository, monkeypatch
):
    source()
    request("PUT", "/key", {"api_key": KEY})
    snapshot = preview(isolated_repository, "performance")
    body = ExplanationInput(
        kind="performance", summary_sha256=snapshot["summary_sha256"], approved=True
    )
    calls = provider(monkeypatch)
    result = explain(isolated_repository, body)
    assert result["is_synthetic"] and result["summary_sha256"] == snapshot["summary_sha256"]
    assert "PRIVATE REASONING" not in json.dumps(result)
    sent = json.loads(calls[0][0].data)["messages"][1]["content"].split("\n", 1)[1]
    assert json.loads(sent) == snapshot["summary"]
    assert "local_reference" not in sent and "date_range" not in sent
    provider(monkeypatch, text="Revenue will improve 99%.")
    with pytest.raises(DomainError, match="numeric claims"):
        explain(isolated_repository, body)
    for unsafe in [KEY, "<think>internal</think>"]:
        provider(monkeypatch, text=unsafe)
        assert request("POST", "/explain", body.model_dump()).status_code == 502


def test_actual_model_and_plan_summaries_preserve_forecast_gates(isolated_repository):
    repo = isolated_repository
    data, _, model_id = saved_model(repo)
    report = preview(repo, "model")
    assert report["summary"]["algorithm"] == "XGBoost"
    assert report["local_reference"]["holdout"]["model"]["rows"] > 0
    assert report["summary"]["holdout_error_relative_to_baseline"] in {"lower", "higher", "equal"}
    create_plan(
        repo,
        PlanConfig(
            dataset_id=data.id,
            budget=500,
            as_of_date=date(2026, 10, 29),
            start_date=date(2026, 10, 30),
        ),
    )
    report = preview(repo, "budget")
    assert report["local_reference"]["estimated_revenue"] is None
    assert report["local_reference"]["estimated_roas"] is None
    assert report["local_reference"]["forecast_status"] == "unavailable"
    assert report["summary"]["forecast_available"] is False
    assert "model_id" not in json.dumps(report["summary"])
