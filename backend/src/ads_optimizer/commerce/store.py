"""Independent immutable commerce snapshots; no raw order IDs or customer fields."""

import hashlib
import hmac
import json
import os
import sqlite3
import tempfile
import uuid
from datetime import datetime, timedelta, timezone

from ads_optimizer.domain import DomainError


def now():
    return datetime.now(timezone.utc).isoformat()


class CommerceStore:
    def __init__(self, root):
        self.root = root / "commerce"
        self.root.mkdir(parents=True, exist_ok=True)
        self.root.chmod(0o700)
        self.staging = self.root / "staging"
        self.staging.mkdir(exist_ok=True)
        with self.connect() as conn:
            conn.execute(
                "CREATE TABLE IF NOT EXISTS snapshots (id TEXT PRIMARY KEY, kind TEXT, "
                "manifest TEXT, payload TEXT, fingerprint TEXT UNIQUE)"
            )
            conn.execute("CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT)")
        (self.root / "catalog.sqlite").chmod(0o600)

    def connect(self):
        return sqlite3.connect(self.root / "catalog.sqlite", timeout=30)

    def order_key(self, store_id, original):
        path = self.root / "order-id-key"
        if not path.exists():
            descriptor, temporary = tempfile.mkstemp(dir=self.root)
            try:
                with os.fdopen(descriptor, "wb") as stream:
                    stream.write(os.urandom(32))
                try:
                    os.link(temporary, path)
                except FileExistsError:
                    pass
            finally:
                os.unlink(temporary)
        return hmac.new(
            path.read_bytes(), f"{store_id}\0{original}".encode(), hashlib.sha256
        ).hexdigest()

    def stage(self, payload):
        self.expire()
        token = uuid.uuid4().hex
        payload["created_at"] = now()
        path = self.staging / f"{token}.json"
        path.write_text(json.dumps(payload))
        path.chmod(0o600)
        return token

    def staged(self, token):
        self.expire()
        if len(token) != 32 or any(c not in "0123456789abcdef" for c in token):
            raise DomainError("That commerce preview is unavailable. Upload it again.", 404)
        path = self.staging / f"{token}.json"
        if not path.exists():
            raise DomainError("That commerce preview expired or was saved. Upload it again.", 404)
        return json.loads(path.read_text())

    def expire(self):
        cutoff = datetime.now(timezone.utc) - timedelta(hours=24)
        for path in self.staging.glob("*.json"):
            if datetime.fromtimestamp(path.stat().st_mtime, timezone.utc) < cutoff:
                path.unlink(missing_ok=True)

    def discard(self, token):
        self.staged(token)
        (self.staging / f"{token}.json").unlink(missing_ok=True)

    def save(self, kind, manifest, payload, *, select=False):
        fingerprint = hashlib.sha256(
            json.dumps(
                {"kind": kind, "payload": payload, "definitions": manifest.get("definitions")},
                sort_keys=True,
                allow_nan=False,
            ).encode()
        ).hexdigest()
        identifier = uuid.uuid4().hex
        if kind in {"reconciliation", "profit_plan"}:
            fingerprint = identifier
        manifest = {**manifest, "id": identifier, "kind": kind, "created_at": now()}
        try:
            with self.connect() as conn:
                conn.execute(
                    "INSERT INTO snapshots VALUES (?,?,?,?,?)",
                    (
                        identifier,
                        kind,
                        json.dumps(manifest),
                        json.dumps(payload),
                        fingerprint,
                    ),
                )
                if select:
                    conn.execute(
                        "INSERT OR REPLACE INTO settings VALUES ('selected',?)", (identifier,)
                    )
        except sqlite3.IntegrityError as error:
            raise DomainError(
                "This normalized commerce snapshot is already saved. Select it instead.", 409
            ) from error
        return manifest

    def get(self, identifier, kind=None):
        with self.connect() as conn:
            row = conn.execute(
                "SELECT manifest,payload FROM snapshots WHERE id=?", (identifier,)
            ).fetchone()
        if not row:
            raise DomainError("That commerce snapshot is no longer available.", 404)
        manifest, payload = map(json.loads, row)
        if kind and manifest["kind"] != kind:
            raise DomainError("Choose the correct type of commerce snapshot.")
        return manifest, payload

    def list(self, kind):
        with self.connect() as conn:
            return [
                json.loads(row[0])
                for row in conn.execute(
                    "SELECT manifest FROM snapshots WHERE kind=? ORDER BY rowid DESC", (kind,)
                )
            ]

    def selected(self):
        with self.connect() as conn:
            row = conn.execute("SELECT value FROM settings WHERE key='selected'").fetchone()
        return row[0] if row else None

    def select(self, identifier):
        if identifier:
            self.get(identifier, "orders")
        with self.connect() as conn:
            conn.execute("INSERT OR REPLACE INTO settings VALUES ('selected',?)", (identifier,))

    def delete(self, identifier):
        self.get(identifier)
        ids = {identifier}
        # Dependency closure: orders -> costs/reconciliations -> profit plans.
        changed = True
        while changed:
            changed = False
            for kind in ["costs", "reconciliation", "profit_plan"]:
                for item in self.list(kind):
                    dependencies = set(item.get("dependencies", []))
                    if item["id"] not in ids and dependencies & ids:
                        ids.add(item["id"])
                        changed = True
        with self.connect() as conn:
            conn.executemany("DELETE FROM snapshots WHERE id=?", [(item,) for item in ids])
            if self.selected() in ids:
                conn.execute("DELETE FROM settings WHERE key='selected'")
        return len(ids)

    def delete_for_ad(self, identifier):
        for item in self.list("reconciliation"):
            if item["ad_dataset_id"] == identifier:
                self.delete(item["id"])
