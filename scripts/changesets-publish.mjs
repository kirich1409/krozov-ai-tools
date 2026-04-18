#!/usr/bin/env node
// Wrapper around publishing.
//
// 1. Runs `npm publish --access public` from plugins/maven-mcp (the only
//    npm-published plugin). Idempotent across re-runs only at the npm level —
//    npm refuses to re-publish an existing version, which we treat as a hard
//    failure here (the workflow should not call this script unless the version
//    actually bumped).
// 2. Creates per-plugin git tags `{plugin}--v{version}` for every entry in
//    marketplace.json. Skips tags that already exist (idempotent).
// 3. Pushes all newly-created tags in a single batch.
// 4. Prints a JSON array `[{name, version}]` to stdout for changesets/action.
//
// Invoked by changesets/action@v1 as the `publish:` script after the Version
// Packages PR has been merged.

import { spawnSync } from "node:child_process";
import { readFile } from "node:fs/promises";
import path from "node:path";
import { MARKETPLACE_PATH } from "./plugin-map.mjs";

const cwd = process.cwd();

function run(cmd, args, opts = {}) {
  const r = spawnSync(cmd, args, { stdio: "inherit", cwd, ...opts });
  if (r.status !== 0) {
    console.error(`Command failed: ${cmd} ${args.join(" ")}`);
    process.exit(r.status ?? 1);
  }
  return r;
}

function silent(cmd, args, opts = {}) {
  return spawnSync(cmd, args, { stdio: "ignore", cwd, ...opts });
}

const marketplace = JSON.parse(
  await readFile(path.join(cwd, MARKETPLACE_PATH), "utf8")
);

// 1. Publish maven-mcp to npm. Uses NODE_AUTH_TOKEN from the workflow env.
run("npm", ["publish", "--access", "public"], {
  cwd: path.join(cwd, "plugins/maven-mcp")
});

// 2. Configure git identity (CI environment only).
run("git", ["config", "user.name", "github-actions[bot]"]);
run("git", [
  "config",
  "user.email",
  "41898282+github-actions[bot]@users.noreply.github.com"
]);

// Fetch all tags so the idempotency check sees sibling per-plugin tags
// from previous releases. actions/checkout otherwise gives us a sparse view.
run("git", ["fetch", "--tags", "--quiet", "origin"]);

// plugin.name comes from marketplace.json, validated by validate.sh's
// check_name_consistency. Do not source plugin names from changeset content —
// they end up as git refs and shell args.
const tagsToPush = [];
for (const plugin of marketplace.plugins) {
  const tag = `${plugin.name}--v${plugin.version}`;
  const exists = silent("git", ["rev-parse", "-q", "--verify", `refs/tags/${tag}`]);
  if (exists.status === 0) {
    console.log(`Tag ${tag} already exists, skipping`);
    continue;
  }
  run("git", ["tag", "-a", tag, "-m", `Release ${plugin.name} ${plugin.version}`]);
  tagsToPush.push(tag);
}

// 3. Push all new tags in a single round-trip.
if (tagsToPush.length > 0) {
  run("git", ["push", "origin", ...tagsToPush]);
  for (const tag of tagsToPush) console.log(`Pushed ${tag}`);
} else {
  console.log("No new per-plugin tags to push");
}

// 4. Output JSON for changesets/action to consume (publishedPackages output).
console.log(
  JSON.stringify(
    marketplace.plugins.map((p) => ({ name: p.name, version: p.version }))
  )
);
