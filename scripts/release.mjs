#!/usr/bin/env node
// Bump versions for a single plugin (and optionally cascade patch-bumps to
// dependents in the developer-workflow* family) for a workflow_dispatch-driven
// release. Invoked by .github/workflows/release.yml. Reads inputs from env
// vars; writes JSON updates in place; prints a JSON summary to stdout that the
// workflow consumes to drive tagging, npm publish, and GitHub Release.
//
// Local dry-run example (from repo root):
//   PLUGIN=sensitive-guard BUMP=patch CASCADE=false node scripts/release.mjs
//   git checkout -- .   # roll back changes
//
// Hard rules:
//   - No external dependencies (built-in semver math only).
//   - Pretty-print JSON with 2-space indent + trailing newline (matches repo).
//   - Subprocess invocations (none needed today) must use spawnSync with
//     array args; never shell interpolation. The workflow handles git/tag/push.

import { readFileSync, writeFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

// Anchor paths to the script's own location so invocation cwd doesn't matter.
const REPO_ROOT = join(dirname(fileURLToPath(import.meta.url)), '..');
const MARKETPLACE_PATH = join(REPO_ROOT, '.claude-plugin', 'marketplace.json');

// ----- helpers --------------------------------------------------------------

function die(msg) {
  process.stderr.write(`ERROR: ${msg}\n`);
  process.exit(1);
}

function readJson(path) {
  return JSON.parse(readFileSync(path, 'utf8'));
}

// Existing repo files escape non-ASCII characters as \uXXXX (em-dashes,
// etc.). JSON.stringify emits them as literal characters, which would make
// every release diff include cosmetic re-escaping noise. Re-encode any
// non-ASCII codepoint outside printable ASCII back to \uXXXX form so the
// output byte-matches the repo's existing serialization.
function asciiSafeStringify(data) {
  const json = JSON.stringify(data, null, 2);
  return json.replace(/[\u0080-\uffff]/g, (ch) => {
    return '\\u' + ch.charCodeAt(0).toString(16).padStart(4, '0');
  });
}

function writeJson(path, data) {
  writeFileSync(path, asciiSafeStringify(data) + '\n');
}

// Built-in semver bump. Versions are validated as MAJOR.MINOR.PATCH triples.
function bumpVersion(current, kind) {
  const m = /^(\d+)\.(\d+)\.(\d+)$/.exec(current);
  if (!m) die(`current version is not semver MAJOR.MINOR.PATCH: ${current}`);
  const maj = Number(m[1]);
  const min = Number(m[2]);
  const pat = Number(m[3]);
  switch (kind) {
    case 'major': return `${maj + 1}.0.0`;
    case 'minor': return `${maj}.${min + 1}.0`;
    case 'patch': return `${maj}.${min}.${pat + 1}`;
    default: die(`unknown bump kind: ${kind}`);
  }
}

function manifestPath(source) {
  // marketplace `source` points at the plugin folder containing
  // .claude-plugin/plugin.json. For maven-mcp this is plugins/maven-mcp/plugin
  // (the npm workspace package.json is one level up at plugins/maven-mcp/).
  return join(REPO_ROOT, source, '.claude-plugin', 'plugin.json');
}

function findEntry(marketplace, name) {
  const e = marketplace.plugins.find((p) => p.name === name);
  if (!e) die(`plugin '${name}' not found in marketplace.json`);
  return e;
}

// Workspace package.json path for plugins that ship as npm packages.
// Currently only maven-mcp does; its nested layout puts the manifest at
// plugins/maven-mcp/plugin/.claude-plugin/plugin.json while the npm package
// lives at plugins/maven-mcp/package.json. Returns null for plugins with no
// workspace package.json.
function packageJsonPath(name) {
  if (name === 'maven-mcp') return join(REPO_ROOT, 'plugins', 'maven-mcp', 'package.json');
  return null;
}

// Apply a version bump to all files owned by `name`:
//   - the plugin manifest (plugin.json)
//   - the marketplace.json entry (in-memory only — caller writes once at end)
//   - workspace package.json, if the plugin ships as an npm package
function applyVersionToPlugin(marketplace, name, newVersion) {
  const entry = findEntry(marketplace, name);
  entry.version = newVersion;

  const manifest = readJson(manifestPath(entry.source));
  manifest.version = newVersion;
  writeJson(manifestPath(entry.source), manifest);

  const pkgPath = packageJsonPath(name);
  if (pkgPath) {
    const pkg = readJson(pkgPath);
    pkg.version = newVersion;
    writeJson(pkgPath, pkg);
  }
}

// Bump a cascade dependent: patch-bump its own version AND rewrite its
// `dependencies[primaryName].version` to `^MAJ.MIN.0` of the new primary
// version, in a single manifest read-write. Returns the new dependent
// version.
function applyCascadeBump(marketplace, dependent, primaryName, primaryNewVersion) {
  const m = /^(\d+)\.(\d+)\.\d+$/.exec(primaryNewVersion);
  if (!m) die(`cascade target version is not semver: ${primaryNewVersion}`);
  const range = `^${m[1]}.${m[2]}.0`;

  const newVersion = bumpVersion(dependent.version, 'patch');
  const entry = findEntry(marketplace, dependent.name);
  entry.version = newVersion;

  const mPath = manifestPath(dependent.source);
  const manifest = readJson(mPath);
  manifest.version = newVersion;
  if (Array.isArray(manifest.dependencies)) {
    const dep = manifest.dependencies.find((d) => d && d.name === primaryName);
    if (dep) dep.version = range;
  }
  writeJson(mPath, manifest);

  return newVersion;
}

// One-level cascade across the developer-workflow* family. The family is
// shallow (experts → workflow → kotlin/swift), so a single pass suffices —
// no transitive cascade needed. Returns the list of cascaded entries
// {name, version} in marketplace order.
function cascade(marketplace, primaryName, primaryNewVersion) {
  const cascaded = [];
  for (const entry of marketplace.plugins) {
    if (entry.name === primaryName) continue;
    if (!entry.name.startsWith('developer-workflow')) continue;

    const manifest = readJson(manifestPath(entry.source));
    const deps = Array.isArray(manifest.dependencies) ? manifest.dependencies : [];
    if (!deps.some((d) => d && d.name === primaryName)) continue;

    const newVersion = applyCascadeBump(marketplace, entry, primaryName, primaryNewVersion);
    cascaded.push({ name: entry.name, version: newVersion });
  }
  return cascaded;
}

// ----- main -----------------------------------------------------------------

const PLUGIN = process.env.PLUGIN;
const BUMP = process.env.BUMP;
// workflow_dispatch boolean inputs arrive as the strings 'true'/'false'; be
// defensive against whitespace and casing for local dry-runs.
const CASCADE_ENABLED = String(process.env.CASCADE ?? '').trim().toLowerCase() === 'true';

if (!PLUGIN) die('PLUGIN env var is required');
if (!BUMP) die('BUMP env var is required');
if (!['patch', 'minor', 'major'].includes(BUMP)) die(`BUMP must be patch|minor|major, got: ${BUMP}`);

const marketplace = readJson(MARKETPLACE_PATH);
const entry = findEntry(marketplace, PLUGIN);

const currentVersion = readJson(manifestPath(entry.source)).version;
const newVersion = bumpVersion(currentVersion, BUMP);

// Apply primary bump.
applyVersionToPlugin(marketplace, PLUGIN, newVersion);

// developer-workflow* family invariant: bumping a member can break dependents
// whose `dependencies` ranges no longer include the new version. The cascade
// patch-bumps each dependent and widens its range to the new MAJ.MIN band.
let cascaded = [];
if (CASCADE_ENABLED && PLUGIN.startsWith('developer-workflow')) {
  cascaded = cascade(marketplace, PLUGIN, newVersion);
}

// Persist marketplace.json once after all in-memory mutations (primary entry
// and any cascaded entries' version fields).
writeJson(MARKETPLACE_PATH, marketplace);

const summary = {
  primary: { name: PLUGIN, version: newVersion },
  cascaded,
};
process.stdout.write(JSON.stringify(summary) + '\n');
