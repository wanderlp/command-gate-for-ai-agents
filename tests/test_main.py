"""Tests for the top-level `main()` entry point (issue #12) and the root callback."""

from __future__ import annotations

import sqlite3
from typing import TYPE_CHECKING
from unittest.mock import patch

import pytest
from typer.testing import CliRunner

from cgate.cli.main import app, main

if TYPE_CHECKING:
    from pathlib import Path


def test_main_converts_uncaught_sqlite_error_into_clean_exit(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """A locked/corrupted DB must not surface as a raw traceback."""
    with (
        patch("cgate.cli.main.app", side_effect=sqlite3.OperationalError("database is locked")),
        pytest.raises(SystemExit) as exc_info,
    ):
        main()

    assert exc_info.value.code == 1
    assert "database is locked" in capsys.readouterr().err


def test_main_does_not_swallow_other_exceptions() -> None:
    """Only sqlite3.Error is converted; anything else still propagates."""
    with (
        patch("cgate.cli.main.app", side_effect=RuntimeError("boom")),
        pytest.raises(RuntimeError, match="boom"),
    ):
        main()


def test_bare_invocation_shows_help_when_nothing_to_auto_install(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """dev mode / already-installed: maybe_auto_install returns False, so a
    bare `cgate` falls through to the same help it always showed."""
    monkeypatch.setattr("cgate.cli.main.maybe_auto_install", lambda: False)

    result = CliRunner().invoke(app, [])

    assert result.exit_code == 0
    assert "Usage:" in result.stdout


def test_bare_invocation_skips_help_when_auto_install_ran(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A fresh download: maybe_auto_install handles everything and returns
    True, so root() must not also print the generic help text."""
    monkeypatch.setattr("cgate.cli.main.maybe_auto_install", lambda: True)

    result = CliRunner().invoke(app, [])

    assert result.exit_code == 0
    assert "Usage:" not in result.stdout


def test_version_flag_never_triggers_auto_install(monkeypatch: pytest.MonkeyPatch) -> None:
    """--version's eager callback must exit before root()'s body -- and
    therefore before maybe_auto_install -- ever runs."""
    calls: list[None] = []
    monkeypatch.setattr(
        "cgate.cli.main.maybe_auto_install", lambda: calls.append(None) or False
    )

    result = CliRunner().invoke(app, ["--version"])

    assert result.exit_code == 0
    assert calls == []


def test_real_subcommand_never_triggers_auto_install(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Any actual subcommand sets ctx.invoked_subcommand, so root() must
    return immediately without considering auto-install at all."""
    monkeypatch.setenv("CGATE_DB_PATH", str(tmp_path / "cgate.db"))
    calls: list[None] = []
    monkeypatch.setattr(
        "cgate.cli.main.maybe_auto_install", lambda: calls.append(None) or False
    )

    result = CliRunner().invoke(app, ["connections", "list"])

    assert result.exit_code == 0, result.stdout
    assert calls == []
