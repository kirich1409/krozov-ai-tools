// Canonical workspace ↔ plugin map.
// Single source of truth shared by:
//   - scripts/changesets-version.mjs (post-`changeset version` sync of plugin.json + marketplace.json)
//   - scripts/changesets-publish.mjs (per-plugin git tag emission)
//   - scripts/validate.sh (three-way version invariant check) — kept in sync manually
//
// Each entry MUST have all four fields. Adding a new plugin requires updating
// this file AND the mirrored mapping at the top of scripts/validate.sh.
//
// Fields:
//   pkgName      — `name` in the workspace package.json (npm package name).
//                  For maven-mcp this is the scoped npm package (@krozov/maven-central-mcp);
//                  for the rest it equals the plugin name.
//   pluginName   — `name` in plugin.json and the entry in marketplace.json.
//                  Used as the prefix for the per-plugin git tag `{pluginName}--v{version}`.
//   workspaceDir — directory holding the workspace package.json.
//   manifestPath — path to plugin.json relative to repo root.
//                  NOTE: maven-mcp's manifest is one level deeper than its workspace dir.

export const PLUGIN_MAP = [
  {
    pkgName: "@krozov/maven-central-mcp",
    pluginName: "maven-mcp",
    workspaceDir: "plugins/maven-mcp",
    manifestPath: "plugins/maven-mcp/plugin/.claude-plugin/plugin.json"
  },
  {
    pkgName: "sensitive-guard",
    pluginName: "sensitive-guard",
    workspaceDir: "plugins/sensitive-guard",
    manifestPath: "plugins/sensitive-guard/.claude-plugin/plugin.json"
  },
  {
    pkgName: "developer-workflow",
    pluginName: "developer-workflow",
    workspaceDir: "plugins/developer-workflow",
    manifestPath: "plugins/developer-workflow/.claude-plugin/plugin.json"
  },
  {
    pkgName: "developer-workflow-experts",
    pluginName: "developer-workflow-experts",
    workspaceDir: "plugins/developer-workflow-experts",
    manifestPath: "plugins/developer-workflow-experts/.claude-plugin/plugin.json"
  },
  {
    pkgName: "developer-workflow-kotlin",
    pluginName: "developer-workflow-kotlin",
    workspaceDir: "plugins/developer-workflow-kotlin",
    manifestPath: "plugins/developer-workflow-kotlin/.claude-plugin/plugin.json"
  },
  {
    pkgName: "developer-workflow-swift",
    pluginName: "developer-workflow-swift",
    workspaceDir: "plugins/developer-workflow-swift",
    manifestPath: "plugins/developer-workflow-swift/.claude-plugin/plugin.json"
  }
];

export const MARKETPLACE_PATH = ".claude-plugin/marketplace.json";
