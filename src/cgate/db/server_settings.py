"""ServerSettingsRepo: per-server auto-approve opt-in rows (`server_settings` table)."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from cgate.db.connection import Database, connect
from cgate.db.rows import col_int, col_opt_dt, col_opt_str, col_str, iso

if TYPE_CHECKING:
    import sqlite3


@dataclass(frozen=True, slots=True)
class ServerSetting:
    """Explicit auto-approve opt-in state for one server alias.

    ``updated_at``/``updated_by`` are None only for the implicit default
    returned by ``get_or_default`` when no row exists -- persisted rows
    always carry both audit fields.
    """

    server_alias: str
    auto_allowed: bool
    updated_at: datetime | None
    updated_by: str | None


def _row_to_setting(row: sqlite3.Row) -> ServerSetting:
    """Convert a SQLite row into a typed ServerSetting value object."""
    return ServerSetting(
        server_alias=col_str(row, "server_alias"),
        auto_allowed=bool(col_int(row, "auto_allowed")),
        updated_at=col_opt_dt(row, "updated_at"),
        updated_by=col_opt_str(row, "updated_by"),
    )


class ServerSettingsRepo:
    """Per-server opt-in CRUD; no row means auto-execute is NOT allowed."""

    _db: Database  # class-level annotation required by strict mode

    def __init__(self, db: Database) -> None:
        """Store the database handle for subsequent operations."""
        self._db = db

    def get(self, alias: str) -> ServerSetting | None:
        """Fetch the explicit setting for an alias, or None if never set."""
        with connect(self._db) as conn:
            row = conn.execute(
                """
                SELECT server_alias, auto_allowed, updated_at, updated_by
                FROM server_settings WHERE server_alias = ?
                """,
                (alias,),
            ).fetchone()
        return _row_to_setting(row) if row is not None else None

    def get_or_default(self, alias: str) -> ServerSetting:
        """Fetch the setting, defaulting to auto_allowed=False when no row exists."""
        setting = self.get(alias)
        if setting is None:
            return ServerSetting(
                server_alias=alias,
                auto_allowed=False,
                updated_at=None,
                updated_by=None,
            )
        return setting

    def set(self, *, alias: str, auto_allowed: bool, updated_by: str) -> ServerSetting:
        """Upsert the opt-in row for an alias and return the value now in effect."""
        now = datetime.now(UTC)
        with connect(self._db) as conn:
            _ = conn.execute(
                """
                INSERT INTO server_settings
                    (server_alias, auto_allowed, updated_at, updated_by)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(server_alias) DO UPDATE SET
                    auto_allowed = excluded.auto_allowed,
                    updated_at = excluded.updated_at,
                    updated_by = excluded.updated_by
                """,
                (alias, int(auto_allowed), iso(now), updated_by),
            )
        return ServerSetting(
            server_alias=alias,
            auto_allowed=auto_allowed,
            updated_at=now,
            updated_by=updated_by,
        )

    def list_all(self) -> list[ServerSetting]:
        """Return every alias with an explicit setting, ordered by alias."""
        with connect(self._db) as conn:
            rows = conn.execute(
                """
                SELECT server_alias, auto_allowed, updated_at, updated_by
                FROM server_settings ORDER BY server_alias ASC
                """
            ).fetchall()
        return [_row_to_setting(row) for row in rows]
