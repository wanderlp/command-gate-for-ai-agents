"""The `cgate watch` dashboard's Textual theme -- single source for its palette.

Lives in its own module (rather than `watch/app.py`, where it's activated)
so `watch/render.py`'s pure markup helpers can pull the same hex values for
status glyphs and warnings, instead of Rich's generic named colors drifting
out of sync with whatever the app's theme actually is.
"""

from __future__ import annotations

from textual.theme import Theme

# Deep, near-black surfaces with a teal primary give the dashboard its own
# identity instead of Textual's generic default. warning/error/success map
# directly onto the semantics already baked into render.py's status glyphs
# (pending/running=warning, executed=success, rejected/failed/risky=error).
CGATE_THEME: Theme = Theme(
    name="cgate",
    primary="#2DD4BF",
    secondary="#60A5FA",
    warning="#FBBF24",
    error="#F87171",
    success="#4ADE80",
    accent="#FB923C",
    foreground="#E5E7EB",
    background="#0B0E14",
    surface="#12151C",
    panel="#1E2330",
    dark=True,
)

__all__ = ["CGATE_THEME"]
