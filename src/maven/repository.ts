import type { MavenMetadata } from "./types.js";

export interface MavenRepository {
  readonly name: string;
  readonly url: string;
  fetchMetadata(groupId: string, artifactId: string): Promise<MavenMetadata>;
}

export class HttpMavenRepository implements MavenRepository {
  readonly name: string;
  readonly url: string;

  constructor(name: string, url: string) {
    this.name = name;
    this.url = url.replace(/\/+$/, "");
  }

  buildMetadataUrl(groupId: string, artifactId: string): string {
    const groupPath = groupId.replace(/\./g, "/");
    return `${this.url}/${groupPath}/${artifactId}/maven-metadata.xml`;
  }

  async fetchMetadata(groupId: string, artifactId: string): Promise<MavenMetadata> {
    const url = this.buildMetadataUrl(groupId, artifactId);
    const response = await fetch(url, { signal: AbortSignal.timeout(10_000) });
    if (!response.ok) {
      throw new Error(`Metadata fetch failed from ${this.name}: ${response.status} ${response.statusText}`);
    }
    const xml = await response.text();
    return this.parseMetadataXml(xml, groupId, artifactId);
  }

  parseMetadataXml(xml: string, groupId: string, artifactId: string): MavenMetadata {
    const versions: string[] = [];
    const versionRegex = /<version>([^<]+)<\/version>/g;
    let match: RegExpExecArray | null;
    while ((match = versionRegex.exec(xml)) !== null) {
      versions.push(match[1]);
    }

    const latest = xml.match(/<latest>([^<]+)<\/latest>/)?.[1];
    const release = xml.match(/<release>([^<]+)<\/release>/)?.[1];
    const lastUpdated = xml.match(/<lastUpdated>([^<]+)<\/lastUpdated>/)?.[1];

    return { groupId, artifactId, versions, latest, release, lastUpdated };
  }
}

export const MAVEN_CENTRAL = new HttpMavenRepository(
  "Maven Central",
  "https://repo1.maven.org/maven2",
);

export const GOOGLE_MAVEN = new HttpMavenRepository(
  "Google",
  "https://maven.google.com",
);

export const GRADLE_PLUGIN_PORTAL = new HttpMavenRepository(
  "Gradle Plugin Portal",
  "https://plugins.gradle.org/m2",
);

export const WELL_KNOWN_URLS = new Set([
  MAVEN_CENTRAL.url,
  GOOGLE_MAVEN.url,
  GRADLE_PLUGIN_PORTAL.url,
]);
