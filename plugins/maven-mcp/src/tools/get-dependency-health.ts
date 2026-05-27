import type { MavenRepository } from "../maven/repository.js";
import { resolveAll } from "../maven/resolver.js";
import { classifyVersion, findLatestVersion } from "../version/classify.js";
import type { StabilityType } from "../version/types.js";
import { buildPomUrl, extractGitHubRepo, extractScmUrl, extractLicenses } from "../github/pom-scm.js";
import type { GitHubRepo } from "../github/pom-scm.js";
import { guessGitHubRepo } from "../github/guess-repo.js";
import { GitHubClient } from "../github/github-client.js";
import type { GitHubRelease, GitHubRepoMeta } from "../github/github-client.js";
import { fetchWithRetry } from "../http/client.js";

const MS_PER_DAY = 86_400_000;
const MS_PER_MONTH = MS_PER_DAY * 30;

export interface DependencyHealthInput {
  dependencies: { groupId: string; artifactId: string; version?: string }[];
}

export interface IssueHealth {
  /** null when the Search API call failed (rate-limited or network error). */
  open: number | null;
  /** null when the Search API call failed (rate-limited or network error). */
  closed: number | null;
  closeRatio: number | null;
  medianDaysToClose: number | null;
}

export interface GitHubHealth {
  stars: number;
  forks: number;
  openIssues: number;
  archived: boolean;
  ownerType: string;
  ownerPublicRepos: number | null;
  ownerAccountCreatedAt: string | null;
  lastCommit: string | null;
  lastRelease: string | null;
  releaseCount: number;
  releaseCadenceDays: number | null;
  license: string | null;
  createdAt: string | null;
  issues: IssueHealth | null;
}

export interface DependencyHealth {
  groupId: string;
  artifactId: string;
  latestVersion?: string;
  stability?: StabilityType;
  versionCount: number;
  lastPublishedToMaven?: string;
  repository: { owner: string; repo: string; url: string } | null;
  scm: { url: string; host: string } | null;
  github: GitHubHealth | null;
  signals: string[];
  healthError?: string;
}

export interface DependencyHealthResult {
  results: DependencyHealth[];
}

export function scmHost(url: string): string {
  if (!url) return "other";
  // scp-like SSH form: git@github.com:owner/repo.git — new URL() throws on these
  const scpMatch = url.match(/^[^/@]+@([^:/]+):/);
  let host: string;
  if (scpMatch) {
    host = scpMatch[1].toLowerCase();
  } else {
    try {
      host = new URL(url).hostname.toLowerCase();
    } catch {
      return "other";
    }
  }
  if (host === "github.com" || host.endsWith(".github.com")) return "github";
  if (host === "gitlab.com" || host.endsWith(".gitlab.com")) return "gitlab";
  if (host === "bitbucket.org" || host.endsWith(".bitbucket.org")) return "bitbucket";
  return "other";
}

function monthsSince(iso: string | null): number | null {
  if (!iso) return null;
  const t = Date.parse(iso);
  if (Number.isNaN(t)) return null;
  return Math.floor((Date.now() - t) / MS_PER_MONTH);
}

function summarizeReleases(releases: GitHubRelease[]): {
  last: string | null;
  cadenceDays: number | null;
  count: number;
} {
  const times = releases
    .filter((r) => !r.draft && !r.prerelease && r.published_at)
    .map((r) => Date.parse(r.published_at!))
    .filter((t) => !Number.isNaN(t))
    .sort((a, b) => b - a); // newest first

  if (times.length === 0) return { last: null, cadenceDays: null, count: 0 };
  const last = new Date(times[0]).toISOString();
  if (times.length < 2) return { last, cadenceDays: null, count: times.length };

  const gaps: number[] = [];
  for (let i = 0; i < times.length - 1; i++) gaps.push(times[i] - times[i + 1]);
  gaps.sort((a, b) => a - b);
  const mid = Math.floor(gaps.length / 2);
  const medianMs = gaps.length % 2 ? gaps[mid] : (gaps[mid - 1] + gaps[mid]) / 2;
  return { last, cadenceDays: Math.round(medianMs / MS_PER_DAY), count: times.length };
}

