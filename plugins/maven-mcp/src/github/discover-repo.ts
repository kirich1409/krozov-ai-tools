import type { MavenRepository } from "../maven/repository.js";
import type { GitHubRepo } from "./pom-scm.js";
import { buildPomUrl, extractGitHubRepo } from "./pom-scm.js";
import { guessGitHubRepo } from "./guess-repo.js";
import { GitHubClient } from "./github-client.js";

export async function discoverGitHubRepo(
  repos: MavenRepository[],
  groupId: string,
  artifactId: string,
  version: string,
  githubClient?: GitHubClient,
): Promise<GitHubRepo | null> {
  // Step 1: Try each Maven repo's POM for GitHub SCM info
  for (const repo of repos) {
    try {
      const pomUrl = buildPomUrl(repo.url, groupId, artifactId, version);
      const response = await fetch(pomUrl, {
        signal: AbortSignal.timeout(10_000),
      });
      if (!response.ok) continue;

      const pomXml = await response.text();
      const ghRepo = extractGitHubRepo(pomXml);
      if (ghRepo) return ghRepo;
    } catch {
      // Fetch failed, try next repo
      continue;
    }
  }

  // Step 2: Try guessing from groupId/artifactId
  const guess = guessGitHubRepo(groupId, artifactId);
  if (!guess) return null;

  // Step 3: Verify guessed repo exists
  const client = githubClient ?? new GitHubClient(process.env.GITHUB_TOKEN);
  const exists = await client.repoExists(guess.owner, guess.repo);
  return exists ? guess : null;
}
