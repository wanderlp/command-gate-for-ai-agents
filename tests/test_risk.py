"""Unit tests for the heuristic high-blast-radius command detector."""

from __future__ import annotations

import pytest

from cgate.db.types import ServerType
from cgate.risk import find_risk

LINUX_SAFE_COMMANDS = [
    "ls -la /home",
    "systemctl status nginx",
    "chmod -R 755 ./project",
    "rm -rf ./build",  # scoped delete, but rm -rf is flagged regardless of target -- see below
]

LINUX_RISKY_COMMANDS = [
    "rm -rf /",
    "rm -rf --no-preserve-root /",
    "rm -fr /var/log",
    "rm --recursive --force /tmp/x",
    "dd if=/dev/zero of=/dev/sda",
    "echo hi > /dev/sda",
    "mkfs.ext4 /dev/sdb1",
    "shred -n1 /dev/sdb",
    "wipefs -a /dev/sdb",
    "chmod -R 777 /",
    "csrutil disable",
    "diskutil eraseDisk",
    "diskutil eraseVolume /dev/disk2",
    "spctl --master-disable",
    ":(){ :|:& };:",
]

WINDOWS_SAFE_COMMANDS = [
    "Get-Service",
    "Restart-Service MyApp",
    "Get-ChildItem C:\\temp",
    "Remove-Item C:\\temp\\file.txt",
]

WINDOWS_RISKY_COMMANDS = [
    "vssadmin delete shadows /all",
    "wbadmin delete catalog -quiet",
    "bcdedit /set {default} recoveryenabled no",
    "bcdedit /set {default} bootstatuspolicy ignoreallfailures",
    "Disable-ComputerRestore -Drive C:\\",
    "reagentc /disable",
    "diskshadow /s script.txt",
    "Format-Volume -DriveLetter D",
    "Clear-Disk -Number 1 -RemoveData",
    "diskpart",
    "Remove-Item -Recurse -Force C:\\",
    "Remove-Item -Recurse -Force -Path C:\\temp\\build",
    "Set-MpPreference -DisableRealtimeMonitoring $true",
    "netsh advfirewall set allprofiles state off",
    "rd /s /q C:\\temp",
    "del /f /s /q C:\\temp\\*",
]


@pytest.mark.parametrize("command", LINUX_SAFE_COMMANDS[:-1])
def test_find_risk_returns_none_for_safe_linux_commands(command: str) -> None:
    assert find_risk(command, ServerType.LINUX) is None


@pytest.mark.parametrize("command", LINUX_RISKY_COMMANDS)
def test_find_risk_flags_risky_linux_commands(command: str) -> None:
    assert find_risk(command, ServerType.LINUX) is not None


def test_find_risk_flags_rm_rf_even_on_a_scoped_path() -> None:
    """rm -rf is irreversible regardless of target -- flagged broadly on
    purpose, matching the conservative intent behind this feature: better
    an occasional false positive than a silent unattended wipe."""
    assert find_risk("rm -rf ./build", ServerType.LINUX) is not None


@pytest.mark.parametrize("command", WINDOWS_SAFE_COMMANDS)
def test_find_risk_returns_none_for_safe_windows_commands(command: str) -> None:
    assert find_risk(command, ServerType.WINDOWS) is None


@pytest.mark.parametrize("command", WINDOWS_RISKY_COMMANDS)
def test_find_risk_flags_risky_windows_commands(command: str) -> None:
    assert find_risk(command, ServerType.WINDOWS) is not None


def test_find_risk_is_case_insensitive() -> None:
    assert find_risk("RM -RF /", ServerType.LINUX) is not None
    assert find_risk("FORMAT-VOLUME -driveletter D", ServerType.WINDOWS) is not None


def test_find_risk_windows_patterns_do_not_leak_into_linux_matching() -> None:
    """vssadmin is a Windows-only tool; a Linux command mentioning it in
    passing (e.g. a comment) shouldn't be flagged by the Windows pattern set."""
    assert find_risk("echo 'vssadmin delete shadows' > notes.txt", ServerType.LINUX) is None
