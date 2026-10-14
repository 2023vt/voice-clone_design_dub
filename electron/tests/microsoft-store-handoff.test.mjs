import assert from 'node:assert/strict';
import { mkdtempSync, readFileSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import test from 'node:test';

import { createMicrosoftStoreHandoff } from '../../scripts/create_microsoft_store_handoff.mjs';

test('creates a Partner Center handoff only from validated MSIX packages', () => {
  const dir = mkdtempSync(join(tmpdir(), 'voicestudio-microsoft-store-handoff-'));
  const file = 'VoiceStudio-MicrosoftStore-0.5.7-win-x64.msix';
  const packagePath = join(dir, file);
  writeFileSync(packagePath, 'unsigned msix fixture');
  const digest = '194418af6a1cd5ef17de0d7b3b9b9c91e9da9af6cd67534926029dcc00b02c65';
  writeFileSync(
    join(dir, 'store-artifact-manifest-win32-x64.json'),
    JSON.stringify({
      distribution: { target: 'microsoft-store', applicationUpdates: 'store' },
      signingVerification: {
        status: 'store-pending',
        evidence: 'msix-verification-win32-x64.json',
      },
      artifacts: [{ file, bytes: 21, sha256: digest }],
    }),
  );
  writeFileSync(join(dir, 'msix-verification-win32-x64.json'), '{}');
  writeFileSync(join(dir, 'wack-win32-x64.xml'), '<report />');
  const output = join(dir, 'submission.json');

  const handoff = createMicrosoftStoreHandoff({
    releaseDir: dir,
    output,
    version: '0.5.7',
    generatedAt: '2026-10-15T00:00:00.000Z',
  });

  assert.equal(handoff.schemaVersion, 2);
  assert.equal(handoff.lifecycle, 'validated-for-submission');
  assert.equal(handoff.identity.storeId, '9PDMFM4FG106');
  assert.equal(handoff.packages[0].type, 'msix');
  assert.equal(handoff.packages[0].signing, 'Microsoft Store after certification');
  assert.deepEqual(JSON.parse(readFileSync(output, 'utf8')), handoff);
});

test('rejects missing packages or validation evidence', () => {
  const dir = mkdtempSync(join(tmpdir(), 'voicestudio-microsoft-store-reject-'));
  assert.throws(
    () =>
      createMicrosoftStoreHandoff({
        releaseDir: dir,
        output: join(dir, 'submission.json'),
        version: '0.5.7',
      }),
    /x64 MSIX/,
  );
});
