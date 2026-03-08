import type { StabilityFilter, StabilityType } from "./types.js";

const STABILITY_PATTERNS: [RegExp, StabilityType][] = [
  [/[-.]?SNAPSHOT$/i, "snapshot"],
  [/[-.](?:alpha|a(?=\d|[-.]|$))[-.]?\d*/i, "alpha"],
  [/[-.](?:beta|b(?=\d|[-.]|$))[-.]?\d*/i, "beta"],
  [/[-.](?:M|milestone)[-.]?\d*/i, "milestone"],
  [/[-.](?:RC|CR)[-.]?\d*/i, "rc"],
];

export function classifyVersion(version: string): StabilityType {
  for (const [pattern, stability] of STABILITY_PATTERNS) {
    if (pattern.test(version)) {
      return stability;
    }
  }
  return "stable";
}

// Stability levels ordered from most stable to least stable.
// Lower index = more stable.
const STABILITY_RANK: StabilityType[] = [
  "stable", "rc", "milestone", "beta", "alpha", "snapshot",
];

function stabilityRank(stability: StabilityType): number {
  return STABILITY_RANK.indexOf(stability);
}

function lastWhere(versions: string[], predicate: (v: string) => boolean): string | undefined {
  for (let i = versions.length - 1; i >= 0; i--) {
    if (predicate(versions[i])) return versions[i];
  }
  return undefined;
}

export function findLatestVersion(
  versions: string[],
  filter: StabilityFilter = "PREFER_STABLE",
): string | undefined {
  if (filter === "ALL") return versions[versions.length - 1];
  const stable = lastWhere(versions, (v) => classifyVersion(v) === "stable");
  if (filter === "STABLE_ONLY") return stable;
  return stable ?? versions[versions.length - 1];
}

/**
 * Find the latest version that is at least as stable as the current version.
 * E.g., if current is beta, returns latest beta/rc/stable (not alpha/snapshot).
 * If current is stable, returns only stable.
 */
export function findLatestVersionForCurrent(
  versions: string[],
  currentVersion: string,
): string | undefined {
  const currentStability = classifyVersion(currentVersion);
  const maxRank = stabilityRank(currentStability);
  return lastWhere(versions, (v) => stabilityRank(classifyVersion(v)) <= maxRank);
}
