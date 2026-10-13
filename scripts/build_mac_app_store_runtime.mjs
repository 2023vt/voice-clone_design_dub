#!/usr/bin/env node
import { spawnSync } from "node:child_process";
import { createHash } from "node:crypto";
import {
  chmod,
  cp,
  mkdir,
  readFile,
  readdir,
  readlink,
  realpath,
  rename,
  rm,
  symlink,
  unlink,
  writeFile,
} from "node:fs/promises";
import { arch as hostArch, platform as hostPlatform } from "node:os";
import { dirname, isAbsolute, join, relative, resolve } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

const root = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const PYTHON_REQUEST = "3.11";
const RUNTIME_IMPORTS =
  "import fastapi, uvicorn, omnivoice, faster_whisper, sentencepiece, torch, torchaudio, torchvision";

function run(command, args, options = {}) {
  const result = spawnSync(command, args, {
    cwd: root,
    encoding: "utf8",
    stdio: options.capture ? ["ignore", "pipe", "inherit"] : "inherit",
    env: options.env ?? process.env,
  });
  if (result.status !== 0) throw new Error(`${command} ${args.join(" ")} failed`);
  return result.stdout?.trim() ?? "";
}

function isInside(parent, candidate) {
  const path = relative(parent, candidate);
  return path === "" || (!path.startsWith("..") && !isAbsolute(path));
}

export async function assertRelocatable(rootDir, current = rootDir) {
  for (const entry of await readdir(current, { withFileTypes: true })) {
    const path = join(current, entry.name);
    if (entry.isDirectory()) await assertRelocatable(rootDir, path);
    if (!entry.isSymbolicLink()) continue;
    const target = await readlink(path);
    if (isAbsolute(target) || !isInside(rootDir, resolve(dirname(path), target))) {
      throw new Error(`Runtime contains an external symlink: ${relative(rootDir, path)}`);
    }
  }
}

async function sha256(path) {
  return createHash("sha256")
    .update(await readFile(path))
    .digest("hex");
}

async function makeVenvRelative(venv) {
  const python = join(venv, "bin", "python");
  await unlink(python);
  await symlink(`../../.python/bin/python${PYTHON_REQUEST}`, python);
  const configPath = join(venv, "pyvenv.cfg");
  const config = (await readFile(configPath, "utf8")).replace(
    /^home = .*$/m,
    "home = ../.python/bin",
  );
  await writeFile(configPath, config);
}

async function build(output) {
  if (hostPlatform() !== "darwin" || hostArch() !== "arm64") {
    throw new Error("The bundled local runtime must be built natively on macOS arm64");
  }
  const uv = process.env.UV?.trim() || "uv";
  const pending = `${output}.incoming-${process.pid}`;
  const managed = join(pending, "managed-python");
  const template = join(pending, "runtime");
  const bundledPython = join(template, ".python");
  const venv = join(template, ".venv");
  await rm(pending, { recursive: true, force: true });
  await mkdir(template, { recursive: true });

  const uvEnv = { ...process.env, UV_PYTHON_INSTALL_DIR: managed };
  run(uv, ["python", "install", PYTHON_REQUEST], { env: uvEnv });
  const managedExecutable = await realpath(
    run(uv, ["python", "find", "--managed-python", PYTHON_REQUEST], {
      capture: true,
      env: uvEnv,
    }),
  );
  await cp(resolve(managedExecutable, "..", ".."), bundledPython, {
    recursive: true,
    dereference: true,
    preserveTimestamps: true,
  });

  const pythonName = `python${PYTHON_REQUEST}`;
  const bundledExecutable = join(bundledPython, "bin", pythonName);
  run(uv, ["venv", "--relocatable", "--python", bundledExecutable, venv]);
  await makeVenvRelative(venv);

  await Promise.all([
    cp(join(root, "pyproject.toml"), join(template, "pyproject.toml")),
    cp(join(root, "uv.lock"), join(template, "uv.lock")),
  ]);
  run(uv, ["sync", "--frozen", "--no-dev", "--no-editable"], {
    env: {
      ...process.env,
      UV_PROJECT: root,
      UV_PROJECT_ENVIRONMENT: venv,
      UV_PYTHON_DOWNLOADS: "never",
    },
  });
  // A future uv sync may normalize interpreter links. Reassert the archive's
  // relative contract before validating and signing it.
  await makeVenvRelative(venv);
  run(join(venv, "bin", "python"), ["-c", RUNTIME_IMPORTS]);
  const packages = JSON.parse(
    run(uv, ["pip", "list", "--format", "json", "--python", join(venv, "bin", "python")], {
      capture: true,
    }),
  );
  const uvVersion = run(uv, ["--version"], { capture: true });
  await writeFile(
    join(template, "runtime-manifest.json"),
    `${JSON.stringify(
      {
        schemaVersion: 1,
        platform: "darwin",
        arch: "arm64",
        python: ".venv/bin/python",
        pythonVersion: run(bundledExecutable, ["--version"], { capture: true }),
        pythonSha256: await sha256(bundledExecutable),
        uvVersion,
        lockSha256: await sha256(join(root, "uv.lock")),
        packages,
      },
      null,
      2,
    )}\n`,
  );
  await chmod(join(venv, "bin", "python"), 0o755).catch(() => {});
  await assertRelocatable(template);

  await mkdir(dirname(output), { recursive: true });
  await rm(output, { recursive: true, force: true });
  await rename(template, output);
  await rm(pending, { recursive: true, force: true });
  process.stdout.write(`${output}\n`);
}

if (process.argv[1] && import.meta.url === pathToFileURL(resolve(process.argv[1])).href) {
  const requested = process.argv.find((value) => value.startsWith("--output="))?.slice(9);
  const output = resolve(
    requested || join(root, "electron", "build", "runtime", "aarch64-apple-darwin"),
  );
  await build(output);
}
