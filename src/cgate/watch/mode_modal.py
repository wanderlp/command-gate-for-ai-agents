"""Confirmation modal for toggling the global behavior mode (PROPOSE <-> AUTO)."""

from __future__ import annotations

import getpass
import sqlite3
from typing import TYPE_CHECKING, ClassVar

from textual.containers import Vertical
from textual.screen import ModalScreen
from textual.widgets import Static
from typing_extensions import override

from cgate.db.mode import AppModeNotSetError, Mode

if TYPE_CHECKING:
    from textual.app import ComposeResult
    from textual.events import Key

    from cgate.db.mode import AppModeRepo


def _updated_by() -> str:
    """Return the OS username for the audit column, falling back to 'unknown'."""
    try:
        return getpass.getuser() or "unknown"
    except (KeyError, OSError):
        return "unknown"


def mode_markup(mode: Mode) -> str:
    """Render a mode label: yellow for PROPOSE (safe), red for AUTO (live fire)."""
    match mode:
        case Mode.PROPOSE:
            return "[yellow]PROPOSE[/yellow]"
        case Mode.AUTO:
            return "[red]AUTO ⚡[/red]"


class ModeModal(ModalScreen[bool]):
    """Ask the user to confirm switching the global mode to the OTHER mode.

    Dismisses with ``True`` when the user pressed ``y`` and the new mode was
    persisted; dismisses with ``False`` on any other key, with no writes.
    """

    CSS: ClassVar[str] = """
    ModeModal { align: center middle; }
    #mode-dialog {
        width: 64;
        height: auto;
        border: solid $panel;
        background: $surface;
        padding: 1 2;
    }
    #mode-error { color: red; }
    """

    _mode_repo: AppModeRepo  # class-level annotation required by strict mode
    _target: Mode  # class-level annotation required by strict mode

    def __init__(self, *, mode_repo: AppModeRepo) -> None:
        """Store the repository used to read the current mode and persist the new one."""
        super().__init__()
        self._mode_repo = mode_repo
        self._target = Mode.PROPOSE

    @override
    def compose(self) -> ComposeResult:
        """Show the current mode, the target mode, and the confirm/cancel hint."""
        try:
            current = self._mode_repo.get().mode
        except AppModeNotSetError:
            # Safe-by-default: an unset mode behaves as PROPOSE everywhere else.
            current = Mode.PROPOSE
        self._target = Mode.AUTO if current is Mode.PROPOSE else Mode.PROPOSE
        with Vertical(id="mode-dialog"):
            yield Static("[bold]Switch global mode[/bold]")
            yield Static(f"Current mode: {mode_markup(current)}")
            yield Static(f"Switch to:    {mode_markup(self._target)}")
            if self._target is Mode.AUTO:
                yield Static(
                    "[red]In AUTO mode, commands for servers with auto-approve "
                    "run without manual approval.[/red]"
                )
            yield Static("[dim]y = confirm — any other key cancels[/dim]")
            yield Static("", id="mode-error")

    def on_key(self, event: Key) -> None:
        """Confirm on ``y``; cancel on any other key, writing nothing."""
        if event.key != "y":
            self.dismiss(False)  # noqa: FBT003 - ModalScreen[bool].dismiss takes the result positionally
            return
        try:
            _ = self._mode_repo.set(mode=self._target, updated_by=_updated_by())
        except sqlite3.Error as exc:
            _ = self.query_one("#mode-error", Static).update(
                f"[red]Could not save the mode:[/red] {exc}"
            )
            return
        self.dismiss(True)  # noqa: FBT003 - ModalScreen[bool].dismiss takes the result positionally


__all__ = ["ModeModal"]
