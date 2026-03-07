# maven-central-mcp Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Build a TypeScript MCP server that provides Maven Central dependency intelligence via 4 tools, distributed as an npm package.

**Architecture:** Standalone Node.js process communicating via stdio MCP transport. Fetches data from Maven Central Search API and Metadata XML. Classifies version stability via regex patterns. No external dependencies beyond `@modelcontextprotocol/sdk` and `zod`.

**Tech Stack:** TypeScript, Node.js, `@modelcontextprotocol/sdk`, `zod/v4`, `vitest` for testing

---

### Task 1: Project scaffolding

**Files:**
- Create: `package.json`
- Create: `tsconfig.json`
- Create: `src/index.ts`

**Step 1: Initialize npm project and install dependencies**

Run:
```bash
cd /Users/krozov/dev/projects/mcp-maven-central
npm init -y
npm install @modelcontextprotocol/sdk zod
npm install -D typescript @types/node vitest
```

**Step 2: Configure package.json**

Set in `package.json`:
- `name`: `maven-central-mcp`
- `version`: `0.1.0`
- `type`: `module`
- `bin`: `{"maven-central-mcp": "./dist/index.js"}`
- `scripts.build`: `tsc`
- `scripts.test`: `vitest run`
- `scripts.dev`: `tsc --watch`

**Step 3: Create tsconfig.json**

```json
{
  "compilerOptions": {
    "target": "ES2022",
    "module": "Node16",
    "moduleResolution": "Node16",
    "outDir": "./dist",
    "rootDir": "./src",
    "strict": true,
    "esModuleInterop": true,
    "skipLibCheck": true,
    "declaration": true
  },
  "include": ["src"]
}
```

**Step 4: Create minimal src/index.ts entry point**

```typescript
import { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import { StdioServerTransport } from "@modelcontextprotocol/sdk/server/stdio.js";

const server = new McpServer({
  name: "maven-central-mcp",
  version: "0.1.0",
});

async function main() {
  const transport = new StdioServerTransport();
  await server.connect(transport);
  console.error("maven-central-mcp running on stdio");
}

main().catch((error) => {
  console.error("Fatal error:", error);
  process.exit(1);
});
```

**Step 5: Verify build**

Run: `npm run build`
Expected: Compiles without errors, `dist/index.js` created.

**Step 6: Init git and commit**

```bash
git init
git remote add origin git@github.com:kirich1409/maven-central-mcp.git
```

Create `.gitignore`:
```
node_modules/
dist/
```

```bash
git add .
git commit -m "chore: project scaffolding with MCP server entry point"
```

---

### Task 2: Version classification module

**Files:**
- Create: `src/version/classify.ts`
- Create: `src/version/compare.ts`
- Create: `src/version/types.ts`
- Test: `src/version/__tests__/classify.test.ts`
- Test: `src/version/__tests__/compare.test.ts`

**Step 1: Write types**

Create `src/version/types.ts`:

```typescript
export type StabilityType = "stable" | "rc" | "beta" | "alpha" | "milestone" | "snapshot";

export type StabilityFilter = "STABLE_ONLY" | "PREFER_STABLE" | "ALL";

export type UpgradeType = "major" | "minor" | "patch" | "none";

export interface VersionInfo {
  version: string;
  stability: StabilityType;
}
```

**Step 2: Write failing tests for classify**

Create `src/version/__tests__/classify.test.ts`:

```typescript
import { describe, it, expect } from "vitest";
import { classifyVersion } from "../classify.js";

describe("classifyVersion", () => {
  it("classifies stable versions", () => {
    expect(classifyVersion("3.5.11")).toBe("stable");
    expect(classifyVersion("1.0")).toBe("stable");
    expect(classifyVersion("2.0.0")).toBe("stable");
  });

  it("classifies snapshot versions", () => {
    expect(classifyVersion("1.0-SNAPSHOT")).toBe("snapshot");
    expect(classifyVersion("2.0.0-SNAPSHOT")).toBe("snapshot");
  });

  it("classifies alpha versions", () => {
    expect(classifyVersion("1.0-alpha-1")).toBe("alpha");
    expect(classifyVersion("1.0.0-alpha1")).toBe("alpha");
    expect(classifyVersion("1.0-a1")).toBe("alpha");
  });

  it("classifies beta versions", () => {
    expect(classifyVersion("1.0-beta-1")).toBe("beta");
    expect(classifyVersion("1.0.0-beta1")).toBe("beta");
    expect(classifyVersion("1.0-b1")).toBe("beta");
  });

  it("classifies RC versions", () => {
    expect(classifyVersion("1.0-RC1")).toBe("rc");
    expect(classifyVersion("1.0-rc-2")).toBe("rc");
    expect(classifyVersion("1.0-CR1")).toBe("rc");
  });

  it("classifies milestone versions", () => {
    expect(classifyVersion("1.0-M1")).toBe("milestone");
    expect(classifyVersion("1.0-milestone-2")).toBe("milestone");
  });
});
```

**Step 3: Run tests to verify they fail**

Run: `npx vitest run src/version/__tests__/classify.test.ts`
Expected: FAIL — module not found

**Step 4: Implement classifyVersion**

Create `src/version/classify.ts`:

```typescript
import type { StabilityType } from "./types.js";

const STABILITY_PATTERNS: [RegExp, StabilityType][] = [
  [/[-.]?SNAPSHOT$/i, "snapshot"],
  [/[-.](?:alpha|a)[-.]?\d*/i, "alpha"],
  [/[-.](?:beta|b)[-.]?\d*/i, "beta"],
  [/[-.](?:M|milestone)[-.]?\d*/i, "milestone"],
  [/[-.](?:RC|CR)[-.]?\d*/i, "rc"],
];

export function classifyVersion(version: string): StabilityType {
  for (const [pattern, stability] of STABILITY_PATTERNS) {
    if (pattern.test(version)) {
      return stability;
    }
  }
  return "stable";
}
```

**Step 5: Run tests to verify they pass**

Run: `npx vitest run src/version/__tests__/classify.test.ts`
Expected: All PASS

**Step 6: Write failing tests for compareVersions**

Create `src/version/__tests__/compare.test.ts`:

```typescript
import { describe, it, expect } from "vitest";
import { getUpgradeType } from "../compare.js";

describe("getUpgradeType", () => {
  it("detects major upgrade", () => {
    expect(getUpgradeType("1.0.0", "2.0.0")).toBe("major");
  });

  it("detects minor upgrade", () => {
    expect(getUpgradeType("1.0.0", "1.1.0")).toBe("minor");
  });

  it("detects patch upgrade", () => {
    expect(getUpgradeType("1.0.0", "1.0.1")).toBe("patch");
  });

  it("detects no upgrade", () => {
    expect(getUpgradeType("1.0.0", "1.0.0")).toBe("none");
  });

  it("handles two-segment versions", () => {
    expect(getUpgradeType("1.0", "2.0")).toBe("major");
    expect(getUpgradeType("1.0", "1.1")).toBe("minor");
  });
});
```

**Step 7: Run tests to verify they fail**

Run: `npx vitest run src/version/__tests__/compare.test.ts`
Expected: FAIL

**Step 8: Implement getUpgradeType**

Create `src/version/compare.ts`:

```typescript
import type { UpgradeType } from "./types.js";

function parseSegments(version: string): number[] {
  return version
    .replace(/[-+].*$/, "")
    .split(".")
    .map((s) => parseInt(s, 10) || 0);
}

export function getUpgradeType(current: string, latest: string): UpgradeType {
  const cur = parseSegments(current);
  const lat = parseSegments(latest);

  const maxLen = Math.max(cur.length, lat.length);
  while (cur.length < maxLen) cur.push(0);
  while (lat.length < maxLen) lat.push(0);

  if (lat[0] > cur[0]) return "major";
  if (lat[1] > cur[1]) return "minor";
  if (lat[2] > cur[2]) return "patch";
  return "none";
}
```

**Step 9: Run all tests**

Run: `npx vitest run`
Expected: All PASS

**Step 10: Commit**

