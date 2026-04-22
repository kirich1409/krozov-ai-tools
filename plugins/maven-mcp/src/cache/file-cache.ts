import { readFile, writeFile, mkdir, rename } from "node:fs/promises";
import * as os from "node:os";
import * as path from "node:path";
import { randomBytes } from "node:crypto";

const DEFAULT_CACHE_DIR = path.join(os.homedir(), ".cache", "maven-central-mcp");

interface CacheEntry<T> {
  data: T;
  timestamp: number;
}

// Keys look like path segments separated by "/". Each segment is restricted
// to filesystem-safe characters so newlines, "..", leading "/", and backslashes
// cannot escape the cache directory.
const KEY_SEGMENT = /^[a-zA-Z0-9._:-]+$/;

function validateKey(key: string): void {
  if (!key || key.length > 512) {
    throw new Error("FileCache: invalid cache key (empty or too long)");
  }
  if (key.startsWith("/") || key.includes("\0") || key.includes("\\")) {
    throw new Error(`FileCache: invalid cache key: ${key}`);
  }
  for (const segment of key.split("/")) {
    if (
      segment === "" ||
      segment === "." ||
      segment === ".." ||
      !KEY_SEGMENT.test(segment)
    ) {
      throw new Error(`FileCache: invalid cache key segment: "${segment}"`);
    }
  }
}

export class FileCache {
  // Coalesces concurrent misses for the same key — fetchFn runs exactly once
  // while any in-flight promise exists.
  private readonly inflight = new Map<string, Promise<unknown>>();

  constructor(private readonly baseDir: string = DEFAULT_CACHE_DIR) {}

  async get<T>(key: string, ttlMs?: number): Promise<T | undefined> {
    validateKey(key);
    try {
      const raw = await readFile(this.filePath(key), "utf-8");
      const entry: CacheEntry<T> = JSON.parse(raw);

      if (ttlMs !== undefined && Date.now() - entry.timestamp > ttlMs) {
        return undefined;
      }

      return entry.data;
    } catch {
      return undefined;
    }
  }

  async set<T>(key: string, data: T): Promise<void> {
    validateKey(key);
    const filePath = this.filePath(key);
    // Owner-only permissions: cache may hold GitHub tokens / API responses
    // that should not be readable by other users on shared systems.
    await mkdir(path.dirname(filePath), { recursive: true, mode: 0o700 });

    const entry: CacheEntry<T> = { data, timestamp: Date.now() };
    // Atomic write: write to a tmp file in the same directory, then rename.
    // Without this, a concurrent writer could observe a torn JSON blob.
    const tmpPath = `${filePath}.${process.pid}.${randomBytes(4).toString("hex")}.tmp`;
    await writeFile(tmpPath, JSON.stringify(entry), { mode: 0o600 });
    await rename(tmpPath, filePath);
  }

  /**
   * Returns cached value if present, otherwise calls fetchFn and caches the result.
   * Results that are null or undefined are NOT cached, so subsequent calls will retry.
   * Concurrent calls for the same key share a single fetchFn invocation.
   */
  async getOrFetch<T>(
    key: string,
    ttlMs: number | undefined,
    fetchFn: () => Promise<T>,
  ): Promise<T> {
    const cached = await this.get<T>(key, ttlMs);
    if (cached !== undefined) return cached;

    const existing = this.inflight.get(key) as Promise<T> | undefined;
    if (existing) return existing;

    const promise = (async () => {
      try {
        const data = await fetchFn();
        if (data !== null && data !== undefined) {
          await this.set(key, data);
        }
        return data;
      } finally {
        this.inflight.delete(key);
      }
    })();
    this.inflight.set(key, promise);
    return promise;
  }

  private filePath(key: string): string {
    return path.join(this.baseDir, `${key}.json`);
  }
}
