"""Headless Textual pilot tests for the History browser and command-detail modal."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import TYPE_CHECKING

import pytest
from textual.widgets import ListView, Static

from cgate.connections.store import ConnectionsRepo
from cgate.db.batches import BatchesRepo
from cgate.db.commands import CommandsRepo
from cgate.db.connection import Database, init_database
from cgate.db.mode import AppModeRepo
from cgate.db.server_settings import ServerSettingsRepo
from cgate.db.types import CommandStatus, ServerType
from cgate.watch.app import WatchApp
from cgate.watch.command_detail_modal import CommandDetailModal
from cgate.watch.history_modal import HistoryModal

if TYPE_CHECKING:
    from pathlib import Path


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


def _resolved_batch_with_command(repos: Repos, *, title: str, reason: str | None = None) -> None:
    lot = repos.batches.create(title=title, description=None, requested_by_agent=None)
    cmd = repos.commands.add(
        batch_id=lot.id,
        server_alias="linux-1",
        server_type=ServerType.LINUX,
        command="uptime",
        reason=reason,
    )
    repos.commands.update_status(
        cmd.id, status=CommandStatus.EXECUTED, approved_by="wlopez", result="14:32 up 3 days"
    )
    repos.batches.mark_resolved(lot.id)


def test_h_key_opens_the_history_modal(repos: Repos) -> None:
    async def scenario() -> bool:
        async with _app(repos).run_test() as pilot:
            await pilot.pause()
            await pilot.press("h")
            await pilot.pause()
            return isinstance(pilot.app.screen, HistoryModal)

    assert asyncio.run(scenario())


def test_history_shows_nothing_yet_when_no_batch_has_resolved(repos: Repos) -> None:
    async def scenario() -> str:
        async with _app(repos).run_test() as pilot:
            await pilot.pause()
            await pilot.press("h")
            await pilot.pause()
            return str(pilot.app.screen.query_one("#history-detail-header").content)

    header = asyncio.run(scenario())
    assert "No resolved batches" in header


def test_history_lists_resolved_batch_and_its_commands(repos: Repos) -> None:
    _resolved_batch_with_command(repos, title="past deploy")

    async def scenario() -> str:
        async with _app(repos).run_test() as pilot:
            await pilot.pause()
            await pilot.press("h")
            await pilot.pause()
            return str(pilot.app.screen.query_one("#history-detail-header").content)

    header = asyncio.run(scenario())
    assert "past deploy" in header


def test_history_never_shows_a_batch_still_pending(repos: Repos) -> None:
    """The whole point of this screen is resolved batches -- the live queue
    already shows anything still pending."""
    _resolved_batch_with_command(repos, title="done already")
    still_open = repos.batches.create(title="still open", description=None, requested_by_agent=None)
    _ = repos.commands.add(
        batch_id=still_open.id,
        server_alias="linux-1",
        server_type=ServerType.LINUX,
        command="uptime",
    )

    async def scenario() -> list[str]:
        async with _app(repos).run_test() as pilot:
            await pilot.pause()
            await pilot.press("h")
            await pilot.pause()
            list_view = pilot.app.screen.query_one("#history-list", ListView)
            return [str(child.query_one(Static).content) for child in list_view.children]

    titles = asyncio.run(scenario())
    assert any("done already" in title for title in titles)
    assert not any("still open" in title for title in titles)


def test_entering_a_command_in_history_opens_its_detail(repos: Repos) -> None:
    _resolved_batch_with_command(repos, title="past deploy", reason="scheduled patch window")

    async def scenario() -> bool:
        async with _app(repos).run_test() as pilot:
            await pilot.pause()
            await pilot.press("h")
            await pilot.pause()
            history = pilot.app.screen
            assert isinstance(history, HistoryModal)
            history.query_one("#history-rows", ListView).focus()
            await pilot.pause()
            await pilot.press("enter")
            await pilot.pause()
            return isinstance(pilot.app.screen, CommandDetailModal)

    assert asyncio.run(scenario())


def test_command_detail_modal_shows_full_result_and_reason(repos: Repos) -> None:
    _resolved_batch_with_command(repos, title="past deploy", reason="scheduled patch window")

    async def scenario() -> str:
        async with _app(repos).run_test() as pilot:
            await pilot.pause()
            await pilot.press("h")
            await pilot.pause()
            history = pilot.app.screen
            assert isinstance(history, HistoryModal)
            history.query_one("#history-rows", ListView).focus()
            await pilot.pause()
            await pilot.press("enter")
            await pilot.pause()
            detail = pilot.app.screen
            assert isinstance(detail, CommandDetailModal)
            return str(detail.query_one("#detail-text").content)

    body = asyncio.run(scenario())
    assert "scheduled patch window" in body
    assert "14:32 up 3 days" in body


def test_escape_closes_the_history_modal(repos: Repos) -> None:
    async def scenario() -> bool:
        async with _app(repos).run_test() as pilot:
            await pilot.pause()
            await pilot.press("h")
            await pilot.pause()
            assert isinstance(pilot.app.screen, HistoryModal)
            await pilot.press("escape")
            await pilot.pause()
            return isinstance(pilot.app.screen, HistoryModal)

    still_open = asyncio.run(scenario())
    assert not still_open
