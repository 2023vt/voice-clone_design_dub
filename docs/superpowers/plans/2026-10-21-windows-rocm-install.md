# Windows ROCm installation repair

> Execute with superpowers:subagent-driven-development. Owner authorization: keep full Windows installation in #3045. Do not pause for another scope approval.

**Goal:** Complete opt-in native Windows ROCm provisioning for source and Electron in existing PR #3045, using one verified recipe and honest engine capability gates.

**Design:** `docs/superpowers/specs/2026-10-21-windows-rocm-install-design.md`

## Global Constraints

- Work only in this PR's isolated feature worktree on the existing local codex/review-3045 branch; publish to the existing PR branch with `git push origin HEAD:feat/phase2-windows-rocm`; never push/merge main. New code files <=200 lines; smallest edits to legacy large files.
- User-started opt-in only; Windows x64 Python 3.12 and AMD 7.2.1 Torch 2.9.1 stack. No Linux wheels on Windows, no default or other-OS behavior change, no automatic models or driver installation.
- One recipe, SHA-256 verified CT2 archive/member, exact package/ABI/HIP/GPU readiness; timeout/crash/CPU fallback fail. Same shared installer used by Electron and source; recipe bytes included in stamp and packaged resources.
- Preserve user data and models. Retain DLL handles for actual backend process lifetime. Preserve CPU overrides and CUDA/Linux HIP routing. No blanket sidecar pin changes or unsupported engine parity claims.
- Fail-before/pass-after tests, offline HF flags and initially empty cache. No hardware/packaged runtime success claim without measured evidence. No version bump/release. Only configured human git identity, no AI attribution.

## Task 1: Shared pinned Windows provisioning and verification

Own `scripts/windows-rocm-recipe.json`, new small modules under `backend/core/windows_rocm/`, optional `scripts/smoke_windows_rocm.py`, and focused tests. No edits to existing source/Electron/ASR entrypoints yet.

1. Inspect #2600's recipe/installer/smoke (commit 906015fa) and #2607's focused initialization helpers; verify official wheel/archive metadata and copy only needed pieces with appropriate human credit later.
2. Implement a stdlib-only recipe/installer entry point callable as target Python `-m backend.core.windows_rocm.install --uv <uv executable>` and `--verify-only`. Installer target is current interpreter, strictly win32 x64 cp312. Use subprocess children for all native probes so imports never lock packages during reinstall; bound subprocesses. Shared DLL initializer must be available for actual backend imports later.
3. Expose recipe loading/identity/ABI helpers and probe CLI suitable for Electron/source. Provision runtime dependencies, official CT2 archive/member with digest validation and no unsafe extraction, and exact version/HIP/GPU validation. Never silently fall back to CPU or accept timeouts. Use clean temporary downloads with retry safety.
4. Optional standalone smoke uses only explicit local model/WAV paths, consumes CT2 inference, refuses remote assets and reports content-free scope. No input means clearly model-free verification, not ASR proof.
5. Add meaningful failing regressions before implementation; run focused offline tests, Ruff and new-file size checks. Report commands/results and interfaces to controller, commit only owned files using configured identity. Write report in this plan's .superpowers workspace.

## Task 2: Electron and source bootstrap integration

Depends on Task 1's stable entry point. Own `electron/src/main/runtime-project.ts`, extracted <=200-line Electron helpers, `electron/scripts/torch-variant.mjs`, `scripts/setup-api.mjs`, `scripts/setup.py`, packaging config and their tests. No ASR/model_manager edits.

1. Add explicit Windows x64 ROCm selection with cp312 interpreter and strict reuse checks; preserve Linux/macOS/default/CPU/CUDA behavior. Unsupported Windows architectures must fail explicitly when ROCm is requested.
2. Skip locked torch/audio/vision/CT2 and CUDA packages before frozen sync on fresh install AND repair; invoke Task 1 installer after sync and before any torch-dependent imports/repairNativeLibraries. Disable project constraints for the Windows overlay only. Avoid importing torch into setup parent before replacement.
3. Include recipe bytes/ABI in readiness, run strict model-free Windows verification when marking/accepting ready, and never inherit current generic timeout-as-ready policy. Stage/package recipe/helpers and execute with correct working directory. Interrupted retries keep data/models.
4. Integrate source setup's variant propagation and cp312 selection. Existing direct setup.py Windows opt-in must invoke shared installer too. Tests assert actual command ordering/exclusions, correct Python, repair, stamp invalidation and other platforms.
5. Run targeted tests and TypeScript where dependencies available; record fail-before/pass-after evidence, self-review, commit owned changes and report.

## Task 3: Backend capability boundaries, docs and final validation

Own focused backend runtime compatibility hooks/tests, README, Windows install docs, credited CHANGELOG entry and any narrow integration regressions. Depends on Task 1/2.

1. Initialize HIP DLL search before all actual CT2/faster-whisper import paths and keep handles alive. Allow verified Windows HIP CT2 via hardware capability family `rocm`, preserve CPU override and old CUDA/Linux HIP behavior. Stock/non-HIP CT2 never enters native HIP execution.
2. Address removed torchaudio interfaces needed for pyannote imports with a bounded no-op-on-old-stacks adapter, or explicitly gate unsupported heavy pipelines with actionable diagnostics before native execution. Do not claim solving MIOpen Unicode/SDK problems without evidence. Main TTS/basic ASR must remain usable on installed HIP stack.
3. Do not overwrite incompatible optional sidecar pins; document accurate compatibility and setup limitations. Update Windows/README instructions for source + Electron opt-in, driver/hardware matrix, verification, repair/rollback and local-only smoke. Credit focused #2600/#2607 contributions and document overlap.
4. Run focused integration + prior backend/sidecar/GPU suites, Electron runtime/source tests, TypeScript/locales, packaging resource contract, size/format/diff checks. Distinguish mocked, no-GPU, real-native and external CI evidence. Commit and report.

## Task 4: Fresh review prerequisite and diagnostic boundaries

1. Keep the Windows ROCm source prerequisite check local in both source setup invocations; require manual VC++ installation when missing and preserve pre-existing default setup behavior. Cover missing/present prerequisites and no-download/no-process failure boundaries.
2. Trace the reported Windows/HSA prose through actual diagnostic and renderer consumers before changing localization. Preserve raw machine/CLI notes when the reported prose does not reach the active UI; record concrete call-graph evidence and scoped verification.

## Final gate

Whole-branch independent review against current main, fix confirmed findings, rerun covering tests. Update #3045 title/body to actual full installation scope/results and publish local `codex/review-3045` only with `git push origin HEAD:feat/phase2-windows-rocm` to the existing PR destination. Read fresh bot comments/checks. Keep open with clear hardware/CI gates; no merge. Comments documenting overlap already exist on all three requested PRs.

Focused PR updates use covering tests and report only measured results. Publishing
an update leaves the PR open and does not authorize a merge. Before any later
merge/landing, require current-head full active CI to be green and run these
three full validation gates separately from the repository root; all must pass:

- `uv run pytest tests/ -q`
- `uv run pytest backend/tests/ -q`
- `bun run check:electron`

For each gate, set `HF_HUB_OFFLINE=1` and point `HF_HUB_CACHE` at a newly created,
initially empty directory. Record the full-gate results separately from focused
checks and external CI evidence. These are before-merge requirements; listing
them does not claim that they have run or passed. This task still performs no merge.
