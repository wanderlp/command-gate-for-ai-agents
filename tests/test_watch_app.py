"""Headless Textual pilot tests for the `cgate watch` dashboard."""

from __future__ import annotations

import asyncio
import sqlite3
from dataclasses import dataclass
from typing import TYPE_CHECKING
from unittest.mock import patch

import pytest
from textual.widgets import ListView

from cgate.connections.store import ConnectionsRepo
from cgate.db.batches import BatchesRepo
from cgate.db.commands import CommandsRepo
from cgate.db.connection import Database, init_database
from cgate.db.mode import AppModeRepo
from cgate.db.server_settings import ServerSettingsRepo
from cgate.db.types import CommandStatus, ServerType
from cgate.executor.base import ExecutionResult
from cgate.watch.app import ActivePanel, WatchApp
from cgate.watch.command_detail_modal import CommandDetailModal

if TYPE_CHECKING:
    from pathlib import Path

COMMAND_COUNT = 3


@dataclass(frozen=True, slots=True)
class Repos:
    db: Database
    batches: BatchesRepo
    commands: CommandsRepo
    connections: ConnectionsRepo
    mode: AppModeRepo
    server_settings: ServerSettingsRepo


@pytest.fixture
def repos(tmp_path: Path) -> Repos:
    db = Database(path=tmp_path / "cgate.db")
    init_database(db)
    return Repos(
        db=db,
        batches=BatchesRepo(db),
        commands=CommandsRepo(db),
        connections=ConnectionsRepo(db),
        mode=AppModeRepo(db),
        server_settings=ServerSettingsRepo(db),
    )


def _app(repos: Repos) -> WatchApp:
    return WatchApp(
        db=repos.db,
        batches=repos.batches,
        commands=repos.commands,
        connections=repos.connections,
        mode=repos.mode,
        server_settings=repos.server_settings,
    )


def _success() -> ExecutionResult:
    return ExecutionResult("hello\n", "", 0, 42, None)


def test_idle_state_when_queue_is_empty(repos: Repos) -> None:
    async def scenario() -> str:
        async with _app(repos).run_test() as pilot:
            await pilot.pause()
            panel = pilot.app.query_one(ActivePanel)
            return str(panel.query_one("#active-header").content)

    header_text = asyncio.run(scenario())
    assert "No pending batches" in header_text


def test_approve_one_executes_and_advances(repos: Repos) -> None:
    lot = repos.batches.create(title="lot", description=None, requested_by_agent=None)
    first = repos.commands.add(
        batch_id=lot.id, server_alias="linux-1", server_type=ServerType.LINUX, command="uptime"
    )
    _ = repos.connections.add(
        alias="linux-1",
        hostname="linux.example",
        server_type=ServerType.LINUX,
        detection_ssh=True,
        detection_winrm=False,
    )

    async def scenario() -> None:
        with patch("cgate.watch.approval.execute_command", return_value=_success()):
            async with _app(repos).run_test() as pilot:
                await pilot.pause()
                await pilot.press("y")
                await pilot.pause()

    asyncio.run(scenario())

    updated = repos.commands.get(first.id)
    assert updated is not None
    assert updated.status is CommandStatus.EXECUTED


def test_reject_all_resolves_the_active_batch(repos: Repos) -> None:
    lot = repos.batches.create(title="lot", description=None, requested_by_agent=None)
    for index in range(COMMAND_COUNT):
        _ = repos.commands.add(
            batch_id=lot.id,
            server_alias="linux-1",
            server_type=ServerType.LINUX,
            command=str(index),
        )

    async def scenario() -> None:
        async with _app(repos).run_test() as pilot:
            await pilot.pause()
            await pilot.press("r")
            await pilot.pause()

    asyncio.run(scenario())

    commands_in_lot = repos.commands.list_for_batch(lot.id)
    assert all(command.status is CommandStatus.REJECTED for command in commands_in_lot)
    resolved = repos.batches.get(lot.id)
    assert resolved is not None
    assert resolved.resolved_at is not None


def test_selecting_a_batch_in_the_sidebar_pins_it_active(repos: Repos) -> None:
    """A human can jump the queue and prioritize approving a batch further
    down instead of being forced through strict FIFO order."""
    older = repos.batches.create(title="older", description=None, requested_by_agent=None)
    _ = repos.commands.add(
        batch_id=older.id, server_alias="linux-1", server_type=ServerType.LINUX, command="a"
    )
    newer = repos.batches.create(title="newer", description=None, requested_by_agent=None)
    _ = repos.commands.add(
        batch_id=newer.id, server_alias="linux-1", server_type=ServerType.LINUX, command="b"
    )

    async def scenario() -> tuple[str, object]:
        async with _app(repos).run_test() as pilot:
            await pilot.pause()
            pilot.app.query_one("#queue-list", ListView).focus()
            await pilot.pause()
            await pilot.press("down")  # highlight the second (newer) batch
            await pilot.press("enter")  # pin it as active
            await pilot.pause()
            header = str(pilot.app.query_one("#active-header").content)
            return header, pilot.app._pinned_batch_id  # noqa: SLF001

    header, pinned_id = asyncio.run(scenario())
    assert "newer" in header
    assert pinned_id == newer.id


