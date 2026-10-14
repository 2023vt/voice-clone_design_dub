# Microsoft Store publishing runbook

## Current status

- Package: unsigned x64 MSIX for Partner Center; direct NSIS installers are unchanged.
- Identity: `Yupcha.VoiceStudio`, Store ID `9PDMFM4FG106`.
- Update owner: Microsoft Store. The in-app updater is unavailable in this build.
- Signing: Microsoft signs the package after certification; no publisher certificate is required.
- Submission: manual owner action after the workflow and certification evidence pass.

## Build and validate

Run the manual `Microsoft Store MSIX package` workflow on the branch or release
commit intended for submission. It:

1. validates the shared Store metadata and Partner Center identity;
2. builds an unsigned x64 MSIX without changing direct Windows packaging;
3. checks the manifest identity, publisher, four-part version, architecture and
   required capabilities;
4. signs a disposable copy with an ephemeral certificate, installs it, launches
   the packaged setup screen and removes it;
5. runs the Windows App Certification Kit against another disposable copy;
6. records package provenance and assembles the canonical listing assets.

Download the `microsoft-store-partner-center-handoff` workflow artifact. Retain:

- `VoiceStudio-MicrosoftStore-<version>-win-x64.msix`;
- `microsoft-store-submission.json`;
- `store-artifact-manifest-win32-x64.json`;
- `msix-verification-win32-x64.json`;
- `wack-win32-x64.xml`;
- the `listing/` directory.

Only the original unsigned MSIX is a submission artifact. The ephemeral test
certificate and signed copies never leave the workflow runner.

## Submit

In Partner Center, open VoiceStudio (`9PDMFM4FG106`) and start a submission:

1. upload the validated x64 MSIX under Packages;
2. set pricing and availability, category, age ratings and properties;
3. use `store/metadata.json`, `store/privacy.json` and the generated listing
   assets for descriptions, URLs, logo and screenshots;
4. declare generative AI and voice cloning accurately and explain that audio is
   marked through VoiceStudio's synthetic-audio path;
5. note for certification that the managed runtime and models are downloaded
   only after explicit user actions and stored in the user's writable data area;
6. submit privately first and record the submission ID and review findings.

Do not upload the direct NSIS EXE to this MSIX product. Do not sign the Store
artifact locally; Microsoft re-signs accepted MSIX packages.

## Acceptance and rollback

After certification, install from the private Store audience on a clean Windows
10/11 x64 machine. Verify first-run runtime setup, model installation, synthesis,
microphone capture, import/export, offline relaunch and a Store-delivered update.
Promote availability only after those checks pass.

For a failed submission, fix the branch and submit a package with a higher
four-part package version. Never reuse package identity with lower or equal
version bytes. Before publication, withdraw the submission in Partner Center;
after publication, remove availability there without changing direct downloads.

Lifecycle: `built -> WACK passed -> submitted -> certified -> private install verified -> published`