```bash
git add src/version/
git commit -m "feat: version classification and comparison module"
```

---

### Task 3: Maven Central API client

**Files:**
- Create: `src/maven/client.ts`
- Create: `src/maven/types.ts`
- Test: `src/maven/__tests__/client.test.ts`

**Step 1: Write types**

Create `src/maven/types.ts`:

```typescript
export interface MavenSearchResponse {
  response: {
    numFound: number;
    docs: MavenArtifact[];
  };
}

export interface MavenArtifact {
  id: string;
  g: string;
  a: string;
  v: string;
  latestVersion: string;
  timestamp: number;
  versionCount: number;
}

export interface MavenMetadata {
  groupId: string;
  artifactId: string;
  versions: string[];
  latest?: string;
  release?: string;
  lastUpdated?: string;
}
```

**Step 2: Write failing tests for client**

Create `src/maven/__tests__/client.test.ts`:

```typescript
import { describe, it, expect, vi, beforeEach } from "vitest";
import { MavenCentralClient } from "../client.js";

describe("MavenCentralClient", () => {
  let client: MavenCentralClient;

  beforeEach(() => {
    client = new MavenCentralClient();
  });

  it("builds correct search URL", () => {
    const url = client.buildSearchUrl("io.ktor", "ktor-server-core", 10);
    expect(url).toBe(
      "https://search.maven.org/solrsearch/select?q=g:io.ktor+AND+a:ktor-server-core&rows=10&wt=json"
    );
  });

  it("builds correct metadata URL", () => {
    const url = client.buildMetadataUrl("io.ktor", "ktor-server-core");
    expect(url).toBe(
      "https://repo1.maven.org/maven2/io/ktor/ktor-server-core/maven-metadata.xml"
    );
  });

  it("parses metadata XML correctly", () => {
    const xml = `<?xml version="1.0" encoding="UTF-8"?>
<metadata>
  <groupId>io.ktor</groupId>
  <artifactId>ktor-server-core</artifactId>
  <versioning>
    <latest>3.1.1</latest>
    <release>3.1.1</release>
    <versions>
      <version>2.0.0</version>
      <version>3.0.0</version>
      <version>3.1.1</version>
    </versions>
    <lastUpdated>20250301</lastUpdated>
  </versioning>
</metadata>`;

    const result = client.parseMetadataXml(xml, "io.ktor", "ktor-server-core");
    expect(result.groupId).toBe("io.ktor");
    expect(result.artifactId).toBe("ktor-server-core");
    expect(result.versions).toEqual(["2.0.0", "3.0.0", "3.1.1"]);
    expect(result.latest).toBe("3.1.1");
    expect(result.release).toBe("3.1.1");
  });
});
```

**Step 3: Run tests to verify they fail**

Run: `npx vitest run src/maven/__tests__/client.test.ts`
Expected: FAIL

**Step 4: Implement MavenCentralClient**

Create `src/maven/client.ts`:

```typescript
import type { MavenMetadata, MavenSearchResponse } from "./types.js";

const SEARCH_BASE = "https://search.maven.org/solrsearch/select";
const REPO_BASE = "https://repo1.maven.org/maven2";

export class MavenCentralClient {
  buildSearchUrl(groupId: string, artifactId: string, rows: number): string {
    return `${SEARCH_BASE}?q=g:${groupId}+AND+a:${artifactId}&rows=${rows}&wt=json`;
  }

  buildMetadataUrl(groupId: string, artifactId: string): string {
    const groupPath = groupId.replace(/\./g, "/");
    return `${REPO_BASE}/${groupPath}/${artifactId}/maven-metadata.xml`;
  }

  async searchArtifact(groupId: string, artifactId: string): Promise<MavenSearchResponse> {
    const url = this.buildSearchUrl(groupId, artifactId, 1);
    const response = await fetch(url);
    if (!response.ok) {
      throw new Error(`Maven Central search failed: ${response.status} ${response.statusText}`);
    }
    return response.json() as Promise<MavenSearchResponse>;
  }

  async fetchMetadata(groupId: string, artifactId: string): Promise<MavenMetadata> {
    const url = this.buildMetadataUrl(groupId, artifactId);
    const response = await fetch(url);
    if (!response.ok) {
      throw new Error(`Maven Central metadata fetch failed: ${response.status} ${response.statusText}`);
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
```