def test_approve_after_pinning_acts_on_the_pinned_batch_not_fifo_first(repos: Repos) -> None:
    older = repos.batches.create(title="older", description=None, requested_by_agent=None)
    _ = repos.commands.add(
        batch_id=older.id, server_alias="linux-1", server_type=ServerType.LINUX, command="a"
    )
    newer = repos.batches.create(title="newer", description=None, requested_by_agent=None)
    newer_cmd = repos.commands.add(
        batch_id=newer.id, server_alias="linux-1", server_type=ServerType.LINUX, command="b"
    )
    _ = repos.connections.add(
        alias="linux-1",
        hostname="linux.example",
        server_type=ServerType.LINUX,
        detection_ssh=True,
        detection_winrm=False,
    )

    async def scenario() -> None:
        with patch("cgate.watch.approval.execute_command", return_value=_success()):
            async with _app(repos).run_test() as pilot:
                await pilot.pause()
                pilot.app.query_one("#queue-list", ListView).focus()
                await pilot.pause()
                await pilot.press("down")
                await pilot.press("enter")
                await pilot.pause()
                await pilot.press("y")
                await pilot.pause()

    asyncio.run(scenario())

    updated_newer = repos.commands.get(newer_cmd.id)
    assert updated_newer is not None
    assert updated_newer.status is CommandStatus.EXECUTED
    older_cmd = repos.commands.list_for_batch(older.id)[0]
    assert older_cmd.status is CommandStatus.PENDING


def test_pinned_batch_falls_back_to_fifo_once_it_resolves(repos: Repos) -> None:
    """Self-correcting: no explicit unpin needed once the chosen batch is done."""
    lot = repos.batches.create(title="lot", description=None, requested_by_agent=None)
    _ = repos.commands.add(
        batch_id=lot.id, server_alias="linux-1", server_type=ServerType.LINUX, command="a"
    )

    async def scenario() -> None:
        async with _app(repos).run_test() as pilot:
            await pilot.pause()
            pilot.app.query_one("#queue-list", ListView).focus()
            await pilot.pause()
            await pilot.press("enter")  # pin the only batch (itself)
            await pilot.press("n")  # reject its only command -> the batch resolves
            await pilot.pause()

    asyncio.run(scenario())

    resolved = repos.batches.get(lot.id)
    assert resolved is not None
    assert resolved.resolved_at is not None


def test_entering_a_command_row_opens_the_detail_modal(repos: Repos) -> None:
    lot = repos.batches.create(title="lot", description=None, requested_by_agent=None)
    _ = repos.commands.add(
        batch_id=lot.id,
        server_alias="linux-1",
        server_type=ServerType.LINUX,
        command="uptime",
        reason="checking uptime after patching",
    )

    async def scenario() -> bool:
        async with _app(repos).run_test() as pilot:
            await pilot.pause()
            pilot.app.query_one("#rows", ListView).focus()
            await pilot.pause()
            await pilot.press("enter")
            await pilot.pause()
            return isinstance(pilot.app.screen, CommandDetailModal)

    opened = asyncio.run(scenario())
    assert opened


def test_refresh_renders_clean_message_on_sqlite_error(repos: Repos) -> None:
    """issue #12 (reopened): Textual's widget exception handler prints a
    raw ``rich.traceback.Traceback(show_locals=True)`` on any exception
    raised from a timer/handler, bypassing ``cli/main.py``'s
    ``sqlite3.Error`` boundary entirely. ``_refresh`` must catch the
    DB error itself and render a clean in-UI message instead -- the
    next polling tick retries automatically."""

    async def scenario() -> str:
        async with _app(repos).run_test() as pilot:
            await pilot.pause()
            with patch.object(
                repos.batches,
                "list_pending",
                side_effect=sqlite3.OperationalError("database is locked"),
            ):
                pilot.app._refresh()  # noqa: SLF001 -- private but the only entry point
                await pilot.pause()
            return str(pilot.app.query_one("#waiting-notice").content)

    out = asyncio.run(scenario())
    assert "database is locked" in out
    assert "locking" in out.lower()


def test_refresh_survives_db_error_in_subsequent_call(repos: Repos) -> None:
    """issue #12 (extended): the original ``_refresh`` catch only
    wrapped ``list_pending``; if ``count_waiting`` or ``list_for_batch``
    raised instead, the watch app would still die on Textual's traceback.
    The full body must be inside one try."""

    async def scenario() -> tuple[str, str]:
        async with _app(repos).run_test() as pilot:
            await pilot.pause()
            with patch(
                "cgate.watch.app.count_waiting",
                side_effect=sqlite3.OperationalError("database is locked"),
            ):
                pilot.app._refresh()  # noqa: SLF001
                await pilot.pause()
            notice = str(pilot.app.query_one("#waiting-notice").content)
            sub = str(pilot.app.sub_title)
            return notice, sub

    notice, sub = asyncio.run(scenario())
    assert "database is locked" in notice
    assert sub == "database error"


