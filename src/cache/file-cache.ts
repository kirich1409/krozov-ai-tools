import { readFile, writeFile, mkdir } from "node:fs/promises";
import * as os from "node:os";
import * as path from "node:path";

const DEFAULT_CACHE_DIR = path.join(os.homedir(), ".cache", "maven-central-mcp");

interface CacheEntry<T> {
  data: T;
  timestamp: number;
}

export class FileCache {
  constructor(private readonly baseDir: string = DEFAULT_CACHE_DIR) {}

  async get<T>(key: string, ttlMs?: number): Promise<T | undefined> {
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
    const filePath = this.filePath(key);
    await mkdir(path.dirname(filePath), { recursive: true });

    const entry: CacheEntry<T> = { data, timestamp: Date.now() };
    await writeFile(filePath, JSON.stringify(entry));
  }

  async getOrFetch<T>(
    key: string,
    ttlMs: number | undefined,
    fetchFn: () => Promise<T>,
  ): Promise<T> {
    const cached = await this.get<T>(key, ttlMs);
    if (cached !== undefined) return cached;

    const data = await fetchFn();
    if (data !== null && data !== undefined) {
      await this.set(key, data);
    }
    return data;
  }

  private filePath(key: string): string {
    return path.join(this.baseDir, `${key}.json`);
  }
}
