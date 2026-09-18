"""Read-only detail view for one command: full result, reason, audit fields."""

from __future__ import annotations

from typing import TYPE_CHECKING, ClassVar

from textual.binding import Binding
from textual.containers import Vertical, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import Static
from typing_extensions import override

from cgate.watch.render import format_command_detail

if TYPE_CHECKING:
    from textual.app import ComposeResult
    from textual.binding import BindingType

    from cgate.db.types import Command


class CommandDetailModal(ModalScreen[None]):
    """Full detail for one command: untruncated result, reason, and approver.

    Unlike the queue rows -- capped at `render._RESULT_SNIPPET_MAX_CHARS`
    and one line -- this shows the command's full result. Read-only:
    makes no writes, dismisses on Escape or Enter.
    """

    CSS: ClassVar[str] = """
    CommandDetailModal { align: center middle; }
    #detail-dialog {
        width: 90%;
        height: 80%;
        border: round $primary;
        background: $surface;
        padding: 1 2;
    }
    #detail-body { height: 1fr; margin-top: 1; }
    """

    BINDINGS: ClassVar[list[BindingType]] = [
        Binding("escape", "close", "Close", show=False, priority=True),
        Binding("enter", "close", "Close", show=False, priority=True),
    ]

    _command: Command

    def __init__(self, command: Command) -> None:
        """Remember the command whose detail this modal shows."""
        super().__init__()
        self._command = command

    @override
    def compose(self) -> ComposeResult:
        """Show the title, the full command detail, and the close hint."""
        with Vertical(id="detail-dialog"):
            yield Static("[bold]Command detail[/bold]")
            with VerticalScroll(id="detail-body"):
                yield Static(format_command_detail(self._command), id="detail-text", markup=True)
            yield Static("[dim]Esc / Enter = close[/dim]")

    def action_close(self) -> None:
        """Dismiss without writing anything -- this view is read-only."""
        _ = self.dismiss(None)


__all__ = ["CommandDetailModal"]
