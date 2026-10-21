"""User-started provisioning for the current interpreter, stdlib only."""

import argparse
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

from .artifacts import checked_wheel, download_archive
from .failures import VerificationFailure, failure_report
from .recipe import load_recipe, recipe_identity, validate_target
from .verify import PROJECT_ROOT, verify_environment


def install_command(uv, packages, reinstall):
    command = [str(uv), "--no-config", "pip", "install", "--python", sys.executable]
    for name in reinstall:
        command.extend(["--reinstall-package", name])
    return command + list(packages)


def run_install(command):
    # The Windows overlay intentionally differs from project/CUDA constraints.
    environment = {
        key: value
        for key, value in os.environ.items()
        if key not in {"UV_CONSTRAINT", "UV_BUILD_CONSTRAINT", "UV_OVERRIDE", "PIP_CONSTRAINT"}
    }
    try:
        subprocess.run(command, cwd=PROJECT_ROOT, env=environment, check=True, stdout=sys.stderr, timeout=1800)
    except (OSError, subprocess.CalledProcessError, subprocess.TimeoutExpired) as exc:
        raise RuntimeError(f"Windows ROCm package installation failed: {exc}") from exc


def provision(uv):
    """Reuse strictly verified installs; repair only confirmed package failures."""
    validate_target()
    try:
        return verify_environment()
    except VerificationFailure as exc:
        if not exc.repairable:
            raise
    recipe = load_recipe()
    base = recipe["torch"]["find_links"]
    # Verify CT2 before changing any package, and discard downloads on any failure.
    with tempfile.TemporaryDirectory(prefix="voicestudio-windows-rocm-") as temporary:
        folder = Path(temporary)
        archive = folder / "ctranslate2.zip"
        ct2 = recipe["ctranslate2"]
        download_archive(ct2["archive_url"], archive, ct2["archive_size"])
        wheel = checked_wheel(archive, folder, ct2)
        urls = [base + name for section in ("runtime", "torch") for name in recipe[section]["wheel_files"]]
        pins = recipe["runtime"]["packages"] + recipe["torch"]["packages"]
        run_install(install_command(uv, urls, [pin.split("==")[0] for pin in pins]))
        # Dependencies (e.g. PyYAML, numpy) remain resolved by uv; HIP binary stays pinned.
        run_install(install_command(uv, [str(wheel)], ["ctranslate2"]))
    return verify_environment()


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--uv", default="uv", help="uv executable used for this interpreter")
    parser.add_argument("--verify-only", action="store_true", help="No downloads, model access or package changes")
    args = parser.parse_args(argv)
    try:
        validate_target()
        report = verify_environment() if args.verify_only else provision(args.uv)
        print(json.dumps(dict(report, recipe_sha256=recipe_identity())))
        return 0
    except Exception as exc:  # noqa: BLE001 - CLI boundary emits bounded machine-readable failure.
        print(json.dumps(failure_report(exc)))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
