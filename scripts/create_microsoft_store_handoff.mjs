import assert from "node:assert/strict";
import { createHash } from "node:crypto";
import {
  closeSync,
  existsSync,
  openSync,
  readFileSync,
  readSync,
  readdirSync,
  statSync,
  writeFileSync,
} from "node:fs";
import { basename, dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const root = resolve(dirname(fileURLToPath(import.meta.url)), "..");

function sha256(path) {
  const hash = createHash("sha256");
  const descriptor = openSync(path, "r");
  const buffer = Buffer.allocUnsafe(1024 * 1024);
  try {
    for (;;) {
      const length = readSync(descriptor, buffer, 0, buffer.length, null);
      if (!length) break;
      hash.update(buffer.subarray(0, length));
    }
  } finally {
    closeSync(descriptor);
  }
  return hash.digest("hex");
}

export function createMicrosoftStoreHandoff({
  releaseDir,
  output,
  version,
  generatedAt = new Date().toISOString(),
}) {
  assert.match(version, /^\d+\.\d+\.\d+$/, "Version must be a release version");

  const packages = readdirSync(releaseDir)
    .filter((name) =>
      new RegExp(
        `^VoiceStudio-MicrosoftStore-${version.replaceAll(".", "\\.")}-win-(x64|arm64)\\.msix$`,
      ).test(name),
    )
    .sort()
    .map((file) => {
      const architecture = file.match(/-win-(x64|arm64)\.msix$/)?.[1];
      assert(architecture, `Cannot determine architecture for ${file}`);
      const provenance = `store-artifact-manifest-win32-${architecture}.json`;
      const verification = `msix-verification-win32-${architecture}.json`;
      const wackReport = `wack-win32-${architecture}.xml`;
      for (const evidence of [provenance, verification, wackReport]) {
        assert(existsSync(resolve(releaseDir, evidence)), `Missing validation evidence: ${evidence}`);
      }
      const manifest = JSON.parse(readFileSync(resolve(releaseDir, provenance), "utf8"));
      assert.equal(manifest.distribution?.target, "microsoft-store");
      assert.equal(manifest.distribution?.applicationUpdates, "store");
      assert.deepEqual(manifest.signingVerification, {
        status: "store-pending",
        evidence: verification,
      });
      const path = resolve(releaseDir, file);
      const digest = sha256(path);
      const artifact = manifest.artifacts?.find((item) => item.file === file);
      assert(artifact, `${provenance} does not describe ${file}`);
      assert.equal(artifact.bytes, statSync(path).size, `${file} size differs from provenance`);
      assert.equal(artifact.sha256, digest, `${file} digest differs from provenance`);
      return {
        architecture,
        type: "msix",
        file,
        sha256: digest,
        bytes: statSync(path).size,
        provenance,
        verification,
        wackReport,
        signing: "Microsoft Store after certification",
      };
    });

  assert(packages.some((item) => item.architecture === "x64"), "An x64 MSIX is required");
  const metadata = JSON.parse(readFileSync(resolve(root, "store/metadata.json"), "utf8"));
  const assets = JSON.parse(readFileSync(resolve(root, "store/assets.json"), "utf8"));
  const handoff = {
    schemaVersion: 2,
    generatedAt,
    lifecycle: "validated-for-submission",
    ownerApprovalRequiredForSubmission: true,
    identity: metadata.microsoftStore,
    listing: metadata.listing,
    category: metadata.categories["microsoft-store"],
    privacyPolicyUrl: metadata.urls.privacyPolicy,
    supportUrl: metadata.urls.support,
    applicableLicenseTermsUrl: `${metadata.urls.source}/blob/main/LICENSE`,
    supportedLanguages: [metadata.identity.defaultLocale.toLowerCase()],
    assets: {
      boxArt: assets.iconSource,
      screenshots: assets.screenshots,
    },
    packages,
  };
  writeFileSync(output, `${JSON.stringify(handoff, null, 2)}\n`);
  return handoff;
}

function option(name, fallback) {
  const prefix = `--${name}=`;
  return process.argv.find((value) => value.startsWith(prefix))?.slice(prefix.length) ?? fallback;
}

if (process.argv[1] && resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  const { version } = JSON.parse(readFileSync(resolve(root, "package.json"), "utf8"));
  const releaseDir = resolve(root, option("release-dir", "electron/release"));
  const output = resolve(
    root,
    option("output", "electron/release/microsoft-store-submission.json"),
  );
  createMicrosoftStoreHandoff({ releaseDir, output, version });
  console.log(`Wrote ${basename(output)}`);
}
