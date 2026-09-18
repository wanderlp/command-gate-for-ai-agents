"""Regenerate the `cgate watch` demo screenshots used in README.md.

Seeds a throwaway in-memory-ish SQLite DB with realistic fake batches/commands
(no real servers or SSH/WinRM involved), drives the Textual app headlessly via
its own test pilot, and exports SVG screenshots -- the same mechanism Textual
apps use for their own docs. Run after any change to the watch UI's look that
should be reflected in the README:

    uv run python scripts/render_demo_screenshots.py

Output: docs/img/watch-dashboard.svg, docs/img/watch-history.svg
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from pathlib import Path

import cgate.watch.app as watch_app_module
from cgate.connections.store import ConnectionsRepo
from cgate.db.batches import BatchesRepo
from cgate.db.commands import CommandsRepo
from cgate.db.connection import Database, init_database
from cgate.db.mode import AppModeRepo, Mode
from cgate.db.server_settings import ServerSettingsRepo
from cgate.db.types import CommandStatus, ServerType
from cgate.watch.app import WatchApp

# Screenshots should show a clean release version, not whatever dev/local
# version hatch-vcs derives from the current git state.
_DEMO_VERSION = "0.2.4"
watch_app_module.__version__ = _DEMO_VERSION

_REPO_ROOT = Path(__file__).resolve().parents[1]
_IMG_DIR = _REPO_ROOT / "docs" / "img"
_DB_PATH = _REPO_ROOT / ".demo-screenshot.db"
_WINDOW_SIZE = (112, 32)


def _seed_queue() -> tuple[
    Database, BatchesRepo, CommandsRepo, ConnectionsRepo, AppModeRepo, ServerSettingsRepo
]:
    if _DB_PATH.exists():
        _DB_PATH.unlink()
    db = Database(path=_DB_PATH)
    init_database(db)
    batches = BatchesRepo(db)
    commands = CommandsRepo(db)
    connections = ConnectionsRepo(db)
    mode = AppModeRepo(db)
    server_settings = ServerSettingsRepo(db)

    mode.set(mode=Mode.AUTO, updated_by="demo")
    connections.add(
        alias="dev-1", hostname="dev-1.internal", server_type=ServerType.LINUX,
        detection_ssh=True, detection_winrm=False,
    )
    connections.add(
        alias="stage-2", hostname="stage-2.internal", server_type=ServerType.LINUX,
        detection_ssh=True, detection_winrm=False,
    )
    connections.add(
        alias="prod-db", hostname="prod-db.internal", server_type=ServerType.WINDOWS,
        detection_ssh=False, detection_winrm=True,
    )
    server_settings.set(alias="dev-1", auto_allowed=True, updated_by="demo")

    batch = batches.create(
        title="deploy v2",
        description="Roll out v2.3.1 to staging and restart the app service",
        requested_by_agent="claude-code",
    )

    executed = commands.add(
        batch_id=batch.id, server_alias="dev-1", server_type=ServerType.LINUX,
        command="systemctl restart app", reason="restart service to pick up new config",
    )
    commands.update_status(
        executed.id, status=CommandStatus.EXECUTED,
        approved_by="auto:watch:demo", result="Restarted app.service successfully",
    )

    running = commands.add(
        batch_id=batch.id, server_alias="dev-1", server_type=ServerType.LINUX,
        command="curl -sf https://dev-1/healthz", reason="verify health after restart",
    )
    commands.update_status(running.id, status=CommandStatus.APPROVED, approved_by="auto:watch:demo")

    commands.add(
        batch_id=batch.id, server_alias="stage-2", server_type=ServerType.LINUX,
        command="systemctl status app", reason="confirm rollout reached staging",
    )

    commands.add(
        batch_id=batch.id, server_alias="prod-db", server_type=ServerType.WINDOWS,
        command="Remove-Item -Recurse -Force C:\\temp\\old-app",
        reason="clean up staging artifacts before the next release",
        risk_label="recursive force delete (Remove-Item -Recurse -Force)",
    )

    return db, batches, commands, connections, mode, server_settings


def _seed_history(batches: BatchesRepo, commands: CommandsRepo) -> None:
    now = datetime.now(UTC)

    b1 = batches.create(title="deploy v2", description=None, requested_by_agent="claude-code")
    c1 = commands.add(
        batch_id=b1.id, server_alias="dev-1", server_type=ServerType.LINUX,
        command="systemctl restart app", reason="restart service to pick up new config",
    )
    commands.update_status(
        c1.id, status=CommandStatus.EXECUTED,
        approved_by="auto:watch:demo", result="Restarted app.service successfully",
    )
    batches.mark_resolved(b1.id, resolved_at=now - timedelta(days=2))

    b2 = batches.create(title="rotate logs", description=None, requested_by_agent="claude-code")
    c2 = commands.add(
        batch_id=b2.id, server_alias="stage-2", server_type=ServerType.LINUX,
        command="logrotate -f /etc/logrotate.conf",
    )
    commands.update_status(
        c2.id, status=CommandStatus.EXECUTED, approved_by="jsmith", result="rotated 4 files",
    )
    batches.mark_resolved(b2.id, resolved_at=now - timedelta(days=1))

    b3 = batches.create(title="backup db", description=None, requested_by_agent="claude-code")
    c3 = commands.add(
        batch_id=b3.id, server_alias="prod-db", server_type=ServerType.WINDOWS,
        command="Backup-SqlDatabase -Name orders",
    )
    commands.update_status(
        c3.id, status=CommandStatus.EXECUTED, approved_by="jsmith",
        result="Backup complete: orders.bak",
    )
    batches.mark_resolved(b3.id, resolved_at=now - timedelta(hours=5))

    b4 = batches.create(title="cleanup tmp", description=None, requested_by_agent="claude-code")
    c4 = commands.add(
        batch_id=b4.id, server_alias="dev-1", server_type=ServerType.LINUX,
        command="rm -rf /tmp/build-cache",
    )
    commands.update_status(c4.id, status=CommandStatus.REJECTED, approved_by="jsmith")
    batches.mark_resolved(b4.id, resolved_at=now - timedelta(hours=1))


async def main() -> None:
    """Render both screenshots and clean up the throwaway demo DB."""
    _IMG_DIR.mkdir(parents=True, exist_ok=True)
    db, batches, commands, connections, mode, server_settings = _seed_queue()
    app = WatchApp(
        db=db, batches=batches, commands=commands,
        connections=connections, mode=mode, server_settings=server_settings,
    )
    try:
        async with app.run_test(size=_WINDOW_SIZE) as pilot:
            await pilot.pause()
            dashboard_svg = app.export_screenshot(title="cgate watch")
            (_IMG_DIR / "watch-dashboard.svg").write_text(dashboard_svg, encoding="utf-8")
            print(f"wrote {_IMG_DIR / 'watch-dashboard.svg'}")

            _seed_history(batches, commands)
            await pilot.press("h")
            await pilot.pause()
            await pilot.press("slash")
            await pilot.pause()
            for ch in "dev-1":
                await pilot.press(ch)
            await pilot.pause()
            history_svg = app.export_screenshot(title="cgate watch — history")
            (_IMG_DIR / "watch-history.svg").write_text(history_svg, encoding="utf-8")
            print(f"wrote {_IMG_DIR / 'watch-history.svg'}")
    finally:
        _DB_PATH.unlink(missing_ok=True)


if __name__ == "__main__":
    asyncio.run(main())
