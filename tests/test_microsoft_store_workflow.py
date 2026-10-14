from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "microsoft-store.yml"


def load_workflow():
    return yaml.load(WORKFLOW.read_text(), Loader=yaml.BaseLoader)


def test_store_workflow_is_manual_unsigned_msix_and_distribution_scoped():
    workflow = load_workflow()
    assert set(workflow["on"]) == {"workflow_dispatch"}
    assert workflow["env"]["VOICESTUDIO_DISTRIBUTION"] == "microsoft-store"
    assert workflow["env"]["CSC_IDENTITY_AUTO_DISCOVERY"] == "false"
    package = workflow["jobs"]["package"]
    build = next(step for step in package["steps"] if step.get("name") == "Build unsigned Store MSIX")
    assert "electron-builder" in build["run"]
    assert "--win appx --x64" in build["run"]
    assert "--publish never" in build["run"]
    source = WORKFLOW.read_text()
    assert "ELECTRON_WINDOWS_CSC" not in source
    assert "store-submission-api" not in source


def test_checkouts_do_not_persist_github_credentials():
    workflow = load_workflow()
    checkouts = [
        step
        for job in workflow["jobs"].values()
        for step in job.get("steps", [])
        if str(step.get("uses", "")).startswith("actions/checkout@")
    ]
    assert checkouts
    assert all(step.get("with", {}).get("persist-credentials") == "false" for step in checkouts)


def test_store_package_records_msix_wack_and_provenance_evidence():
    package = load_workflow()["jobs"]["package"]
    names = [step.get("name") for step in package["steps"]]
    assert "Verify MSIX identity and manifest" in names
    assert "Install and launch a temporary self-signed copy" in names
    assert "Run Windows App Certification Kit" in names
    assert "Record provenance" in names
    assert "Create Partner Center handoff" in names
    upload = next(
        step for step in package["steps"] if step.get("name") == "Save Partner Center handoff"
    )
    paths = upload["with"]["path"]
    assert "VoiceStudio-MicrosoftStore-*-win-x64.msix" in paths
    assert "msix-verification-win32-x64.json" in paths
    assert "wack-win32-x64.xml" in paths
    assert "microsoft-store-submission.json" in paths


def test_only_disposable_copies_are_self_signed():
    source = WORKFLOW.read_text()
    assert "Copy-Item $source.FullName $testPackage" in source
    assert "sign /fd SHA256" in source
    assert "VoiceStudio-Wack-x64.msix" in source
    assert "AppxSignature.p7x" not in source


def test_appx_commands_run_in_windows_powershell():
    package = load_workflow()["jobs"]["package"]
    appx_steps = [
        step
        for step in package["steps"]
        if step.get("name")
        in {
            "Install and launch a temporary self-signed copy",
            "Run Windows App Certification Kit",
        }
    ]
    assert len(appx_steps) == 2
    assert all(step.get("shell") == "powershell" for step in appx_steps)
    assert all("Copy-Item $source.FullName $testPackage" in step["run"] for step in appx_steps)
    assert all("Cert:\\LocalMachine\\TrustedPeople" in step["run"] for step in appx_steps)
    install_step = next(
        step
        for step in appx_steps
        if step["name"] == "Install and launch a temporary self-signed copy"
    )
    assert "Get-AppxPackageManifest" in install_step["run"]
    assert "shell:AppsFolder\\$aumid" in install_step["run"]
