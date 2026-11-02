"""Immutable advisory reports, stored separately from source data and model artifacts."""

import json
import sqlite3

from ads_optimizer.domain import DomainError


class PlanStore:
    def __init__(self, data_root):
        self.root = data_root / "optimization"
        self.root.mkdir(parents=True, exist_ok=True)
        with self.connect() as conn:
            conn.execute(
                "CREATE TABLE IF NOT EXISTS plans "
                "(id TEXT PRIMARY KEY, dataset_id TEXT NOT NULL, report TEXT NOT NULL)"
            )

    def connect(self):
        return sqlite3.connect(self.root / "plans.sqlite", timeout=30)

    def save(self, report):
        with self.connect() as conn:
            conn.execute(
                "INSERT INTO plans VALUES (?,?,?)",
                (report["id"], report["dataset"]["id"], json.dumps(report, allow_nan=False)),
            )
        return report

    def get(self, plan_id):
        with self.connect() as conn:
            row = conn.execute("SELECT report FROM plans WHERE id=?", (plan_id,)).fetchone()
        if not row:
            raise DomainError("This saved budget plan is no longer available.", 404)
        return json.loads(row[0])

    def list(self, dataset_id):
        with self.connect() as conn:
            rows = conn.execute(
                "SELECT report FROM plans WHERE dataset_id=? ORDER BY rowid DESC LIMIT 50",
                (dataset_id,),
            ).fetchall()
        return [summary(json.loads(row[0])) for row in rows]

    def delete_for_dataset(self, dataset_id):
        with self.connect() as conn:
            conn.execute("DELETE FROM plans WHERE dataset_id=?", (dataset_id,))


def summary(report):
    return {
        key: report[key]
        for key in ["id", "created_at", "config", "method_label", "totals", "is_synthetic"]
    }
