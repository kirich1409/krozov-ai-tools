import type { UpgradeType, StabilityType } from "./types.js";
import { classifyVersion } from "./classify.js";

function parseSegments(version: string): number[] {
  return version
    .replace(/[-+].*$/, "")
    .split(".")
    .map((s) => parseInt(s, 10) || 0);
}

export function getUpgradeType(current: string, latest: string): UpgradeType {
  // Only classify real upgrades. Downgrades and equal versions are "none".
  // Using semver-aware compare makes pre-release transitions (2.0.0-beta → 2.0.0,
  // 2.0.0-beta → 2.0.0-rc) register as upgrades instead of being swallowed by
  // the naive `parseSegments` strip.
  if (compareVersions(latest, current) <= 0) return "none";

  const cur = parseSegments(current);
  const lat = parseSegments(latest);
  const maxLen = Math.max(cur.length, lat.length);
  while (cur.length < maxLen) cur.push(0);
  while (lat.length < maxLen) lat.push(0);

  if (lat[0] !== cur[0]) return "major";
  if (lat[1] !== cur[1]) return "minor";
  if (lat[2] !== cur[2]) return "patch";
  // Core segments are identical but compareVersions already said latest > current:
  // pre-release progression (e.g. 2.0.0-beta-1 → 2.0.0-rc-1 → 2.0.0). Report as patch.
  return "patch";
}

// Higher weight = more stable. Stable release ranks highest so that
// "2.0.0" sorts above any "2.0.0-*" pre-release of the same core.
const PRERELEASE_WEIGHT: Record<StabilityType, number> = {
  snapshot: 0,
  alpha: 1,
  beta: 2,
  milestone: 3,
  rc: 4,
  stable: 5,
};

function compareNumberArrays(a: number[], b: number[]): number {
  const max = Math.max(a.length, b.length);
  for (let i = 0; i < max; i++) {
    const ai = a[i] ?? 0;
    const bi = b[i] ?? 0;
    if (ai !== bi) return ai < bi ? -1 : 1;
  }
  return 0;
}

function extractPrereleaseNumbers(version: string): number[] {
  const dash = version.indexOf("-");
  const plus = version.indexOf("+");
  const cut =
    dash === -1 ? plus : plus === -1 ? dash : Math.min(dash, plus);
  if (cut === -1) return [];
  const suffix = version.slice(cut + 1);
  const matches = suffix.match(/\d+/g);
  return matches ? matches.map((n) => parseInt(n, 10)) : [];
}

/**
 * Compare two Maven version strings. Returns negative if `a < b`,
 * positive if `a > b`, zero if equal.
 *
 * Order:
 *   1. Numeric core (major.minor.patch.…).
 *   2. Stability tier: stable > rc > milestone > beta > alpha > snapshot.
 *   3. Numeric tail within the pre-release suffix (e.g. `beta-1` < `beta-2`).
 *   4. Lexicographic fallback for full determinism.
 */
export function compareVersions(a: string, b: string): number {
  const coreDiff = compareNumberArrays(parseSegments(a), parseSegments(b));
  if (coreDiff !== 0) return coreDiff;

  const weightDiff =
    PRERELEASE_WEIGHT[classifyVersion(a)] -
    PRERELEASE_WEIGHT[classifyVersion(b)];
  if (weightDiff !== 0) return weightDiff;

  const tailDiff = compareNumberArrays(
    extractPrereleaseNumbers(a),
    extractPrereleaseNumbers(b),
  );
  if (tailDiff !== 0) return tailDiff;

  return a < b ? -1 : a > b ? 1 : 0;
}
