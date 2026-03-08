export interface GradleDependency {
  groupId: string | null;
  artifactId: string | null;
  version: string | null;
  configuration: string;
  source: string;
  catalogRef?: string;
}

const CONFIGURATIONS = [
  "implementation", "api", "compileOnly", "runtimeOnly",
  "testImplementation", "testCompileOnly", "testRuntimeOnly",
  "kapt", "ksp", "annotationProcessor",
];

const CONFIG_PATTERN = CONFIGURATIONS.join("|");

export function parseGradleDependencies(content: string): GradleDependency[] {
  const deps: GradleDependency[] = [];

  const stringRegex = new RegExp(
    `\\b(${CONFIG_PATTERN})\\s*[( ]\\s*["']([^"':]+):([^"':]+)(?::([^"']+))?["']\\s*\\)?`,
    "g",
  );
  let match: RegExpExecArray | null;
  while ((match = stringRegex.exec(content)) !== null) {
    deps.push({
      groupId: match[2],
      artifactId: match[3],
      version: match[4] ?? null,
      configuration: match[1],
      source: "build.gradle.kts",
    });
  }

  const catalogRegex = new RegExp(
    `\\b(${CONFIG_PATTERN})\\s*\\(\\s*libs\\.([a-zA-Z0-9.]+)\\s*\\)`,
    "g",
  );
  while ((match = catalogRegex.exec(content)) !== null) {
    deps.push({
      groupId: null,
      artifactId: null,
      version: null,
      configuration: match[1],
      source: "build.gradle.kts",
      catalogRef: match[2],
    });
  }

  return deps;
}
