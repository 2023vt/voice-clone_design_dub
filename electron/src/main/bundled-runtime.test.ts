// @vitest-environment node
import { mkdtemp, mkdir, readFile, rm, symlink, writeFile } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { dirname, join } from 'node:path';
import { afterEach, describe, expect, it } from 'vitest';
import { BUNDLED_RUNTIME_MANIFEST, materializeBundledRuntime } from './bundled-runtime';

const roots: string[] = [];

async function fixture() {
  const root = await mkdtemp(join(tmpdir(), 'vs-bundled-runtime-'));
  roots.push(root);
  const template = join(root, 'template');
  const project = join(root, 'container', 'project');
  const python = '.venv/bin/python3';
  await mkdir(dirname(join(template, python)), { recursive: true });
  await writeFile(join(template, python), 'python');
  await symlink('python3', join(template, '.venv', 'bin', 'python'));
  await writeFile(
    join(template, BUNDLED_RUNTIME_MANIFEST),
    JSON.stringify({ schemaVersion: 1, platform: 'darwin', arch: 'arm64', python }),
  );
  return { root, template, project };
}

afterEach(async () => {
  await Promise.all(roots.splice(0).map((root) => rm(root, { recursive: true, force: true })));
});

describe('bundled runtime materialization', () => {
  it('copies the runtime into the writable container and reuses the same build', async () => {
    const { template, project } = await fixture();

    expect(await materializeBundledRuntime(template, project, 'darwin', 'arm64')).toBe(true);
    expect(await readFile(join(project, '.venv', 'bin', 'python3'), 'utf8')).toBe('python');
    await writeFile(join(project, 'kept'), 'same installation');

    expect(await materializeBundledRuntime(template, project, 'darwin', 'arm64')).toBe(false);
    expect(await readFile(join(project, 'kept'), 'utf8')).toBe('same installation');
  });

  it('atomically replaces an older bundled runtime', async () => {
    const { template, project } = await fixture();
    await mkdir(project, { recursive: true });
    await writeFile(join(project, 'old'), 'runtime');

    expect(await materializeBundledRuntime(template, project, 'darwin', 'arm64')).toBe(true);
    await expect(readFile(join(project, 'old'))).rejects.toMatchObject({ code: 'ENOENT' });
  });

  it('rejects manifests for a different architecture', async () => {
    const { template, project } = await fixture();

    await expect(materializeBundledRuntime(template, project, 'darwin', 'x64')).rejects.toThrow(
      'does not match',
    );
  });

  it('rejects symlinks that escape the packaged runtime', async () => {
    const { template, project } = await fixture();
    await symlink('/usr/bin/python3', join(template, '.venv', 'bin', 'external'));

    await expect(materializeBundledRuntime(template, project, 'darwin', 'arm64')).rejects.toThrow(
      'external symlink',
    );
  });

  it('repairs a matching installation with a tampered symlink', async () => {
    const { template, project } = await fixture();
    await materializeBundledRuntime(template, project, 'darwin', 'arm64');
    await symlink('/usr/bin/python3', join(project, 'tampered'));

    expect(await materializeBundledRuntime(template, project, 'darwin', 'arm64')).toBe(true);
    await expect(readFile(join(project, 'tampered'))).rejects.toMatchObject({ code: 'ENOENT' });
  });
});
