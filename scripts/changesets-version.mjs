#!/usr/bin/env node
// Wrapper around `changeset version`.
//
// 1. Runs `npx changeset version` (which bumps workspace package.json files
//    and writes per-package CHANGELOG.md entries).
// 2. For every plugin in PLUGIN_MAP, copies the new workspace version into:
//      - plugins/<plugin>/.claude-plugin/plugin.json (or maven-mcp's nested manifest)
//      - .claude-plugin/marketplace.json entry for the plugin
// 3. For every plugin.json with a non-empty `dependencies` array (which is an
//    array of {name, version} objects, NOT the npm map form), rewrites each
//    entry whose `name` matches a plugin in PLUGIN_MAP to `^MAJOR.MINOR.0`
//    of the dependency's new version.
//
// Invoked by changesets/action@v1 as the `version:` script.

import { spawnSync } from "node:child_process";
import { readFile, writeFile } from "node:fs/promises";
import path from "node:path";
import { PLUGIN_MAP, MARKETPLACE_PATH } from "./plugin-map.mjs";

const cwd = process.cwd();

function run(cmd, args, opts = {}) {
  const r = spawnSync(cmd, args, { stdio: "inherit", cwd, ...opts });
  if (r.status !== 0) {
    console.error(`Command failed: ${cmd} ${args.join(" ")}`);
    process.exit(r.status ?? 1);
  }
  return r;
}

async function readJson(relPath) {
  const abs = path.join(cwd, relPath);
  return JSON.parse(await readFile(abs, "utf8"));
}

async function writeJson(relPath, obj) {
  const abs = path.join(cwd, relPath);
  // Match existing files: 2-space indent, trailing newline.
  await writeFile(abs, JSON.stringify(obj, null, 2) + "\n");
}

// 1. Run the standard version command. spawnSync with array args (no shell).
run("npx", ["changeset", "version"]);

// 2. Read fresh workspace versions from each plugin's package.json.
//    Workspace name is npm package name (@krozov/maven-central-mcp); plugin
//    manifest sits at plugins/maven-mcp/plugin/.claude-plugin/plugin.json —
//    one level deeper than other plugins.
const newVersions = new Map(); // pluginName -> new version
for (const entry of PLUGIN_MAP) {
  const pkg = await readJson(path.join(entry.workspaceDir, "package.json"));
  if (!pkg.version) {
    console.error(`Missing version in ${entry.workspaceDir}/package.json`);
    process.exit(1);
  }
  newVersions.set(entry.pluginName, pkg.version);
}

// 3. Sync plugin.json + marketplace.json.
const marketplace = await readJson(MARKETPLACE_PATH);

for (const entry of PLUGIN_MAP) {
  const newVersion = newVersions.get(entry.pluginName);
  const manifest = await readJson(entry.manifestPath);
  manifest.version = newVersion;

  // Claude Code plugin.json 'dependencies' is an array of {name, version}
  // objects, not the npm map form. Do not convert.
  if (Array.isArray(manifest.dependencies)) {
    for (const dep of manifest.dependencies) {
      if (!newVersions.has(dep.name)) continue;
      const depVersion = newVersions.get(dep.name);
      const [maj, min] = depVersion.split(".");
      dep.version = `^${maj}.${min}.0`;
    }
  }

  await writeJson(entry.manifestPath, manifest);

  const marketEntry = marketplace.plugins.find((p) => p.name === entry.pluginName);
  if (!marketEntry) {
    console.error(`marketplace.json missing entry for plugin '${entry.pluginName}'`);
    process.exit(1);
  }
  marketEntry.version = newVersion;
}

await writeJson(MARKETPLACE_PATH, marketplace);

console.log("Synced plugin.json + marketplace.json with new workspace versions.");