**Step 5: Run tests to verify they pass**

Run: `npx vitest run src/maven/__tests__/client.test.ts`
Expected: All PASS

**Step 6: Commit**

```bash
git add src/maven/
git commit -m "feat: Maven Central API client with search and metadata fetching"
```

---

### Task 4: Tool — get_latest_version

**Files:**
- Create: `src/tools/get-latest-version.ts`
- Test: `src/tools/__tests__/get-latest-version.test.ts`
- Modify: `src/index.ts`

**Step 1: Write failing test**

Create `src/tools/__tests__/get-latest-version.test.ts`:

```typescript
import { describe, it, expect, vi } from "vitest";
import { getLatestVersionHandler } from "../get-latest-version.js";
import type { MavenCentralClient } from "../../maven/client.js";

function mockClient(versions: string[]): MavenCentralClient {
  return {
    fetchMetadata: vi.fn().mockResolvedValue({
      groupId: "io.ktor",
      artifactId: "ktor-server-core",
      versions,
      latest: versions[versions.length - 1],
      release: versions[versions.length - 1],
    }),
  } as unknown as MavenCentralClient;
}

describe("getLatestVersionHandler", () => {
  it("returns latest stable version with STABLE_ONLY filter", async () => {
    const client = mockClient(["1.0.0", "2.0.0-beta1", "2.0.0-RC1", "1.5.0"]);
    const result = await getLatestVersionHandler(client, {
      groupId: "io.ktor",
      artifactId: "ktor-server-core",
      stabilityFilter: "STABLE_ONLY",
    });
    expect(result.latestVersion).toBe("1.5.0");
    expect(result.stability).toBe("stable");
  });

  it("returns latest version with ALL filter", async () => {
    const client = mockClient(["1.0.0", "2.0.0-beta1", "2.0.0-RC1"]);
    const result = await getLatestVersionHandler(client, {
      groupId: "io.ktor",
      artifactId: "ktor-server-core",
      stabilityFilter: "ALL",
    });
    expect(result.latestVersion).toBe("2.0.0-RC1");
  });

  it("prefers stable with PREFER_STABLE filter", async () => {
    const client = mockClient(["1.0.0", "2.0.0-beta1"]);
    const result = await getLatestVersionHandler(client, {
      groupId: "io.ktor",
      artifactId: "ktor-server-core",
      stabilityFilter: "PREFER_STABLE",
    });
    expect(result.latestVersion).toBe("1.0.0");
    expect(result.stability).toBe("stable");
  });

  it("falls back to unstable with PREFER_STABLE when no stable exists", async () => {
    const client = mockClient(["1.0.0-alpha1", "2.0.0-beta1"]);
    const result = await getLatestVersionHandler(client, {
      groupId: "io.ktor",
      artifactId: "ktor-server-core",
      stabilityFilter: "PREFER_STABLE",
    });
    expect(result.latestVersion).toBe("2.0.0-beta1");
  });
});
```

**Step 2: Run test to verify it fails**

Run: `npx vitest run src/tools/__tests__/get-latest-version.test.ts`
Expected: FAIL

**Step 3: Implement handler**

Create `src/tools/get-latest-version.ts`:

