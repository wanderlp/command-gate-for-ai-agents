"""CLI commands for browsing and exporting the resolved-batch audit trail."""

from __future__ import annotations

import csv
import io
import json
from enum import StrEnum

# Typer resolves Annotated parameter types at runtime via
# inspect.signature(eval_str=True); moving this into TYPE_CHECKING (as the
# linter would otherwise suggest) makes `history export --help` raise
# NameError: name 'Path' is not defined the moment Typer builds the command.
from pathlib import Path  # noqa: TC003
from typing import TYPE_CHECKING, Annotated

import typer
from rich.console import Console

from cgate.core.paths import db_path
from cgate.db.batches import BatchesRepo
from cgate.db.commands import CommandsRepo
from cgate.db.connection import Database, init_database
from cgate.db.rows import iso

if TYPE_CHECKING:
    from cgate.db.types import Batch, Command

history_app = typer.Typer(help="Browse and export the resolved-batch audit trail.")
console = Console()

_CSV_FIELDNAMES: list[str] = [
    "batch_id",
    "batch_title",
    "batch_description",
    "requested_by_agent",
    "batch_created_at",
    "batch_resolved_at",
    "command_id",
    "position",
    "server_alias",
    "server_type",
    "command",
    "status",
    "result",
    "approved_by",
    "reason",
    "risk_label",
    "command_created_at",
    "command_resolved_at",
]


class ExportFormat(StrEnum):
    """Output format for `cgate history export`."""

    CSV = "csv"
    JSON = "json"


def _csv_row(batch: Batch, command: Command) -> dict[str, str]:
    """Flatten one command, with its batch's context repeated, into a CSV row.

    One row per command (not per batch) so a spreadsheet or `awk`/`grep`
    over the export can filter/sort by any command-level field directly.
    """
    return {
        "batch_id": batch.id,
        "batch_title": batch.title,
        "batch_description": batch.description or "",
        "requested_by_agent": batch.requested_by_agent or "",
        "batch_created_at": iso(batch.created_at),
        "batch_resolved_at": iso(batch.resolved_at) if batch.resolved_at else "",
        "command_id": command.id,
        "position": str(command.position),
        "server_alias": command.server_alias,
        "server_type": command.server_type.value,
        "command": command.command,
        "status": command.status.value,
        "result": command.result or "",
        "approved_by": command.approved_by or "",
        "reason": command.reason or "",
        "risk_label": command.risk_label or "",
        "command_created_at": iso(command.created_at),
        "command_resolved_at": iso(command.resolved_at) if command.resolved_at else "",
    }


def _json_command(command: Command) -> dict[str, object]:
    return {
        "id": command.id,
        "position": command.position,
        "server_alias": command.server_alias,
        "server_type": command.server_type.value,
        "command": command.command,
        "status": command.status.value,
        "result": command.result,
        "approved_by": command.approved_by,
        "reason": command.reason,
        "risk_label": command.risk_label,
        "created_at": iso(command.created_at),
        "resolved_at": iso(command.resolved_at) if command.resolved_at else None,
    }


def _json_batch(batch: Batch, commands: list[Command]) -> dict[str, object]:
    """Nest a batch's commands under it.

    The natural shape for JSON, unlike the CSV export's
    one-row-per-command flattening.
    """
    return {
        "batch_id": batch.id,
        "title": batch.title,
        "description": batch.description,
        "requested_by_agent": batch.requested_by_agent,
        "created_at": iso(batch.created_at),
        "resolved_at": iso(batch.resolved_at) if batch.resolved_at else None,
        "commands": [_json_command(command) for command in commands],
    }


def _render_csv(batches: list[Batch], commands_repo: CommandsRepo) -> str:
    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=_CSV_FIELDNAMES)
    writer.writeheader()
    for batch in batches:
        for command in commands_repo.list_for_batch(batch.id):
            writer.writerow(_csv_row(batch, command))
    return buffer.getvalue()


def _render_json(batches: list[Batch], commands_repo: CommandsRepo) -> str:
    payload = [_json_batch(batch, commands_repo.list_for_batch(batch.id)) for batch in batches]
    return json.dumps(payload, indent=2)


@history_app.command("export")
def export_cmd(
    *,
    output: Annotated[
        Path | None,
        typer.Option(
            "--output",
            "-o",
            help="File to write to. Prints to stdout when omitted.",
        ),
    ] = None,
    export_format: Annotated[
        ExportFormat,
        typer.Option("--format", "-f", help="Output format."),
    ] = ExportFormat.CSV,
    limit: Annotated[
        int | None,
        typer.Option(
            "--limit",
            help=(
                "Cap how many resolved batches to include (most recently resolved "
                "first). Exports the full audit trail by default."
            ),
        ),
    ] = None,
) -> None:
    """Export every resolved batch and its commands -- the full audit trail.

    A human-only export: this reads the same data `cgate watch`'s History
    screen (`h`) shows, for compliance reporting or offline analysis. Not
    exposed to AI agents over MCP -- an agent that proposed a batch can
    already poll its own `check_status(batch_id)` at any time, resolved or
    not, and there's no reason to hand it a browse of everyone else's.
    """
    db = Database(path=db_path())
    init_database(db)
    batches_repo = BatchesRepo(db)
    commands_repo = CommandsRepo(db)
    resolved = batches_repo.list_resolved(limit=limit)

    text = (
        _render_csv(resolved, commands_repo)
        if export_format is ExportFormat.CSV
        else _render_json(resolved, commands_repo)
    )

    if output is None:
        typer.echo(text)
        return
    _ = output.write_text(text, encoding="utf-8")
    console.print(f"Wrote [bold]{len(resolved)}[/bold] resolved batch(es) to {output}")


__all__ = ["history_app"]
