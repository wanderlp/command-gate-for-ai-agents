# Technical details

Architecture, full install options, and the development workflow for
`command-gate-for-ai-agents` (`cgate`). See [README.md](./README.md) for what this
project is and why it exists.

## Install

`cgate` ships as a single binary per platform. Pick yours.

### Windows

1. Download `cgate-windows-amd64.exe` from the [latest release](https://github.com/wanderlp/command-gate-for-ai-agents/releases/latest).
2. Run it — double-click it, or `.\cgate-windows-amd64.exe` from the folder you
   downloaded it to, with no arguments. A completely bare invocation of a binary
   that isn't installed yet triggers first-run setup automatically: it copies itself
   into `%USERPROFILE%\bin\cgate.exe`, adds that directory to your user-level `PATH`
   (via `HKEY_CURRENT_USER\Environment` — no admin rights needed), and registers
   with every IA client (Claude Code, opencode, Cursor) it finds, all with no
   prompts. Pauses for Enter before closing so a double-click launch's console
   window doesn't vanish before you've read the summary.
3. Open a new terminal (PATH changes to already-open shells don't take effect until
   restarted) and restart your IA client. Done — Claude Code now exposes
   `propose_command`, `list_connections`, and `check_status` as tools it can call.

Once installed, plain `cgate` goes back to showing help, exactly like any other CLI
— the automatic first-run behavior only fires for a genuinely fresh download. Later,
`cgate mcp install` re-registers (or registers a client you installed afterward)
with its normal confirm-per-client prompts.

For a scripted/silent deployment, add `--unattended`
(`.\cgate-windows-amd64.exe --unattended`): same install, same zero prompts, but it
skips the "Press Enter to close" pause and exits on its own the moment setup
finishes, instead of waiting on a keypress nobody is there to send.

### macOS / Linux

Same flow — download `cgate-macos-arm64` or `cgate-linux-x86_64` from the
[latest release](https://github.com/wanderlp/command-gate-for-ai-agents/releases/latest),
`chmod +x` it, then run it (`./cgate-<platform>`) with no arguments. First-run setup
copies itself into `~/.local/bin/cgate` and adds that directory to your `PATH` by
appending an export line to your shell's rc file (`~/.zshrc`, `~/.bashrc`,
`~/.config/fish/config.fish`, or `~/.profile` as a fallback — detected from `$SHELL`,
best-effort: it won't find every possible shell setup, e.g. a classic macOS bash
profile that only sources `~/.bash_profile`), then registers with every IA client it
finds. Open a new terminal (or `source` the rc file it names) and restart your IA
client afterward.

First-run setup only handles first-time setup, on purpose: if something already
exists at the install path, it leaves it alone (bare `cgate` just shows help, same
as any properly-installed copy) rather than silently overwriting it — use
`cgate update apply` to update an existing install instead. The explicit
`cgate install` subcommand still exists too, for scripting or re-running just the
copy-and-PATH step on its own (it doesn't chain into MCP registration or pause).

### Via package manager

Manifest templates live under [`packaging/`](./packaging/README.md). Publishing
them requires creating separate tap/bucket repos (Scoop convention:
`<user>/scoop-bucket`; Homebrew convention: `<user>/homebrew-tap`) and pasting
the manifests there with the placeholder SHA256 replaced. See
`packaging/README.md` for the full flow. Once published, users install with:

```powershell
# Scoop (Windows)
scoop bucket add wanderlp https://github.com/wanderlp/scoop-bucket
scoop install cgate
```

```bash
# Homebrew (macOS, Linux)
brew tap wanderlp/tap
brew install cgate
```

Winget is not yet supported — submit path requires PR to `microsoft/winget-pkgs`.

### First-run warnings (binaries are not code-signed)

- **Windows SmartScreen**: "Windows protected your PC" → click **More info** →
  **Run anyway**. One-time per machine.
- **macOS Gatekeeper**: "cgate can't be opened because it is from an unidentified
  developer" → right-click the binary → **Open** → confirm. One-time per machine.

Both are unsigned-binary friction, not bugs. Code signing is on the roadmap
(see Phase 2).

## Typical workflow

```text
# 1. IA agent calls propose_command via MCP.  Humans never see this step.

# 2. Run the watch dashboard: a full-screen queue + active-batch view.
$ cgate watch
# Sidebar shows the FIFO batch queue; the main panel shows the active
# batch's commands. y=approve  n=reject  a=approve rest  r=reject rest  q=quit.
# Stays open and keeps polling for new batches even when the queue drains.

# 3. Stay current.
$ cgate update check
Latest: cgate 0.2.0 (release v0.2.0)
Update available: 0.1.0 -> 0.2.0
Run `cgate update apply` to install.

# On Windows the swap sometimes finishes in the background after `apply`
# exits (see "Self-update on Windows" below) -- check on it with:
$ cgate update status
```

## Status

Phase 1 complete: end-to-end propose → approve → execute → audit loop working,
plus a round of security/robustness hardening (host key verification, TLS
validation, DB race-condition fixes, GitHub Actions build-provenance
attestation verification on self-update, and more).
284 unit/integration tests pass; ruff + basedpyright pass with a handful of
accepted pre-existing findings (no known bugs, just style/complexity debt).

## Development

```console
git clone https://github.com/wanderlp/command-gate-for-ai-agents.git
cd command-gate-for-ai-agents
uv sync --extra dev
uv run cgate --version
uv run pytest
uv run ruff check .
uv run basedpyright src
```

To build a release binary locally:

```console
uv run python scripts/build-binary.py
ls dist/
```

On Windows, build the companion helper binary the same way (see "Self-update
on Windows" below):

```console
uv run python scripts/build-binary.py --name=cgate-helper --entry=src/cgate/helper/__main__.py --minimal --windowed
```

## Layout

```text
src/cgate/
├── cli/          # Top-level CLI: connections, mcp, update, watch
├── connections/  # Saved server connections + WinRM/SSH detection + keyring auth
├── core/         # Shared paths, primitives, and install/PATH registration
├── db/           # Local SQLite persistence (batches, commands, connections)
├── executor/     # WinRM and SSH execution
├── helper/       # Standalone cgate-helper.exe: Windows-only file swap for self-update
├── mcp_server/   # MCP server exposing propose_command / list_connections / check_status
└── watch/        # Interactive approval queue (y/n/a/r controls)
```

Release assets are produced by `.github/workflows/release.yml` on every tag push
(`git tag v0.1.5 && git push origin main v0.1.5`) and uploaded as platform-native
binaries to a GitHub Release.

### Self-update on Windows: the compiled helper

Windows locks a running executable's own image file, so `cgate.exe` cannot
rename or delete itself while it's the process doing the work. `cgate update
apply` and `cgate uninstall --binary` both hand that step off to
`cgate-helper.exe` — a second, much smaller binary (`src/cgate/helper/`,
Windows-only, built and attestation-verified alongside the main binary) that
never shares an image name with `cgate.exe`. It waits for the caller's PID to
actually exit (not a fixed delay), retries the rename/delete briefly to
absorb a lingering AV scan, and logs the outcome to `update.log` (see `cgate
update status`). If the helper isn't available yet — offline, or a version
that predates this feature — both commands fall back to a `cmd.exe`-based
delayed swap/delete, same as before. Either way, a version upgrading *from*
a build that predates this feature still needs one manual recovery step the
first time, since the code making that decision at that moment is the old
binary — a one-time bootstrap cost.

`cgate-helper.exe` is built with `--windowed` (a GUI-subsystem binary), not
`--console`. A console-subsystem `--onefile` build still briefly flashes a
blank console window when launched detached: only the *outer* bootloader
process is covered by the launcher's `CREATE_NO_WINDOW` flag, but that
bootloader spawns its own internal child to actually run the Python code
(same parent/child pattern `cgate.exe` itself has), and that spawn isn't
covered by anyone's creation flags. A GUI-subsystem binary never gets a
console at any level of that process tree, so there's nothing to flash.
