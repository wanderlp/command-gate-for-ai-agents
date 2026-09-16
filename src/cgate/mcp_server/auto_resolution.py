"""Resolve whether a proposed command queues for approval or executes immediately."""
from __future__ import annotations

from typing import TYPE_CHECKING, Literal, TypedDict

from cgate.db.mode import AppModeNotSetError, Mode

if TYPE_CHECKING:
    from cgate.db.mode import AppModeRepo
    from cgate.db.server_settings import ServerSettingsRepo


class BehaviorDecision(TypedDict):
    """The resolved behavior for one proposed command, with audit context."""

    action: Literal["queue", "execute"]
    mode: str
    server_auto_allowed: bool
    reason: Literal["global_propose", "server_not_opted_in", "both_allowed"]


def resolve_auto_behavior(
    *,
    mode_repo: AppModeRepo,
    settings_repo: ServerSettingsRepo,
    server_alias: str,
) -> BehaviorDecision:
    """Execute only when the global mode is AUTO and the server has opted in.

    An unset global mode (AppModeNotSetError) behaves as PROPOSE, and an
    alias without an explicit server_settings row behaves as not opted in:
    auto-execution requires both sides to be explicit.
    """
    try:
        mode = mode_repo.get().mode
    except AppModeNotSetError:
        mode = Mode.PROPOSE
    auto_allowed = settings_repo.get_or_default(server_alias).auto_allowed
    match mode:
        case Mode.PROPOSE:
            return {
                "action": "queue",
                "mode": mode.value,
                "server_auto_allowed": auto_allowed,
                "reason": "global_propose",
            }
        case Mode.AUTO:
            if not auto_allowed:
                return {
                    "action": "queue",
                    "mode": mode.value,
                    "server_auto_allowed": auto_allowed,
                    "reason": "server_not_opted_in",
                }
            return {
                "action": "execute",
                "mode": mode.value,
                "server_auto_allowed": auto_allowed,
                "reason": "both_allowed",
            }
