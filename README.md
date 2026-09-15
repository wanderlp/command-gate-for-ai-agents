# command-gate-for-ai-agents (`cgate`)

Give your AI agents hands — safely.

AI agents can now write and run real shell commands against real servers. That's
powerful, and also the kind of thing that goes badly the first time an agent
misunderstands what you asked for. `cgate` sits between the agent and your
infrastructure: the agent proposes a command, a human decides whether it runs, and
every proposal, decision, and result is recorded.

You stop choosing between "the agent can't actually do anything" and "the agent can do
anything, unsupervised."

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
