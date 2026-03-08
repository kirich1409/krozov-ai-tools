import type { GitHubRepo } from "./pom-scm.js";

const GITHUB_GROUP_PREFIXES = ["com.github.", "io.github."] as const;

export function guessGitHubRepo(
  groupId: string,
  artifactId: string,
): GitHubRepo | null {
  for (const prefix of GITHUB_GROUP_PREFIXES) {
    if (groupId.startsWith(prefix) && groupId.length > prefix.length) {
      const rest = groupId.slice(prefix.length);
      const owner = rest.split(".")[0];
      return { owner, repo: artifactId };
    }
  }
  return null;
}
