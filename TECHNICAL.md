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

### Via PyPI (pip / pipx / uv)

```bash
pipx install command-gate   # or: uv tool install command-gate, or: pip install command-gate
cgate mcp install           # registers with any AI client it finds
```

This is a plain Python package (`hatchling` wheel + sdist), published via GitHub
OIDC trusted publishing on every tag push -- no API token stored anywhere. Two
things work differently from the binary in the sections above:

- No first-run bootstrap. `maybe_auto_install()` (`src/cgate/cli/install.py`) only
  fires for a frozen PyInstaller binary that isn't at its install target yet --
  `pipx`/`uv tool` already handle the install-and-PATH step, so run
  `cgate mcp install` once yourself to register with Claude Code / opencode / Cursor.
- `cgate update apply` doesn't work here. `current_binary_path()` returns `None`
  for a non-frozen install, so the command prints a message and points you at the
  latest release instead of trying to self-swap. Update with
  `pipx upgrade command-gate` / `uv tool upgrade command-gate` / `pip install -U
  command-gate` instead.

### Via package manager

```powershell
# Scoop (Windows)
scoop bucket add wanderlp https://github.com/wanderlp/scoop-bucket
scoop install cgate
```

```bash
# Homebrew (macOS, Linux) -- arm64 (Apple Silicon) only for now, no Intel build yet
brew tap wanderlp/tap
brew install cgate
```

