import { existsSync } from "node:fs";
import { dirname, join, resolve } from "node:path";

export const BUILD_FILE_MARKERS = [
  "settings.gradle.kts",
  "settings.gradle",
  "build.gradle.kts",
  "build.gradle",
  "pom.xml",
] as const;

export function findProjectRoot(startDir: string): string | null {
  let current = resolve(startDir);

  while (true) {
    for (const marker of BUILD_FILE_MARKERS) {
      if (existsSync(join(current, marker))) {
        return current;
      }
    }

    const parent = dirname(current);
    if (parent === current) {
      return null;
    }
    current = parent;
  }
}
