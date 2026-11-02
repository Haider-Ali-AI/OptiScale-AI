"""Persist a bounded local workspace transactionally across stateless invocations.

Postgres row locking serializes all requests. Each invocation restores its own
scratch directory; success is sent only after the complete workspace is committed.
This intentionally favors correctness over throughput for one owner.
"""

import io
import os
import tempfile
import zipfile
from contextvars import ContextVar
from pathlib import Path, PurePosixPath

from fastapi.responses import JSONResponse, Response

from ads_optimizer.domain import DomainError

request_root: ContextVar[Path | None] = ContextVar("request_workspace_root", default=None)
MAX_STATE_BYTES = 64 * 1024 * 1024


def serverless():
    return os.environ.get("VERCEL") == "1" or os.environ.get("ADS_SERVERLESS") == "1"


def pack(root):
    files = [p for p in root.rglob("*") if p.is_file()]
    if any(p.is_symlink() for p in root.rglob("*")):
        raise DomainError("Workspace links cannot be saved.", 503)
    if sum(p.stat().st_size for p in files) > MAX_STATE_BYTES:
        raise DomainError("Hosted workspace exceeds 64 MiB. Delete unused datasets/models.", 413)
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as archive:
        for path in files:
            archive.write(path, path.relative_to(root).as_posix())
    payload = output.getvalue()
    if len(payload) > MAX_STATE_BYTES:
        raise DomainError("Hosted workspace archive exceeds 64 MiB. Delete unused data.", 413)
    return payload


def unpack(payload, root):
    if not payload:
        return
    if len(payload) > MAX_STATE_BYTES:
        raise DomainError("Saved workspace exceeds the hosted size limit.", 503)
    try:
        with zipfile.ZipFile(io.BytesIO(payload)) as archive:
            members = archive.infolist()
            if sum(m.file_size for m in members) > MAX_STATE_BYTES or len(members) > 10000:
                raise ValueError("oversized archive")
            for member in members:
                path = PurePosixPath(member.filename)
                mode = member.external_attr >> 16
                if path.is_absolute() or ".." in path.parts or mode & 0o170000 == 0o120000:
                    raise ValueError("unsafe archive path")
                destination = root / path
                if member.is_dir():
                    destination.mkdir(parents=True, exist_ok=True)
                else:
                    destination.parent.mkdir(parents=True, exist_ok=True)
                    destination.write_bytes(archive.read(member))
    except (ValueError, zipfile.BadZipFile, RuntimeError) as error:
        raise DomainError(
            "Saved workspace could not be restored. Contact the owner.", 503
        ) from error


async def persisted_response(request, call_next):
    url = (
        os.environ.get("ADS_DATABASE_URL")
        or os.environ.get("POSTGRES_URL")
        or os.environ.get("DATABASE_URL")
    )
    if not url:
        return JSONResponse(
            status_code=503,
            content={"detail": "Hosted storage is not configured. Connect a Postgres database."},
        )
    import psycopg

    try:
        async with await psycopg.AsyncConnection.connect(url, connect_timeout=10) as connection:
            async with connection.cursor() as cursor:
                await cursor.execute("SET LOCAL lock_timeout = '10s'")
                await cursor.execute(
                    "CREATE TABLE IF NOT EXISTS ads_workspace "
                    "(id integer PRIMARY KEY CHECK (id=1), payload bytea NOT NULL)"
                )
                await cursor.execute(
                    "INSERT INTO ads_workspace VALUES (1, %s) ON CONFLICT DO NOTHING", (b"",)
                )
                await cursor.execute("SELECT payload FROM ads_workspace WHERE id=1 FOR UPDATE")
                row = await cursor.fetchone()
                with tempfile.TemporaryDirectory(prefix="adwise-") as folder:
                    root = Path(folder)
                    unpack(bytes(row[0]), root)
                    token = request_root.set(root)
                    try:
                        response = await call_next(request)
                        # Streaming CSVs must finish reading before scratch files are removed.
                        body = bytearray()
                        async for chunk in response.body_iterator:
                            body.extend(chunk)
                            if len(body) > MAX_STATE_BYTES:
                                raise DomainError("Hosted export exceeds 64 MiB.", 413)
                        if response.status_code < 400:
                            await cursor.execute(
                                "UPDATE ads_workspace SET payload=%s WHERE id=1", (pack(root),)
                            )
                        result = Response(
                            bytes(body),
                            status_code=response.status_code,
                            headers=dict(response.headers),
                        )
                    finally:
                        request_root.reset(token)
            # Commit before returning success, including before clients receive exports.
        return result
    except DomainError as error:
        return JSONResponse(status_code=error.status, content={"detail": error.message})
    except psycopg.Error:
        return JSONResponse(
            status_code=503,
            content={
                "detail": "Hosted storage is unavailable or busy. "
                "Refresh before retrying; this action could not be confirmed."
            },
        )
