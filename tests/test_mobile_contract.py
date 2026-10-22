"""The mobile apps build against committed, generated contracts.

Both fail when the source they were generated from changes without a
regeneration in the same PR, so iOS and Android never drift from the backend
API or the desktop theme.
"""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
CONTRACT = ROOT / "mobile" / "contract"

sys.path.insert(0, str(ROOT / "scripts"))
import export_openapi  # noqa: E402


def test_openapi_contract_matches_backend():
    committed = (CONTRACT / "openapi.json").read_text(encoding="utf-8")
    assert committed == export_openapi.render(export_openapi.build_schema()), (
        "mobile/contract/openapi.json is stale; run `uv run python scripts/export_openapi.py`"
    )


def test_openapi_operation_ids_are_unique():
    schema = json.loads((CONTRACT / "openapi.json").read_text(encoding="utf-8"))
    ids = [op["operationId"] for ops in schema["paths"].values() for op in ops.values() if "operationId" in op]
    assert len(ids) == len(set(ids))


# Resolve the binary once, the way test_uninstall_elevation.py resolves `pwsh`.
# A bare "bun" argv[0] is NOT launchable everywhere: an npm-installed bun on
# Windows is `bun`, `bun.cmd` and `bun.ps1` with no `bun.exe`, and CreateProcess
# does not apply PATHEXT the way shutil.which does. So `which` finds the shim,
# the spawn then fails, and the probe raises instead of answering.
BUN = shutil.which("bun")


def _electron_deps_installed() -> bool:
    """Whether bun can resolve the Electron workspace's installed deps.

    Never raises. This runs inside the skipif decorator below, i.e. at
    COLLECTION time, so an exception escaping here does not skip one test — it
    aborts the entire `tests/` session (pytest exits 2 having run nothing),
    which is what a bare "bun" argv[0] did on every Windows checkout. A probe
    whose whole job is "is this optional tool usable?" answers False when it
    cannot find out; it does not take the suite down with it.
    """
    if BUN is None:
        return False
    try:
        probe = subprocess.run(
            [BUN, "--no-install", "-e", "Bun.resolveSync('tailwindcss/theme.css', process.argv[1])", str(ROOT / "electron")],
            capture_output=True, timeout=60,
        )
    except (OSError, subprocess.SubprocessError):
        # OSError: cannot be launched at all. SubprocessError: TimeoutExpired
        # from a wedged bun — also not an answer, and also not worth the suite.
        return False
    return probe.returncode == 0


# ci.yml also runs `bun scripts/export-mobile-tokens.ts --check` after
# `bun install`, so this skip can't hide drift on CI.
@pytest.mark.skipif(not _electron_deps_installed(), reason="needs bun and installed Electron deps")
def test_mobile_tokens_match_electron_theme():
    # BUN is non-None here: the skipif above only lets this run once the probe
    # has launched it successfully.
    result = subprocess.run(
        [BUN, "--no-install", "scripts/export-mobile-tokens.ts", "--check"],
        cwd=ROOT, capture_output=True, text=True, timeout=120,
    )
    assert result.returncode == 0, result.stderr


# ── the probe's own contract (#878-style: a guard that fails open, loudly) ───
# These exist because the failure they pin was invisible to CI: `bun` is a real
# binary on the Linux/macOS runners, so the bare-name spawn worked there and
# died only on a contributor's Windows checkout — with pytest exiting 2 and no
# test output to connect it to anything.

def _probe_with(monkeypatch, bun, run):
    module = sys.modules[__name__]
    monkeypatch.setattr(module, "BUN", bun, raising=False)
    monkeypatch.setattr(subprocess, "run", run)


def test_electron_probe_launches_the_resolved_bun_path(monkeypatch):
    seen = []

    def record(argv, **kwargs):
        seen.append(argv)
        return subprocess.CompletedProcess(argv, 0, b"", b"")

    _probe_with(monkeypatch, "/shim/bun.cmd", record)
    assert _electron_deps_installed() is True
    assert seen[0][0] == "/shim/bun.cmd", (
        "argv[0] must be the resolved binary, not a bare 'bun': on Windows the "
        "npm shim has no .exe and CreateProcess cannot launch it"
    )


def test_electron_probe_treats_an_unlaunchable_bun_as_not_installed(monkeypatch):
    def unlaunchable(argv, **kwargs):
        raise FileNotFoundError(2, "The system cannot find the file specified")

    _probe_with(monkeypatch, "/shim/bun.cmd", unlaunchable)
    assert _electron_deps_installed() is False


def test_electron_probe_treats_a_wedged_bun_as_not_installed(monkeypatch):
    def wedged(argv, **kwargs):
        raise subprocess.TimeoutExpired(cmd=argv, timeout=60)

    _probe_with(monkeypatch, "/shim/bun.cmd", wedged)
    assert _electron_deps_installed() is False


def test_mobile_string_keys_are_namespaced():
    for path in CONTRACT.glob("strings*.en.json"):
        data = json.loads(path.read_text(encoding="utf-8"))
        assert list(data) == ["mobile"], f"{path.name}: new mobile keys belong under `mobile.`"


def test_openapi_contract_is_version_neutral():
    # The app version differs by environment and changes every release; a
    # contract that embedded it would go stale on every version bump.
    schema = {"info": {"version": "9.8.7"}, "components": {"x": {"default": "9.8.7"}}}
    rendered = json.loads(export_openapi.render(schema))
    assert "9.8.7" not in json.dumps(rendered)
    committed = json.loads((CONTRACT / "openapi.json").read_text(encoding="utf-8"))
    assert committed["info"]["version"] == export_openapi.VERSION_PLACEHOLDER