```typescript
import { classifyVersion } from "../version/classify.js";
import type { StabilityFilter } from "../version/types.js";
import type { MavenCentralClient } from "../maven/client.js";

export interface GetLatestVersionInput {
  groupId: string;
  artifactId: string;
  stabilityFilter?: StabilityFilter;
}

export interface GetLatestVersionResult {
  groupId: string;
  artifactId: string;
  latestVersion: string;
  stability: string;
  allVersionsCount: number;
}

export async function getLatestVersionHandler(
  client: MavenCentralClient,
  input: GetLatestVersionInput,
): Promise<GetLatestVersionResult> {
  const metadata = await client.fetchMetadata(input.groupId, input.artifactId);
  const filter = input.stabilityFilter ?? "PREFER_STABLE";
  const versions = [...metadata.versions].reverse();

  let selected: string | undefined;

  if (filter === "ALL") {
    selected = versions[0];
  } else if (filter === "STABLE_ONLY") {
    selected = versions.find((v) => classifyVersion(v) === "stable");
    if (!selected) {
      throw new Error(
        `No stable version found for ${input.groupId}:${input.artifactId}`,
      );
    }
  } else {
    // PREFER_STABLE
    selected = versions.find((v) => classifyVersion(v) === "stable") ?? versions[0];
  }

  return {
    groupId: input.groupId,
    artifactId: input.artifactId,
    latestVersion: selected!,
    stability: classifyVersion(selected!),
    allVersionsCount: metadata.versions.length,
  };
}
```

**Step 4: Run tests to verify they pass**

Run: `npx vitest run src/tools/__tests__/get-latest-version.test.ts`
Expected: All PASS

**Step 5: Register tool in index.ts**

Update `src/index.ts` to import and register the tool with zod schema:

```typescript
import { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import { StdioServerTransport } from "@modelcontextprotocol/sdk/server/stdio.js";
import { z } from "zod";
import { MavenCentralClient } from "./maven/client.js";
import { getLatestVersionHandler } from "./tools/get-latest-version.js";

const server = new McpServer({
  name: "maven-central-mcp",
  version: "0.1.0",
});

const client = new MavenCentralClient();

server.tool(
  "get_latest_version",
  "Find the latest version of a Maven artifact with stability-aware selection",
  {
    groupId: z.string().describe("Maven group ID (e.g. io.ktor)"),
    artifactId: z.string().describe("Maven artifact ID (e.g. ktor-server-core)"),
    stabilityFilter: z
      .enum(["STABLE_ONLY", "PREFER_STABLE", "ALL"])
      .optional()
      .describe("Version stability filter (default: PREFER_STABLE)"),
  },
  async (params) => {
    const result = await getLatestVersionHandler(client, params);
    return { content: [{ type: "text", text: JSON.stringify(result, null, 2) }] };
  },
);

async function main() {
  const transport = new StdioServerTransport();
  await server.connect(transport);
  console.error("maven-central-mcp running on stdio");
}

main().catch((error) => {
  console.error("Fatal error:", error);
  process.exit(1);
});
```

**Step 6: Build and verify**

Run: `npm run build`
Expected: Compiles without errors

**Step 7: Commit**

```bash
git add src/tools/ src/index.ts
git commit -m "feat: add get_latest_version tool"
```

---

### Task 5: Tool — check_version_exists

**Files:**
- Create: `src/tools/check-version-exists.ts`
- Test: `src/tools/__tests__/check-version-exists.test.ts`
- Modify: `src/index.ts`

**Step 1: Write failing test**

Create `src/tools/__tests__/check-version-exists.test.ts`:

```typescript
import { describe, it, expect, vi } from "vitest";
import { checkVersionExistsHandler } from "../check-version-exists.js";
import type { MavenCentralClient } from "../../maven/client.js";

function mockClient(versions: string[]): MavenCentralClient {
  return {
    fetchMetadata: vi.fn().mockResolvedValue({
      groupId: "io.ktor",
      artifactId: "ktor-server-core",
      versions,
    }),
  } as unknown as MavenCentralClient;
}

describe("checkVersionExistsHandler", () => {
  it("returns true and stability for existing version", async () => {
    const client = mockClient(["1.0.0", "2.0.0-beta1"]);
    const result = await checkVersionExistsHandler(client, {
      groupId: "io.ktor",
      artifactId: "ktor-server-core",
      version: "1.0.0",
    });
    expect(result.exists).toBe(true);
    expect(result.stability).toBe("stable");
  });

  it("returns false for non-existing version", async () => {
    const client = mockClient(["1.0.0"]);
    const result = await checkVersionExistsHandler(client, {
      groupId: "io.ktor",
      artifactId: "ktor-server-core",
      version: "9.9.9",
    });
    expect(result.exists).toBe(false);
  });
});
```

