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
 * Strips XML comments so a commented-out element cannot poison a match
 * (e.g. `<!-- <url>https://github.com/wrong/repo</url> -->`). Loops to handle
 * smuggled forms like `<!<!----->-- evil -->` where a fresh `<!--` only
 * surfaces after the inner comment is stripped.
 */
function stripXmlComments(pomXml: string): string {
  let xml = pomXml;
  let prev: string;
  do {
    prev = xml;
    xml = xml.replace(/<!--[\s\S]*?-->/g, "");
  } while (xml !== prev);
  return xml;
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
  const xml = stripXmlComments(pomXml);

  // Extract <scm> block
  const scmMatch = xml.match(/<scm>([\s\S]*?)<\/scm>/);

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
  const withoutScm = xml.replace(/<scm>[\s\S]*?<\/scm>/, "");
  const rootUrl = withoutScm.match(/<url>\s*(.*?)\s*<\/url>/);
  if (rootUrl) {
    return parseGitHubUrl(rootUrl[1]);
  }

  return null;
}

// Maven SCM connection strings are prefixed like `scm:git:https://…` or
// `scm:git:git://…`. Strip the leading `scm:<provider>:` so the bare URL
// remains for host classification.
function cleanScmConnection(value: string): string {
  return value.replace(/^scm:[a-z]+:/i, "");
}

/**
 * Extracts the raw SCM URL from POM XML (any host, not only GitHub). Used to
 * report where the source lives even when GitHub-specific metrics are
 * unavailable (GitLab/Bitbucket/self-hosted/closed source).
 *
 * Priority mirrors extractGitHubRepo: <scm><url> → <connection> →
 * <developerConnection> → root <url>.
 */
export function extractScmUrl(pomXml: string): string | null {
  const xml = stripXmlComments(pomXml);

  const scmMatch = xml.match(/<scm>([\s\S]*?)<\/scm>/);
  if (scmMatch) {
    const scmBlock = scmMatch[1];

    const scmUrl = scmBlock.match(/<url>\s*(.*?)\s*<\/url>/);
    if (scmUrl && scmUrl[1]) return scmUrl[1].trim();

    const conn = scmBlock.match(/<connection>\s*(.*?)\s*<\/connection>/);
    if (conn && conn[1]) return cleanScmConnection(conn[1].trim());

    const devConn = scmBlock.match(/<developerConnection>\s*(.*?)\s*<\/developerConnection>/);
    if (devConn && devConn[1]) return cleanScmConnection(devConn[1].trim());
  }

  const withoutScm = xml.replace(/<scm>[\s\S]*?<\/scm>/, "");
  const rootUrl = withoutScm.match(/<url>\s*(.*?)\s*<\/url>/);
  if (rootUrl && rootUrl[1]) return rootUrl[1].trim();

  return null;
}

/**
 * Extracts declared license names from POM XML (<licenses><license><name>).
 * Regex-based to honour the "no XML parser dependency" non-negotiable.
 */
export function extractLicenses(pomXml: string): string[] {
  const xml = stripXmlComments(pomXml);
  const block = xml.match(/<licenses>([\s\S]*?)<\/licenses>/);
  if (!block) return [];

  const names: string[] = [];
  const licenseRe = /<license>([\s\S]*?)<\/license>/g;
  let match: RegExpExecArray | null;
  while ((match = licenseRe.exec(block[1])) !== null) {
    const nameMatch = match[1].match(/<name>\s*(.*?)\s*<\/name>/);
    if (nameMatch && nameMatch[1]) names.push(nameMatch[1].trim());
  }
  return names;
}
