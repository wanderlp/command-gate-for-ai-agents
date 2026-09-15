"""Install cgate onto this machine.

Copies the running binary into a per-user bin directory and registers
that directory on PATH.
"""

from __future__ import annotations

import sys
from typing import TYPE_CHECKING

import typer
from rich.console import Console

from cgate.cli._console import should_pause, wait_for_enter
from cgate.core.path_env import (
    copy_binary,
    ensure_posix_shell_path,
    ensure_windows_user_path,
    install_dir,
    install_target_path,
)
from cgate.mcp_installer import detect_clients, register
from cgate.update import current_binary_path

if TYPE_CHECKING:
    from pathlib import Path

console = Console()


def _current_source_and_target() -> tuple[Path, Path] | None:
    """Return (source, target) when running from a frozen binary, else None."""
    source = current_binary_path()
    if source is None:
        return None
    return source, install_target_path()


def _perform_install(source: Path, target: Path) -> bool:
    """Copy the binary to ``target`` and register it on PATH.

    Returns True if a fresh install actually happened, False if already
    installed at ``target``. Raises ``typer.Exit(code=1)`` if a
    different file already exists at the target, or if the copy/PATH
    write itself fails -- both print their own explanation first.
    """
    console.print("[bold]Install:[/bold]")
    already_at_target = source.resolve() == target.resolve()
    if already_at_target:
        console.print(f"  Binary: [dim]already running from {target}[/dim]")
    elif target.exists():
        console.print(f"  [red]{target} already exists.[/red]")
        console.print(
            f"  [dim]That looks like an existing cgate install. To update it, "
            f"run `cgate update apply` from {target} instead.[/dim]"
        )
        raise typer.Exit(code=1)
    else:
        try:
            copy_binary(source, target)
        except OSError as exc:
            console.print(f"  [red]Failed to copy binary to {target}:[/red] {exc}")
            raise typer.Exit(code=1) from exc
        console.print(f"  Binary: [green]copied to {target}[/green]")

    directory = install_dir()
    rc_path = None
    try:
        if sys.platform == "win32":
            path_status = ensure_windows_user_path(directory)
        else:
            path_status, rc_path = ensure_posix_shell_path(directory)
    except OSError as exc:
        console.print(f"  [red]Failed to update PATH:[/red] {exc}")
        raise typer.Exit(code=1) from exc

    if path_status == "already_present":
        console.print(f"  PATH: [dim]{directory} already on PATH[/dim]")
    else:
        console.print(f"  PATH: [green]added {directory}[/green]")
        if sys.platform == "win32":
            console.print(
                "  [dim]Open a new terminal for `cgate` to be found on PATH "
                "(already-open shells won't pick this up).[/dim]"
            )
        else:
            console.print(
                f"  [dim]Run `source {rc_path}` or open a new terminal for "
                "`cgate` to be found on PATH.[/dim]"
            )

    return not already_at_target


def _auto_register_mcp_clients(target: Path) -> None:
    """Register every detected IA client with no confirmation prompts.

    Used only by the zero-argument first-run flow, where the user has
    already opted into full automation by not typing anything else.
    Registers against ``target`` directly (``mcp serve``), not
    ``current_binary_command()``'s ``sys.executable`` resolution, which
    at this point in the process still resolves to the pre-copy source
    binary, not the just-installed one.
    """
    clients = detect_clients()
    if not clients:
        console.print(
            "\n[dim]No IA clients detected yet -- run `cgate mcp install` "
            "later once you have one.[/dim]"
        )
        return
    console.print(f"\nRegistering with {len(clients)} detected IA client(s)...")
    command, args = str(target), ["mcp", "serve"]
    for client in clients:
        try:
            register(client, command, args)
        except OSError as exc:
            console.print(f"  [red]Failed to register {client.label}:[/red] {exc}")
            continue
        console.print(f"  [green]Registered {client.label}.[/green]")


def install_cmd() -> None:
    """Copy this binary into ~/bin (Windows) or ~/.local/bin (macOS/Linux) and add it to PATH.

    Safe to run repeatedly: already installed at the target, and already
    on PATH, are both detected and reported rather than redone.
    """
    result = _current_source_and_target()
    if result is None:
        console.print(
            "[yellow]Not running from a packaged binary; nothing to install.[/yellow]\n"
            "[dim]`cgate install` only applies to the downloaded release "
            "binary, not a source checkout.[/dim]"
        )
        return

    source, target = result
    _perform_install(source, target)
    console.print("\nNext: run [bold]cgate mcp install[/bold] to register with your AI clients.")


def maybe_auto_install(*, unattended: bool = False) -> bool:
    """Run automatically when cgate is invoked with no arguments at all.

    A binary just downloaded and double-clicked (or run bare from a
    terminal) is a frozen binary not yet at the install target -- in
    that case, do the full first-run setup (install + MCP client
    registration) with no confirmation prompts, since the whole point
    of this path is "just run the exe, nothing else." Returns True if
    it did this (the caller should not also print help); False when
    there was nothing to auto-install (dev mode, or already properly
    installed), in which case the caller falls through to normal help.

    ``unattended`` skips the "Press Enter to close" pause at the end
    (there are no prompts to skip either way -- this path never has
    any) so a scripted/silent deployment (``cgate-windows-amd64.exe
    --unattended``) runs start to finish and exits on its own, instead
    of waiting on a keypress nobody is there to send.
    """
    result = _current_source_and_target()
    if result is None:
        return False
    source, target = result
    if source.resolve() == target.resolve():
        return False  # already installed -- bare `cgate` should just show help

    console.print("[bold]First run detected -- setting up cgate automatically.[/bold]\n")
    _perform_install(source, target)
    _auto_register_mcp_clients(target)

    console.print(
        "\n[bold]Almost done -- two things only your terminal/AI client can do:[/bold]\n"
        "  1. Open a new terminal (already-open ones won't see the PATH change).\n"
        "  2. Restart your AI client (Claude Code / opencode / Cursor) to load "
        "the new MCP server."
    )
    if should_pause(no_pause=unattended):
        console.print()
        wait_for_enter()
    return True
