export type StabilityType = "stable" | "rc" | "beta" | "alpha" | "milestone" | "snapshot";

export type StabilityFilter = "STABLE_ONLY" | "PREFER_STABLE" | "ALL";

export type UpgradeType = "major" | "minor" | "patch" | "none";

export interface VersionInfo {
  version: string;
  stability: StabilityType;
}
