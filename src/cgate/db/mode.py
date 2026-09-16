"""AppModeRepo: read/upsert the single-row `app_mode` table (global behavior mode)."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum

from cgate.db.connection import Database, connect
from cgate.db.rows import col_str, iso, parse


class Mode(StrEnum):
    """Global behavior mode: queue every proposal, or allow per-server auto-execution."""

    PROPOSE = "propose"
    AUTO = "auto"


class AppModeNotSetError(LookupError):
    """The app_mode row is absent: the global mode has never been explicitly set."""

    def __init__(self) -> None:
        """Create the error with a fixed human-readable message."""
        super().__init__("app mode is not set")


@dataclass(frozen=True, slots=True)
class AppMode:
    """The singleton global mode row (id = 1) with its audit fields."""

    mode: Mode
    updated_at: datetime
    updated_by: str


class AppModeRepo:
    """Read/upsert the single-row app_mode table; absence means "unset"."""

    _db: Database  # class-level annotation required by strict mode

    def __init__(self, db: Database) -> None:
        """Store the database handle for subsequent operations."""
        self._db = db

    def get(self) -> AppMode:
        """Fetch the global mode, raising AppModeNotSetError if never set."""
        with connect(self._db) as conn:
            row = conn.execute(
                "SELECT mode, updated_at, updated_by FROM app_mode WHERE id = 1"
            ).fetchone()
        if row is None:
            raise AppModeNotSetError
        return AppMode(
            mode=Mode(col_str(row, "mode")),
            updated_at=parse(col_str(row, "updated_at")),
            updated_by=col_str(row, "updated_by"),
        )

    def set(self, *, mode: Mode, updated_by: str) -> AppMode:
        """Upsert the singleton row and return the value now in effect."""
        now = datetime.now(UTC)
        with connect(self._db) as conn:
            _ = conn.execute(
                """
                INSERT INTO app_mode (id, mode, updated_at, updated_by)
                VALUES (1, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    mode = excluded.mode,
                    updated_at = excluded.updated_at,
                    updated_by = excluded.updated_by
                """,
                (mode.value, iso(now), updated_by),
            )
        return AppMode(mode=mode, updated_at=now, updated_by=updated_by)
