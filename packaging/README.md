# Packaging manifests

Reference templates for distributing `cgate` via system package managers.

## Status

Published. The manifests are live at
[wanderlp/scoop-bucket](https://github.com/wanderlp/scoop-bucket) and
[wanderlp/homebrew-tap](https://github.com/wanderlp/homebrew-tap), currently
pinned to `v0.2.4`.

The files in this directory are **templates** — they carry a placeholder
version/SHA256 and exist as a reference for the next manual bump (see
"Maintenance" below), not as the live source of truth. The Homebrew formula
is arm64-only for now: `release.yml`'s macOS runner only produces
`cgate-macos-arm64`, so there's no Intel asset to point `on_intel` at yet.

## Layout

- `scoop/cgate.template.json` — Scoop bucket manifest for Windows.
- `brew/cgate.template.rb` — Homebrew formula for macOS and Linux.

Winget is intentionally **not** included yet — winget requires a multi-file
manifest structure under `manifests/<first-letter>/<lowercase-name>/<version>/`
and a PR to `microsoft/winget-pkgs` (which has multi-week review). When you're
ready to go through that, mirror the same shape as these two templates.

## Install

```powershell
scoop bucket add wanderlp https://github.com/wanderlp/scoop-bucket
scoop install cgate
```

```bash
brew tap wanderlp/tap
brew install cgate
```

Both `wanderlp/scoop-bucket` and `wanderlp/homebrew-tap` are their own repos
(git remotes use the `github.com-wanderlp` SSH alias, same as this repo,
since the account's `gh`-stored token is read-only) rather than folders in
here, so future CLI tools can add their own manifest/formula to the same two
repos instead of needing a new tap/bucket each time.

## Maintenance

When `cgate` publishes a new release, repeat for each manifest:

1. Download the new binary asset.
2. Compute its SHA256.
3. Bump `version` and update `hash` (and `url` if the asset name changed).
4. Commit and push.

A future GitHub Action could automate this — point a workflow at the
release and have it open a PR against the scoop/tap repos. Skipped for
now to keep the surface small.