async function fetchPomXml(
  repos: MavenRepository[],
  groupId: string,
  artifactId: string,
  version: string,
): Promise<string | null> {
  for (const repo of repos) {
    try {
      const response = await fetchWithRetry(buildPomUrl(repo.url, groupId, artifactId, version), {
        timeoutMs: 10_000,
      });
      if (!response.ok) continue;
      return await response.text();
    } catch {
      continue;
    }
  }
  return null;
}

async function evaluateOne(
  repos: MavenRepository[],
  client: GitHubClient,
  dep: { groupId: string; artifactId: string; version?: string },
): Promise<DependencyHealth> {
  const { groupId, artifactId } = dep;
  const result: DependencyHealth = {
    groupId,
    artifactId,
    versionCount: 0,
    repository: null,
    scm: null,
    github: null,
    signals: [],
  };

  let versions: string[];
  try {
    const metadata = await resolveAll(repos, groupId, artifactId);
    versions = metadata.versions;
    result.lastPublishedToMaven = metadata.lastUpdated;
  } catch (e) {
    result.healthError = String(e);
    return result;
  }

  // latestVersion/stability always reflect the real latest available version,
  // regardless of which specific version was requested — the tool contract says
  // "latest version & stability" even when a specific version is being assessed.
  const latestVersion =
    findLatestVersion(versions, "PREFER_STABLE") ?? versions[versions.length - 1];
  result.latestVersion = latestVersion;
  result.stability = latestVersion ? classifyVersion(latestVersion) : undefined;
  result.versionCount = versions.length;

  // For POM fetch and SCM extraction, use the requested version when given
  // (so license/SCM reflects the version actually being evaluated).
  const targetVersion = dep.version ?? latestVersion;
  if (!findLatestVersion(versions, "STABLE_ONLY")) result.signals.push("no stable release");

  // POM gives SCM URL, license, and (often) the GitHub repo.
  let ghRepo: GitHubRepo | null = null;
  let pomLicenses: string[] = [];
  if (targetVersion) {
    const pomXml = await fetchPomXml(repos, groupId, artifactId, targetVersion);
    if (pomXml) {
      ghRepo = extractGitHubRepo(pomXml);
      pomLicenses = extractLicenses(pomXml);
      const scmUrl = extractScmUrl(pomXml);
      if (scmUrl) result.scm = { url: scmUrl, host: scmHost(scmUrl) };
    }
  }

  // Fall back to guessing the GitHub repo from io.github.* / com.github.* groups.
  // Use fetchRepo directly — if it returns metadata the repo exists; this avoids
  // a redundant repoExists call followed by fetchRepo for the same endpoint.
  let cachedRepoMeta: GitHubRepoMeta | null = null;
  if (!ghRepo) {
    const guess = guessGitHubRepo(groupId, artifactId);
    if (guess) {
      cachedRepoMeta = await client.fetchRepo(guess.owner, guess.repo);
      if (cachedRepoMeta) ghRepo = guess;
    }
  }

  if (!ghRepo) {
    if (pomLicenses.length === 0) result.signals.push("no license declared");
    if (result.scm && result.scm.host !== "github") {
      // Source repo is public but hosted on a non-GitHub forge — GitHub metrics simply
      // aren't available; this is not a transparency red flag.
      result.signals.push(`SCM hosted on ${result.scm.host}; GitHub metrics unavailable`);
    } else {
      // No SCM information at all — genuinely unknown source provenance.
      result.signals.push("no public GitHub repository found");
      result.healthError = "GitHub repository not found; activity metrics unavailable";
    }
    return result;
  }

  result.repository = {
    owner: ghRepo.owner,
    repo: ghRepo.repo,
    url: `https://github.com/${ghRepo.owner}/${ghRepo.repo}`,
  };
  if (!result.scm) result.scm = { url: result.repository.url, host: "github" };

  // Reuse the repo metadata fetched during the guess-path existence check if available.
  const repoMeta = cachedRepoMeta ?? (await client.fetchRepo(ghRepo.owner, ghRepo.repo));
  if (!repoMeta) {
    if (pomLicenses.length === 0) result.signals.push("no license declared");
    result.healthError = "GitHub repository metadata unavailable (rate limit or network)";
    return result;
  }

  const [releases, issues] = await Promise.all([
    client.fetchReleases(ghRepo.owner, ghRepo.repo),
    client.fetchIssueStats(ghRepo.owner, ghRepo.repo),
  ]);
  const { last, cadenceDays, count } = summarizeReleases(releases);

  // Publisher scale/age — non-fatal enrichment, gathered last.
  const ownerLogin = repoMeta.owner?.login ?? ghRepo.owner;
  const owner = await client.fetchUser(ownerLogin);

  const spdx = repoMeta.license?.spdx_id;
  const license =
    spdx && spdx !== "NOASSERTION" ? spdx : (pomLicenses[0] ?? null);

  result.github = {
    stars: repoMeta.stargazers_count ?? 0,
    forks: repoMeta.forks_count ?? 0,
    openIssues: repoMeta.open_issues_count ?? 0,
    archived: Boolean(repoMeta.archived),
    ownerType: repoMeta.owner?.type ?? "unknown",
    ownerPublicRepos: owner?.public_repos ?? null,
    ownerAccountCreatedAt: owner?.created_at ?? null,
    lastCommit: repoMeta.pushed_at ?? null,
    lastRelease: last,
    releaseCount: count,
    releaseCadenceDays: cadenceDays,
    license,
    createdAt: repoMeta.created_at ?? null,
    issues,
  };

  if (result.github.archived) result.signals.push("repository archived");
  const commitMonths = monthsSince(result.github.lastCommit);
  if (commitMonths !== null && commitMonths >= 12) {
    result.signals.push(`no commits in ${commitMonths} months`);
  }
  const releaseMonths = monthsSince(result.github.lastRelease);
  if (releaseMonths !== null && releaseMonths >= 18) {
    result.signals.push(`no release in ${releaseMonths} months`);
  }
  if (!license) result.signals.push("no license declared");
  if (issues && issues.closeRatio !== null && issues.closeRatio < 0.5 && (issues.open ?? 0) >= 50) {
    result.signals.push("high open-issue backlog, low close ratio");
  }
  if (issues && issues.medianDaysToClose !== null && issues.medianDaysToClose >= 180) {
    result.signals.push(`slow issue response (median ${issues.medianDaysToClose} days to close)`);
  }

  return result;
}

/**
 * Run `fn` over `items` with at most `limit` concurrent inflight calls.
 * Result order matches input order.
 */
async function mapWithConcurrency<T, R>(
  items: T[],
  limit: number,
  fn: (item: T) => Promise<R>,
): Promise<R[]> {
  const results = new Array<R>(items.length);
  let next = 0;
  const worker = async (): Promise<void> => {
    for (;;) {
      const i = next++;
      if (i >= items.length) return;
      results[i] = await fn(items[i]);
    }
  };
  await Promise.all(Array.from({ length: Math.min(limit, items.length) }, worker));
  return results;
}

const HEALTH_CONCURRENCY = 5;

export async function getDependencyHealthHandler(
  repos: MavenRepository[],
  input: DependencyHealthInput,
): Promise<DependencyHealthResult> {
  const client = new GitHubClient(process.env.GITHUB_TOKEN);
  const results = await mapWithConcurrency(
    input.dependencies,
    HEALTH_CONCURRENCY,
    (dep) => evaluateOne(repos, client, dep),
  );
  return { results };
}
