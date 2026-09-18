"""Top-level command-gate CLI."""

from __future__ import annotations

import sqlite3
from typing import Annotated

import typer
from rich.console import Console

from cgate import __version__
from cgate.cli.connections import connections_app
from cgate.cli.history import history_app
from cgate.cli.install import install_cmd, maybe_auto_install
from cgate.cli.mcp import mcp_app
from cgate.cli.uninstall import uninstall_cmd
from cgate.cli.update import update_app
from cgate.cli.watch import watch_app
from cgate.update import maybe_heal_pending_update

app = typer.Typer(
    name="cgate",
    help="Middleware/CLI between AI agents and servers -- IA proposes, human approves.",
    invoke_without_command=True,
)
app.add_typer(connections_app, name="connections")
app.add_typer(history_app, name="history")
app.add_typer(mcp_app, name="mcp")
app.add_typer(update_app, name="update")
app.add_typer(watch_app, name="watch")
app.command("install")(install_cmd)
app.command("uninstall")(uninstall_cmd)


def _version_callback(*, value: bool) -> None:
    if value:
        typer.echo(f"cgate {__version__}")
        raise typer.Exit(code=0)


@app.callback()
def root(
    ctx: typer.Context,
    *,
    _version: Annotated[
        bool,
        typer.Option(
            "--version",
            "-V",
            callback=_version_callback,
            is_eager=True,
            help="Show version and exit.",
        ),
    ] = False,
    unattended: Annotated[
        bool,
        typer.Option(
            "--unattended",
            help=(
                "For first-run auto-install only: skip the 'Press Enter to "
                "close' pause and exit immediately once done. No prompts "
                "happen either way -- this only controls the pause, for "
                "scripted/silent deployment."
            ),
        ),
    ] = False,
) -> None:
    """Display help or route to a command group.

    A completely bare invocation (no subcommand, no options) used to
    just print help via Typer's ``no_args_is_help``. Now it first checks
    whether this is a freshly downloaded binary that isn't installed
    yet -- if so, ``maybe_auto_install()`` runs the full first-run setup
    instead, so "download and double-click" is enough on its own. Once
    properly installed, bare `cgate` goes back to printing help, exactly
    as before.
    """
    if ctx.invoked_subcommand is not None:
        return
    if maybe_auto_install(unattended=unattended):
        return
    typer.echo(ctx.get_help())


def main() -> None:
    """Run the CLI, turning an uncaught sqlite3.Error into a clean exit.

    Every command opens its own SQLite connection with no shared boundary
    that catches DB failures; a locked database (another cgate process
    holding it) or a corrupted file otherwise surfaces as a raw traceback
    from deep inside whichever command hit it first, instead of a clear
    message (issue #12). This is the entry point PyInstaller's bundled
    binary and the pip console-script both call, so it covers every
    command without needing its own try/except.

    Before dispatching the command, attempt to self-heal a staged update
    left behind by a previous failed ``update apply``: if ``<binary>.new``
    is on disk and no other ``cgate.exe`` is alive, we spawn the helper
    (detached, waiting on our PID) so the swap completes the moment we
    exit. Fire-and-forget, silent on any condition that prevents it.
    """
    maybe_heal_pending_update()
    try:
        app()
    except sqlite3.Error as exc:
        Console(stderr=True).print(
            f"[red]cgate's local database is locked or corrupted:[/red] {exc}\n"
            "[dim]Another cgate process may be holding it, or the file may "
            "be damaged.[/dim]"
        )
        raise SystemExit(1) from exc


if __name__ == "__main__":
    main()
