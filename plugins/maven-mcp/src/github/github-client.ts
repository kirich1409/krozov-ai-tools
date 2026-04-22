import { fetchWithRetry } from "../http/client.js";

export interface GitHubRelease {
  tag_name: string;
  body: string;
  html_url: string;
}

const GITHUB_API = "https://api.github.com";
const ACCEPT_HEADER = "application/vnd.github.v3+json";

const CHANGELOG_NAMES = ["CHANGELOG.md", "changelog.md", "CHANGES.md"];

// GitHub `contents` endpoint only embeds base64 content when the file is
// ≤ 1 MB. Above that, `content` is empty and the API returns `download_url`.
const MAX_INLINE_CONTENT_SIZE = 900_000;

interface GitHubContentsResponse {
  content?: string;
  encoding?: string;
  size?: number;
  download_url?: string | null;
}

export class GitHubClient {
  private readonly headers: Record<string, string>;

  constructor(token?: string) {
    this.headers = {
      Accept: ACCEPT_HEADER,
    };
    if (token) {
      this.headers["Authorization"] = `Bearer ${token}`;
    }
  }

  async fetchReleases(owner: string, repo: string): Promise<GitHubRelease[]> {
    try {
      const response = await fetchWithRetry(
        `${GITHUB_API}/repos/${owner}/${repo}/releases?per_page=100`,
        { headers: this.headers, timeoutMs: 15_000 },
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
        const response = await fetchWithRetry(
          `${GITHUB_API}/repos/${owner}/${repo}/contents/${name}`,
          { headers: this.headers, timeoutMs: 10_000 },
        );
        if (!response.ok) continue;
        const data = (await response.json()) as GitHubContentsResponse;
        const decoded = await this.decodeChangelogContents(data);
        if (decoded !== null) return decoded;
      } catch {
        continue;
      }
    }
    return null;
  }

  async repoExists(owner: string, repo: string): Promise<boolean> {
    try {
      const response = await fetchWithRetry(
        `${GITHUB_API}/repos/${owner}/${repo}`,
        { headers: this.headers, timeoutMs: 10_000 },
      );
      return response.ok;
    } catch {
      return false;
    }
  }

  /**
   * Files > 1 MB come back with `content === ""` and a `download_url` pointing
   * at raw.githubusercontent.com. Fall back to fetching that raw URL so the
   * changelog isn't silently truncated to the empty string.
   */
  private async decodeChangelogContents(
    data: GitHubContentsResponse,
  ): Promise<string | null> {
    const hasInlineContent = typeof data.content === "string" && data.content.length > 0;
    const oversized = (data.size ?? 0) > MAX_INLINE_CONTENT_SIZE;

    if (hasInlineContent && !oversized) {
      return Buffer.from(data.content!, "base64").toString("utf-8");
    }
    if (data.download_url) {
      try {
        const raw = await fetchWithRetry(data.download_url, { timeoutMs: 15_000 });
        if (!raw.ok) return null;
        return await raw.text();
      } catch {
        return null;
      }
    }
    return null;
  }
}