**Step 2: Run test to verify it fails**

Run: `npx vitest run src/tools/__tests__/check-version-exists.test.ts`
Expected: FAIL

**Step 3: Implement handler**

Create `src/tools/check-version-exists.ts`:

```typescript
import { classifyVersion } from "../version/classify.js";
import type { MavenCentralClient } from "../maven/client.js";

export interface CheckVersionExistsInput {
  groupId: string;
  artifactId: string;
  version: string;
}

export interface CheckVersionExistsResult {
  groupId: string;
  artifactId: string;
  version: string;
  exists: boolean;
  stability?: string;
}

export async function checkVersionExistsHandler(
  client: MavenCentralClient,
  input: CheckVersionExistsInput,
): Promise<CheckVersionExistsResult> {
  const metadata = await client.fetchMetadata(input.groupId, input.artifactId);
  const exists = metadata.versions.includes(input.version);

  return {
    groupId: input.groupId,
    artifactId: input.artifactId,
    version: input.version,
    exists,
    stability: exists ? classifyVersion(input.version) : undefined,
  };
}
```

**Step 4: Run tests, register tool in index.ts, build, commit**

Register in `src/index.ts`:
```typescript
import { checkVersionExistsHandler } from "./tools/check-version-exists.js";

server.tool(
  "check_version_exists",
  "Verify a specific version exists and classify its stability",
  {
    groupId: z.string().describe("Maven group ID"),
    artifactId: z.string().describe("Maven artifact ID"),
    version: z.string().describe("Version to check"),
  },
  async (params) => {
    const result = await checkVersionExistsHandler(client, params);
    return { content: [{ type: "text", text: JSON.stringify(result, null, 2) }] };
  },
);
```

Run: `npx vitest run && npm run build`

```bash
git add src/
git commit -m "feat: add check_version_exists tool"
```

---

### Task 6: Tool — check_multiple_dependencies

**Files:**
- Create: `src/tools/check-multiple-dependencies.ts`
- Test: `src/tools/__tests__/check-multiple-dependencies.test.ts`
- Modify: `src/index.ts`

**Step 1: Write failing test**

Create `src/tools/__tests__/check-multiple-dependencies.test.ts`:

```typescript
import { describe, it, expect, vi } from "vitest";
import { checkMultipleDependenciesHandler } from "../check-multiple-dependencies.js";
import type { MavenCentralClient } from "../../maven/client.js";

describe("checkMultipleDependenciesHandler", () => {
  it("returns latest versions for multiple dependencies", async () => {
    const client = {
      fetchMetadata: vi.fn()
        .mockResolvedValueOnce({
          groupId: "io.ktor",
          artifactId: "ktor-server-core",
          versions: ["2.0.0", "3.0.0"],
        })
        .mockResolvedValueOnce({
          groupId: "org.jetbrains.kotlin",
          artifactId: "kotlin-stdlib",
          versions: ["1.9.0", "2.0.0"],
        }),
    } as unknown as MavenCentralClient;

    const result = await checkMultipleDependenciesHandler(client, {
      dependencies: [
        { groupId: "io.ktor", artifactId: "ktor-server-core" },
        { groupId: "org.jetbrains.kotlin", artifactId: "kotlin-stdlib" },
      ],
    });

    expect(result.results).toHaveLength(2);
    expect(result.results[0].latestVersion).toBe("3.0.0");
    expect(result.results[1].latestVersion).toBe("2.0.0");
  });
});
```

**Step 2: Implement handler**

Create `src/tools/check-multiple-dependencies.ts`:

