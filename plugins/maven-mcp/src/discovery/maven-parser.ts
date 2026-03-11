import type { RepositoryConfig } from "./types.js";

export function parseMavenRepositories(content: string): RepositoryConfig[] {
  const repos: RepositoryConfig[] = [];

  const repoBlockRegex = /<repository>([\s\S]*?)<\/repository>/g;
  let match: RegExpExecArray | null;

  while ((match = repoBlockRegex.exec(content)) !== null) {
    const block = match[1];
    const url = block.match(/<url>([^<]+)<\/url>/)?.[1]?.trim();
    if (!url) continue;

    const id = block.match(/<id>([^<]+)<\/id>/)?.[1]?.trim();
    repos.push({ name: id ?? url, url });
  }

  return repos;
}
