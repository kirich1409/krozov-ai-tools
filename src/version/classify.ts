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

export function findLatestVersion(
  versions: string[],
  filter: StabilityFilter = "STABLE_ONLY",
): string | undefined {
  const reversed = [...versions].reverse();
  if (filter === "ALL") return reversed[0];
  const stable = reversed.find((v) => classifyVersion(v) === "stable");
  if (filter === "STABLE_ONLY") return stable;
  return stable ?? reversed[0];
}
