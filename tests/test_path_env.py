"""Tests for cgate.core.path_env.

Every Windows-registry test replaces `path_env.winreg` with an in-memory
fake -- never the real stdlib module -- so this suite can run safely even
though this machine has a real HKEY_CURRENT_USER\\Environment\\Path.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Self

import pytest

from cgate.core import path_env


class _FakeKey:
    def __init__(self, hive: object, subkey: str) -> None:
        self.hive = hive
        self.subkey = subkey

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *exc: object) -> bool:
        return False


class FakeWinReg:
    """Minimal in-memory stand-in for the parts of `winreg` this module uses."""

    HKEY_CURRENT_USER = object()
    HKEY_LOCAL_MACHINE = object()
    KEY_READ = 1
    KEY_WRITE = 2
    REG_SZ = 1
    REG_EXPAND_SZ = 2

    def __init__(self) -> None:
        self.values: dict[tuple[object, str, str], tuple[str, int]] = {}
        self.set_value_calls: list[tuple[str, int, str]] = []

    def CreateKeyEx(  # noqa: N802 -- must match winreg's real attribute name
        self, hive: object, subkey: str, _reserved: int = 0, _access: int = 0
    ) -> _FakeKey:
        assert hive is self.HKEY_CURRENT_USER, "must never target a hive other than HKCU"
        return _FakeKey(hive, subkey)

    def QueryValueEx(self, key: _FakeKey, name: str) -> tuple[str, int]:  # noqa: N802
        try:
            return self.values[(key.hive, key.subkey, name)]
        except KeyError:
            raise FileNotFoundError(name) from None

    def SetValueEx(  # noqa: N802 -- must match winreg's real attribute name
        self, key: _FakeKey, name: str, _reserved: int, value_type: int, value: str
    ) -> None:
        self.set_value_calls.append((name, value_type, value))
        self.values[(key.hive, key.subkey, name)] = (value, value_type)


@pytest.fixture(autouse=True)
def _never_touch_real_registry(monkeypatch: pytest.MonkeyPatch) -> None:
    """Defense in depth: even a test that forgets to install its own fake
    can never fall through to the real winreg module."""
    monkeypatch.setattr(path_env, "winreg", FakeWinReg())


# --- install_dir / install_target_path / copy_binary ---


def test_install_dir_windows(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    assert path_env.install_dir() == tmp_path / "bin"


def test_install_dir_posix(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(sys, "platform", "linux")
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    assert path_env.install_dir() == tmp_path / ".local" / "bin"


def test_install_target_path_windows_name(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    assert path_env.install_target_path() == tmp_path / "bin" / "cgate.exe"


def test_install_target_path_posix_name(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(sys, "platform", "darwin")
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    assert path_env.install_target_path() == tmp_path / ".local" / "bin" / "cgate"


def test_copy_binary_creates_parent_dir_and_preserves_mode(tmp_path: Path) -> None:
    source = tmp_path / "src" / "cgate"
    source.parent.mkdir()
    source.write_bytes(b"binary content")
    source.chmod(0o755)
    target = tmp_path / "dest" / "bin" / "cgate"

    path_env.copy_binary(source, target)

    assert target.read_bytes() == b"binary content"
    if sys.platform != "win32":
        assert target.stat().st_mode & 0o111


# --- Windows: ensure_windows_user_path ---


def test_ensure_windows_user_path_adds_when_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = FakeWinReg()
    monkeypatch.setattr(path_env, "winreg", fake)

    status = path_env.ensure_windows_user_path(Path("C:/Users/x/bin"))

    assert status == "added"
    assert len(fake.set_value_calls) == 1
    name, value_type, value = fake.set_value_calls[0]
    assert name == "Path"
    assert value_type == fake.REG_EXPAND_SZ
    assert value == str(Path("C:/Users/x/bin"))


def test_ensure_windows_user_path_preserves_existing_type_and_appends(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake = FakeWinReg()
    fake.values[(fake.HKEY_CURRENT_USER, "Environment", "Path")] = (
        "C:\\existing",
        fake.REG_SZ,
    )
    monkeypatch.setattr(path_env, "winreg", fake)

    status = path_env.ensure_windows_user_path(Path("C:/Users/x/bin"))

    assert status == "added"
    _name, value_type, value = fake.set_value_calls[0]
    assert value_type == fake.REG_SZ  # not silently upgraded to REG_EXPAND_SZ
    assert value == f"C:\\existing;{Path('C:/Users/x/bin')}"


def test_ensure_windows_user_path_detects_already_present_case_insensitive(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake = FakeWinReg()
    fake.values[(fake.HKEY_CURRENT_USER, "Environment", "Path")] = (
        "C:\\Windows;C:\\USERS\\X\\BIN",
        fake.REG_EXPAND_SZ,
    )
    monkeypatch.setattr(path_env, "winreg", fake)

    status = path_env.ensure_windows_user_path(Path("C:/Users/x/bin"))

    assert status == "already_present"
    assert fake.set_value_calls == []


def test_ensure_windows_user_path_detects_already_present_via_expandvars(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake = FakeWinReg()
    fake.values[(fake.HKEY_CURRENT_USER, "Environment", "Path")] = (
        "%USERPROFILE%\\bin",
        fake.REG_EXPAND_SZ,
    )
    monkeypatch.setattr(path_env, "winreg", fake)
    monkeypatch.setenv("USERPROFILE", "C:\\Users\\x")

    status = path_env.ensure_windows_user_path(Path("C:/Users/x/bin"))

    assert status == "already_present"
    assert fake.set_value_calls == []


def test_broadcast_environment_change_swallows_failures(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(sys, "platform", "win32")

    class ExplodingWindll:
        @property
        def user32(self) -> object:
            msg = "boom"
            raise OSError(msg)

    monkeypatch.setattr(path_env.ctypes, "windll", ExplodingWindll())

    path_env._broadcast_environment_change()  # noqa: SLF001 -- unit-testing this internal directly


def test_broadcast_environment_change_noop_off_windows(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sys, "platform", "linux")
    path_env._broadcast_environment_change()  # noqa: SLF001 -- must not raise or touch ctypes.windll


# --- POSIX: detect_shell_rc / ensure_posix_shell_path ---


@pytest.mark.parametrize(
    ("shell", "expected"),
    [
        ("/bin/zsh", ".zshrc"),
        ("/bin/bash", ".bashrc"),
        ("/usr/bin/fish", None),  # handled separately, different relative path
    ],
)
def test_detect_shell_rc(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, shell: str, expected: str | None
) -> None:
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    monkeypatch.setenv("SHELL", shell)
    if expected is not None:
        assert path_env.detect_shell_rc() == tmp_path / expected
    else:
        assert path_env.detect_shell_rc() == tmp_path / ".config" / "fish" / "config.fish"


def test_detect_shell_rc_falls_back_to_profile_when_unset(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    monkeypatch.delenv("SHELL", raising=False)
    assert path_env.detect_shell_rc() == tmp_path / ".profile"


def test_ensure_posix_shell_path_creates_new_file_with_marker(tmp_path: Path) -> None:
    rc = tmp_path / ".zshrc"
    bin_dir = tmp_path / "bin"

    status, returned_rc = path_env.ensure_posix_shell_path(bin_dir, rc_path=rc)

    assert status == "added"
    assert returned_rc == rc
    content = rc.read_text(encoding="utf-8")
    assert "# Added by cgate install" in content
    assert str(bin_dir) in content


def test_ensure_posix_shell_path_is_idempotent(tmp_path: Path) -> None:
    rc = tmp_path / ".zshrc"
    bin_dir = tmp_path / "bin"

    path_env.ensure_posix_shell_path(bin_dir, rc_path=rc)
    status, _ = path_env.ensure_posix_shell_path(bin_dir, rc_path=rc)

    assert status == "already_present"
    assert rc.read_text(encoding="utf-8").count("# Added by cgate install") == 1


def test_ensure_posix_shell_path_preserves_existing_content(tmp_path: Path) -> None:
    rc = tmp_path / ".zshrc"
    rc.write_text("alias ll='ls -la'\n", encoding="utf-8")

    path_env.ensure_posix_shell_path(tmp_path / "bin", rc_path=rc)

    content = rc.read_text(encoding="utf-8")
    assert "alias ll" in content
    assert "# Added by cgate install" in content
