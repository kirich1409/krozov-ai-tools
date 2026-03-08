export interface GitHubRelease {
  tag_name: string;
  body: string;
  html_url: string;
}

const GITHUB_API = "https://api.github.com";
const USER_AGENT = "maven-central-mcp";
const ACCEPT_HEADER = "application/vnd.github.v3+json";

const CHANGELOG_NAMES = ["CHANGELOG.md", "changelog.md", "CHANGES.md"];

export class GitHubClient {
  private readonly token?: string;

  constructor(token?: string) {
    this.token = token;
  }

  private buildHeaders(): Record<string, string> {
    const headers: Record<string, string> = {
      Accept: ACCEPT_HEADER,
      "User-Agent": USER_AGENT,
    };
    if (this.token) {
      headers["Authorization"] = `Bearer ${this.token}`;
    }
    return headers;
  }

  async fetchReleases(owner: string, repo: string): Promise<GitHubRelease[]> {
    try {
      const response = await fetch(
        `${GITHUB_API}/repos/${owner}/${repo}/releases?per_page=100`,
        {
          headers: this.buildHeaders(),
          signal: AbortSignal.timeout(15_000),
        }
      );
      if (!response.ok) return [];
      return (await response.json()) as GitHubRelease[];
    } catch {
      return [];
    }
  }

  async fetchChangelog(owner: string, repo: string): Promise<string | null> {
    for (const name of CHANGELOG_NAMES) {
      try {
        const response = await fetch(
          `${GITHUB_API}/repos/${owner}/${repo}/contents/${name}`,
          {
            headers: this.buildHeaders(),
            signal: AbortSignal.timeout(10_000),
          }
        );
        if (!response.ok) continue;
        const data = (await response.json()) as { content: string };
        return Buffer.from(data.content, "base64").toString("utf-8");
      } catch {
        return null;
      }
    }
    return null;
  }

  async repoExists(owner: string, repo: string): Promise<boolean> {
    try {
      const response = await fetch(
        `${GITHUB_API}/repos/${owner}/${repo}`,
        {
          headers: this.buildHeaders(),
          signal: AbortSignal.timeout(10_000),
        }
      );
      return response.ok;
    } catch {
      return false;
    }
  }
}
