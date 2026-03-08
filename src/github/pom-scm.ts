export interface GitHubRepo {
  owner: string;
  repo: string;
}

/**
 * Builds a Maven POM URL from repository URL and artifact coordinates.
 */
export function buildPomUrl(
  repoUrl: string,
  groupId: string,
  artifactId: string,
  version: string,
): string {
  const base = repoUrl.replace(/\/+$/, "");
  const groupPath = groupId.replace(/\./g, "/");
  return `${base}/${groupPath}/${artifactId}/${version}/${artifactId}-${version}.pom`;
}

const GITHUB_REPO_RE =
  /github\.com[/:]([A-Za-z0-9_.-]+)\/([A-Za-z0-9_.-]+)/;

function parseGitHubUrl(url: string): GitHubRepo | null {
  const m = url.match(GITHUB_REPO_RE);
  if (!m) return null;
  const owner = m[1];
  let repo = m[2];
  repo = repo.replace(/\.git$/, "");
  // Strip path suffixes like /tree/main
  repo = repo.split("/")[0];
  return { owner, repo };
}

/**
 * Extracts GitHub owner/repo from POM XML using regex-based parsing.
 *
 * Priority:
 * 1. <scm><url>
 * 2. <scm><connection>
 * 3. <scm><developerConnection>
 * 4. Root <url> (outside <scm>)
 */
export function extractGitHubRepo(pomXml: string): GitHubRepo | null {
  // Extract <scm> block
  const scmMatch = pomXml.match(/<scm>([\s\S]*?)<\/scm>/);

  if (scmMatch) {
    const scmBlock = scmMatch[1];

    // Try <url> inside <scm>
    const scmUrl = scmBlock.match(/<url>\s*(.*?)\s*<\/url>/);
    if (scmUrl) {
      const result = parseGitHubUrl(scmUrl[1]);
      if (result) return result;
    }

    // Try <connection>
    const conn = scmBlock.match(/<connection>\s*(.*?)\s*<\/connection>/);
    if (conn) {
      const result = parseGitHubUrl(conn[1]);
      if (result) return result;
    }

    // Try <developerConnection>
    const devConn = scmBlock.match(
      /<developerConnection>\s*(.*?)\s*<\/developerConnection>/,
    );
    if (devConn) {
      const result = parseGitHubUrl(devConn[1]);
      if (result) return result;
    }
  }

  // Fallback: root <url> outside <scm>
  // Remove <scm> block first to avoid matching URLs inside it
  const withoutScm = pomXml.replace(/<scm>[\s\S]*?<\/scm>/, "");
  const rootUrl = withoutScm.match(/<url>\s*(.*?)\s*<\/url>/);
  if (rootUrl) {
    return parseGitHubUrl(rootUrl[1]);
  }

  return null;
}