def test_first_pending_returns_none_on_db_error(repos: Repos) -> None:
    """issue #12 (extended): ``_first_pending`` powers every action
    handler (approve/reject). If it raised sqlite3.Error, a user keypress
    would trigger Textual's raw traceback. Must catch internally and
    return ``None`` so the action handler is a silent no-op while the
    error stays on screen."""

    async def scenario() -> str:
        async with _app(repos).run_test() as pilot:
            await pilot.pause()
            with patch.object(
                repos.batches,
                "list_pending",
                side_effect=sqlite3.OperationalError("database is locked"),
            ):
                result = pilot.app._first_pending()  # noqa: SLF001
                await pilot.pause()
            assert result is None
            return str(pilot.app.query_one("#waiting-notice").content)

    notice = asyncio.run(scenario())
    assert "database is locked" in notice


def test_reject_action_keeps_tui_alive_on_db_error(repos: Repos) -> None:
    """issue #12 (extended): ``action_reject_one`` calls ``reject_one``
    which opens DB. If the DB throws mid-reject, Textual would print a
    raw traceback. The action must keep the TUI alive and surface the
    error inline."""

    lot = repos.batches.create(title="lot", description=None, requested_by_agent=None)
    _ = repos.commands.add(
        batch_id=lot.id,
        server_alias="linux-1",
        server_type=ServerType.LINUX,
        command="uptime",
    )
    _ = repos.connections.add(
        alias="linux-1",
        hostname="linux.example",
        server_type=ServerType.LINUX,
        detection_ssh=True,
        detection_winrm=False,
    )

    async def scenario() -> tuple[str, bool]:
        async with _app(repos).run_test() as pilot:
            await pilot.pause()
            with patch.object(
                repos.commands,
                "update_status",
                side_effect=sqlite3.OperationalError("database is locked"),
            ):
                await pilot.press("n")
                await pilot.pause()
            notice = str(pilot.app.query_one("#waiting-notice").content)
            # The bus flag must have been released so the next keypress
            # can take effect.
            idle = not pilot.app._busy  # noqa: SLF001
            return notice, idle

    notice, idle = asyncio.run(scenario())
    assert "database is locked" in notice
    assert idle, "action handler must not leave the TUI in a busy state on DB error"


def test_approve_action_swallows_db_error_from_approve_one(repos: Repos) -> None:
    """issue #12 (extended): ``_approve`` runs ``approve_one`` on a worker
    thread. If the DB throws there, the await propagates the exception
    into the event loop -- Textual swallows it and prints the traceback.
    The async wrapper must catch and render the error inline."""

    lot = repos.batches.create(title="lot", description=None, requested_by_agent=None)
    _ = repos.commands.add(
        batch_id=lot.id,
        server_alias="linux-1",
        server_type=ServerType.LINUX,
        command="uptime",
    )
    _ = repos.connections.add(
        alias="linux-1",
        hostname="linux.example",
        server_type=ServerType.LINUX,
        detection_ssh=True,
        detection_winrm=False,
    )

    async def scenario() -> tuple[str, bool]:
        async with _app(repos).run_test() as pilot:
            await pilot.pause()
            with patch(
                "cgate.watch.app.approve_one",
                side_effect=sqlite3.OperationalError("database is locked"),
            ):
                await pilot.press("y")
                await pilot.pause()
            notice = str(pilot.app.query_one("#waiting-notice").content)
            idle = not pilot.app._busy  # noqa: SLF001
            return notice, idle

    notice, idle = asyncio.run(scenario())
    assert "database is locked" in notice
    assert idle, "_approve must release _busy even when approve_one raises sqlite3.Error"


def test_approve_action_swallows_connection_not_found_from_approve_one(repos: Repos) -> None:
    """A connection removed after its command was queued makes approve_one
    raise ConnectionNotFoundError -- not a sqlite3.Error. Uncaught, that
    would crash the whole dashboard over one bad command instead of just
    that one approval."""
    lot = repos.batches.create(title="lot", description=None, requested_by_agent=None)
    _ = repos.commands.add(
        batch_id=lot.id,
        server_alias="linux-1",
        server_type=ServerType.LINUX,
        command="uptime",
    )
    # No matching connection is registered, so approve_one raises
    # ConnectionNotFoundError instead of executing anything.

    async def scenario() -> tuple[str, bool]:
        async with _app(repos).run_test() as pilot:
            await pilot.pause()
            await pilot.press("y")
            await pilot.pause()
            notice = str(pilot.app.query_one("#waiting-notice").content)
            idle = not pilot.app._busy  # noqa: SLF001
            return notice, idle

    notice, idle = asyncio.run(scenario())
    assert "linux-1" in notice
    assert idle, "_approve must release _busy even when approve_one raises ConnectionNotFoundError"
