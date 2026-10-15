# Snap Store runbook

## Current status

- Branch: `feat/snap-store`, based on `feat/store-publishing-foundation`.
- Lifecycle: packaging prepared; no store revision has been uploaded.
- Package: Electron x64 Snap alongside the existing AppImage and Debian packages.
- Confinement: `strict`, using the `core22` base supported by the pinned
  electron-builder. Recheck the supported bases before the first submission.
- Update owner: Snap Store. The in-app updater is unavailable in this build.
- Expected Snap name: `voicestudio`; the owner must reserve and confirm it
  before any upload workflow is added or run.

No store credentials, listing changes, uploads or releases are part of the
build-only rehearsal workflow.

## Package and interface contract

Build with `VOICESTUDIO_DISTRIBUTION=snap-store`. The resulting package embeds
`snap-store` and `store` as its distribution and update-owner metadata. Direct
Linux builds still produce AppImage and Debian packages with their existing
updater metadata.

The Snap requests only interfaces needed by maintained desktop behaviour:

| Interface | Purpose | Connection expectation |
| --- | --- | --- |
| `browser-support` | Chromium sandbox inside strict confinement | Automatic with `allow-sandbox: true` |
| `desktop`, `desktop-legacy`, `x11`, `wayland`, `unity7`, `gsettings` | Desktop integration | Automatic on supported desktops |
| `network` | User-started runtime and model downloads | Automatic |
| `network-bind` | Local backend and opt-in LAN sharing | Automatic |
| `audio-playback` | Preview and generated audio playback | Automatic |
| `audio-record` | User-started recording and dictation | Manual unless the Store grants auto-connect |
| `opengl` | GPU/display access | Automatic |
| `home` | Non-hidden user files and project folders | Automatic on traditional distributions |

`removable-media` is intentionally absent. Electron's file chooser uses the
desktop portal, which grants access to the exact user-selected file, including
files on removable media. Add a broader interface only if confinement testing
proves a maintained workflow cannot use the portal, and document the Store
review request here first.

Snap rewrites `HOME` into its writable user-data area. Consequently Electron
settings, the managed runtime, backend data, models and caches remain writable
and survive refresh through Snap's data-copy lifecycle. User-selected imports
and exports use portal paths. Validate custom runtime and data relocation
separately: a selected portal file is not guaranteed to retain executable
permissions.

## Build and inspect

Run the build-only GitHub workflow `.github/workflows/snap-store.yml`, or on an
x64 Linux builder:

```bash
export VOICESTUDIO_DISTRIBUTION=snap-store
export VOICESTUDIO_RUST_TARGET=x86_64-unknown-linux-gnu
node scripts/validate_store_foundation.mjs --distribution=snap-store
bun install --frozen-lockfile
bun run check:electron
cd electron
bun x electron-builder --config electron-builder.config.mjs --linux snap --x64 --publish never
node tests/packaging-contract.mjs --artifact
node ../scripts/verify_snap_artifact.mjs
node ../scripts/create_store_artifact_manifest.mjs --distribution=snap-store --platform=linux --arch=x64
node ../scripts/create_snap_store_assets.mjs
```

Inspect these workflow artifacts before installing:

- `VoiceStudio-Electron-<version>-linux-x64.snap`
- `VoiceStudio-Electron-<version>-snap-verification.json`
- `store-artifact-manifest-linux-x64.json`
- `snap-store-assets/icon.png`, five screenshots and `listing-assets.json`

The package verifier also requires electron-builder's desktop runtime scripts
and libraries to be expanded at the Snap root. A nested template archive or a
missing `desktop-init.sh` is a blocking packaging failure.

The asset manifest derives only from `store/assets.json`; do not fork listing
copy or image sources in the Snap dashboard.

## Confinement validation

Install the rehearsal locally with `sudo snap install --dangerous <file>.snap`.
Record `snap connections voicestudio` and relevant denials from the system log.
Connect `audio-record` manually while testing until an auto-connect request is
approved.

Complete every item on a clean supported host:

- clean install and first launch;
- first-run managed Python installation and offline relaunch;
- model installation followed by offline synthesis;
- microphone capture, audio playback and dictation;
- GPU discovery and one GPU-backed generation where hardware is available;
- file import/export in the home directory and on removable media through the portal;
- project open/save and watch-folder access;
- custom runtime and data-location selection, restart and cleanup;
- opt-in LAN sharing, including backend binding and a second-device request;
- refresh to a newer candidate revision and rollback to the previous revision;
- removal without affecting AppImage/Debian data or installation.

A failed item is a branch blocker. Prefer a narrower interface or portal flow;
do not switch to classic confinement merely to pass the test.

## Submission and evidence

The owner must first reserve the name, approve visibility and listing answers,
and add narrowly scoped Snapcraft credentials as a repository secret. Upload
the validated artifact without releasing it, record the assigned revision, then
release that exact revision to `candidate`. Stable promotion requires a separate
owner approval after independent install, refresh and rollback verification.

For each submitted revision retain:

- the package and `store-artifact-manifest-linux-x64.json`;
- the Store revision number and channel;
- the downloaded Snap assertion and its SHA-256 digest;
- automated/manual review findings and their resolutions;
- `snap connections`, install, refresh, rollback and offline-test logs;
- the workflow run URL and source commit.

Set `signingVerification` in the final provenance record only after the Store
assertion has been downloaded and matched to the submitted revision.

Recheck Canonical's current documentation before submission: [strict
confinement](https://snapcraft.io/docs/explanation/security/snap-confinement/),
[interfaces](https://snapcraft.io/docs/reference/interfaces/), [desktop file
portals](https://snapcraft.io/docs/explanation/snap-development/xdg-desktop-portals/)
and [revision/channel management](https://documentation.ubuntu.com/snapcraft/stable/how-to/publishing/manage-revisions-and-releases/).

## Rollback or delisting

To recover one test machine, use `sudo snap revert voicestudio` or specify the
known-good revision. For a channel rollback, have the owner release the previous
known-good revision back to that channel, verify a refresh on a separate host,
and record the new channel map. Closing a channel or changing listing visibility
is an owner action; document its effect on existing installations before doing
either.
