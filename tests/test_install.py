"""Tests for the `cgate install` top-level command."""

from __future__ import annotations

import sys
from typing import TYPE_CHECKING

import pytest
from typer.testing import CliRunner

from cgate.cli.install import maybe_auto_install
from cgate.cli.main import app
from cgate.core import path_env
from cgate.mcp_installer import ClientInstall
from tests.test_path_env import FakeWinReg

if TYPE_CHECKING:
    from pathlib import Path


@pytest.fixture
def runner() -> CliRunner:
    return CliRunner()


@pytest.fixture
def isolated_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> dict:
    """Wire the install command to operate entirely under tmp_path: a fake
    source binary, a fake install directory, and PATH-registration
    functions mocked out so no test ever touches the real registry or a
    real shell rc file by default."""
    name = "cgate.exe" if sys.platform == "win32" else "cgate"
    source = tmp_path / "downloads" / name
    source.parent.mkdir()
    source.write_bytes(b"fake binary")
    if sys.platform != "win32":
        source.chmod(0o755)
    bin_dir = tmp_path / "bin"
    target = bin_dir / name

    monkeypatch.setattr("cgate.cli.install.current_binary_path", lambda: source)
    monkeypatch.setattr("cgate.cli.install.install_dir", lambda: bin_dir)
    monkeypatch.setattr("cgate.cli.install.install_target_path", lambda: target)
    monkeypatch.setattr("cgate.cli.install.ensure_windows_user_path", lambda _d: "added")
    monkeypatch.setattr(
        "cgate.cli.install.ensure_posix_shell_path",
        lambda _d: ("added", tmp_path / ".zshrc"),
    )
    return {"source": source, "target": target, "bin_dir": bin_dir}


def test_install_help_lists_no_hidden_requirements(runner: CliRunner) -> None:
    result = runner.invoke(app, ["install", "--help"])
    assert result.exit_code == 0
    assert "install" in result.stdout.lower()


def test_install_copies_binary_and_preserves_executable_bit(
    runner: CliRunner, isolated_env: dict
) -> None:
    result = runner.invoke(app, ["install"])

    assert result.exit_code == 0, result.stdout
    target = isolated_env["target"]
    assert target.exists()
    assert target.read_bytes() == b"fake binary"
    if sys.platform != "win32":
        assert target.stat().st_mode & 0o111
    assert "copied to" in result.stdout


def test_install_reports_path_already_added(runner: CliRunner, isolated_env: dict) -> None:
    result = runner.invoke(app, ["install"])

    assert result.exit_code == 0, result.stdout
    assert "added" in result.stdout.lower()
    assert "Next: run" in result.stdout
    assert "cgate mcp install" in result.stdout


def test_install_reports_path_already_present(
    runner: CliRunner, isolated_env: dict, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("cgate.cli.install.ensure_windows_user_path", lambda _d: "already_present")
    monkeypatch.setattr(
        "cgate.cli.install.ensure_posix_shell_path",
        lambda _d: ("already_present", isolated_env["bin_dir"] / ".zshrc"),
    )

    result = runner.invoke(app, ["install"])

    assert result.exit_code == 0, result.stdout
    assert "already on PATH" in result.stdout


def test_install_skips_copy_when_already_running_from_target(
    runner: CliRunner, isolated_env: dict, monkeypatch: pytest.MonkeyPatch
) -> None:
    target = isolated_env["target"]
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(b"already installed")
    monkeypatch.setattr("cgate.cli.install.current_binary_path", lambda: target)

    result = runner.invoke(app, ["install"])

    assert result.exit_code == 0, result.stdout
    assert target.read_bytes() == b"already installed"  # untouched, not re-copied
    assert "already running from" in result.stdout


def test_install_refuses_to_overwrite_a_different_existing_file(
    runner: CliRunner, isolated_env: dict
) -> None:
    target = isolated_env["target"]
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(b"some other cgate install")

    result = runner.invoke(app, ["install"])

    assert result.exit_code == 1
    assert target.read_bytes() == b"some other cgate install"  # never overwritten
    assert "update apply" in " ".join(result.stdout.split())


def test_install_dev_mode_is_graceful(runner: CliRunner, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("cgate.cli.install.current_binary_path", lambda: None)

    result = runner.invoke(app, ["install"])

    assert result.exit_code == 0, result.stdout
    assert "not running from a packaged binary" in result.stdout.lower()


@pytest.mark.skipif(sys.platform != "win32", reason="exercises the real Windows PATH mechanics")
def test_install_end_to_end_never_touches_the_real_registry(
    runner: CliRunner, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Runs through cgate.core.path_env's real ensure_windows_user_path
    (not mocked away like isolated_env does), but with winreg replaced by
    an in-memory fake -- proving the full CLI path never reaches the real
    HKEY_CURRENT_USER\\Environment\\Path."""
    fake = FakeWinReg()
    monkeypatch.setattr(path_env, "winreg", fake)

    source = tmp_path / "downloads" / "cgate.exe"
    source.parent.mkdir()
    source.write_bytes(b"fake binary")
    bin_dir = tmp_path / "bin"

    monkeypatch.setattr("cgate.cli.install.current_binary_path", lambda: source)
    monkeypatch.setattr("cgate.cli.install.install_dir", lambda: bin_dir)
    monkeypatch.setattr("cgate.cli.install.install_target_path", lambda: bin_dir / "cgate.exe")

    result = runner.invoke(app, ["install"])

    assert result.exit_code == 0, result.stdout
    assert len(fake.set_value_calls) == 1
    assert fake.set_value_calls[0][2] == str(bin_dir)


# --- maybe_auto_install (bare-invocation first-run trigger) ---


def test_maybe_auto_install_returns_false_in_dev_mode(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("cgate.cli.install.current_binary_path", lambda: None)
    assert maybe_auto_install() is False


def test_maybe_auto_install_returns_false_when_already_installed(
    isolated_env: dict, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("cgate.cli.install.current_binary_path", lambda: isolated_env["target"])
    assert maybe_auto_install() is False


def test_maybe_auto_install_performs_full_first_run_setup(
    isolated_env: dict,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    # Never let this test's auto-registration step reach the real
    # detect_clients(), which would scan this actual machine's home
    # directory for real IA client configs.
    monkeypatch.setattr("cgate.cli.install.detect_clients", list)

    result = maybe_auto_install()

    assert result is True
    assert isolated_env["target"].exists()
    output = capsys.readouterr().out
    assert "First run detected" in output
    assert "Almost done" in output


def test_maybe_auto_install_registers_detected_clients_without_prompting(
    isolated_env: dict,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    fake_client = ClientInstall(
        name="opencode", label="opencode", config_path=tmp_path / "opencode.jsonc"
    )
    monkeypatch.setattr("cgate.cli.install.detect_clients", lambda: [fake_client])
    registered: list[tuple] = []
    monkeypatch.setattr(
        "cgate.cli.install.register",
        lambda client, command, args: registered.append((client, command, args)),
    )

    result = maybe_auto_install()

    assert result is True
    assert len(registered) == 1
    client, command, args = registered[0]
    assert client is fake_client
    assert command == str(isolated_env["target"])
    assert args == ["mcp", "serve"]
    assert "Registered opencode" in capsys.readouterr().out


def test_maybe_auto_install_reports_no_clients_detected(
    isolated_env: dict,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr("cgate.cli.install.detect_clients", list)

    maybe_auto_install()

    assert "No IA clients detected yet" in capsys.readouterr().out
