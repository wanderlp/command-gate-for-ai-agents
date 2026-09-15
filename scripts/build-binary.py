"""Build a single-file cgate executable for the current platform.

Run with ``uv run python scripts/build-binary.py`` from the project root.
Pass ``--name``/``--entry`` to build a different entry point under the same
asset-naming convention (e.g. the ``cgate-helper`` companion binary), and
``--minimal`` to skip the main CLI's heavy ``--collect-all``/
``--hidden-import`` flags, which that companion binary doesn't need.
"""

from __future__ import annotations

import argparse
import os
import platform
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Final

PROJECT_ROOT: Final = Path(__file__).resolve().parents[1]
DIST_DIR: Final = PROJECT_ROOT / "dist"
ENSURE_VERSION_SCRIPT: Final = PROJECT_ROOT / "scripts" / "_ensure_version.py"
ENSURE_REPO_SCRIPT: Final = PROJECT_ROOT / "scripts" / "_ensure_repo.py"
DEFAULT_ENTRY: Final = PROJECT_ROOT / "src" / "cgate" / "__main__.py"


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--name",
        default="cgate",
        help="PyInstaller --name and asset-filename prefix (default: cgate).",
    )
    parser.add_argument(
        "--entry",
        type=Path,
        default=DEFAULT_ENTRY,
        help="Entry-point script to build (default: src/cgate/__main__.py).",
    )
    parser.add_argument(
        "--minimal",
        action="store_true",
        help="Skip the main CLI's --collect-all/--hidden-import flags.",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    """Run PyInstaller and rename its output to the release asset name."""
    args = _parse_args(argv)
    system = platform.system()
    machine = platform.machine().lower()
    match (system, machine):
        case ("Windows", "amd64" | "x86_64"):
            asset_name = f"{args.name}-windows-amd64.exe"
            executable_name = f"{args.name}.exe"
        case ("Darwin", "arm64" | "aarch64"):
            asset_name = f"{args.name}-macos-arm64"
            executable_name = args.name
        case ("Linux", "amd64" | "x86_64"):
            asset_name = f"{args.name}-linux-x86_64"
            executable_name = args.name
        case _:
            print(f"Unsupported build platform: {system} {platform.machine()}", file=sys.stderr)
            return 2

    configured_workpath = os.environ.get("CGATE_BUILD_WORKPATH")
    owns_workpath = configured_workpath is None
    workpath = (
        Path(tempfile.mkdtemp(prefix="cgate-pyinstaller-"))
        if owns_workpath
        else Path(configured_workpath)
    ).resolve()
    specpath = workpath.with_name(f"{workpath.name}-spec")
    workpath.mkdir(parents=True, exist_ok=True)
    specpath.mkdir(parents=True, exist_ok=True)
    DIST_DIR.mkdir(parents=True, exist_ok=True)

    command = [
        sys.executable,
        "-m",
        "PyInstaller",
        "--onefile",
        f"--name={args.name}",
        "--clean",
        "--noconfirm",
        f"--distpath={DIST_DIR}",
        f"--workpath={workpath / 'build'}",
        f"--specpath={specpath}",
        f"--paths={PROJECT_ROOT / 'src'}",
    ]
    if not args.minimal:
        command += [
            "--collect-all=keyring",
            "--collect-all=mcp",
            "--collect-all=paramiko",
            "--collect-all=pywinrm",
            "--collect-all=rich",
            "--hidden-import=cgate.cli.connections",
            "--hidden-import=cgate.cli.mcp",
            "--hidden-import=cgate.cli.watch",
            "--hidden-import=cgate.mcp_server",
        ]
    command.append(str(args.entry))

    try:
        version_step = subprocess.run(
            [sys.executable, str(ENSURE_VERSION_SCRIPT)],
            cwd=PROJECT_ROOT,
            check=False,
        )
        if version_step.returncode != 0:
            return version_step.returncode

        repo_step = subprocess.run(
            [sys.executable, str(ENSURE_REPO_SCRIPT)],
            cwd=PROJECT_ROOT,
            check=False,
        )
        if repo_step.returncode != 0:
            return repo_step.returncode

        completed = subprocess.run(command, cwd=PROJECT_ROOT, check=False)
        if completed.returncode != 0:
            return completed.returncode

        produced = DIST_DIR / executable_name
        target = DIST_DIR / asset_name
        if target.exists():
            target.unlink()
        shutil.move(produced, target)
        size_mb = target.stat().st_size / (1024 * 1024)
        print(f"Binary: {target.resolve()}")
        print(f"Size: {size_mb:.2f} MB")
        return 0
    finally:
        if owns_workpath:
            shutil.rmtree(workpath, ignore_errors=True)
            shutil.rmtree(specpath, ignore_errors=True)


if __name__ == "__main__":
    raise SystemExit(main())
