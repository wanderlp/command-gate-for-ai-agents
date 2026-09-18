"""Pure markup helpers for the cgate watch TUI (spec §Colors in cgate watch)."""

from __future__ import annotations

from typing import TYPE_CHECKING, Final

from rich.markup import escape as escape_markup

from cgate.db.types import CommandStatus, ServerType

if TYPE_CHECKING:
    from cgate.db.types import Batch, Command

_RESULT_SNIPPET_MAX_CHARS: Final = 200

_STATUS_GLYPHS: Final[dict[CommandStatus, str]] = {
    CommandStatus.PENDING: "[yellow]●[/yellow]",
    CommandStatus.APPROVED: "[yellow]◐[/yellow]",
    CommandStatus.EXECUTED: "[green]✓[/green]",
    CommandStatus.REJECTED: "[red]✗[/red]",
    CommandStatus.FAILED: "[red]✗[/red]",
}


def status_glyph(status: CommandStatus) -> str:
    """Return the colored status symbol for one command."""
    return _STATUS_GLYPHS[status]


def server_badge(server_type: ServerType) -> str:
    """Render a compact, colored server-type badge."""
    match server_type:
        case ServerType.WINDOWS:
            return "[cyan]WIN[/cyan]"
        case ServerType.LINUX:
            return "[green]LNX[/green]"


def approver_badge(approved_by: str | None) -> str:
    """Render who or what approved a command.

    ``mcp_server/tools.py`` prefixes auto-executed approvals with
    ``auto:`` (see ``_auto_approve_by``) specifically so this can tell
    them apart from a human's OS username at render time.
    """
    if not approved_by:
        return ""
    if approved_by.startswith("auto:"):
        return " [cyan]⚙ auto[/cyan]"
    return f" [green]👤 {escape_markup(approved_by)}[/green]"


def risk_warning(risk_label: str | None) -> str:
    """Render the high-blast-radius warning line, or an empty string when unflagged.

    Shown regardless of PROPOSE/AUTO mode -- a human scanning the queue
    should see it either way, not just when it happened to be the reason
    AUTO mode queued the command instead of running it.
    """
    if not risk_label:
        return ""
    return f"[bold red]⚠ RISKY:[/bold red] [red]{escape_markup(risk_label)}[/red]"


def format_batch_header(batch: Batch) -> str:
    """Render a bold cyan title with an optional grey italic description below it."""
    lines = [f"[bold cyan]{escape_markup(batch.title)}[/bold cyan]"]
    if batch.description:
        lines.append(f"[grey50 italic]{escape_markup(batch.description)}[/grey50 italic]")
    return "\n".join(lines)


def format_queue_summary(*, pending_commands: int, waiting_batches: int) -> str:
    """Render the always-on queue summary, or an empty string when it's empty.

    Replaces the old "N batch(es) waiting" notice, which only ever
    appeared once a *second* batch queued up -- with only one batch
    pending (the common case) it showed nothing at all, even though
    there could be several commands in it still needing a decision.
    """
    if pending_commands <= 0:
        return ""
    parts = [f"{pending_commands} pending command(s)"]
    if waiting_batches > 0:
        parts.append(f"{waiting_batches} batch(es) waiting")
    return f"[yellow]▲ {' · '.join(parts)}[/yellow]"


def _result_snippet(result: str, *, max_chars: int = _RESULT_SNIPPET_MAX_CHARS) -> str:
    """Trim a result blob to its first line, capped to a display-friendly length."""
    stripped = result.strip()
    if not stripped:
        return ""
    first_line = stripped.splitlines()[0]
    if len(first_line) > max_chars:
        return first_line[:max_chars] + "…"
    return first_line


def format_command_line(command: Command) -> str:
    """Render one command row: status glyph, text, badges, reason, result snippet."""
    glyph = status_glyph(command.status)
    badge = server_badge(command.server_type)
    line = (
        f"{glyph} {escape_markup(command.command)}  {badge} "
        f"[dim]{escape_markup(command.server_alias)}[/dim]"
        f"{approver_badge(command.approved_by)}"
    )
    if command.risk_label:
        line += f"\n    {risk_warning(command.risk_label)}"
    if command.reason:
        line += f"\n    [dim italic]↳ {escape_markup(command.reason)}[/dim italic]"
    if command.status is CommandStatus.APPROVED:
        line += "\n    [dim]⏳ running…[/dim]"
    elif command.status is CommandStatus.EXECUTED and command.result:
        line += f"\n    [dim]{escape_markup(_result_snippet(command.result))}[/dim]"
    elif command.status is CommandStatus.FAILED and command.result:
        line += f"\n    [red dim]{escape_markup(_result_snippet(command.result))}[/red dim]"
    return line


def format_command_detail(command: Command) -> str:
    """Render a command's full detail: status, server, reason, approver, full result.

    Unlike `format_command_line`, the result is shown in full -- not
    capped to `_RESULT_SNIPPET_MAX_CHARS` or truncated to one line.
    """
    server_line = (
        f"[dim]{escape_markup(command.server_alias)}[/dim]  {server_badge(command.server_type)}"
        f"  [dim]status: {command.status.value}[/dim]"
    )
    lines = [
        f"{status_glyph(command.status)} [bold]{escape_markup(command.command)}[/bold]",
        server_line,
    ]
    if command.risk_label:
        lines.append(risk_warning(command.risk_label))
    if command.reason:
        lines.append(f"\n[italic]Reason:[/italic] {escape_markup(command.reason)}")
    if command.approved_by:
        lines.append(f"\n[italic]Approved by:[/italic]{approver_badge(command.approved_by)}")
    if command.result:
        stripped = command.result.strip()
        if stripped:
            lines.append("\n[bold]Result:[/bold]")
            lines.append(escape_markup(stripped))
    return "\n".join(lines)
