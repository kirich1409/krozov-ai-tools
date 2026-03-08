import * as fs from "node:fs";
import * as path from "node:path";

interface CacheEntry<T> {
  data: T;
  timestamp: number;
}

export class FileCache {
  constructor(private readonly baseDir: string) {}

  async get<T>(key: string, ttlMs?: number): Promise<T | undefined> {
    const filePath = this.filePath(key);

    if (!fs.existsSync(filePath)) {
      return undefined;
    }

    try {
      const raw = fs.readFileSync(filePath, "utf-8");
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
    fs.mkdirSync(this.baseDir, { recursive: true });

    const entry: CacheEntry<T> = { data, timestamp: Date.now() };
    fs.writeFileSync(this.filePath(key), JSON.stringify(entry));
  }

  private filePath(key: string): string {
    return path.join(this.baseDir, `${key}.json`);
  }
}
