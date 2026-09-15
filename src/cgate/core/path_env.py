r"""Per-user install directory and PATH registration mechanics.

Pure logic, no typer/rich -- testable without CliRunner. On Windows, every
registry call goes through the module-level ``winreg`` name (never a
function-local ``import winreg``) specifically so tests can replace it
with a fake and never touch the real ``HKEY_CURRENT_USER\Environment``
key on the machine running the test suite.
"""

from __future__ import annotations

import ctypes
import os
import shutil
import sys
from pathlib import Path
from typing import Final

try:
    import winreg
except ImportError:  # non-Windows -- module must still import cleanly
    winreg = None  # type: ignore[assignment]

_ENV_SUBKEY: Final = "Environment"
_PATH_VALUE_NAME: Final = "Path"
_MARKER: Final = "# Added by cgate install"

# WM_SETTINGCHANGE broadcast constants (winuser.h).
_HWND_BROADCAST: Final = 0xFFFF
_WM_SETTINGCHANGE: Final = 0x001A
_SMTO_ABORTIFHUNG: Final = 0x0002
_BROADCAST_TIMEOUT_MS: Final = 5000


def install_dir() -> Path:
    r"""Per-user directory ``cgate install`` copies the binary into.

    Windows: ``%USERPROFILE%\bin`` (already the directory named in
    TECHNICAL.md's manual instructions). macOS/Linux: ``~/.local/bin``.
    No admin/sudo path exists or is planned -- user-level only.
    """
    if sys.platform == "win32":
        return Path.home() / "bin"
    return Path.home() / ".local" / "bin"


def install_target_path() -> Path:
    """Where the installed binary itself should live.

    A fixed filename ("cgate.exe" / "cgate"), not whatever the source
    file happens to be named (e.g. ``cgate-windows-amd64.exe`` as
    downloaded), so `cgate` on PATH resolves regardless of the download's
    original name.
    """
    name = "cgate.exe" if sys.platform == "win32" else "cgate"
    return install_dir() / name


def copy_binary(source: Path, target: Path) -> None:
    """Copy ``source`` to ``target``, preserving the executable bit.

    Uses ``shutil.copy2`` -- NOT ``copyfile``, which does not preserve
    permission bits and would silently produce a non-executable copy on
    macOS/Linux.
    """
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, target)


# ---- Windows: HKCU\Environment\Path ----------------------------------


def ensure_windows_user_path(directory: Path) -> str:
    r"""Ensure ``directory`` is present in ``HKCU\Environment\Path``.

    Returns ``"already_present"`` or ``"added"``. Raises ``OSError`` on a
    genuine registry failure. Windows-only -- the function has no hive
    parameter, so it is structurally impossible for it to target
    anything but ``HKEY_CURRENT_USER``; ``HKEY_LOCAL_MACHINE`` (which
    would require admin rights) is never referenced anywhere in this
    module.
    """
    assert winreg is not None, "ensure_windows_user_path must only be called on win32"
    target = str(directory)

    # CreateKeyEx (not OpenKey) so a brand-new user profile where the
    # Environment key itself doesn't exist yet still works -- it opens or
    # creates atomically instead of needing a separate existence check.
    with winreg.CreateKeyEx(
        winreg.HKEY_CURRENT_USER, _ENV_SUBKEY, 0, winreg.KEY_READ | winreg.KEY_WRITE
    ) as key:
        try:
            current_value, value_type = winreg.QueryValueEx(key, _PATH_VALUE_NAME)
        except FileNotFoundError:
            # Rare but real: brand-new profile, Path value never created.
            # REG_EXPAND_SZ is the type Windows itself uses for a
            # freshly-created user Path value.
            current_value, value_type = "", winreg.REG_EXPAND_SZ

        if _path_dir_present(current_value, target):
            return "already_present"

        new_value = f"{current_value};{target}" if current_value else target
        # value_type is exactly what was read above (or the default) --
        # never assumed, never upgraded. We only ever append a
        # fully-resolved literal directory (no "%...%" tokens of our
        # own), so appending into a REG_EXPAND_SZ value is always safe.
        winreg.SetValueEx(key, _PATH_VALUE_NAME, 0, value_type, new_value)

    _broadcast_environment_change()
    return "added"


