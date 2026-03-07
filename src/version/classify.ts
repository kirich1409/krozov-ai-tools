import type { StabilityType } from "./types.js";

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