Both live in their own repos ([wanderlp/scoop-bucket](https://github.com/wanderlp/scoop-bucket),
[wanderlp/homebrew-tap](https://github.com/wanderlp/homebrew-tap)) rather than
here, so a future CLI tool can add its own manifest/formula to the same two
repos instead of needing a new tap/bucket. Bumping either on a new `cgate`
release is a manual step for now -- see [`packaging/README.md`](./packaging/README.md#maintenance).

Winget is not yet supported — submit path requires PR to `microsoft/winget-pkgs`.

### First-run warnings (binaries are not code-signed)

- **Windows SmartScreen**: "Windows protected your PC" → click **More info** →
  **Run anyway**. One-time per machine.
- **macOS Gatekeeper**: "cgate can't be opened because it is from an unidentified
  developer" → right-click the binary → **Open** → confirm. One-time per machine.

Both are unsigned-binary friction, not bugs. Code signing is on the roadmap
(see Phase 2). Installing via PyPI or a package manager instead of downloading
the binary directly from a browser generally avoids both warnings, since the
Windows "mark of the web" / macOS quarantine flag those checks key off of gets
attached by the browser download itself, not by `pip`/`pipx`/`scoop`/`brew`.

## Typical workflow

```text
# 1. IA agent calls propose_command via MCP.  By default it lands in the
#    approval queue (PROPOSE mode). If you've enabled AUTO mode and opted the
#    target server in, it runs immediately and the response carries the result
#    inline -- see the "Modes" section below for the full picture.

# 2. Run the watch dashboard: a full-screen queue + active-batch view.
$ cgate watch
# Sidebar shows the FIFO batch queue; the main panel shows the active
# batch's commands. y=approve  n=reject  a=approve rest  r=reject rest
# m=toggle mode  s=server settings  h=history  q=quit.
# ↑/↓ + Enter on the sidebar jumps the queue to a specific batch instead
# of being forced through strict FIFO order. Enter on a command opens its
# full, untruncated result -- the queue rows cap it to one line.
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

## Modes: how PROPOSE and AUTO are wired

`propose_command` reads two pieces of state from the local SQLite database before
deciding what to do with a command:

1. **`app_mode`** — a single-row table holding the global mode (`propose` or
   `auto`). Absence means "unset"; absent rows behave as PROPOSE.
2. **`server_settings`** — one row per server alias that has been explicitly
   opted in (`auto_allowed = 1`). Absence means "not allowed."

`cgate/mcp_server/auto_resolution.py:resolve_auto_behavior()` is the one place
that turns those two flags into a `BehaviorDecision`:

| Global mode | Server opted in | Action | `effective_reason` |
|---|---|---|---|
| `propose` (or unset) | (any) | queue | `global_propose` |
| `auto` | no | queue | `server_not_opted_in` |
| `auto` | yes | execute | `both_allowed` |

Only the last row ever executes. Both switches are defaulted to safe, so the
"accidentally enabled" case still requires a second explicit decision before
anything runs.

When `propose_command` does execute, it mirrors `watch/approval.py:approve_one`'s
transition cycle exactly: `PENDING → APPROVED` (with `approved_by = "auto:watch:<user>"`,
falling back to `"auto:mcp"` if `getpass.getuser()` raises) → `EXECUTED` or `FAILED`
with the output captured into the `result` column. The same `update_status(expected_status=...)`
CAS guard applies, so a manual approval racing an auto-approval never produces a
double-execution. Auto-approved rows are filterable as `WHERE approved_by LIKE 'auto:%'`.

### What the AI cannot change

Both flags live only in the database and are mutated exclusively from inside
`cgate watch`:

- **`m`** opens a one-keystroke confirmation modal before flipping the global
  mode.
- **`s`** opens a modal listing every connection; Space toggles a row's
  in-memory checkbox, Enter writes, Esc cancels.

`propose_command` reads both flags but exposes no tool that writes them. The MCP
tool surface is unchanged: still `propose_command`, `list_connections`,
`check_status`. The change is in `propose_command`'s runtime behaviour — same
schema, same names, new optional response fields (`mode`, `server_auto_allowed`,
`effective_reason`, `result`, `approved_by`).

### Pre-flight state for the AI

`propose_command` only reveals the mode after it has been called. To let an AI
agent plan with full information without triggering a proposal just to learn the
rules, two read-only tools are available:

- **`list_connections`** adds one field per entry, `auto_allowed: bool`, sourced
  from `ServerSettingsRepo.get_or_default(alias)` (defaults to `false`). The AI
  sees up front which servers could auto-execute.
- **`get_mode`** returns `{mode: "propose" | "auto", auto_allowed_servers:
  [alias, ...]}`. Read-only; an unset global mode is reported as `"propose"`
  (same safe default as `resolve_auto_behavior`).

Both are non-mutating. `get_mode` and the new field on `list_connections` are
additive: no existing tool's schema or response shape breaks.

## Status

Phase 1 complete: end-to-end propose → approve → execute → audit loop working,
plus a round of security/robustness hardening (host key verification, TLS
validation, DB race-condition fixes, GitHub Actions build-provenance
attestation verification on self-update, and more).
321 unit/integration tests pass; ruff + basedpyright pass with a handful of
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

To regenerate the `cgate watch` screenshots in the README after a UI change:

```console
uv run python scripts/render_demo_screenshots.py
```

Seeds a throwaway DB with fake batches, drives the app headlessly via
Textual's own test pilot, and exports `docs/img/*.svg` -- no real servers
involved.

## Layout

```text
src/cgate/
├── cli/          # Top-level CLI: connections, history, mcp, update, watch
├── connections/  # Saved server connections + WinRM/SSH detection + keyring auth
├── core/         # Shared paths, primitives, and install/PATH registration
├── db/           # Local SQLite persistence (batches, commands, connections,
│                 # app_mode, server_settings)
├── executor/     # WinRM and SSH execution
├── helper/       # Standalone cgate-helper.exe: Windows-only file swap for self-update
├── mcp_server/   # MCP server exposing propose_command / list_connections / check_status
│                 # + auto_resolution.py (mode-aware decision helper)
├── risk.py       # Heuristic high-blast-radius command detector (regex, not a guarantee)
└── watch/        # Interactive approval queue (y/n/a/r/m/s/h controls)
                  # + mode_modal.py + server_settings_modal.py
                  # + history_modal.py + command_detail_modal.py + widgets.py
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
