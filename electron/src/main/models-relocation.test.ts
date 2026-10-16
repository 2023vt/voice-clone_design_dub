// @vitest-environment node
import { existsSync } from 'node:fs';
import { mkdtemp, mkdir, readFile, rm, writeFile } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { dirname, join } from 'node:path';
import { afterEach, expect, it } from 'vitest';
import {
  inspectModelsRelocation,
  modelsRelocationSource,
  relocateModelsDirectory,
} from './models-relocation';
import { readDirectorySetting } from './data-relocation';

const created: string[] = [];
afterEach(async () => {
  await Promise.allSettled(
    created.splice(0).map((path) => rm(path, { recursive: true, force: true })),
  );
});

async function fixture() {
  const root = await mkdtemp(join(tmpdir(), 'VoiceStudio-model-move-'));
  created.push(root);
  const source = join(root, 'old', 'hf_cache');
  const target = join(root, 'new', 'models');
  const environmentPath = join(root, 'config', 'env');
  await mkdir(source, { recursive: true });
  await mkdir(dirname(target), { recursive: true });
  await mkdir(dirname(environmentPath), { recursive: true });
  await writeFile(join(source, 'model.bin'), 'weights');
  await writeFile(environmentPath, `HF_TOKEN=secret\nOMNIVOICE_CACHE_DIR='${source}'\n`);
  return { source, target, environmentPath };
}

it('finds weights left in the Windows default cache after a setting-only change', async () => {
  const { source, target } = await fixture();
  await mkdir(join(source, 'models--k2-fsa--OmniVoice'));
  await mkdir(target);
  expect(await modelsRelocationSource(target, source)).toBe(source);
  await mkdir(join(target, 'models--new--model'));
  expect(await modelsRelocationSource(target, source)).toBe(target);
});

it('copies model weights, activates the cache, then removes the old directory', async () => {
  const { source, target, environmentPath } = await fixture();
  const events: string[] = [];
  const result = await relocateModelsDirectory(source, target, {
    environmentPath,
    stop: async () => {
      events.push('stop');
    },
    start: async () => {
      events.push('start');
    },
    verify: async (path) => {
      expect(path).toBe(target);
      expect(await readFile(join(source, 'model.bin'), 'utf8')).toBe('weights');
      expect(await readFile(join(target, 'model.bin'), 'utf8')).toBe('weights');
      return true;
    },
    progress: (stage) => events.push(stage),
  });
  expect(result.removed_source).toBe(true);
  expect(existsSync(source)).toBe(false);
  expect(await readDirectorySetting('OMNIVOICE_CACHE_DIR', environmentPath)).toBe(target);
  expect(events).toEqual([
    'stopping',
    'stop',
    'copying',
    'switching',
    'restarting',
    'start',
    'cleaning',
    'done',
  ]);
});

it('keeps the original cache and setting when the restarted backend rejects the path', async () => {
  const { source, target, environmentPath } = await fixture();
  let starts = 0;
  await expect(
    relocateModelsDirectory(source, target, {
      environmentPath,
      stop: async () => undefined,
      start: async () => {
        starts++;
      },
      verify: async () => false,
      progress: () => undefined,
    }),
  ).rejects.toThrow('backend_verification_failed');
  expect(starts).toBe(2);
  expect(existsSync(target)).toBe(false);
  expect(await readFile(join(source, 'model.bin'), 'utf8')).toBe('weights');
  expect(await readDirectorySetting('OMNIVOICE_CACHE_DIR', environmentPath)).toBe(source);
  expect(await readFile(environmentPath, 'utf8')).toContain('HF_TOKEN=secret');
});

it('adopts an identical pre-copied model cache without overwriting it', async () => {
  const { source, target, environmentPath } = await fixture();
  await mkdir(target);
  await writeFile(join(target, 'model.bin'), 'weights');
  await mkdir(join(target, 'xet', 'logs'), { recursive: true });
  await writeFile(join(target, 'xet', 'logs', 'download.log'), 'keep');
  expect((await inspectModelsRelocation(source, target)).file_count).toBe(1);
  const result = await relocateModelsDirectory(source, target, {
    environmentPath,
    stop: async () => undefined,
    start: async () => undefined,
    verify: async () => true,
    progress: () => undefined,
  });
  expect(result.removed_source).toBe(true);
  expect(existsSync(source)).toBe(false);
  expect(await readFile(join(target, 'model.bin'), 'utf8')).toBe('weights');
  expect(await readFile(join(target, 'xet', 'logs', 'download.log'), 'utf8')).toBe('keep');
});

it('refuses a pre-copied cache with same-sized but different content', async () => {
  const { source, target, environmentPath } = await fixture();
  await mkdir(target);
  await writeFile(join(target, 'model.bin'), 'changed');
  expect((await inspectModelsRelocation(source, target)).file_count).toBe(1);
  await expect(
    relocateModelsDirectory(source, target, {
      environmentPath,
      stop: async () => undefined,
      start: async () => undefined,
      verify: async () => true,
      progress: () => undefined,
    }),
  ).rejects.toThrow('target_not_empty');
  expect(await readFile(join(source, 'model.bin'), 'utf8')).toBe('weights');
  expect(await readFile(join(target, 'model.bin'), 'utf8')).toBe('changed');
  expect(await readDirectorySetting('OMNIVOICE_CACHE_DIR', environmentPath)).toBe(source);
});

it('preserves both copies if activating a pre-copied model cache fails', async () => {
  const { source, target, environmentPath } = await fixture();
  await mkdir(target);
  await writeFile(join(target, 'model.bin'), 'weights');
  await expect(
    relocateModelsDirectory(source, target, {
      environmentPath,
      stop: async () => undefined,
      start: async () => undefined,
      verify: async () => false,
      progress: () => undefined,
    }),
  ).rejects.toThrow('backend_verification_failed');
  expect(await readFile(join(source, 'model.bin'), 'utf8')).toBe('weights');
  expect(await readFile(join(target, 'model.bin'), 'utf8')).toBe('weights');
  expect(await readDirectorySetting('OMNIVOICE_CACHE_DIR', environmentPath)).toBe(source);
});
