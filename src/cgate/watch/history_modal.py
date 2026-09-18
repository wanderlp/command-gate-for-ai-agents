"""Read-only browser for resolved batches (`h` key in `cgate watch`).

The live queue drops a batch the instant it resolves -- `resolve_at IS
NULL` is exactly what makes it disappear from `list_pending`. Without
this, there was no way to look back at anything that already went
through: not in the TUI, not from any CLI command.
"""

from __future__ import annotations

import sqlite3
from typing import TYPE_CHECKING, ClassVar

from textual.binding import Binding
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import ListItem, ListView, Static
from typing_extensions import override

from cgate.watch.command_detail_modal import CommandDetailModal
from cgate.watch.render import format_batch_header
from cgate.watch.theme import CGATE_THEME
from cgate.watch.widgets import CommandRow

if TYPE_CHECKING:
    from textual.app import ComposeResult
    from textual.binding import BindingType

    from cgate.db.batches import BatchesRepo
    from cgate.db.commands import CommandsRepo
    from cgate.db.types import Batch, BatchId

_HISTORY_LIMIT = 50


class BatchHistoryRow(ListItem):
    """One resolved batch in the history list, carrying its id for lookups."""

    batch_id: BatchId

    def __init__(self, batch: Batch) -> None:
        """Render the resolved timestamp and title, and remember the batch id."""
        resolved = batch.resolved_at.strftime("%Y-%m-%d %H:%M") if batch.resolved_at else "?"
        super().__init__(Static(f"[dim]{resolved}[/dim]  {batch.title}", markup=True))
        self.batch_id = batch.id


class HistoryModal(ModalScreen[None]):
    """Browse resolved batches: title/timestamp list on the left, commands on the right."""

    CSS: ClassVar[str] = """
    HistoryModal { align: center middle; }
    #history-dialog {
        width: 96%;
        height: 90%;
        border: round $primary;
        background: $surface;
    }
    #history-title { padding: 1 2 0 2; }
    #history-hint { padding: 0 2 1 2; }
    #history-body { height: 1fr; }
    #history-list-pane { width: 40; border-right: solid $panel; padding: 1; }
    #history-detail-pane { padding: 1 2; }
    """

    BINDINGS: ClassVar[list[BindingType]] = [
        Binding("escape", "close", "Close", priority=True),
        Binding("q", "close", "Close", show=False, priority=True),
    ]

    _batches: BatchesRepo
    _commands: CommandsRepo
    _resolved: list[Batch]

    def __init__(self, *, batches: BatchesRepo, commands: CommandsRepo) -> None:
        """Store the repositories used to list resolved batches and their commands."""
        super().__init__()
        self._batches = batches
        self._commands = commands
        self._resolved = []

    @override
    def compose(self) -> ComposeResult:
        """Lay out the title, the resolved-batch list, and the detail pane."""
        with Vertical(id="history-dialog"):
            yield Static("[bold]History[/bold] [dim](most recently resolved first)[/dim]",
                          id="history-title")
            with Horizontal(id="history-body"):
                with Vertical(id="history-list-pane"):
                    yield ListView(id="history-list")
                with VerticalScroll(id="history-detail-pane"):
                    yield Static(id="history-detail-header")
                    yield ListView(id="history-rows")
            yield Static(
                (
                    "[dim]↑/↓ = browse batches — Enter on a command = view full result "
                    "— Esc = close[/dim]"
                ),
                id="history-hint",
            )

    def on_mount(self) -> None:
        """Load the resolved batches and show the most recent one's commands."""
        try:
            self._resolved = self._batches.list_resolved(limit=_HISTORY_LIMIT)
        except sqlite3.Error as exc:
            error = CGATE_THEME.error
            self.query_one("#history-detail-header", Static).update(
                f"[{error}]Could not read history:[/{error}] {exc}"
            )
            return
        list_view = self.query_one("#history-list", ListView)
        if not self._resolved:
            self.query_one("#history-detail-header", Static).update(
                "[dim]No resolved batches yet.[/dim]"
            )
            return
        for batch in self._resolved:
            _ = list_view.append(BatchHistoryRow(batch))
        list_view.index = 0
        self._show_batch(self._resolved[0])
        _ = list_view.focus()

    def on_list_view_highlighted(self, event: ListView.Highlighted) -> None:
        """Show the highlighted batch's commands as the sidebar cursor moves."""
        if event.list_view.id != "history-list" or event.item is None:
            return
        if isinstance(event.item, BatchHistoryRow):
            batch = next(
                (b for b in self._resolved if b.id == event.item.batch_id), None
            )
            if batch is not None:
                self._show_batch(batch)

    def on_list_view_selected(self, event: ListView.Selected) -> None:
        """Open the full-detail modal for the command highlighted in the detail pane."""
        if event.list_view.id != "history-rows":
            return
        row = event.item.query_one(CommandRow)
        try:
            command = self._commands.get(row.command_id)
        except sqlite3.Error as exc:
            error = CGATE_THEME.error
            self.query_one("#history-detail-header", Static).update(
                f"[{error}]Could not read this command:[/{error}] {exc}"
            )
            return
        if command is not None:
            _ = self.app.push_screen(CommandDetailModal(command))  # pyright: ignore[reportUnknownMemberType]

    def _show_batch(self, batch: Batch) -> None:
        """Render one resolved batch's header and its commands in the detail pane."""
        self.query_one("#history-detail-header", Static).update(format_batch_header(batch))
        rows = self.query_one("#history-rows", ListView)
        _ = rows.clear()
        try:
            commands_in_batch = self._commands.list_for_batch(batch.id)
        except sqlite3.Error as exc:
            error = CGATE_THEME.error
            self.query_one("#history-detail-header", Static).update(
                f"[{error}]Could not read this batch's commands:[/{error}] {exc}"
            )
            return
        for command in commands_in_batch:
            _ = rows.append(ListItem(CommandRow(command)))
        if commands_in_batch:
            rows.index = 0

    def action_close(self) -> None:
        """Dismiss without writing anything -- this view is read-only."""
        _ = self.dismiss(None)


__all__ = ["HistoryModal"]
