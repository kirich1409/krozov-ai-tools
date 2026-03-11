export interface MavenDependency {
  groupId: string;
  artifactId: string;
  version: string | null;
  configuration: string;
  source: string;
}

const SCOPE_TO_CONFIG: Record<string, string> = {
  compile: "implementation",
  runtime: "runtimeOnly",
  test: "testImplementation",
  provided: "compileOnly",
  system: "compileOnly",
};

export function parseMavenDependencies(content: string): MavenDependency[] {
  const deps: MavenDependency[] = [];
  const depRegex = /<dependency>([\s\S]*?)<\/dependency>/g;
  let match: RegExpExecArray | null;

  while ((match = depRegex.exec(content)) !== null) {
    const block = match[1];
    const groupId = block.match(/<groupId>([^<]+)<\/groupId>/)?.[1]?.trim();
    const artifactId = block.match(/<artifactId>([^<]+)<\/artifactId>/)?.[1]?.trim();
    if (!groupId || !artifactId) continue;

    let version: string | null = block.match(/<version>([^<]+)<\/version>/)?.[1]?.trim() ?? null;
    if (version?.startsWith("${")) version = null;

    const scope = block.match(/<scope>([^<]+)<\/scope>/)?.[1]?.trim() ?? "compile";
    const configuration = SCOPE_TO_CONFIG[scope] ?? "implementation";

    deps.push({ groupId, artifactId, version, configuration, source: "pom.xml" });
  }

  return deps;
}
