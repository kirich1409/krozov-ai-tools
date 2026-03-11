export interface RepositoryConfig {
  name: string;
  url: string;
}

export interface DiscoveryResult {
  repositories: RepositoryConfig[];
  buildSystem: "gradle" | "maven" | "unknown";
  projectRoot: string;
}
