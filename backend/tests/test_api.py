import asyncio

from ads_optimizer.api import app
from httpx import ASGITransport, AsyncClient


def request(method, path):
    async def run():
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            return await client.request(method, path)

    return asyncio.run(run())


def test_first_run_is_empty_and_never_claims_training_or_connections():
    response = request("GET", "/api/v1/workspace")
    assert response.status_code == 200
    state = response.json()
    assert state["dataset_count"] == 0
    assert state["selected_dataset_id"] is None
    assert state["revenue_source"] is None
    assert state["model_status"] == "not_trained"
    assert state["connected_providers"] == []
    assert {c["id"] for c in state["capabilities"] if c["available"]} == {
        "synthetic_generation",
        "campaign_import",
        "benchmarking",
        "commerce",
    }


def test_health_and_openapi_contract():
    assert request("GET", "/api/v1/health").json()["status"] == "ok"
    assert "/api/v1/workspace" in request("GET", "/openapi.json").json()["paths"]


def test_unimplemented_actions_do_not_pretend_to_work():
    for path in ["train", "optimize", "connections"]:
        assert request("POST", f"/api/v1/{path}").status_code == 404
