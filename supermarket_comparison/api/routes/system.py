"""System endpoints: health check, backup and restore."""

from __future__ import annotations

import asyncio
import shutil
import sqlite3
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated, Any

from fastapi import (
    APIRouter,
    Depends,
    File,
    HTTPException,
    UploadFile,
)
from fastapi.responses import FileResponse
from starlette.background import BackgroundTask

from ...storage import Repository
from .history import get_repository

router = APIRouter(prefix="/system", tags=["system"])



# -- database backup / restore ---------------------------------------------
#: Hard limit for an uploaded SQLite backup.
MAX_RESTORE_BYTES: int = 200 * 1024 * 1024

BACKUP_MEDIA_TYPE = "application/octet-stream"

_SQLITE_HEADER = b"SQLite format 3\x00"

_REQUIRED_TABLES = frozenset({"products", "price_points"})


class _RestoreError(Exception):
    """Internal error with the HTTP status the endpoint should return."""

    def __init__(self, status_code: int, detail: str) -> None:
        super().__init__(detail)
        self.status_code = status_code
        self.detail = detail


def _live_db_path(repository: Repository) -> Path | None:
    """Return the on-disk SQLite path, or ``None`` for ``:memory:``/missing."""

    path = repository.db.path
    if str(path) == ":memory:":
        return None
    if not path.exists():
        return None
    return path


def _sqlite_backup(source: Path | str, target: Path | str) -> None:
    """Copy a database consistently while WAL is active (online backup API)."""

    src = sqlite3.connect(str(source), timeout=30.0)
    try:
        dst = sqlite3.connect(str(target))
        try:
            src.backup(dst)
        finally:
            dst.close()
    finally:
        src.close()


def _validate_upload(upload_path: Path) -> tuple[int, int]:
    """Validate the uploaded DB and return ``(products, price_points)`` counts."""

    with upload_path.open("rb") as handle:
        header = handle.read(len(_SQLITE_HEADER))
    if header != _SQLITE_HEADER:
        raise _RestoreError(400, "The upload is not a SQLite 3 database.")

    uri = f"{upload_path.as_uri()}?mode=ro&immutable=1"
    try:
        connection = sqlite3.connect(uri, uri=True)
    except sqlite3.Error as exc:
        raise _RestoreError(400, f"Cannot open the uploaded database: {exc}") from exc

    try:
        integrity = connection.execute("PRAGMA integrity_check").fetchone()
        if not integrity or integrity[0] != "ok":
            raise _RestoreError(
                400, "The uploaded database failed the SQLite integrity check."
            )

        tables = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            )
        }
        missing = sorted(_REQUIRED_TABLES - tables)
        if missing:
            raise _RestoreError(
                400,
                "The uploaded database is missing required tables: "
                + ", ".join(missing)
                + ".",
            )

        products = int(
            connection.execute("SELECT COUNT(*) FROM products").fetchone()[0]
        )
        price_points = int(
            connection.execute("SELECT COUNT(*) FROM price_points").fetchone()[0]
        )
        return products, price_points
    except sqlite3.Error as exc:
        raise _RestoreError(400, f"Invalid SQLite database: {exc}") from exc
    finally:
        connection.close()


def _restore_database(
    upload_path: Path,
    live_path: Path,
    *,
    stamp: str,
) -> tuple[int, int, Path]:
    """Back up the live DB, then atomically replace its contents."""

    products, price_points = _validate_upload(upload_path)

    backup_path = Path(f"{live_path}.bak-{stamp}")
    try:
        _sqlite_backup(live_path, backup_path)
    except (sqlite3.Error, OSError) as exc:
        raise _RestoreError(
            500, f"Could not back up the current database: {exc}"
        ) from exc

    try:
        source = sqlite3.connect(str(upload_path), timeout=30.0)
        try:
            destination = sqlite3.connect(str(live_path), timeout=30.0)
            try:
                source.backup(destination)
            finally:
                destination.close()
        finally:
            source.close()
    except (sqlite3.Error, OSError) as exc:
        raise _RestoreError(500, f"Could not restore the database: {exc}") from exc

    # The restore writes a fresh main database; stale WAL sidecars would shadow
    # or corrupt it for connections that still have them open.
    for suffix in ("-wal", "-shm"):
        Path(f"{live_path}{suffix}").unlink(missing_ok=True)
    return products, price_points, backup_path


@router.get(
    "/backup-db",
    summary="Download a consistent copy of the SQLite database",
)
async def backup_db(
    repository: Annotated[Repository, Depends(get_repository)],
) -> FileResponse:
    """Stream a consistent snapshot of the live database as a ``.db`` file."""

    source_path = _live_db_path(repository)
    if source_path is None:
        raise HTTPException(
            status_code=404,
            detail=(
                "No file-backed SQLite database is available for backup "
                "(in-memory or missing database)."
            ),
        )

    directory = Path(tempfile.mkdtemp(prefix="supermarkt-backup-"))
    target_path = directory / "backup.db"
    try:
        await asyncio.to_thread(_sqlite_backup, source_path, target_path)
    except (sqlite3.Error, OSError) as exc:
        shutil.rmtree(directory, ignore_errors=True)
        raise HTTPException(
            status_code=500, detail=f"Could not back up the database: {exc}"
        ) from exc

    filename = f"supermarkt-{datetime.now(tz=UTC).date().isoformat()}.db"
    return FileResponse(
        target_path,
        media_type=BACKUP_MEDIA_TYPE,
        filename=filename,
        background=BackgroundTask(shutil.rmtree, directory, True),
    )


@router.post(
    "/restore-db",
    summary="Restore the SQLite database from an uploaded backup",
)
async def restore_db(
    repository: Annotated[Repository, Depends(get_repository)],
    file: Annotated[UploadFile, File(description="SQLite backup file")],
) -> dict[str, Any]:
    """Validate an uploaded SQLite file and replace the live database with it."""

    live_path = _live_db_path(repository)
    if live_path is None:
        raise HTTPException(
            status_code=404,
            detail=(
                "No file-backed SQLite database is available for restore "
                "(in-memory or missing database)."
            ),
        )

    data = await file.read(MAX_RESTORE_BYTES + 1)
    if len(data) > MAX_RESTORE_BYTES:
        raise HTTPException(
            status_code=413,
            detail=(
                "The uploaded backup exceeds the "
                f"{MAX_RESTORE_BYTES // (1024 * 1024)} MB limit."
            ),
        )

    directory = Path(tempfile.mkdtemp(prefix="supermarkt-restore-"))
    upload_path = directory / "upload.db"
    stamp = datetime.now(tz=UTC).strftime("%Y%m%d-%H%M%S")
    try:
        await asyncio.to_thread(upload_path.write_bytes, data)
        try:
            products, price_points, backup_path = await asyncio.to_thread(
                _restore_database, upload_path, live_path, stamp=stamp
            )
        except _RestoreError as exc:
            raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc
    finally:
        await asyncio.to_thread(shutil.rmtree, directory, True)

    return {
        "status": "restored",
        "products": products,
        "price_points": price_points,
        "backup_file": str(backup_path),
    }


__all__ = ["router"]
