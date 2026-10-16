import {
  inspectDataRelocation,
  prepareDataRelocation,
  readDirectorySetting,
  writeDirectorySetting,
  type DataRelocationResult,
  type DataRelocationRuntime,
} from './data-relocation';
import { readdir } from 'node:fs/promises';

const KEY = 'OMNIVOICE_CACHE_DIR';

/** A pre-copied cache can be adopted only after every file is verified. */
export const inspectModelsRelocation = (source: string, target: string) =>
  inspectDataRelocation(source, target, true);

async function hasModelDirectories(path: string): Promise<boolean> {
  try {
    return (await readdir(path)).some((name) => name.startsWith('models--'));
  } catch {
    return false;
  }
}

/** Recover a cache stranded by the older "Choose folder" setting-only action. */
export async function modelsRelocationSource(
  active: string,
  legacyDefault?: string,
): Promise<string> {
  if (
    legacyDefault &&
    !(await hasModelDirectories(active)) &&
    (await hasModelDirectories(legacyDefault))
  ) {
    return legacyDefault;
  }
  return active;
}

/** Keep the old cache until the restarted backend confirms the new path. */
export async function relocateModelsDirectory(
  source: string,
  target: string,
  runtime: DataRelocationRuntime,
): Promise<DataRelocationResult> {
  let prepared: Awaited<ReturnType<typeof prepareDataRelocation>> | null = null;
  let previousSetting: string | null = null;
  let settingChanged = false;
  let stopped = false;
  let started = false;
  try {
    runtime.progress('stopping');
    await runtime.stop();
    stopped = true;
    runtime.progress('copying');
    prepared = await prepareDataRelocation(source, target, true);
    previousSetting = await readDirectorySetting(KEY, runtime.environmentPath);
    runtime.progress('switching');
    await writeDirectorySetting(KEY, target, runtime.environmentPath);
    settingChanged = true;
    runtime.progress('restarting');
    await runtime.start();
    started = true;
    if (!(await runtime.verify(target))) throw new Error('backend_verification_failed');
    runtime.progress('cleaning');
    let removedSource = true;
    try {
      await prepared.removeSource();
    } catch {
      removedSource = false;
    }
    runtime.progress('done');
    return {
      path: target,
      size_bytes: prepared.size_bytes,
      file_count: prepared.file_count,
      removed_source: removedSource,
    };
  } catch (error) {
    runtime.progress('rolling_back');
    if (started) await runtime.stop().catch(() => undefined);
    if (settingChanged) {
      await writeDirectorySetting(KEY, previousSetting, runtime.environmentPath).catch(
        () => undefined,
      );
    }
    if (prepared) await prepared.rollback().catch(() => undefined);
    if (stopped) await runtime.start().catch(() => undefined);
    throw error;
  }
}
