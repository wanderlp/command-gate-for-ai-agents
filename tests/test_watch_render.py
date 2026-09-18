"""Unit tests for the pure markup helpers in cgate.watch.render."""

from __future__ import annotations

from datetime import UTC, datetime

from cgate.db.types import Batch, BatchId, Command, CommandId, CommandStatus, ServerType
from cgate.watch.render import (
    approver_badge,
    format_batch_header,
    format_command_detail,
    format_command_line,
    format_queue_summary,
)

_NOW = datetime(2026, 1, 1, tzinfo=UTC)


def _command(
    *,
    status: CommandStatus = CommandStatus.PENDING,
    result: str | None = None,
    approved_by: str | None = None,
    reason: str | None = None,
    command: str = "uptime",
) -> Command:
    return Command(
        id=CommandId("c1"),
        batch_id=BatchId("b1"),
        position=0,
        server_alias="linux-1",
        server_type=ServerType.LINUX,
        command=command,
        status=status,
        result=result,
        approved_by=approved_by,
        created_at=_NOW,
        resolved_at=None,
        reason=reason,
    )


def _batch(*, title: str = "deploy", description: str | None = None) -> Batch:
    return Batch(
        id=BatchId("b1"),
        title=title,
        description=description,
        requested_by_agent="agent",
        created_at=_NOW,
        resolved_at=None,
    )


def test_approver_badge_empty_when_not_yet_approved() -> None:
    assert approver_badge(None) == ""


def test_approver_badge_marks_auto_execution() -> None:
    badge = approver_badge("auto:watch:wlopez")
    assert "auto" in badge
    assert "wlopez" not in badge


def test_approver_badge_shows_human_username() -> None:
    badge = approver_badge("wlopez")
    assert "wlopez" in badge
    assert "auto" not in badge


def test_approver_badge_escapes_markup_in_username() -> None:
    badge = approver_badge("[bold]evil[/bold]")
    assert "\\[bold]" in badge


def test_format_command_line_includes_reason_when_present() -> None:
    line = format_command_line(_command(reason="cleaning up disk space"))
    assert "cleaning up disk space" in line


def test_format_command_line_omits_reason_line_when_absent() -> None:
    line = format_command_line(_command(reason=None))
    assert "↳" not in line


def test_format_command_line_escapes_markup_in_command_text() -> None:
    line = format_command_line(_command(command="echo [bold]hi[/bold]"))
    assert "\\[bold]" in line


def test_format_command_detail_shows_full_untruncated_result() -> None:
    long_result = "x" * 500
    detail = format_command_detail(_command(status=CommandStatus.EXECUTED, result=long_result))
    assert long_result in detail


def test_format_command_detail_includes_reason_and_approver() -> None:
    detail = format_command_detail(
        _command(
            status=CommandStatus.EXECUTED,
            approved_by="auto:watch:wlopez",
            reason="restart the crashed service",
        )
    )
    assert "restart the crashed service" in detail
    assert "auto" in detail


def test_format_batch_header_escapes_markup_in_title() -> None:
    header = format_batch_header(_batch(title="[red]fake[/red] title"))
    assert "\\[red]" in header


def test_format_queue_summary_empty_when_nothing_pending() -> None:
    assert format_queue_summary(pending_commands=0, waiting_batches=0) == ""


def test_format_queue_summary_shows_count_with_a_single_batch() -> None:
    """Regression: the old format_waiting_notice showed nothing at all
    with just one batch pending, even if it had several commands left."""
    summary = format_queue_summary(pending_commands=3, waiting_batches=0)
    assert "3 pending command" in summary
    assert "waiting" not in summary


def test_format_queue_summary_also_mentions_waiting_batches() -> None:
    summary = format_queue_summary(pending_commands=5, waiting_batches=2)
    assert "5 pending command" in summary
    assert "2 batch(es) waiting" in summary
