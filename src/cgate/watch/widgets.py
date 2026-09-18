"""Shared Textual widgets used by both the live dashboard and the history browser."""

from __future__ import annotations

from typing import TYPE_CHECKING

from textual.widgets import Static

from cgate.watch.render import format_command_line

if TYPE_CHECKING:
    from cgate.db.types import Command, CommandId


class CommandRow(Static):
    """One command line, updatable in place.

    Lives in its own module (rather than `watch/app.py`, where it used
    to be defined) so `watch/history_modal.py` can reuse it without
    creating an import cycle back into `app.py`.
    """

    command_id: CommandId

    def __init__(self, command: Command) -> None:
        """Render the initial line for this command and remember its id."""
        super().__init__(format_command_line(command), markup=True)
        self.command_id = command.id

    def update_command(self, command: Command) -> None:
        """Refresh this row's text for the command's current state."""
        _ = self.update(format_command_line(command))


__all__ = ["CommandRow"]
