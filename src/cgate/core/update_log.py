"""Best-effort append-only logging for background update/uninstall operations.

Lives in ``cgate.core`` (not ``cgate.cli``) because it's shared by the
interactive CLI and the non-interactive ``cgate.helper`` binary, which must
not import anything from ``cgate.cli`` (typer/rich/mcp/paramiko/pywinrm).
"""

from __future__ import annotations

from datetime import UTC, datetime

import cgate.core.paths

_LOG_FILENAME = "update.log"


def append_log(message: str) -> None:
    """Append a timestamped line to ``<data_dir>/update.log``. Never raises.

    Best-effort: any failure (permission denied, missing dir, encoding
    errors) is silently swallowed. Logging must never crash the caller --
    in particular, the helper process that runs after the main cgate
    process has exited has no other way to surface failure.

    Uses ``cgate.core.paths.data_dir`` (attribute lookup at call time)
    rather than a module-level import so tests can monkeypatch the data
    directory location.
    """
    try:
        log_path = cgate.core.paths.data_dir() / _LOG_FILENAME
        log_path.parent.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now(UTC).isoformat(timespec="seconds")
        with log_path.open("a", encoding="utf-8") as f:
            f.write(f"[{timestamp}] {message}\n")
    except Exception:
        pass
