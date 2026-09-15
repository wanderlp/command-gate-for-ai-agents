"""Shared console-interaction helpers for CLI commands."""

from __future__ import annotations

import contextlib
import sys


def should_pause(no_pause: bool) -> bool:  # noqa: FBT001 -- CLI flags are plain bools
    """Pause for human review unless --no-pause or stdin is not a TTY."""
    return not no_pause and sys.stdin.isatty()


def wait_for_enter() -> None:
    """Block until the user presses Enter; silently no-op on EOF (pipe/CI)."""
    with contextlib.suppress(EOFError):
        input("Press Enter to close...")
