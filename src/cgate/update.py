"""Self-update via GitHub Releases API. Pure logic; the CLI layer wraps it."""

from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from http import HTTPStatus
from packaging.version import InvalidVersion, Version
from pathlib import Path
from typing import TYPE_CHECKING, Final, NotRequired, TypedDict

if TYPE_CHECKING:
    from sigstore.verify import Verifier
    from sigstore.verify.policy import VerificationPolicy

DEFAULT_REPO: Final = "wanderlp/command-gate"
GITHUB_API: Final = "https://api.github.com"
# Defense in depth (issue #14): the release payload's browser_download_url
# comes from the same trust boundary as the sha256 digest we check it
# against (see issue #4), so this doesn't stop a compromised API response
# on its own -- but it stops a URL field pointed somewhere unexpected
# without also compromising these hosts.
_ALLOWED_DOWNLOAD_HOSTS: Final = frozenset(
    {
        "github.com",
        "objects.githubusercontent.com",
        "release-assets.githubusercontent.com",
    }
)
# Body read has no separate timeout; this only caps the connect/handshake.
# A 29 MB download on a 1 Mbps link takes ~230s; rely on TCP keepalive for
# stalled-transfer detection rather than a per-call wall clock.
REQUEST_TIMEOUT: Final = 30
_DOWNLOAD_CHUNK: Final = 65536


class _AssetPayload(TypedDict):
    name: str
    browser_download_url: str
    size: NotRequired[int]
    digest: NotRequired[str]


class _ReleasePayload(TypedDict, total=False):
    tag_name: str
    html_url: str
    assets: list[_AssetPayload]


class _ProcessInfo(TypedDict):
    ProcessId: int
    CommandLine: NotRequired[str | None]


@dataclass(frozen=True, slots=True)
class Asset:
    """A downloadable asset attached to a GitHub Release."""

    name: str
    download_url: str
    size: int
    # sha256:<hex>; empty string when the source does not provide one.
    digest: str

    @property
    def suffix(self) -> str:
        """Return the platform suffix after the ``cgate-`` prefix."""
        return self.name.removeprefix("cgate-")


@dataclass(frozen=True, slots=True)
class Release:
    """A GitHub Release with its downloadable assets."""

    tag: str
    version: str
    html_url: str
    assets: tuple[Asset, ...]


class UpdateError(Exception):
    """Network, parse, or filesystem error during update."""


def fetch_latest_release(repo: str = DEFAULT_REPO) -> Release:
    """Fetch the latest published GitHub Release via the public API."""
    url = f"{GITHUB_API}/repos/{repo}/releases/latest"
    request = urllib.request.Request(  # noqa: S310 -- URL is fixed to the HTTPS GitHub API.
        url, headers={"Accept": "application/vnd.github+json"}
    )
    try:
        with urllib.request.urlopen(  # noqa: S310 -- Request contains an HTTPS URL.
            request, timeout=REQUEST_TIMEOUT
        ) as response:
            payload = response.read()
    except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError) as exc:
        msg = f"failed to fetch {url}: {exc}"
        raise UpdateError(msg) from exc

    try:
        data: _ReleasePayload = json.loads(payload)
        return _parse_release(data)
    except (json.JSONDecodeError, KeyError, TypeError, ValueError) as exc:
        msg = f"malformed release JSON: {exc}"
        raise UpdateError(msg) from exc


def _parse_release(data: _ReleasePayload) -> Release:
    tag = data.get("tag_name", "")
    assets = tuple(
        Asset(
            name=asset["name"],
            download_url=asset["browser_download_url"],
            size=int(asset.get("size", 0)),
            digest=asset.get("digest", ""),
        )
        for asset in data.get("assets", [])
    )
    return Release(
        tag=tag,
        version=tag.removeprefix("v"),
        html_url=data.get("html_url", ""),
        assets=assets,
    )


def select_asset(release: Release) -> Asset | None:
    """Pick the release asset matching the current OS and architecture."""
    suffix = _platform_suffix()
    return next((asset for asset in release.assets if asset.suffix == suffix), None)


def _platform_suffix() -> str:
    match sys.platform:
        case "win32":
            return "windows-amd64.exe"
        case "darwin":
            return "macos-arm64"
        case _:
            return "linux-x86_64"


