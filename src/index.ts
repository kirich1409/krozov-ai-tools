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
