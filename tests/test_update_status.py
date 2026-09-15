"""Tests for ``cgate update status``."""

from __future__ import annotations

from pathlib import Path

import pytest
from typer.testing import CliRunner

from cgate.cli.main import app


@pytest.fixture
def runner() -> CliRunner:
    return CliRunner()


def test_status_prints_current_version(
    runner: CliRunner, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr("cgate.cli.update.__version__", "1.2.3")
    monkeypatch.setattr("cgate.cli.update.current_binary_path", lambda: None)
    monkeypatch.setattr("cgate.cli.update.data_dir", lambda: tmp_path / "missing")

    result = runner.invoke(app, ["update", "status"])

    assert result.exit_code == 0
    assert "cgate 1.2.3" in result.output


def test_status_reports_missing_log_when_nothing_has_run(
    runner: CliRunner, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr("cgate.cli.update.current_binary_path", lambda: None)
    monkeypatch.setattr("cgate.cli.update.data_dir", lambda: tmp_path / "missing")

    result = runner.invoke(app, ["update", "status"])

    assert "No update.log yet" in result.output


def test_status_flags_a_staged_download(
    runner: CliRunner, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    binary = tmp_path / "cgate.exe"
    binary.write_bytes(b"current")
    (tmp_path / "cgate.exe.new").write_bytes(b"staged")

    monkeypatch.setattr("cgate.cli.update.current_binary_path", lambda: binary)
    monkeypatch.setattr("cgate.cli.update.data_dir", lambda: tmp_path / "data-missing")

    result = runner.invoke(app, ["update", "status"])

    unwrapped = result.output.replace("\n", "")
    assert "Staged download present" in unwrapped
    assert str(binary.with_name("cgate.exe.new")) in unwrapped


def test_status_flags_a_rollback_snapshot(
    runner: CliRunner, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    binary = tmp_path / "cgate.exe"
    binary.write_bytes(b"current")
    (tmp_path / "cgate.exe.previous").write_bytes(b"old")

    monkeypatch.setattr("cgate.cli.update.current_binary_path", lambda: binary)
    monkeypatch.setattr("cgate.cli.update.data_dir", lambda: tmp_path / "data-missing")

    result = runner.invoke(app, ["update", "status"])

    unwrapped = result.output.replace("\n", "")
    assert "Rollback snapshot present" in unwrapped
    assert str(binary.with_name("cgate.exe.previous")) in unwrapped


def test_status_tails_the_update_log(
    runner: CliRunner, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    data = tmp_path / "data"
    data.mkdir()
    lines = [f"[2026-01-01T00:00:{i:02d}+00:00] line {i}" for i in range(20)]
    (data / "update.log").write_text("\n".join(lines) + "\n", encoding="utf-8")

    monkeypatch.setattr("cgate.cli.update.current_binary_path", lambda: None)
    monkeypatch.setattr("cgate.cli.update.data_dir", lambda: data)

    result = runner.invoke(app, ["update", "status"])

    unwrapped = result.output.replace("\n", "")
    assert "Last 15 line(s)" in unwrapped
    assert "line 19" in unwrapped
    assert "line 4" not in unwrapped  # only the most recent 15 of 20 lines shown
