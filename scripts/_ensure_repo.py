"""Ensure src/cgate/_repo.py exists with the GitHub "owner/repo" cgate ships from.

`cgate.update` reads this to know which repo's Releases to check for
`update apply` / attestation verification. Baking it in at build time
(instead of hardcoding it in source) means a future repo rename only
needs this file regenerated -- which CI does on every build -- not a
source-code edit.

Priority order, mirroring _ensure_version.py's shape:
1. An existing _repo.py is left alone (idempotent).
2. `GITHUB_REPOSITORY`, which GitHub Actions sets automatically to the
   exact "owner/repo" the release workflow is running in -- this is
   literally where the binary is about to be uploaded for download.
3. The local `origin` git remote, parsed for "owner/repo" -- covers a
   `python scripts/build-binary.py` run from a plain clone (any host
   alias or URL scheme).
4. A hardcoded fallback, for builds with neither (e.g. a source tarball
   with no .git directory).

Idempotent: re-running with a current _repo.py is a no-op.
"""

from __future__ import annotations

import os
import re
import subprocess
from pathlib import Path

PROJECT_ROOT: Path = Path(__file__).resolve().parents[1]
REPO_FILE: Path = PROJECT_ROOT / "src" / "cgate" / "_repo.py"
_FALLBACK_REPO = "wanderlp/command-gate-for-ai-agents"

_REPO_RE = re.compile(r"""^REPO\s*=\s*['"]([^'"]+)['"]""", re.MULTILINE)
# Matches "owner/repo" (optionally ".git"-suffixed) at the end of an SSH
# URL (plain or host-aliased) or an HTTPS URL.
_REMOTE_PATH_RE = re.compile(r"[:/]([^/:]+/[^/:]+?)(?:\.git)?$")


def _read_existing_repo() -> str | None:
    if not REPO_FILE.exists():
        return None
    text = REPO_FILE.read_text(encoding="utf-8")
    match = _REPO_RE.search(text)
    return match.group(1) if match else None


def _repo_from_git_remote() -> str | None:
    try:
        result = subprocess.run(
            ["git", "remote", "get-url", "origin"],
            cwd=PROJECT_ROOT,
            capture_output=True,
            text=True,
            check=True,
        )
    except (subprocess.CalledProcessError, FileNotFoundError, OSError):
        return None
    match = _REMOTE_PATH_RE.search(result.stdout.strip())
    return match.group(1) if match else None


def main() -> int:
    existing = _read_existing_repo()
    if existing is not None:
        print(f"{REPO_FILE} already has REPO={existing!r}; not regenerating")
        return 0

    repo = os.environ.get("GITHUB_REPOSITORY") or _repo_from_git_remote() or _FALLBACK_REPO
    body = '"""Auto-generated at build time; do not edit by hand."""\n' f'REPO = "{repo}"\n'
    REPO_FILE.parent.mkdir(parents=True, exist_ok=True)
    REPO_FILE.write_text(body, encoding="utf-8")
    print(f"Wrote {REPO_FILE} (REPO={repo!r})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
