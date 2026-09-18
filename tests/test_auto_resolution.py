"""Unit tests for resolve_auto_behavior's mode/opt-in/risk decision matrix."""

from __future__ import annotations

from typing import TYPE_CHECKING

from cgate.db.connection import Database, init_database
from cgate.db.mode import AppModeRepo, Mode
from cgate.db.server_settings import ServerSettingsRepo
from cgate.mcp_server.auto_resolution import resolve_auto_behavior

if TYPE_CHECKING:
    from pathlib import Path


def _db(tmp_path: Path) -> Database:
    db = Database(path=tmp_path / "cgate.db")
    init_database(db)
    return db


def test_propose_mode_queues_with_global_propose_when_not_risky(tmp_path: Path) -> None:
    db = _db(tmp_path)
    decision = resolve_auto_behavior(
        mode_repo=AppModeRepo(db),
        settings_repo=ServerSettingsRepo(db),
        server_alias="srv",
        risk_label=None,
    )
    assert decision["action"] == "queue"
    assert decision["reason"] == "global_propose"
    assert decision["risk_label"] is None


def test_propose_mode_queues_with_risky_command_reason_when_risky(tmp_path: Path) -> None:
    """Item 3: the human should see the risk flag even in PROPOSE mode,
    where everything already queues -- not only when it changed AUTO's
    decision."""
    db = _db(tmp_path)
    decision = resolve_auto_behavior(
        mode_repo=AppModeRepo(db),
        settings_repo=ServerSettingsRepo(db),
        server_alias="srv",
        risk_label="recursive force delete (rm -rf)",
    )
    assert decision["action"] == "queue"
    assert decision["reason"] == "risky_command"
    assert decision["risk_label"] == "recursive force delete (rm -rf)"


def test_auto_mode_queues_when_server_not_opted_in(tmp_path: Path) -> None:
    db = _db(tmp_path)
    _ = AppModeRepo(db).set(mode=Mode.AUTO, updated_by="test")
    decision = resolve_auto_behavior(
        mode_repo=AppModeRepo(db),
        settings_repo=ServerSettingsRepo(db),
        server_alias="srv",
        risk_label=None,
    )
    assert decision["action"] == "queue"
    assert decision["reason"] == "server_not_opted_in"


def test_auto_mode_executes_when_opted_in_and_not_risky(tmp_path: Path) -> None:
    db = _db(tmp_path)
    _ = AppModeRepo(db).set(mode=Mode.AUTO, updated_by="test")
    _ = ServerSettingsRepo(db).set(alias="srv", auto_allowed=True, updated_by="test")
    decision = resolve_auto_behavior(
        mode_repo=AppModeRepo(db),
        settings_repo=ServerSettingsRepo(db),
        server_alias="srv",
        risk_label=None,
    )
    assert decision["action"] == "execute"
    assert decision["reason"] == "both_allowed"
    assert decision["risk_label"] is None


def test_auto_mode_still_queues_a_risky_command_even_when_opted_in(tmp_path: Path) -> None:
    """The whole point of item 3: a risky command never auto-runs, even
    with both switches (global AUTO + per-server opt-in) already flipped."""
    db = _db(tmp_path)
    _ = AppModeRepo(db).set(mode=Mode.AUTO, updated_by="test")
    _ = ServerSettingsRepo(db).set(alias="srv", auto_allowed=True, updated_by="test")
    decision = resolve_auto_behavior(
        mode_repo=AppModeRepo(db),
        settings_repo=ServerSettingsRepo(db),
        server_alias="srv",
        risk_label="wipes/formats a disk",
    )
    assert decision["action"] == "queue"
    assert decision["reason"] == "risky_command"
    assert decision["risk_label"] == "wipes/formats a disk"


def test_auto_mode_not_opted_in_still_surfaces_risk_label_even_though_unused_as_reason(
    tmp_path: Path,
) -> None:
    db = _db(tmp_path)
    _ = AppModeRepo(db).set(mode=Mode.AUTO, updated_by="test")
    decision = resolve_auto_behavior(
        mode_repo=AppModeRepo(db),
        settings_repo=ServerSettingsRepo(db),
        server_alias="srv",
        risk_label="formats a block device",
    )
    assert decision["reason"] == "server_not_opted_in"
    assert decision["risk_label"] == "formats a block device"
