import type { RepositoryConfig } from "./types.js";
import { MAVEN_CENTRAL, GOOGLE_MAVEN, GRADLE_PLUGIN_PORTAL } from "../maven/repository.js";

const WELL_KNOWN_REPOS: Record<string, RepositoryConfig> = {
  mavenCentral: { name: MAVEN_CENTRAL.name, url: MAVEN_CENTRAL.url },
  google: { name: GOOGLE_MAVEN.name, url: GOOGLE_MAVEN.url },
  gradlePluginPortal: { name: GRADLE_PLUGIN_PORTAL.name, url: GRADLE_PLUGIN_PORTAL.url },
};

export function parseGradleRepositories(content: string): RepositoryConfig[] {
  const repos: RepositoryConfig[] = [];

  // Well-known: mavenCentral(), google(), gradlePluginPortal()
  for (const [funcName, config] of Object.entries(WELL_KNOWN_REPOS)) {
    const pattern = new RegExp(`\\b${funcName}\\s*\\(\\s*\\)`, "g");
    if (pattern.test(content)) {
      repos.push(config);
    }
  }

  // maven("url") or maven('url')
  const mavenDirectRegex = /\bmaven\s*\(\s*["']([^"']+)["']\s*\)/g;
  let match: RegExpExecArray | null;
  while ((match = mavenDirectRegex.exec(content)) !== null) {
    repos.push({ name: match[1], url: match[1] });
  }

  // maven(url = "url") or maven(url = 'url')
  const mavenUrlParamRegex = /\bmaven\s*\(\s*url\s*=\s*["']([^"']+)["']\s*\)/g;
  while ((match = mavenUrlParamRegex.exec(content)) !== null) {
    repos.push({ name: match[1], url: match[1] });
  }

  // maven { url = uri("url") } or maven { url = uri('url') }
  const mavenBlockUriRegex = /\bmaven\s*\{[^}]*url\s*=\s*uri\s*\(\s*["']([^"']+)["']\s*\)/g;
  while ((match = mavenBlockUriRegex.exec(content)) !== null) {
    repos.push({ name: match[1], url: match[1] });
  }

  // Groovy: maven { url 'url' } or maven { url "url" }
  const mavenBlockGroovyRegex = /\bmaven\s*\{[^}]*url\s+["']([^"']+)["']/g;
  while ((match = mavenBlockGroovyRegex.exec(content)) !== null) {
    repos.push({ name: match[1], url: match[1] });
  }

  return repos;
}
