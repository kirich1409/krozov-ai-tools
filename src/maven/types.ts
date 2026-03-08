export interface MavenMetadata {
  groupId: string;
  artifactId: string;
  versions: string[];
  latest?: string;
  release?: string;
  lastUpdated?: string;
}