def compare_versions(current: str, latest: str) -> int:
    """Compare versions per PEP 440.

    Returns positive when ``current`` is newer than ``latest``, zero when
    equal, negative when ``current`` is older. Dev segments (``0.1.6.dev1``)
    and local segments (``+g<hash>``) are handled correctly, unlike a naive
    split-and-compare which falls back to lexicographic order on those.

    Falls back to lexicographic comparison when either string is not a
    valid PEP 440 version, so legacy data sources cannot crash the updater.
    """

    def _parse(version: str) -> Version | None:
        try:
            return Version(version)
        except InvalidVersion:
            return None

    parsed_current = _parse(current)
    parsed_latest = _parse(latest)
    if parsed_current is not None and parsed_latest is not None:
        if parsed_current > parsed_latest:
            return 1
        if parsed_current < parsed_latest:
            return -1
        return 0
    if latest != current:
        return (current > latest) - (current < latest)
    return 0


def _ensure_allowed_download_host(url: str) -> None:
    """Refuse to fetch a release asset from an unexpected host (issue #14)."""
    parsed = urllib.parse.urlsplit(url)
    if parsed.scheme != "https" or parsed.hostname not in _ALLOWED_DOWNLOAD_HOSTS:
        msg = f"refusing to download from untrusted host: {url}"
        raise UpdateError(msg)


def download_to(asset: Asset, dest: Path) -> None:
    """Stream an asset to a file and verify size + sha256 before committing.

    The download is staged to ``<dest>.part`` and only renamed onto
    ``dest`` after both the byte count and the SHA-256 match what the
    GitHub Release payload advertised. A mismatch (truncated transfer,
    mirror mismatch, MITM) leaves the part file unlinked and raises
    ``UpdateError`` instead of installing a half-downloaded binary.
    """
    _ensure_allowed_download_host(asset.download_url)
    dest.parent.mkdir(parents=True, exist_ok=True)
    temporary = dest.with_suffix(dest.suffix + ".part")
    sha256 = hashlib.sha256()
    bytes_downloaded = 0
    committed = False
    try:
        with urllib.request.urlopen(  # noqa: S310 -- release assets are HTTPS URLs.
            asset.download_url, timeout=REQUEST_TIMEOUT
        ) as response, temporary.open("wb") as output:
            while True:
                chunk = response.read(_DOWNLOAD_CHUNK)
                if not chunk:
                    break
                output.write(chunk)
                sha256.update(chunk)
                bytes_downloaded += len(chunk)
        if asset.size and bytes_downloaded != asset.size:
            raise UpdateError(
                f"size mismatch: expected {asset.size} bytes, got {bytes_downloaded}"
            )
        if asset.digest:
            expected = asset.digest.removeprefix("sha256:")
            actual = sha256.hexdigest()
            if actual != expected:
                raise UpdateError(
                    f"sha256 mismatch: expected {expected[:16]}..., got {actual[:16]}..."
                )
        _ = temporary.replace(dest)
        committed = True
    except (urllib.error.HTTPError, urllib.error.URLError, OSError, TimeoutError) as exc:
        msg = f"download failed: {exc}"
        raise UpdateError(msg) from exc
    finally:
        if not committed:
            temporary.unlink(missing_ok=True)


GITHUB_OIDC_ISSUER: Final = "https://token.actions.githubusercontent.com"
_SLSA_PROVENANCE_PREDICATE: Final = "https://slsa.dev/provenance/v1"


def _fetch_attestations(asset: Asset, repo: str) -> list[dict[str, object]]:
    """Fetch the raw attestation entries GitHub has for ``asset.digest``.

    Raises ``UpdateError`` if there is no digest to look up, the request
    fails, or GitHub reports no attestation for this digest -- via a bare
    404 (no JSON body) for a digest nothing was ever attested for, or an
    empty ``attestations`` list, which the API does not use today but
    which costs nothing to also treat as "none found".
    """
    if not asset.digest:
        msg = f"cannot verify authenticity: release did not report a digest for {asset.name}"
        raise UpdateError(msg)

    url = f"{GITHUB_API}/repos/{repo}/attestations/{asset.digest}"
    request = urllib.request.Request(  # noqa: S310 -- URL is fixed to the HTTPS GitHub API.
        url, headers={"Accept": "application/vnd.github+json"}
    )
    not_found_msg = (
        f"no build-provenance attestation found for {asset.name} "
        f"(digest {asset.digest}) -- refusing to install an unverifiable binary"
    )
    try:
        with urllib.request.urlopen(  # noqa: S310 -- Request contains an HTTPS URL.
            request, timeout=REQUEST_TIMEOUT
        ) as response:
            payload = response.read()
    except urllib.error.HTTPError as exc:
        if exc.code == HTTPStatus.NOT_FOUND:
            raise UpdateError(not_found_msg) from exc
        msg = f"failed to fetch attestation for {asset.name}: {exc}"
        raise UpdateError(msg) from exc
    except (urllib.error.URLError, TimeoutError) as exc:
        msg = f"failed to fetch attestation for {asset.name}: {exc}"
        raise UpdateError(msg) from exc

    try:
        data = json.loads(payload)
        attestations = data.get("attestations", [])
    except (json.JSONDecodeError, AttributeError) as exc:
        msg = f"malformed attestation response for {asset.name}: {exc}"
        raise UpdateError(msg) from exc

    if not attestations:
        raise UpdateError(not_found_msg)
    return attestations


