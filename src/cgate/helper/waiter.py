"""Pure, mockable primitives used by ``cgate.helper.__main__``.

Kept separate from the argparse entry point so tests can exercise the
actual wait/retry/safety logic without going through subprocess spawning.
"""

from __future__ import annotations

import ctypes
import sys
import time
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path

# WaitForSingleObject return codes (winbase.h).
_WAIT_OBJECT_0 = 0x00000000
_WAIT_TIMEOUT = 0x00000102
# Rights needed only to wait on the handle, not to inspect/control the process.
_SYNCHRONIZE = 0x00100000


def _pid_alive(pid: int) -> bool:
    """Return whether a process with this PID is still running.

    Windows-only: uses ``OpenProcess`` + ``WaitForSingleObject`` (a zero
    timeout, so this never blocks) instead of shelling out to
    ``tasklist``/WMI, since this runs in a tight poll loop. A process
    handle becomes signaled the instant the process terminates, so a
    ``WAIT_TIMEOUT`` result means "still running"; ``OpenProcess`` failing
    outright means the PID has already exited (or never existed).
    """
    if sys.platform != "win32":
        return False
    kernel32 = ctypes.windll.kernel32  # type: ignore[attr-defined]
    handle = kernel32.OpenProcess(_SYNCHRONIZE, False, pid)  # noqa: FBT003 -- Win32 ABI positional arg
    if not handle:
        return False
    try:
        return kernel32.WaitForSingleObject(handle, 0) == _WAIT_TIMEOUT
    finally:
        kernel32.CloseHandle(handle)


def wait_for_pids(pids: list[int], *, timeout: float = 30.0, poll_interval: float = 0.25) -> bool:
    """Block until every PID in ``pids`` has exited, or ``timeout`` elapses.

    Returns True if all exited within the timeout, False otherwise. This
    is a best-effort wait, not a hard precondition -- the caller proceeds
    with the file operation (and its own retry loop) either way, so a
    timeout here just means "start the retries a bit early."
    """
    deadline = time.monotonic() + timeout
    remaining = set(pids)
    while remaining and time.monotonic() < deadline:
        remaining = {pid for pid in remaining if _pid_alive(pid)}
        if remaining:
            time.sleep(poll_interval)
    return not remaining


def retry_replace(
    source: Path, target: Path, *, total_seconds: float = 10.0, interval: float = 1.0
) -> str | None:
    """Retry moving ``source`` onto ``target`` for up to ``total_seconds``.

    Mirrors ``cgate.update.replace_binary``'s return contract: None on
    success, an error description string on failure. Retries absorb a
    lingering AV scan or a slow-to-release OS handle after the process
    being replaced has already exited.
    """
    deadline = time.monotonic() + total_seconds
    last_error = "no attempts made"
    while True:
        try:
            source.replace(target)
        except OSError as exc:
            last_error = f"{type(exc).__name__}: {exc}"
            if time.monotonic() >= deadline:
                return last_error
            time.sleep(interval)
        else:
            return None


def retry_delete(target: Path, *, total_seconds: float = 10.0, interval: float = 1.0) -> str | None:
    """Retry deleting ``target`` for up to ``total_seconds``. Same contract as ``retry_replace``."""
    deadline = time.monotonic() + total_seconds
    last_error = "no attempts made"
    while True:
        try:
            target.unlink()
        except OSError as exc:
            last_error = f"{type(exc).__name__}: {exc}"
            if time.monotonic() >= deadline:
                return last_error
            time.sleep(interval)
        else:
            return None


TARGET_NAMES: frozenset[str] = frozenset({"cgate.exe", "cgate-helper.exe"})
SOURCE_NAMES: frozenset[str] = frozenset({"cgate.exe.new", "cgate-helper.exe.new"})


def is_safe_target(
    path: Path, *, helper_dir: Path, allowed_names: frozenset[str] = TARGET_NAMES
) -> bool:
    """Refuse to touch anything outside the helper's own install directory.

    Not a security boundary -- a caller that controls the helper's
    location also controls this argument. It's a sanity rail against
    bugs: a wrong path slipping through should fail loudly instead of
    silently deleting or overwriting something unexpected. ``allowed_names``
    differs for a ``replace``'s source (the staged ``*.new`` download) vs.
    either operation's target (the live ``cgate.exe``/``cgate-helper.exe``).
    """
    try:
        same_dir = path.resolve().parent == helper_dir.resolve()
    except OSError:
        return False
    return same_dir and path.name.lower() in allowed_names
