"""Standalone Windows file-swap helper (``cgate-helper.exe``).

Built as its own PyInstaller binary, separate from the main ``cgate.exe``,
so it never shares an image name with the process it's replacing/deleting
and there is nothing to disambiguate on Windows's process list. Must not
import anything from ``cgate.cli`` -- keep this package's dependency graph
to the standard library plus ``cgate.core`` only.
"""

from __future__ import annotations
