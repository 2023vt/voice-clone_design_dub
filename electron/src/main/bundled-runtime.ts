import { randomUUID } from 'node:crypto';
import { cp, mkdir, readFile, readdir, readlink, rename, rm, stat } from 'node:fs/promises';
import { dirname, isAbsolute, join, relative, resolve } from 'node:path';

export const BUNDLED_RUNTIME_MANIFEST = 'runtime-manifest.json';

interface BundledRuntimeManifest {
  schemaVersion: 1;
  platform: NodeJS.Platform;
  arch: string;
  python: string;
}

function inside(root: string, candidate: string): boolean {
  const path = relative(root, candidate);
  return path === '' || (!path.startsWith('..') && !isAbsolute(path));
}

async function validateLinks(root: string, current = root): Promise<void> {
  for (const entry of await readdir(current, { withFileTypes: true })) {
    const path = join(current, entry.name);
    if (entry.isDirectory()) {
      await validateLinks(root, path);
      continue;
    }
    if (!entry.isSymbolicLink()) continue;
    const target = await readlink(path);
    if (isAbsolute(target) || !inside(root, resolve(dirname(path), target))) {
      throw new Error(`Bundled runtime contains an external symlink: ${relative(root, path)}`);
    }
  }
}

async function loadManifest(
  template: string,
  platform: NodeJS.Platform,
  arch: string,
): Promise<BundledRuntimeManifest> {
  const raw = JSON.parse(
    await readFile(join(template, BUNDLED_RUNTIME_MANIFEST), 'utf8'),
  ) as Partial<BundledRuntimeManifest>;
  if (
    raw.schemaVersion !== 1 ||
    raw.platform !== platform ||
    raw.arch !== arch ||
    typeof raw.python !== 'string' ||
    raw.python.length === 0 ||
    isAbsolute(raw.python) ||
    !inside(template, resolve(template, raw.python))
  ) {
    throw new Error('Bundled runtime manifest does not match this application build');
  }
  const python = await stat(join(template, raw.python));
  if (!python.isFile()) throw new Error('Bundled runtime interpreter is missing');
  return raw as BundledRuntimeManifest;
}

async function sameManifest(template: string, project: string): Promise<boolean> {
  try {
    const [source, installed] = await Promise.all([
      readFile(join(template, BUNDLED_RUNTIME_MANIFEST)),
      readFile(join(project, BUNDLED_RUNTIME_MANIFEST)),
    ]);
    return source.equals(installed);
  } catch {
    return false;
  }
}

async function installedRuntimeMatches(
  template: string,
  project: string,
  platform: NodeJS.Platform,
  arch: string,
): Promise<boolean> {
  try {
    if (!(await sameManifest(template, project))) return false;
    const manifest = await loadManifest(project, platform, arch);
    await validateLinks(project);
    return (await stat(join(project, manifest.python))).isFile();
  } catch {
    return false;
  }
}

/** Copy the immutable store runtime into the writable application container. */
export async function materializeBundledRuntime(
  template: string,
  project: string,
  platform: NodeJS.Platform = process.platform,
  arch: string = process.arch,
): Promise<boolean> {
  await loadManifest(template, platform, arch);
  await validateLinks(template);
  if (await installedRuntimeMatches(template, project, platform, arch)) {
    return false;
  }

  const parent = dirname(project);
  const id = randomUUID();
  const pending = join(parent, `.incoming-runtime-${id}`);
  const previous = join(parent, `.previous-runtime-${id}`);
  await mkdir(parent, { recursive: true });
  try {
    await cp(template, pending, {
      recursive: true,
      preserveTimestamps: true,
      verbatimSymlinks: true,
    });
    await loadManifest(pending, platform, arch);
    let moved = false;
    try {
      await rename(project, previous);
      moved = true;
    } catch (error) {
      if ((error as NodeJS.ErrnoException).code !== 'ENOENT') throw error;
    }
    try {
      await rename(pending, project);
    } catch (error) {
      if (moved) await rename(previous, project);
      throw error;
    }
    await rm(previous, { recursive: true, force: true });
    return true;
  } finally {
    await rm(pending, { recursive: true, force: true });
  }
}
