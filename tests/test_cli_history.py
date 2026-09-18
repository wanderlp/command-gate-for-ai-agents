"""CLI tests for ``cgate history export``."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

import pytest
from typer.testing import CliRunner

from cgate.cli.main import app
from cgate.db.batches import BatchesRepo
from cgate.db.commands import CommandsRepo
from cgate.db.connection import Database, init_database
from cgate.db.types import CommandStatus, ServerType

if TYPE_CHECKING:
    from pathlib import Path


@pytest.fixture
def runner() -> CliRunner:
    return CliRunner()


@pytest.fixture
def isolated_db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Database:
    """Isolated DB so the CLI never touches the real local store."""
    db_file = tmp_path / "cgate.db"
    monkeypatch.setenv("CGATE_DB_PATH", str(db_file))
    db = Database(path=db_file)
    init_database(db)
    return db


def _seed_resolved_batch(  # noqa: PLR0913 - one param per field under test, all but db optional
    db: Database,
    *,
    title: str = "deploy v2",
    command: str = "systemctl restart nginx",
    reason: str | None = None,
    risk_label: str | None = None,
    approved_by: str = "wlopez",
    result: str = "restarted",
) -> None:
    batches = BatchesRepo(db)
    commands = CommandsRepo(db)
    lot = batches.create(title=title, description="rollout", requested_by_agent="claude")
    cmd = commands.add(
        batch_id=lot.id,
        server_alias="web-1",
        server_type=ServerType.LINUX,
        command=command,
        reason=reason,
        risk_label=risk_label,
    )
    _ = commands.update_status(
        cmd.id, status=CommandStatus.EXECUTED, approved_by=approved_by, result=result
    )
    batches.mark_resolved(lot.id)


def _seed_pending_batch(db: Database, *, title: str = "still open") -> None:
    batches = BatchesRepo(db)
    commands = CommandsRepo(db)
    lot = batches.create(title=title, description=None, requested_by_agent="claude")
    _ = commands.add(
        batch_id=lot.id, server_alias="web-1", server_type=ServerType.LINUX, command="uptime"
    )


def test_export_csv_header_only_when_nothing_resolved(
    runner: CliRunner, isolated_db: Database  # noqa: ARG001 - fixture used for its CGATE_DB_PATH side effect
) -> None:
    result = runner.invoke(app, ["history", "export"])
    assert result.exit_code == 0
    lines = result.output.strip().splitlines()
    assert len(lines) == 1
    assert "batch_id" in lines[0]
    assert "command_id" in lines[0]


def test_export_csv_includes_a_resolved_batch_and_its_command(
    runner: CliRunner, isolated_db: Database
) -> None:
    _seed_resolved_batch(isolated_db, reason="apply config change")
    result = runner.invoke(app, ["history", "export"])
    assert result.exit_code == 0
    assert "deploy v2" in result.output
    assert "systemctl restart nginx" in result.output
    assert "apply config change" in result.output
    assert "wlopez" in result.output


def test_export_csv_excludes_pending_batches(runner: CliRunner, isolated_db: Database) -> None:
    _seed_resolved_batch(isolated_db, title="resolved lot")
    _seed_pending_batch(isolated_db, title="still open")
    result = runner.invoke(app, ["history", "export"])
    assert result.exit_code == 0
    assert "resolved lot" in result.output
    assert "still open" not in result.output


def test_export_json_format_round_trips(runner: CliRunner, isolated_db: Database) -> None:
    _seed_resolved_batch(isolated_db, risk_label="recursive force delete (rm -rf)")
    result = runner.invoke(app, ["history", "export", "--format", "json"])
    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert len(payload) == 1
    assert payload[0]["title"] == "deploy v2"
    assert payload[0]["commands"][0]["risk_label"] == "recursive force delete (rm -rf)"


def test_export_respects_limit(runner: CliRunner, isolated_db: Database) -> None:
    _seed_resolved_batch(isolated_db, title="first")
    _seed_resolved_batch(isolated_db, title="second")
    result = runner.invoke(app, ["history", "export", "--format", "json", "--limit", "1"])
    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert len(payload) == 1


def test_export_writes_to_output_file_instead_of_stdout(
    runner: CliRunner, isolated_db: Database, tmp_path: Path
) -> None:
    _seed_resolved_batch(isolated_db)
    out_file = tmp_path / "export.csv"
    result = runner.invoke(app, ["history", "export", "--output", str(out_file)])
    assert result.exit_code == 0
    assert out_file.exists()
    assert "deploy v2" in out_file.read_text(encoding="utf-8")
    assert "deploy v2" not in result.output
    assert "1" in result.output  # confirmation mentions the batch count
