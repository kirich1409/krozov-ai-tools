export interface GradleDependency {
  groupId: string | null;
  artifactId: string | null;
  version: string | null;
  configuration: string;
  source: string;
  /**
   * Full dotted catalog ref including catalog name prefix, e.g. "libs.foo.bar" or
   * "testLibs.x". The first dot-segment is the catalog name; the rest is the alias path.
   * scan.ts splits on the first "." to identify catalog and alias.
   */
  catalogRef?: string;
}

export const PRODUCTION_CONFIGURATIONS = [
  "implementation", "api", "compileOnly", "runtimeOnly",
] as const;

export const NON_PRODUCTION_CONFIGURATIONS = [
  "testImplementation", "testCompileOnly", "testRuntimeOnly",
  "kapt", "ksp", "annotationProcessor",
] as const;

const CONFIG_PATTERN = [...PRODUCTION_CONFIGURATIONS, ...NON_PRODUCTION_CONFIGURATIONS].join("|");

/**
 * Returns true if the Gradle configuration name belongs to a test scope.
 *
 * Rule: a configuration is test-scope if its name starts with "test" (case-sensitive lowercase)
 * or if the camelCase word "Test" appears after a lowercase letter
 * (e.g. androidTestImplementation, commonTestImplementation, iosTestImplementation, kaptTest).
 *
 * Examples that return true:
 *   testImplementation, androidTestImplementation, commonTestImplementation,
 *   iosTestImplementation, kaptTest, jvmTestImplementation, testFixturesImplementation
 *
 * Examples that return false:
 *   implementation, api, kapt, ksp, annotationProcessor, classpath, plugin-dsl,
 *   compileOnly, runtimeOnly
 *
 * Note: testFixturesImplementation is classified as test-scope by this rule.
 *
 * Note: The Gradle dependency parser (CONFIG_PATTERN) only recognizes a fixed list of
 * configurations. Source-set variants like commonTestImplementation are not extracted
 * by the parser today, so this rule is broader than what the scanner currently emits.
 * The audit tool uses this function — not PRODUCTION_CONFIGURATIONS — as the production gate.
 */
export function isTestConfiguration(config: string): boolean {
  if (config.startsWith("test")) return true;
  // Match camelCase word boundary: lowercase letter followed by "Test"
  return /[a-z]Test/.test(config);
}

export function parseGradleDependencies(content: string, source: string = "build.gradle.kts"): GradleDependency[] {
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
      source,
    });
  }

  // Captures any catalog accessor: catalogName.alias — e.g. libs.foo.bar → "libs.foo.bar",
  // testLibs.x → "testLibs.x". The first dot-segment is the catalog name.
  const catalogRegex = new RegExp(
    `\\b(${CONFIG_PATTERN})\\s*\\(\\s*([a-zA-Z_][a-zA-Z0-9_]*)\\.([a-zA-Z0-9.]+)\\s*\\)`,
    "g",
  );
  while ((match = catalogRegex.exec(content)) !== null) {
    deps.push({
      groupId: null,
      artifactId: null,
      version: null,
      configuration: match[1],
      source,
      catalogRef: `${match[2]}.${match[3]}`,
    });
  }

  return deps;
}
