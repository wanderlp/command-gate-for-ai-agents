"""Tests for the standalone cgate-helper binary's pure logic and CLI wiring."""

from __future__ import annotations

from pathlib import Path

import pytest

from cgate.helper import waiter
from cgate.helper.__main__ import build_parser, main


def test_wait_for_pids_returns_true_once_all_exit(monkeypatch: pytest.MonkeyPatch) -> None:
    alive = {1: 2, 2: 1}  # pid -> number of polls before it reports dead

    def fake_alive(pid: int) -> bool:
        if alive[pid] <= 0:
            return False
        alive[pid] -= 1
        return True

    monkeypatch.setattr(waiter, "_pid_alive", fake_alive)
    monkeypatch.setattr(waiter.time, "sleep", lambda _s: None)

    assert waiter.wait_for_pids([1, 2], timeout=5.0, poll_interval=0.01) is True


def test_wait_for_pids_returns_false_on_timeout(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(waiter, "_pid_alive", lambda _pid: True)
    monkeypatch.setattr(waiter.time, "sleep", lambda _s: None)

    assert waiter.wait_for_pids([1], timeout=0.05, poll_interval=0.01) is False


def test_retry_replace_succeeds_after_transient_failures(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    source = tmp_path / "cgate.exe.new"
    target = tmp_path / "cgate.exe"
    source.write_bytes(b"new")
    target.write_bytes(b"old")

    attempts = {"count": 0}
    real_replace = Path.replace

    def flaky_replace(self: Path, other: Path) -> Path:
        attempts["count"] += 1
        if attempts["count"] < 3:
            raise PermissionError(13, "locked")
        return real_replace(self, other)

    monkeypatch.setattr(Path, "replace", flaky_replace)
    monkeypatch.setattr(waiter.time, "sleep", lambda _s: None)

    error = waiter.retry_replace(source, target, total_seconds=1.0, interval=0.01)
    assert error is None
    assert attempts["count"] == 3
    assert target.read_bytes() == b"new"


def test_retry_replace_gives_up_after_total_seconds(monkeypatch: pytest.MonkeyPatch) -> None:
    def always_fails(self: Path, other: Path) -> Path:  # noqa: ARG001
        raise PermissionError(13, "locked")

    monkeypatch.setattr(Path, "replace", always_fails)
    monkeypatch.setattr(waiter.time, "sleep", lambda _s: None)

    error = waiter.retry_replace(
        Path("source"), Path("target"), total_seconds=0.05, interval=0.01
    )
    assert error is not None
    assert "PermissionError" in error


def test_retry_delete_succeeds(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    target = tmp_path / "cgate.exe"
    target.write_bytes(b"data")
    monkeypatch.setattr(waiter.time, "sleep", lambda _s: None)

    assert waiter.retry_delete(target, total_seconds=1.0, interval=0.01) is None
    assert not target.exists()


def test_is_safe_target_accepts_expected_names_in_helper_dir(tmp_path: Path) -> None:
    (tmp_path / "cgate.exe").write_bytes(b"")
    assert waiter.is_safe_target(tmp_path / "cgate.exe", helper_dir=tmp_path) is True
    assert waiter.is_safe_target(tmp_path / "cgate-helper.exe", helper_dir=tmp_path) is True


def test_is_safe_target_rejects_other_directory(tmp_path: Path) -> None:
    other = tmp_path / "elsewhere"
    other.mkdir()
    assert waiter.is_safe_target(other / "cgate.exe", helper_dir=tmp_path) is False


def test_is_safe_target_rejects_unexpected_name(tmp_path: Path) -> None:
    assert waiter.is_safe_target(tmp_path / "notepad.exe", helper_dir=tmp_path) is False


def test_build_parser_requires_an_operation() -> None:
    with pytest.raises(SystemExit):
        build_parser().parse_args([])


def test_main_replace_success(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    source = tmp_path / "cgate.exe.new"
    target = tmp_path / "cgate.exe"
    source.write_bytes(b"new")
    target.write_bytes(b"old")

    monkeypatch.setattr("cgate.helper.__main__._helper_dir", lambda: tmp_path)
    monkeypatch.setattr("cgate.helper.__main__.wait_for_pids", lambda *_a, **_k: True)
    logged: list[str] = []
    monkeypatch.setattr("cgate.helper.__main__.append_log", logged.append)

    code = main(["replace", "--target", str(target), "--source", str(source)])
    assert code == 0
    assert target.read_bytes() == b"new"
    assert any("succeeded" in line for line in logged)


def test_main_delete_success(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    target = tmp_path / "cgate.exe"
    target.write_bytes(b"old")

    monkeypatch.setattr("cgate.helper.__main__._helper_dir", lambda: tmp_path)
    monkeypatch.setattr("cgate.helper.__main__.wait_for_pids", lambda *_a, **_k: True)
    monkeypatch.setattr("cgate.helper.__main__.append_log", lambda _msg: None)

    code = main(["delete", "--target", str(target)])
    assert code == 0
    assert not target.exists()


def test_main_refuses_unsafe_target(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    outside = tmp_path / "elsewhere" / "cgate.exe"
    outside.parent.mkdir()
    outside.write_bytes(b"old")

    monkeypatch.setattr("cgate.helper.__main__._helper_dir", lambda: tmp_path)
    logged: list[str] = []
    monkeypatch.setattr("cgate.helper.__main__.append_log", logged.append)

    code = main(["delete", "--target", str(outside)])
    assert code == 3
    assert outside.exists()
    assert any("unsafe" in line for line in logged)


def test_main_logs_failure_and_returns_2(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    target = tmp_path / "cgate.exe"
    target.write_bytes(b"old")

    monkeypatch.setattr("cgate.helper.__main__._helper_dir", lambda: tmp_path)
    monkeypatch.setattr("cgate.helper.__main__.wait_for_pids", lambda *_a, **_k: True)
    monkeypatch.setattr(
        "cgate.helper.__main__.retry_delete", lambda *_a, **_k: "OSError: still locked"
    )
    logged: list[str] = []
    monkeypatch.setattr("cgate.helper.__main__.append_log", logged.append)

    code = main(["delete", "--target", str(target)])
    assert code == 2
    assert any("failed" in line for line in logged)
