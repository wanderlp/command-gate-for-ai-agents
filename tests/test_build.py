"""Smoke-test the platform-native PyInstaller binary."""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

_ = pytest.importorskip("PyInstaller")


def _run(command: list[str], *, cwd: Path, env: dict[str, str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(  # noqa: S603 - commands are constructed solely by this test
        command,
        cwd=cwd,
        env=env,
        capture_output=True,
        text=True,
        check=False,
        timeout=300,
    )


# IMAGE_SUBSYSTEM_WINDOWS_GUI (2): no console at any level of the process
# tree, ever. IMAGE_SUBSYSTEM_WINDOWS_CUI (3): a console-subsystem binary,
# which briefly flashes a blank console window when a PyInstaller
# --onefile build's bootloader spawns its own internal child process --
# see the "Self-update on Windows" section of TECHNICAL.md.
_IMAGE_SUBSYSTEM_WINDOWS_GUI = 2


def _pe_subsystem(exe: Path) -> int:
    """Read the Subsystem field straight out of the PE header.

    The field sits at the same fixed byte offset in both PE32 and PE32+
    (BaseOfData, present only in PE32, is exactly as many bytes shorter
    than PE32+'s wider ImageBase field, so everything after it lines up)
    -- no need for a PE-parsing dependency for one field.
    """
    data = exe.read_bytes()
    e_lfanew = int.from_bytes(data[0x3C:0x40], "little")
    subsystem_offset = e_lfanew + 4 + 20 + 68  # PE sig + COFF header + fixed offset
    return int.from_bytes(data[subsystem_offset : subsystem_offset + 2], "little")


def test_built_binary_exposes_the_complete_cli(tmp_path: Path) -> None:
    # Given: an isolated PyInstaller workspace and cgate data directory.
    project_root = Path(__file__).resolve().parents[1]
    env = {
        **os.environ,
        "APPDATA": str(tmp_path),
        "CGATE_BUILD_WORKPATH": str(tmp_path / "pyinstaller"),
        "CGATE_DB_PATH": str(tmp_path / "cgate.db"),
        "HOME": str(tmp_path),
        "LOCALAPPDATA": str(tmp_path),
    }

    try:
        # When: the release binary is built and each public CLI surface is invoked.
        build = _run(
            [sys.executable, "scripts/build-binary.py"],
            cwd=project_root,
            env=env,
        )
        assert build.returncode == 0, f"{build.stdout}\n{build.stderr}"
        binary_lines = [
            line.removeprefix("Binary: ").strip()
            for line in build.stdout.splitlines()
            if line.startswith("Binary: ")
        ]
        assert len(binary_lines) == 1, build.stdout
        binary = Path(binary_lines[0])
        assert binary.is_file()

        version = _run([str(binary), "--version"], cwd=project_root, env=env)
        root_help = _run([str(binary), "--help"], cwd=project_root, env=env)
        connections_help = _run(
            [str(binary), "connections", "--help"], cwd=project_root, env=env
        )
        connections_list = _run(
            [str(binary), "connections", "list"], cwd=project_root, env=env
        )

        # Then: the binary exposes version, command groups, and database-backed behavior.
        assert version.returncode == 0, version.stderr
        # The version baked into the PyInstaller binary comes from the nearest
        # git tag at build time (see scripts/_ensure_version.py); assert shape
        # only so this test stays valid for every release.
        assert re.search(r"^cgate \d+\.\d+\.\d+", version.stdout), version.stdout
        assert root_help.returncode == 0, root_help.stderr
        assert all(command in root_help.stdout for command in ("connections", "watch"))
        assert connections_help.returncode == 0, connections_help.stderr
        assert connections_list.returncode == 0, connections_list.stderr
        assert "No connections saved." in connections_list.stdout
    finally:
        shutil.rmtree(project_root / "dist", ignore_errors=True)


@pytest.mark.skipif(sys.platform != "win32", reason="PE subsystem only exists on Windows PE binaries")
def test_built_helper_binary_is_windowed_not_console(tmp_path: Path) -> None:
    """Regression test for the blank-console flash a user hit in production:
    cgate-helper.exe must be a GUI-subsystem binary, not console -- see
    scripts/build-binary.py's --windowed flag and TECHNICAL.md."""
    project_root = Path(__file__).resolve().parents[1]
    env = {
        **os.environ,
        "CGATE_BUILD_WORKPATH": str(tmp_path / "pyinstaller"),
    }

    try:
        build = _run(
            [
                sys.executable,
                "scripts/build-binary.py",
                "--name=cgate-helper",
                "--entry=src/cgate/helper/__main__.py",
                "--minimal",
                "--windowed",
            ],
            cwd=project_root,
            env=env,
        )
        assert build.returncode == 0, f"{build.stdout}\n{build.stderr}"
        binary = project_root / "dist" / "cgate-helper-windows-amd64.exe"
        assert binary.is_file()
        assert _pe_subsystem(binary) == _IMAGE_SUBSYSTEM_WINDOWS_GUI
    finally:
        shutil.rmtree(project_root / "dist", ignore_errors=True)
