# command-gate-for-ai-agents (`cgate`)

Give your AI agents hands — safely.

AI agents can now write and run real shell commands against real servers. That's
powerful, and also the kind of thing that goes badly the first time an agent
misunderstands what you asked for. `cgate` sits between the agent and your
infrastructure: the agent proposes a command, a human decides whether it runs, and
every proposal, decision, and result is recorded.

You stop choosing between "the agent can't actually do anything" and "the agent can do
anything, unsupervised."

> **⚠️ Beta.** `cgate` is under active development. Expect rough edges, breaking
> changes between releases, and incoming revisions as it matures — feedback and bug
> reports are welcome.

## Why teams use it

- **Agents propose, humans decide.** Every command an AI agent wants to run on a
  connected server lands in an approval queue first. Nothing executes without a human
  saying yes.
- **A full audit trail.** Every proposal, approval, rejection, and execution result is
  recorded — who approved it, when, and what happened.
- **Drops into the AI tools you already use.** Registers itself as an MCP server for
  Claude Code, opencode, Cursor, and other MCP-compatible clients.
- **One binary, nothing to configure.** Ships as a single executable per platform —
  download it and run it, done.

## Modes: PROPOSE and AUTO

`cgate` ships in two modes, and you pick per server which ones can ever run
unattended. The default is the safe one.

**PROPOSE** (default): every command an AI agent calls lands in the watch queue. You
press `y` or `n` per command. Nothing runs without you.

**AUTO**: when the agent calls `propose_command`, it runs immediately **only if the
target server is on your allow-list**. Servers are off by default — you opt them in
explicitly. Two switches need to land in the "go" position before anything runs
unattended: the global mode is AUTO *and* that specific server is opted in.

```text
┌─────────────────────────────────────────────────────────────┐
│ cgate watch          MODE: AUTO ⚡ | 1 servers auto-allowed  │
├─────────────────────────────────────────────────────────────┤
│ [Queue]            [Servers]                                │
│ ▶ "deploy v2"      dev-1   LNX [✓]                         │
│                    stage-2 LNX [ ]                          │
│                    prod-db WIN [ ]                          │
├─────────────────────────────────────────────────────────────┤
│ [y]approve [n]reject [a]approve batch [m]ode [h]istory ...  │
└─────────────────────────────────────────────────────────────┘
```

↑/↓ + Enter on the queue sidebar jumps straight to any pending batch — you're not
forced to clear the queue in strict arrival order to get to the one you actually
want to approve next.

### Switching modes

Press **`m`** in `cgate watch` to flip the global mode (one keystroke + `y` to
confirm). Press **`s`** to open the server allow-list and toggle any connection on or
off. Both modals need an explicit `y` or `Enter`; everything else cancels without
writing. AI agents have no MCP tool that can change either setting — only your
keystrokes can.

### Why two switches?

If you leave `MODE: AUTO` on by accident, the worst case is that nothing runs on
servers that haven't been explicitly opted in. To actually run something
unattended you must enable the mode **and** flip the per-server switch. Belt and
suspenders, default-safe at every level.

### A third switch: high-blast-radius commands never auto-run

Even with both switches flipped, a command matching a known high-blast-radius
pattern — a recursive force-delete, a raw disk write, deleting shadow copies or
backups, disabling System Restore, and similar — always queues for a human. It
shows a bold red `⚠ RISKY` warning in `cgate watch` (in **either** mode, so you
notice it in PROPOSE too, not only when it changed what AUTO would have done),
and the MCP response carries `effective_reason: "risky_command"` so the agent
knows why. This is a regex-based heuristic, not a guarantee — it catches the
common, obvious forms (see `src/cgate/risk.py`), not every possible obfuscation.
Absence of the flag is not the same as "safe."

### The audit trail still works

Every command a batch ever queued shows an `⚙ auto` or `👤 <username>` badge next
to it, so you always know whether a human or AUTO mode approved it — and once a
batch resolves, it doesn't vanish: press **`h`** in `cgate watch` to browse every
resolved batch, see the agent's stated `reason` for wanting the command, and view
the full, untruncated result.

Need it outside the TUI — for a compliance report, or just to grep offline?

```bash
cgate history export                          # full audit trail as CSV, to stdout
cgate history export --format json -o audit.json
cgate history export --limit 100               # only the 100 most recently resolved batches
```

Human-only: this isn't exposed to AI agents over MCP. An agent that proposed a
batch can already poll `check_status(batch_id)` for it at any time, resolved or
not, so there's no reason to hand it a browse of everyone else's history too.

Prefer raw SQL? The same data is still just a query away:

```sql
SELECT * FROM commands WHERE approved_by LIKE 'auto:%';
```

### What the AI sees (and what it can ask first)

The MCP server exposes three read-only tools the AI can use to plan with full
information, plus `propose_command` to act:

- **`list_connections`** — every saved connection and its `auto_allowed` flag
  (the AI knows up front which servers could auto-execute).
- **`get_mode`** — the current global mode (`propose` or `auto`) and the list of
  aliases opted into auto-execution. Read-only, safe to call any time.
- **`check_status`** — what's pending in a given batch.

With these, the AI never has to guess whether a command will auto-run or wait
for you — it can call `get_mode` and `list_connections` first, plan accordingly,
and only invoke `propose_command` when it knows what will happen.

## Get started

1. Download the binary for your platform from the
   [latest release](https://github.com/wanderlp/command-gate-for-ai-agents/releases/latest).
2. Run it (double-click it, or just `.\cgate-windows-amd64.exe` from the folder you
   downloaded it to). On first run it installs itself into a per-user bin directory,
   adds that directory to your `PATH`, and registers with any AI clients it finds —
   no admin/sudo, no flags to remember.
3. Open a new terminal and restart your AI client. Done.

From there, `cgate watch` opens a live approval queue: agent proposals show up as they
come in, you approve or reject with a keypress, and the result streams back to the
agent.

> First run on Windows or macOS may show a one-time "unrecognized publisher" warning —
> these binaries aren't code-signed yet. See
> [TECHNICAL.md](./TECHNICAL.md#first-run-warnings-binaries-are-not-code-signed) for
> what to do about it.

## Learn more

Package-manager installs, architecture, development setup, and building from source
live in [TECHNICAL.md](./TECHNICAL.md).

## License

[MIT](./LICENSE)
