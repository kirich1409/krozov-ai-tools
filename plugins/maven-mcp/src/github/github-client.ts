import { fetchWithRetry } from "../http/client.js";

export interface GitHubRelease {
  tag_name: string;
  body: string;
  html_url: string;
  published_at?: string | null;
  draft?: boolean;
  prerelease?: boolean;
}

export interface GitHubRepoMeta {
  stargazers_count: number;
  forks_count: number;
  archived: boolean;
  pushed_at: string | null;
  open_issues_count: number;
  created_at: string | null;
  license: { spdx_id: string | null; name: string | null } | null;
  owner: { login: string; type: string };
}

export interface IssueStats {
  open: number;
  closed: number;
  /** closed / (open + closed); null when either count is unavailable. */
  closeRatio: number | null;
  /** Median days-to-close over recent closed issues; null when unavailable. */
  medianDaysToClose: number | null;
}

export interface GitHubUser {
  public_repos: number | null;
  created_at: string | null;
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

  /** Fetch repository metadata (stars, activity, license, owner). null on failure. */
  async fetchRepo(owner: string, repo: string): Promise<GitHubRepoMeta | null> {
    try {
      const response = await fetchWithRetry(
        `${GITHUB_API}/repos/${owner}/${repo}`,
        { headers: this.headers, timeoutMs: 10_000 },
      );
      if (!response.ok) return null;
      return (await response.json()) as GitHubRepoMeta;
    } catch {
      return null;
    }
  }

  /**
   * Publisher/owner account signals: public-repo count and account creation
   * date, used to gauge maintainer scale and account age. null on failure
   * (non-fatal — repo metrics still stand without it).
   */
  async fetchUser(login: string): Promise<GitHubUser | null> {
    try {
      const response = await fetchWithRetry(`${GITHUB_API}/users/${login}`, {
        headers: this.headers,
        timeoutMs: 10_000,
      });
      if (!response.ok) return null;
      return (await response.json()) as GitHubUser;
    } catch {
      return null;
    }
  }

  /**
   * Issue dynamics via the GitHub Search API: open vs closed counts, close
   * ratio, and median days-to-close over recent closed issues. Returns null
   * when both counts are unavailable (Search API is rate-limited more strictly
   * than the core API). PRs are excluded via `type:issue`.
   */
  async fetchIssueStats(owner: string, repo: string): Promise<IssueStats | null> {
    const open = await this.searchIssueCount(owner, repo, "open");
    const closed = await this.searchIssueCount(owner, repo, "closed");
    if (open === null && closed === null) return null;

    const medianDaysToClose = await this.medianDaysToCloseRecent(owner, repo);
    const total = (open ?? 0) + (closed ?? 0);
    const closeRatio =
      open !== null && closed !== null && total > 0 ? closed / total : null;

    return { open: open ?? 0, closed: closed ?? 0, closeRatio, medianDaysToClose };
  }

  private async searchIssueCount(
    owner: string,
    repo: string,
    state: "open" | "closed",
  ): Promise<number | null> {
    try {
      const q = `repo:${owner}/${repo} type:issue state:${state}`;
      const url = `${GITHUB_API}/search/issues?q=${encodeURIComponent(q)}&per_page=1`;
      const response = await fetchWithRetry(url, { headers: this.headers, timeoutMs: 10_000 });
      if (!response.ok) return null;
      const data = (await response.json()) as { total_count?: number };
      return typeof data.total_count === "number" ? data.total_count : null;
    } catch {
      return null;
    }
  }

  private async medianDaysToCloseRecent(owner: string, repo: string): Promise<number | null> {
    try {
      const q = `repo:${owner}/${repo} type:issue state:closed`;
      const url = `${GITHUB_API}/search/issues?q=${encodeURIComponent(q)}&sort=updated&order=desc&per_page=30`;
      const response = await fetchWithRetry(url, { headers: this.headers, timeoutMs: 10_000 });
      if (!response.ok) return null;
      const data = (await response.json()) as {
        items?: { created_at?: string; closed_at?: string }[];
      };
      const durations = (data.items ?? [])
        .map((i) =>
          i.created_at && i.closed_at
            ? Date.parse(i.closed_at) - Date.parse(i.created_at)
            : null,
        )
        .filter((d): d is number => d !== null && Number.isFinite(d) && d >= 0)
        .sort((a, b) => a - b);
      if (durations.length === 0) return null;
      const mid = Math.floor(durations.length / 2);
      const medianMs =
        durations.length % 2 ? durations[mid] : (durations[mid - 1] + durations[mid]) / 2;
      return Math.round(medianMs / 86_400_000);
    } catch {
      return null;
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