def _path_dir_present(current_value: str, target: str) -> bool:
    """Case-insensitive, ``;``-split, ``%VAR%``-tolerant membership check.

    Deliberately does not call ``Path.resolve()`` (which touches the
    filesystem and requires the path to exist) -- pure string
    normalization, so it works identically whether or not the directory
    exists yet.
    """
    target_norm = os.path.normcase(os.path.normpath(target))
    for raw_entry in current_value.split(";"):
        entry = raw_entry.strip()
        if not entry:
            continue
        expanded = os.path.expandvars(entry)  # handles %USERPROFILE%\bin etc.
        if os.path.normcase(os.path.normpath(expanded)) == target_norm:
            return True
    return False


def _broadcast_environment_change() -> None:
    """Best-effort WM_SETTINGCHANGE broadcast.

    Lets newly-launched processes pick up the PATH change without a full
    logoff (already-open shells still won't see it). Must never be
    fatal -- wrapped broadly and always swallowed.

    ``argtypes``/``restype`` are declared explicitly and are NOT
    optional: without them ctypes defaults every argument to 32-bit
    ``c_int`` on a 64-bit process, corrupting the HWND, the lParam
    string pointer, and the output pointer -- silent memory corruption,
    not just "might not work". The output parameter is ``DWORD_PTR``
    (pointer-sized, 8 bytes on 64-bit Windows), so it uses ``c_size_t``,
    not ``c_ulong`` (which stays 32-bit under Windows' LLP64 model and
    would be undersized for the write).
    """
    if sys.platform != "win32":
        return
    try:
        user32 = ctypes.windll.user32  # type: ignore[attr-defined]
        send = user32.SendMessageTimeoutW
        send.argtypes = [
            ctypes.c_void_p,  # HWND
            ctypes.c_uint,  # UINT Msg
            ctypes.c_void_p,  # WPARAM
            ctypes.c_wchar_p,  # LPARAM ("Environment")
            ctypes.c_uint,  # UINT fuFlags
            ctypes.c_uint,  # UINT uTimeout
            ctypes.POINTER(ctypes.c_size_t),  # PDWORD_PTR lpdwResult
        ]
        send.restype = ctypes.c_ssize_t  # LRESULT
        result = ctypes.c_size_t()
        send(
            ctypes.c_void_p(_HWND_BROADCAST),
            _WM_SETTINGCHANGE,
            None,
            "Environment",
            _SMTO_ABORTIFHUNG,
            _BROADCAST_TIMEOUT_MS,
            ctypes.byref(result),
        )
    except (OSError, AttributeError, TypeError):
        pass


# ---- POSIX: shell rc file ---------------------------------------------


def detect_shell_rc() -> Path:
    """Best-effort ``$SHELL``-based rc file detection.

    A heuristic, not a guarantee: ``$SHELL`` reflects the login shell,
    not necessarily whatever shell actually launched ``cgate install``,
    and classic macOS bash setups that source ``.bash_profile`` instead
    of ``.bashrc`` won't be picked up. Falls back to ``~/.profile`` (a
    portable POSIX default) for anything unrecognized.
    """
    name = Path(os.environ.get("SHELL", "")).name
    home = Path.home()
    if name == "zsh":
        return home / ".zshrc"
    if name == "fish":
        return home / ".config" / "fish" / "config.fish"
    if name == "bash":
        return home / ".bashrc"
    return home / ".profile"


def ensure_posix_shell_path(directory: Path, rc_path: Path | None = None) -> tuple[str, Path]:
    """Ensure ``directory`` is exported on PATH via a shell rc file.

    Idempotent via ``_MARKER``. ``rc_path`` is injectable so tests never
    touch a real home-directory dotfile. Returns ``(status, rc_path)``
    where status is ``"already_present"`` or ``"added"``. Cannot affect
    the currently-running parent shell -- the caller must tell the user
    to restart their terminal or ``source`` the file.
    """
    rc_path = rc_path if rc_path is not None else detect_shell_rc()
    existing = rc_path.read_text(encoding="utf-8") if rc_path.exists() else ""
    if _MARKER in existing:
        return "already_present", rc_path
    rc_path.parent.mkdir(parents=True, exist_ok=True)
    block = f'\n{_MARKER}\nexport PATH="{directory}:$PATH"\n'
    with rc_path.open("a", encoding="utf-8") as f:
        f.write(block)
    return "added", rc_path
