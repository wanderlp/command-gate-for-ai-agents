"""Install cgate onto this machine.

Copies the running binary into a per-user bin directory and registers
that directory on PATH.
"""

from __future__ import annotations

import sys

import typer
from rich.console import Console

from cgate.core.path_env import (
    copy_binary,
    ensure_posix_shell_path,
    ensure_windows_user_path,
    install_dir,
    install_target_path,
)
from cgate.update import current_binary_path

console = Console()


def install_cmd() -> None:
    """Copy this binary into ~/bin (Windows) or ~/.local/bin (macOS/Linux) and add it to PATH.

    Safe to run repeatedly: already installed at the target, and already
    on PATH, are both detected and reported rather than redone.
    """
    source = current_binary_path()
    if source is None:
        console.print(
            "[yellow]Not running from a packaged binary; nothing to install.[/yellow]\n"
            "[dim]`cgate install` only applies to the downloaded release "
            "binary, not a source checkout.[/dim]"
        )
        return

    target = install_target_path()
    already_at_target = source.resolve() == target.resolve()

    console.print("[bold]Install:[/bold]")
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

    console.print("\nNext: run [bold]cgate mcp install[/bold] to register with your AI clients.")
