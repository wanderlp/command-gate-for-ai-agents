"""Heuristic detection of high-blast-radius commands.

Not a security boundary: a regex-based safety net, easy to defeat with
obfuscation (variables, aliases, unusual quoting/flag ordering, encoding).
Its job is narrower -- catch the common, obvious forms of "this could wipe
a disk or kill recovery" so AUTO mode's opt-in never silently runs one
unattended, and so a human scanning the queue sees a clear warning even in
PROPOSE mode. A command that matches nothing here is not "safe"; it just
didn't trip this particular tripwire.

Patterns cover Windows/PowerShell and Linux -- the latter also catches an
SSH-connected macOS box, since `cgate` has no separate macOS `ServerType`
and macOS shares the same Unix shell family (plus a few macOS-specific
tools: `diskutil`, `csrutil`, `spctl`).
"""

from __future__ import annotations

import re
from typing import Final

from cgate.db.types import ServerType

# Sourced from widely-cited "dangerous commands" references (rm -rf, dd,
# mkfs, fork bombs) and MITRE ATT&CK T1490 "Inhibit System Recovery"
# (vssadmin/wbadmin/bcdedit/REAgentC -- the standard ransomware precursor
# set that deletes shadow copies and disables recovery before encrypting).
_LINUX_PATTERNS: Final[tuple[tuple[str, re.Pattern[str]], ...]] = (
    ("fork bomb", re.compile(r":\(\)\s*\{\s*:\s*\|\s*:\s*&?\s*\}\s*;\s*:")),
    ("delete with --no-preserve-root", re.compile(r"--no-preserve-root", re.IGNORECASE)),
    (
        "writes directly to a raw disk device",
        re.compile(
            r"(\bdd\b[^\n;|&]*\bof=|[>]{1,2}\s*)/dev/(sd|nvme|hd|xvd|disk|rdisk)\w*", re.IGNORECASE
        ),
    ),
    ("formats a block device", re.compile(r"\bmkfs(\.\w+)?\s+[^\n;|&]*/dev/", re.IGNORECASE)),
    ("wipes/erases a device", re.compile(r"\b(wipefs|shred)\b[^\n;|&]*/dev/", re.IGNORECASE)),
    (
        "recursive chmod on the filesystem root",
        re.compile(
            r"\bchmod\b[^\n;|&]*-[a-zA-Z]*[Rr][a-zA-Z]*\b[^\n;|&]*\s/(\s|\*|$)", re.IGNORECASE
        ),
    ),
    (
        "disables macOS System Integrity Protection",
        re.compile(r"\bcsrutil\s+disable\b", re.IGNORECASE),
    ),
    ("disables macOS Gatekeeper", re.compile(r"\bspctl\b[^\n;|&]*--master-disable", re.IGNORECASE)),
    (
        "erases a macOS disk/volume",
        re.compile(r"\bdiskutil\s+erase(disk|volume|all)?\b", re.IGNORECASE),
    ),
)

_WINDOWS_PATTERNS: Final[tuple[tuple[str, re.Pattern[str]], ...]] = (
    (
        "deletes shadow copies (blocks recovery)",
        re.compile(r"\bvssadmin\b[^\n;|&]*\bdelete\b[^\n;|&]*\bshadows\b", re.IGNORECASE),
    ),
    (
        "deletes Windows backups (blocks recovery)",
        re.compile(r"\bwbadmin\b[^\n;|&]*\bdelete\b", re.IGNORECASE),
    ),
    (
        "disables startup recovery",
        re.compile(r"\bbcdedit\b[^\n;|&]*(recoveryenabled\s+no|ignoreallfailures)", re.IGNORECASE),
    ),
    ("disables System Restore", re.compile(r"\bDisable-ComputerRestore\b", re.IGNORECASE)),
    (
        "disables Windows Recovery Environment",
        re.compile(r"\breagentc\b[^\n;|&]*/disable", re.IGNORECASE),
    ),
    ("deletes volume shadow copies", re.compile(r"\bdiskshadow\b", re.IGNORECASE)),
    (
        "wipes/formats a disk",
        re.compile(r"\b(Format-Volume|Clear-Disk|Remove-Partition)\b", re.IGNORECASE),
    ),
    ("uses the low-level disk partitioning tool", re.compile(r"\bdiskpart\b", re.IGNORECASE)),
    (
        "disables real-time antivirus protection",
        re.compile(r"\bSet-MpPreference\b[^\n;|&]*DisableRealtimeMonitoring", re.IGNORECASE),
    ),
    (
        "turns off the Windows Firewall",
        re.compile(r"\bnetsh\s+advfirewall\s+set\s+allprofiles\s+state\s+off\b", re.IGNORECASE),
    ),
    (
        "recursive force-delete (Remove-Item -Recurse -Force)",
        re.compile(r"\bRemove-Item\b(?=[^\n;|&]*-Recurse\b)(?=[^\n;|&]*-Force\b)", re.IGNORECASE),
    ),
    (
        "recursive force-delete of a drive root or folder",
        re.compile(
            r"\b(rd|rmdir)\b[^\n;|&]*/s[^\n;|&]*/q|\bdel\b[^\n;|&]*/f[^\n;|&]*/s[^\n;|&]*/q",
            re.IGNORECASE,
        ),
    ),
)


def _is_rm_rf(command: str) -> bool:
    """`rm` with both recursive and force flags, in any order or spelling."""
    if not re.search(r"\brm\b", command, re.IGNORECASE):
        return False
    combined_short_flags = re.search(
        r"-[a-zA-Z]*r[a-zA-Z]*f\b|-[a-zA-Z]*f[a-zA-Z]*r\b", command, re.IGNORECASE
    )
    long_flags = re.search(r"--recursive\b", command, re.IGNORECASE) and re.search(
        r"--force\b", command, re.IGNORECASE
    )
    return bool(combined_short_flags) or bool(long_flags)


def find_risk(command: str, server_type: ServerType) -> str | None:
    """Return a short human-readable label for a matched high-blast-radius pattern.

    None otherwise -- which is not the same as "safe" (see the module docstring).
    """
    patterns = _WINDOWS_PATTERNS if server_type is ServerType.WINDOWS else _LINUX_PATTERNS
    for label, pattern in patterns:
        if pattern.search(command):
            return label
    if server_type is ServerType.LINUX and _is_rm_rf(command):
        return "recursive force delete (rm -rf)"
    return None


__all__ = ["find_risk"]