```typescript
import { classifyVersion } from "../version/classify.js";
import type { MavenCentralClient } from "../maven/client.js";

interface Dependency {
  groupId: string;
  artifactId: string;
}

export interface CheckMultipleDependenciesInput {
  dependencies: Dependency[];
}

export interface DependencyResult {
  groupId: string;
  artifactId: string;
  latestVersion: string;
  stability: string;
  error?: string;
}

export interface CheckMultipleDependenciesResult {
  results: DependencyResult[];
}

export async function checkMultipleDependenciesHandler(
  client: MavenCentralClient,
  input: CheckMultipleDependenciesInput,
): Promise<CheckMultipleDependenciesResult> {
  const results = await Promise.all(
    input.dependencies.map(async (dep) => {
      try {
        const metadata = await client.fetchMetadata(dep.groupId, dep.artifactId);
        const versions = [...metadata.versions].reverse();
        const latest = versions.find((v) => classifyVersion(v) === "stable") ?? versions[0];
        return {
          groupId: dep.groupId,
          artifactId: dep.artifactId,
          latestVersion: latest,
          stability: classifyVersion(latest),
        };
      } catch (e) {
        return {
          groupId: dep.groupId,
          artifactId: dep.artifactId,
          latestVersion: "",
          stability: "",
          error: e instanceof Error ? e.message : String(e),
        };
      }
    }),
  );

  return { results };
}
```

**Step 3: Run tests, register in index.ts, build, commit**

Register in `src/index.ts`:
```typescript
import { checkMultipleDependenciesHandler } from "./tools/check-multiple-dependencies.js";

server.tool(
  "check_multiple_dependencies",
  "Bulk lookup of latest versions for a list of Maven dependencies",
  {
    dependencies: z.array(z.object({
      groupId: z.string().describe("Maven group ID"),
      artifactId: z.string().describe("Maven artifact ID"),
    })).describe("List of dependencies to check"),
  },
  async (params) => {
    const result = await checkMultipleDependenciesHandler(client, params);
    return { content: [{ type: "text", text: JSON.stringify(result, null, 2) }] };
  },
);
```

Run: `npx vitest run && npm run build`

```bash
git add src/
git commit -m "feat: add check_multiple_dependencies tool"
```

---

### Task 7: Tool — compare_dependency_versions

**Files:**
- Create: `src/tools/compare-dependency-versions.ts`
- Test: `src/tools/__tests__/compare-dependency-versions.test.ts`
- Modify: `src/index.ts`

**Step 1: Write failing test**

Create `src/tools/__tests__/compare-dependency-versions.test.ts`:

```typescript
import { describe, it, expect, vi } from "vitest";
import { compareDependencyVersionsHandler } from "../compare-dependency-versions.js";
import type { MavenCentralClient } from "../../maven/client.js";

describe("compareDependencyVersionsHandler", () => {
  it("compares current versions against latest", async () => {
    const client = {
      fetchMetadata: vi.fn()
        .mockResolvedValueOnce({
          groupId: "io.ktor",
          artifactId: "ktor-server-core",
          versions: ["2.0.0", "3.0.0", "3.1.0"],
        })
        .mockResolvedValueOnce({
          groupId: "org.slf4j",
          artifactId: "slf4j-api",
          versions: ["2.0.0", "2.0.1"],
        }),
    } as unknown as MavenCentralClient;

    const result = await compareDependencyVersionsHandler(client, {
      dependencies: [
        { groupId: "io.ktor", artifactId: "ktor-server-core", currentVersion: "2.0.0" },
        { groupId: "org.slf4j", artifactId: "slf4j-api", currentVersion: "2.0.0" },
      ],
    });

    expect(result.results).toHaveLength(2);
    expect(result.results[0].upgradeType).toBe("major");
    expect(result.results[0].latestVersion).toBe("3.1.0");
    expect(result.results[1].upgradeType).toBe("patch");
  });
});
```

**Step 2: Implement handler**

Create `src/tools/compare-dependency-versions.ts`:

```typescript
import { classifyVersion } from "../version/classify.js";
import { getUpgradeType } from "../version/compare.js";
import type { MavenCentralClient } from "../maven/client.js";

interface DependencyWithVersion {
  groupId: string;
  artifactId: string;
  currentVersion: string;
}

export interface CompareDependencyVersionsInput {
  dependencies: DependencyWithVersion[];
}

export interface CompareResult {
  groupId: string;
  artifactId: string;
  currentVersion: string;
  latestVersion: string;
  latestStability: string;
  upgradeType: string;
  upgradeAvailable: boolean;
  error?: string;
}

export interface CompareDependencyVersionsResult {
  results: CompareResult[];
  summary: { total: number; upgradeable: number; major: number; minor: number; patch: number };
}

export async function compareDependencyVersionsHandler(
  client: MavenCentralClient,
  input: CompareDependencyVersionsInput,
): Promise<CompareDependencyVersionsResult> {
  const results = await Promise.all(
    input.dependencies.map(async (dep) => {
      try {
        const metadata = await client.fetchMetadata(dep.groupId, dep.artifactId);
        const versions = [...metadata.versions].reverse();
        const latest = versions.find((v) => classifyVersion(v) === "stable") ?? versions[0];
        const upgradeType = getUpgradeType(dep.currentVersion, latest);

        return {
          groupId: dep.groupId,
          artifactId: dep.artifactId,
          currentVersion: dep.currentVersion,
          latestVersion: latest,
          latestStability: classifyVersion(latest),
          upgradeType,
          upgradeAvailable: upgradeType !== "none",
        };
      } catch (e) {
        return {
          groupId: dep.groupId,
          artifactId: dep.artifactId,
          currentVersion: dep.currentVersion,
          latestVersion: "",
          latestStability: "",
          upgradeType: "none",
          upgradeAvailable: false,
          error: e instanceof Error ? e.message : String(e),
        };
      }
    }),
  );

  const summary = {
    total: results.length,
    upgradeable: results.filter((r) => r.upgradeAvailable).length,
    major: results.filter((r) => r.upgradeType === "major").length,
    minor: results.filter((r) => r.upgradeType === "minor").length,
    patch: results.filter((r) => r.upgradeType === "patch").length,
  };

  return { results, summary };
}
```

**Step 3: Run tests, register in index.ts, build, commit**

Register in `src/index.ts`:
```typescript
import { compareDependencyVersionsHandler } from "./tools/compare-dependency-versions.js";

server.tool(
  "compare_dependency_versions",
  "Compare current dependency versions against latest available, showing upgrade type (major/minor/patch)",
  {
    dependencies: z.array(z.object({
      groupId: z.string().describe("Maven group ID"),
      artifactId: z.string().describe("Maven artifact ID"),
      currentVersion: z.string().describe("Currently used version"),
    })).describe("Dependencies with current versions to compare"),
  },
  async (params) => {
    const result = await compareDependencyVersionsHandler(client, params);
    return { content: [{ type: "text", text: JSON.stringify(result, null, 2) }] };
  },
);
```

Run: `npx vitest run && npm run build`

```bash
git add src/
git commit -m "feat: add compare_dependency_versions tool"
```

---

### Task 8: README and npm packaging

**Files:**
- Create: `README.md`
- Modify: `package.json` (add description, keywords, repository, license, files, engines)

**Step 1: Update package.json for publishing**

Add to `package.json`:
```json
{
  "description": "MCP server for Maven Central dependency intelligence",
  "keywords": ["mcp", "maven", "maven-central", "dependencies"],
  "repository": {
    "type": "git",
    "url": "https://github.com/kirich1409/maven-central-mcp"
  },
  "license": "MIT",
  "files": ["dist"],
  "engines": { "node": ">=18" }
}
```

Add shebang `#!/usr/bin/env node` as first line of `src/index.ts`.

**Step 2: Create README.md**

Include: description, quick start (npx, Claude Desktop config, VS Code config), tools table, license.

**Step 3: Build, test, commit**

Run: `npm run build && npx vitest run`

```bash
git add .
git commit -m "docs: add README and prepare for npm publishing"
```

---

### Task 9: Final integration test and push

**Step 1: Full build and test**

Run: `npm run build && npx vitest run`
Expected: All pass

**Step 2: Manual smoke test**

Run: `echo '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2024-11-05","capabilities":{},"clientInfo":{"name":"test","version":"1.0"}}}' | node dist/index.js`
Expected: JSON response with server capabilities

**Step 3: Push to remote**

```bash
git push -u origin main
```