def _matches_attested_subject(
    entry: dict[str, object],
    *,
    identity_policy: VerificationPolicy,
    verifier: Verifier,
    expected_digest: str,
) -> str | None:
    """Verify one attestation entry against ``identity_policy``.

    Returns ``None`` on a fully matching, verified entry, or a
    human-readable reason it didn't match otherwise -- never raises, so
    the caller can try every entry and report all the reasons together.
    """
    from sigstore.errors import VerificationError  # noqa: PLC0415
    from sigstore.models import Bundle  # noqa: PLC0415

    try:
        bundle = Bundle.from_json(json.dumps(entry["bundle"]))
        _, raw_statement = verifier.verify_dsse(bundle, identity_policy)
        statement = json.loads(raw_statement)
    except (KeyError, TypeError, ValueError, VerificationError) as exc:
        return str(exc)
    if statement.get("predicateType") != _SLSA_PROVENANCE_PREDICATE:
        return f"unexpected predicateType: {statement.get('predicateType')}"
    subjects = statement.get("subject", [])
    if any(subject.get("digest", {}).get("sha256") == expected_digest for subject in subjects):
        return None
    return "attested subject digest does not match the downloaded asset"


def verify_attestation(asset: Asset, release: Release, *, repo: str = DEFAULT_REPO) -> None:
    """Verify the downloaded asset's GitHub Actions build-provenance attestation.

    ``download_to`` already checks ``asset.digest`` against the downloaded
    bytes, but that digest comes from the same Release API response as the
    download URL itself -- it only proves the bytes were not corrupted or
    substituted in transit, not that they came from our own release
    workflow (issue #4). This additionally requires a Sigstore-signed
    attestation, issued by GitHub's OIDC provider to *this* repo's release
    workflow at *this exact tag* (the ``attest-build-provenance`` step in
    ``release.yml``), whose signed subject digest matches ``asset.digest``.

    Uses the bundled Sigstore trust root (``offline=True``) rather than
    fetching current root metadata via TUF on every update check: this
    avoids adding a second live trust dependency to the update path, at
    the cost of needing a ``sigstore`` package upgrade if Sigstore ever
    rotates its root keys (rare and well-announced).

    Fail-closed, intentionally with no bypass flag (same posture as the
    download host allow-list, issue #14): raises ``UpdateError`` if the
    digest is missing, no attestation exists, the signature/identity does
    not check out, or the attested subject does not match this asset.
    """
    # Deferred: sigstore pulls in tuf/cryptography and costs ~0.6s to
    # import. cli/update.py is loaded on every `cgate` invocation (it's
    # registered as a sub-app in main()), so a top-level import here would
    # tax every command, not just `update apply`.
    import logging  # noqa: PLC0415

    from sigstore.verify import Verifier  # noqa: PLC0415
    from sigstore.verify import policy as verify_policy  # noqa: PLC0415

    attestations = _fetch_attestations(asset, repo)

    # The warning is expected and permanent given `offline=True` below; it
    # would otherwise print an unstyled line to stderr on every `apply` via
    # Python's handler-less-root lastResort handler.
    logging.getLogger("sigstore").setLevel(logging.ERROR)

    identity_policy = verify_policy.AllOf(
        [
            verify_policy.OIDCIssuer(GITHUB_OIDC_ISSUER),
            verify_policy.GitHubWorkflowRepository(repo),
            verify_policy.GitHubWorkflowRef(f"refs/tags/{release.tag}"),
        ]
    )
    verifier = Verifier.production(offline=True)
    expected_digest = asset.digest.removeprefix("sha256:")

    errors = [
        reason
        for entry in attestations
        if (
            reason := _matches_attested_subject(
                entry,
                identity_policy=identity_policy,
                verifier=verifier,
                expected_digest=expected_digest,
            )
        )
        is not None
    ]
    if len(errors) < len(attestations):
        return  # at least one entry matched

    msg = (
        f"could not verify a build-provenance attestation for {asset.name} against "
        f"{repo}@refs/tags/{release.tag}: {'; '.join(errors) or 'no valid attestation'}"
    )
    raise UpdateError(msg)


