"""Entry point for the standalone ``cgate-helper.exe`` binary.

Fully unattended: never prompts, always exits with a code and a log line.
Invoked by the main ``cgate.exe`` (see ``cgate.update.spawn_helper``) after
it has decided a self-lock swap/delete needs to happen from a process that
isn't ``cgate.exe`` itself.

Usage:
    cgate-helper.exe replace --target PATH --source PATH --wait-pid N [...]
    cgate-helper.exe delete  --target PATH --wait-pid N [...]
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from cgate.core.update_log import append_log
from cgate.helper.waiter import (
    SOURCE_NAMES,
    is_safe_target,
    retry_delete,
    retry_replace,
    wait_for_pids,
)

_WAIT_TIMEOUT_SECONDS = 30.0
_RETRY_TOTAL_SECONDS = 10.0


def _helper_dir() -> Path:
    """Return the directory this helper (or its source, when unfrozen) lives in."""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent


def build_parser() -> argparse.ArgumentParser:
    """Build the ``replace``/``delete`` subcommand parser."""
    parser = argparse.ArgumentParser(prog="cgate-helper")
    subparsers = parser.add_subparsers(dest="operation", required=True)

    replace = subparsers.add_parser("replace", help="Move --source onto --target.")
    replace.add_argument("--target", required=True, type=Path)
    replace.add_argument("--source", required=True, type=Path)
    replace.add_argument("--wait-pid", type=int, action="append", default=[], dest="wait_pids")

    delete = subparsers.add_parser("delete", help="Delete --target.")
    delete.add_argument("--target", required=True, type=Path)
    delete.add_argument("--wait-pid", type=int, action="append", default=[], dest="wait_pids")

    return parser


def main(argv: list[str] | None = None) -> int:
    """Run one wait-then-replace/delete operation. Never prompts."""
    args = build_parser().parse_args(argv)
    helper_dir = _helper_dir()

    if not is_safe_target(args.target, helper_dir=helper_dir):
        append_log(f"helper {args.operation}: refusing unsafe target {args.target}")
        return 3
    if args.operation == "replace" and not is_safe_target(
        args.source, helper_dir=helper_dir, allowed_names=SOURCE_NAMES
    ):
        append_log(f"helper replace: refusing unsafe source {args.source}")
        return 3

    if args.wait_pids and not wait_for_pids(args.wait_pids, timeout=_WAIT_TIMEOUT_SECONDS):
        append_log(
            f"helper {args.operation}: timed out after {_WAIT_TIMEOUT_SECONDS:g}s waiting for "
            f"PID(s) {args.wait_pids} to exit; proceeding anyway"
        )

    if args.operation == "replace":
        error = retry_replace(args.source, args.target, total_seconds=_RETRY_TOTAL_SECONDS)
    else:
        error = retry_delete(args.target, total_seconds=_RETRY_TOTAL_SECONDS)

    if error is not None:
        append_log(f"helper {args.operation} failed for {args.target}: {error}")
        return 2

    append_log(f"helper {args.operation} succeeded for {args.target}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
