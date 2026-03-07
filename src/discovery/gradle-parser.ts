import type { RepositoryConfig } from "./types.js";

const WELL_KNOWN_REPOS: Record<string, RepositoryConfig> = {
  mavenCentral: { name: "Maven Central", url: "https://repo1.maven.org/maven2" },
  google: { name: "Google", url: "https://maven.google.com" },
  gradlePluginPortal: { name: "Gradle Plugin Portal", url: "https://plugins.gradle.org/m2" },
};

export function parseGradleRepositories(content: string): RepositoryConfig[] {
  const repos: RepositoryConfig[] = [];
  const seen = new Set<string>();

  function add(config: RepositoryConfig) {
    if (!seen.has(config.url)) {
      seen.add(config.url);
      repos.push(config);
    }
  }

  // Well-known: mavenCentral(), google(), gradlePluginPortal()
  for (const [funcName, config] of Object.entries(WELL_KNOWN_REPOS)) {
    const pattern = new RegExp(`\\b${funcName}\\s*\\(\\s*\\)`, "g");
    if (pattern.test(content)) {
      add(config);
    }
  }

  // maven("url") or maven('url')
  const mavenDirectRegex = /\bmaven\s*\(\s*["']([^"']+)["']\s*\)/g;
  let match: RegExpExecArray | null;
  while ((match = mavenDirectRegex.exec(content)) !== null) {
    add({ name: match[1], url: match[1] });
  }

  // maven(url = "url") or maven(url = 'url')
  const mavenUrlParamRegex = /\bmaven\s*\(\s*url\s*=\s*["']([^"']+)["']\s*\)/g;
  while ((match = mavenUrlParamRegex.exec(content)) !== null) {
    add({ name: match[1], url: match[1] });
  }

  // maven { url = uri("url") } or maven { url = uri('url') }
  const mavenBlockUriRegex = /\bmaven\s*\{[^}]*url\s*=\s*uri\s*\(\s*["']([^"']+)["']\s*\)/g;
  while ((match = mavenBlockUriRegex.exec(content)) !== null) {
    add({ name: match[1], url: match[1] });
  }

  // Groovy: maven { url 'url' } or maven { url "url" }
  const mavenBlockGroovyRegex = /\bmaven\s*\{[^}]*url\s+["']([^"']+)["']/g;
  while ((match = mavenBlockGroovyRegex.exec(content)) !== null) {
    add({ name: match[1], url: match[1] });
  }

  return repos;
}