def replace_binary(new_path: Path, target: Path) -> str | None:
    """Replace ``target`` with ``new_path``. Return None on success or an
    error description (suitable for printing) on failure.

    The string distinguishes a Windows file lock from a generic OSError so
    the CLI can recommend the right recovery (kill running process vs.
    check permissions / antivirus).
    """
    try:
        _ = new_path.replace(target)
    except PermissionError as exc:
        return f"permission denied: {exc}"
    except OSError as exc:
        return f"{type(exc).__name__}: {exc}"
    return None


def find_blocking_processes(
    binary_path: Path, *, exclude_pid: int | None = None
) -> list[int]:
    """Return PIDs of running processes whose image name matches the binary.

    Uses ``tasklist`` on Windows (the only platform where executables are
    locked while running). Returns an empty list on other platforms or when
    the lookup cannot be performed, so the caller can fall back to a manual
    message without crashing. ``exclude_pid`` lets the caller skip its own
    process so an in-place update does not suicide before reporting success.
    """
    if sys.platform != "win32":
        return []
    try:
        completed = subprocess.run(
            ["tasklist", "/FO", "CSV", "/NH"],
            capture_output=True,
            text=True,
            check=False,
            timeout=10,
        )
    except (subprocess.SubprocessError, OSError):
        return []
    target_name = binary_path.name.lower()
    pids: list[int] = []
    for line in completed.stdout.splitlines():
        parts = [part.strip().strip('"') for part in line.split(",")]
        if len(parts) < 2 or parts[0].lower() != target_name:
            continue
        try:
            pid = int(parts[1])
        except ValueError:
            continue
        if exclude_pid is not None and pid == exclude_pid:
            continue
        pids.append(pid)
    return pids


def find_mcp_serving_pids(pids: list[int]) -> list[int]:
    """Return which of the given PIDs were launched as ``cgate mcp serve``.

    Distinguishes "another cgate.exe happens to be running" from "a live MCP
    session an IA client is actively depending on", so callers can warn
    accordingly before killing it (see issue #19). Windows only; returns an
    empty list on other platforms, when there is nothing to check, or when
    the command-line lookup itself fails -- callers then fall back to a
    generic warning rather than a hard failure. Uses PowerShell's CIM
    cmdlets rather than the deprecated ``wmic``, which newer Windows builds
    no longer ship.
    """
    if sys.platform != "win32" or not pids:
        return []
    try:
        completed = subprocess.run(
            [
                "powershell",
                "-NoProfile",
                "-NonInteractive",
                "-Command",
                (
                    "Get-CimInstance Win32_Process -Filter \"Name='cgate.exe'\" "
                    "| Select-Object ProcessId, CommandLine | ConvertTo-Json -Compress"
                ),
            ],
            capture_output=True,
            text=True,
            check=False,
            timeout=10,
        )
    except (subprocess.SubprocessError, OSError):
        return []
    if completed.returncode != 0 or not completed.stdout.strip():
        return []
    try:
        payload: _ProcessInfo | list[_ProcessInfo] = json.loads(completed.stdout)
    except json.JSONDecodeError:
        return []
    rows = [payload] if isinstance(payload, dict) else payload
    wanted = set(pids)
    return [
        row["ProcessId"]
        for row in rows
        if row.get("ProcessId") in wanted
        and (row.get("CommandLine") or "").strip().lower().endswith("mcp serve")
    ]


def kill_process(pid: int) -> bool:
    """Force-kill the process with the given PID. Returns True on success."""
    if sys.platform != "win32":
        return False
    try:
        completed = subprocess.run(
            ["taskkill", "/F", "/PID", str(pid)],
            capture_output=True,
            text=True,
            check=False,
            timeout=10,
        )
    except (subprocess.SubprocessError, OSError):
        return False
    return completed.returncode == 0


def current_binary_path() -> Path | None:
    """Return the running cgate binary path, or ``None`` in development mode."""
    executable = Path(sys.executable).resolve()
    return executable if executable.name.startswith("cgate") else None
