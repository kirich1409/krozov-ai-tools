import type { UpgradeType } from "./types.js";

function parseSegments(version: string): number[] {
  return version
    .replace(/[-+].*$/, "")
    .split(".")
    .map((s) => parseInt(s, 10) || 0);
}

export function getUpgradeType(current: string, latest: string): UpgradeType {
  const cur = parseSegments(current);
  const lat = parseSegments(latest);

  const maxLen = Math.max(cur.length, lat.length);
  while (cur.length < maxLen) cur.push(0);
  while (lat.length < maxLen) lat.push(0);

  if (lat[0] !== cur[0]) return lat[0] > cur[0] ? "major" : "none";
  if (lat[1] !== cur[1]) return lat[1] > cur[1] ? "minor" : "none";
  if (lat[2] !== cur[2]) return lat[2] > cur[2] ? "patch" : "none";
  return "none";
}
