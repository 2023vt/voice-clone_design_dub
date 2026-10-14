import assert from "node:assert/strict";
import { mkdtemp, mkdir, rm, symlink, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import test from "node:test";
import { assertRelocatable } from "./build_mac_app_store_runtime.mjs";

test("accepts internal relative runtime symlinks", async (context) => {
  const root = await mkdtemp(join(tmpdir(), "vs-runtime-contract-"));
  context.after(() => rm(root, { recursive: true, force: true }));
  await mkdir(join(root, "bin"));
  await writeFile(join(root, "bin", "python3"), "python");
  await symlink("python3", join(root, "bin", "python"));

  await assert.doesNotReject(assertRelocatable(root));
});

test("rejects runtime symlinks to the build machine", async (context) => {
  const root = await mkdtemp(join(tmpdir(), "vs-runtime-contract-"));
  context.after(() => rm(root, { recursive: true, force: true }));
  await symlink("/usr/bin/python3", join(root, "python"));

  await assert.rejects(assertRelocatable(root), /external symlink/);
});
