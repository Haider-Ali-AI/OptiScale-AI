"""Truthful first-run capability state, independent of HTTP or React state."""

from ads_optimizer.data.repository import Repository
from ads_optimizer.hosting.workspace import serverless
from ads_optimizer.ml.store import ModelStore
from ads_optimizer.schemas import Capability, WorkspaceState


def get_workspace_state(repo: Repository) -> WorkspaceState:
    datasets = repo.list()
    selected = repo.selected()
    models = [
        j
        for j in ModelStore(repo.root).jobs()
        if selected and j["config"]["dataset_id"] == selected.id and j["status"] == "succeeded"
    ]
    return WorkspaceState(
        hosting_notice=(
            "Hosted single-owner workspace · persistent Postgres storage · "
            "64 MiB workspace limit · 4 MiB uploads. "
            "Training runs within the request (up to 10,000 rows); keep the page open. "
            "Big Data experiments run in the local app."
        )
        if serverless()
        else None,
        datasets=datasets,
        selected_dataset=selected,
        dataset_count=len(datasets),
        selected_dataset_id=selected.id if selected else None,
        revenue_source=selected.revenue_source if selected else None,
        model_status=(
            "validated"
            if any(j["result"]["acceptance"]["eligible"] for j in models)
            else "trained"
            if models
            else "not_trained"
        ),
        capabilities=[
            Capability(
                id="synthetic_generation",
                phase=1,
                available=True,
                reason="Generate up to 10,000 deterministic synthetic campaign rows.",
            ),
            Capability(
                id="campaign_import",
                phase=1,
                available=True,
                reason="Preview, map, validate and save authorized campaign CSVs.",
            ),
            Capability(
                id="analytics",
                phase=1,
                available=selected is not None,
                reason="Review weighted campaign metrics for a selected dataset.",
            ),
            Capability(
                id="benchmarking",
                phase=2,
                available=not serverless(),
                reason="Run measured 10K–10M synthetic experiments in Big Data Lab; "
                "optional Spark availability is checked locally.",
            ),
            Capability(
                id="training",
                phase=3,
                available=selected is not None,
                reason="Train and evaluate a local revenue model on the selected dataset.",
            ),
            Capability(
                id="optimization",
                phase=4,
                available=bool(selected and selected.data_ready_for_revenue),
                reason="Plan advisory budgets with an accepted model or an explicit historical "
                "heuristic; each request checks history, definitions and spending support.",
            ),
            Capability(
                id="commerce",
                phase=6,
                available=True,
                reason=(
                    "Import separate commerce CSVs, reconcile evidenced sales and screen "
                    "advisory contribution-profit plans."
                ),
            ),
            Capability(
                id="connections",
                phase=7,
                reason="Live read-only connections are future work; no accounts are connected.",
            ),
        ],
    )
