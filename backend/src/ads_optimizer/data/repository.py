"""Single-user SQLite catalog + isolated Parquet datasets, with atomic catalog writes."""

import hashlib
import json
import os
import shutil
import sqlite3
import uuid
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path

import pandas as pd

from ads_optimizer.data.validation import grain_frame
from ads_optimizer.domain import DIMENSIONS, METRICS, DatasetManifest, DomainError


def frame_fingerprint(frame: pd.DataFrame) -> str:
    columns = sorted(frame.columns)
    ordered = frame[columns].sort_values(columns, kind="stable").reset_index(drop=True)
    return hashlib.sha256(ordered.to_json(orient="split", double_precision=10).encode()).hexdigest()


def coverage(frame: pd.DataFrame) -> dict[str, float]:
    return {
        key: float((frame[key].notna() & (frame[key] != "unknown")).mean())
        for key in [*METRICS, "age", "gender", "city", "device"]
    }


class Repository:
    def __init__(self, root: Path):
        self.root = root
        self.root.mkdir(parents=True, exist_ok=True)
        (self.root / "datasets").mkdir(exist_ok=True)
        (self.root / "staging").mkdir(exist_ok=True)
        with self.connect() as conn:
            conn.execute(
                "CREATE TABLE IF NOT EXISTS datasets (id TEXT PRIMARY KEY, "
                "fingerprint TEXT UNIQUE, manifest TEXT NOT NULL)"
            )
            conn.execute("CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT)")

    def connect(self):
        conn = sqlite3.connect(self.root / "catalog.sqlite", timeout=30)
        conn.execute("PRAGMA foreign_keys=ON")
        return conn

    def list(self) -> list[DatasetManifest]:
        with self.connect() as conn:
            rows = conn.execute("SELECT manifest FROM datasets ORDER BY rowid DESC").fetchall()
        return [DatasetManifest.model_validate_json(row[0]) for row in rows]

    def get(self, dataset_id: str) -> DatasetManifest:
        # Only IDs from the local catalog may become filesystem paths.
        with self.connect() as conn:
            row = conn.execute("SELECT manifest FROM datasets WHERE id=?", (dataset_id,)).fetchone()
        if row is None:
            raise DomainError("That dataset is no longer available. Choose another dataset.", 404)
        return DatasetManifest.model_validate_json(row[0])

    def selected(self) -> DatasetManifest | None:
        with self.connect() as conn:
            row = conn.execute("SELECT value FROM settings WHERE key='selected_dataset'").fetchone()
        return self.get(row[0]) if row and row[0] else None

    def select(self, dataset_id: str | None):
        if dataset_id is not None:
            self.get(dataset_id)
        with self.connect() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO settings VALUES ('selected_dataset', ?)", (dataset_id,)
            )

    def read(self, dataset_id: str) -> pd.DataFrame:
        manifest = self.get(dataset_id)
        return pd.read_parquet(self.root / "datasets" / manifest.id / "campaigns.parquet")

    def save(
        self, frame: pd.DataFrame, metadata: dict, truth: dict | None = None
    ) -> DatasetManifest:
        fingerprint = frame_fingerprint(frame)
        with self.connect() as conn:
            existing = conn.execute(
                "SELECT id FROM datasets WHERE fingerprint=?", (fingerprint,)
            ).fetchone()
        if existing:
            raise DomainError(
                "This normalized dataset is already saved. Select it from Saved datasets.", 409
            )
        metadata = {**metadata, "warnings": list(metadata.get("warnings", []))}
        if metadata["source"] != "synthetic_generator":
            keys = pd.MultiIndex.from_frame(grain_frame(frame))
            for prior in self.list():
                if prior.is_synthetic != metadata["is_synthetic"]:
                    continue
                if prior.date_end < frame.date.min() or prior.date_start > frame.date.max():
                    continue
                prior_keys = pd.MultiIndex.from_frame(grain_frame(self.read(prior.id)))
                overlap = len(keys.intersection(prior_keys))
                if overlap:
                    metadata["warnings"].append(
                        f"{overlap:,} observation keys overlap dataset {prior.name}. "
                        "Kept separate; do not add overlapping reports together."
                    )
        dataset_id = uuid.uuid4().hex
        folder = self.root / "datasets" / dataset_id
        folder.mkdir()
        manifest = DatasetManifest(
            id=dataset_id,
            imported_at=datetime.now(timezone.utc).isoformat(),
            rows=len(frame),
            date_start=frame.date.min(),
            date_end=frame.date.max(),
            coverage=coverage(frame),
            options={
                key: sorted(frame[key].dropna().astype(str).unique().tolist())[:1000]
                for key in DIMENSIONS
                if key != "date"
            },
            **metadata,
        )
        try:
            frame.to_parquet(folder / "campaigns.parquet", index=False)
            if truth is not None:
                (folder / "simulation_truth.evaluation-only.json").write_text(json.dumps(truth))
            with self.connect() as conn:
                conn.execute("BEGIN IMMEDIATE")
                if manifest.parent_dataset_id:
                    parent = conn.execute(
                        "SELECT id FROM datasets WHERE id=?", (manifest.parent_dataset_id,)
                    ).fetchone()
                    selection = conn.execute(
                        "SELECT value FROM settings WHERE key='selected_dataset'"
                    ).fetchone()
                    if not parent or not selection or selection[0] != manifest.parent_dataset_id:
                        raise DomainError(
                            "The selected report changed. Review it before saving your answers.",
                            409,
                        )
                conn.execute(
                    "INSERT INTO datasets VALUES (?, ?, ?)",
                    (dataset_id, fingerprint, manifest.model_dump_json()),
                )
                conn.execute(
                    "INSERT OR REPLACE INTO settings VALUES ('selected_dataset', ?)", (dataset_id,)
                )
        except sqlite3.IntegrityError as error:
            shutil.rmtree(folder)
            raise DomainError("This dataset was already saved by another request.", 409) from error
        except Exception:
            shutil.rmtree(folder)
            raise
        return manifest

    def delete(self, dataset_id: str):
        from ads_optimizer.ml.store import ModelStore
        from ads_optimizer.optimization.store import PlanStore

        manifest = self.get(dataset_id)
        with self.connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            ModelStore(self.root).delete_for_dataset(manifest.id)
            PlanStore(self.root).delete_for_dataset(manifest.id)
            if (self.root / "commerce").exists():
                from ads_optimizer.commerce.store import CommerceStore

                CommerceStore(self.root).delete_for_ad(manifest.id)
            conn.execute("DELETE FROM datasets WHERE id=?", (manifest.id,))
            conn.execute(
                "UPDATE settings SET value=NULL WHERE key='selected_dataset' AND value=?",
                (manifest.id,),
            )
        shutil.rmtree(self.root / "datasets" / manifest.id, ignore_errors=True)


def get_repository() -> Repository:
    from ads_optimizer.hosting.workspace import request_root

    root = request_root.get()
    return Repository(root) if root is not None else local_repository()


@lru_cache
def local_repository() -> Repository:
    default = Path(__file__).resolve().parents[4] / "data"
    return Repository(Path(os.environ.get("ADS_DATA_DIR", default)))
