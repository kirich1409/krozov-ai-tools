import { describe, it, expect, vi, beforeEach } from "vitest";
import * as fsp from "node:fs/promises";
import { FileCache } from "../file-cache.js";

vi.mock("node:fs/promises");

const mockedFsp = vi.mocked(fsp);

describe("FileCache", () => {
  const baseDir = "/fixtures/maven-cache";
  let cache: FileCache;

  beforeEach(() => {
    vi.resetAllMocks();
    cache = new FileCache(baseDir);
  });

  describe("get", () => {
    it("returns undefined when file does not exist", async () => {
      mockedFsp.readFile.mockRejectedValue(new Error("ENOENT"));

      const result = await cache.get("some-key");

      expect(result).toBeUndefined();
      expect(mockedFsp.readFile).toHaveBeenCalledWith(
        "/fixtures/maven-cache/some-key.json",
        "utf-8"
      );
    });

    it("returns cached data when file exists and no TTL", async () => {
      const entry = { data: { version: "1.0.0" }, timestamp: Date.now() };
      mockedFsp.readFile.mockResolvedValue(JSON.stringify(entry));

      const result = await cache.get<{ version: string }>("my-key");

      expect(result).toEqual({ version: "1.0.0" });
      expect(mockedFsp.readFile).toHaveBeenCalledWith(
        "/fixtures/maven-cache/my-key.json",
        "utf-8"
      );
    });

    it("returns cached data when TTL has not expired", async () => {
      const entry = { data: "hello", timestamp: Date.now() - 1000 };
      mockedFsp.readFile.mockResolvedValue(JSON.stringify(entry));

      const result = await cache.get<string>("key", 5000);

      expect(result).toBe("hello");
    });

    it("returns undefined when TTL has expired", async () => {
      const entry = { data: "hello", timestamp: Date.now() - 10000 };
      mockedFsp.readFile.mockResolvedValue(JSON.stringify(entry));

      const result = await cache.get<string>("key", 5000);

      expect(result).toBeUndefined();
    });

    it("returns undefined when file read throws", async () => {
      mockedFsp.readFile.mockRejectedValue(new Error("read error"));

      const result = await cache.get("key");

      expect(result).toBeUndefined();
    });
  });

  describe("set", () => {
    it("creates directories and writes cache entry atomically", async () => {
      vi.spyOn(Date, "now").mockReturnValue(1700000000000);
      mockedFsp.mkdir.mockResolvedValue(undefined);
      mockedFsp.writeFile.mockResolvedValue();
      mockedFsp.rename.mockResolvedValue();

      await cache.set("my-key", { name: "test" });

      expect(mockedFsp.mkdir).toHaveBeenCalledWith("/fixtures/maven-cache", {
        recursive: true,
        mode: 0o700,
      });

      // writeFile goes to a tmp file in the same directory…
      expect(mockedFsp.writeFile).toHaveBeenCalledWith(
        expect.stringMatching(/^\/fixtures\/maven-cache\/my-key\.json\.\d+\.[0-9a-f]+\.tmp$/),
        JSON.stringify({ data: { name: "test" }, timestamp: 1700000000000 }),
        { mode: 0o600 },
      );

      // …then rename to the final path.
      const tmpPath = mockedFsp.writeFile.mock.calls[0][0] as string;
      expect(mockedFsp.rename).toHaveBeenCalledWith(
        tmpPath,
        "/fixtures/maven-cache/my-key.json",
      );
    });

    it("creates nested directories for keys with path separators", async () => {
      vi.spyOn(Date, "now").mockReturnValue(1700000000000);
      mockedFsp.mkdir.mockResolvedValue(undefined);
      mockedFsp.writeFile.mockResolvedValue();
      mockedFsp.rename.mockResolvedValue();

      await cache.set("scm/io.ktor/ktor-core", { owner: "ktorio", repo: "ktor" });

      expect(mockedFsp.mkdir).toHaveBeenCalledWith("/fixtures/maven-cache/scm/io.ktor", {
        recursive: true,
        mode: 0o700,
      });
      expect(mockedFsp.writeFile).toHaveBeenCalledWith(
        expect.stringMatching(/^\/fixtures\/maven-cache\/scm\/io\.ktor\/ktor-core\.json\.\d+\.[0-9a-f]+\.tmp$/),
        expect.any(String),
        { mode: 0o600 },
      );
      expect(mockedFsp.rename).toHaveBeenCalledWith(
        expect.any(String),
        "/fixtures/maven-cache/scm/io.ktor/ktor-core.json",
      );
    });
  });

  describe("key validation", () => {
    it("rejects keys with traversal sequences", async () => {
      await expect(cache.get("../etc/passwd")).rejects.toThrow(/invalid cache key/);
      await expect(cache.set("a/../b", {})).rejects.toThrow(/invalid cache key/);
    });

    it("rejects absolute paths", async () => {
      await expect(cache.get("/absolute/key")).rejects.toThrow(/invalid cache key/);
    });

    it("rejects null bytes and backslashes", async () => {
      await expect(cache.get("bad\0key")).rejects.toThrow(/invalid cache key/);
      await expect(cache.get("bad\\key")).rejects.toThrow(/invalid cache key/);
    });

    it("rejects empty keys", async () => {
      await expect(cache.get("")).rejects.toThrow(/invalid cache key/);
    });

    it("accepts safe nested keys", async () => {
      mockedFsp.readFile.mockRejectedValue(new Error("ENOENT"));
      await expect(cache.get("scm/io.ktor/ktor-core")).resolves.toBeUndefined();
    });
  });

  describe("getOrFetch", () => {
    it("returns cached value without calling fetchFn", async () => {
      const entry = { data: { name: "cached" }, timestamp: Date.now() };
      mockedFsp.readFile.mockResolvedValue(JSON.stringify(entry));
      const fetchFn = vi.fn();

      const result = await cache.getOrFetch("key", undefined, fetchFn);

      expect(result).toEqual({ name: "cached" });
      expect(fetchFn).not.toHaveBeenCalled();
    });

    it("calls fetchFn and caches result on cache miss", async () => {
      mockedFsp.readFile.mockRejectedValue(new Error("ENOENT"));
      mockedFsp.mkdir.mockResolvedValue(undefined);
      mockedFsp.writeFile.mockResolvedValue();
      mockedFsp.rename.mockResolvedValue();
      const fetchFn = vi.fn().mockResolvedValue({ name: "fetched" });

      const result = await cache.getOrFetch("key", undefined, fetchFn);

      expect(result).toEqual({ name: "fetched" });
      expect(fetchFn).toHaveBeenCalledOnce();
      expect(mockedFsp.writeFile).toHaveBeenCalled();
      expect(mockedFsp.rename).toHaveBeenCalled();
    });

    it("does not cache null results from fetchFn", async () => {
      mockedFsp.readFile.mockRejectedValue(new Error("ENOENT"));
      const fetchFn = vi.fn().mockResolvedValue(null);

      const result = await cache.getOrFetch("key", undefined, fetchFn);

      expect(result).toBeNull();
      expect(mockedFsp.writeFile).not.toHaveBeenCalled();
    });

    it("coalesces concurrent misses (singleflight) so fetchFn runs once per key", async () => {
      mockedFsp.readFile.mockRejectedValue(new Error("ENOENT"));
      mockedFsp.mkdir.mockResolvedValue(undefined);
      mockedFsp.writeFile.mockResolvedValue();
      mockedFsp.rename.mockResolvedValue();

      // Manual deferred — Promise.withResolvers requires Node 22+, CI runs Node 20.
      let resolveShared!: (v: string) => void;
      const sharedPromise = new Promise<string>((r) => { resolveShared = r; });
      const fetchFn = vi.fn().mockImplementation(() => sharedPromise);

      const p1 = cache.getOrFetch("same-key", undefined, fetchFn);
      const p2 = cache.getOrFetch("same-key", undefined, fetchFn);
      const p3 = cache.getOrFetch("same-key", undefined, fetchFn);

      // Yield microtasks so each getOrFetch awaits its get() miss and reaches
      // the inflight check before we resolve the shared fetch.
      await Promise.resolve();
      await Promise.resolve();

      resolveShared("shared-value");
      const results = await Promise.all([p1, p2, p3]);

      expect(results).toEqual(["shared-value", "shared-value", "shared-value"]);
      expect(fetchFn).toHaveBeenCalledTimes(1);
    });

    it("releases the inflight slot after completion so subsequent calls re-fetch on miss", async () => {
      mockedFsp.readFile.mockRejectedValue(new Error("ENOENT"));
      mockedFsp.mkdir.mockResolvedValue(undefined);
      mockedFsp.writeFile.mockResolvedValue();
      mockedFsp.rename.mockResolvedValue();

      const fetchFn = vi.fn()
        .mockResolvedValueOnce("first")
        .mockResolvedValueOnce("second");

      await cache.getOrFetch("k", undefined, fetchFn);
      await cache.getOrFetch("k", undefined, fetchFn);

      expect(fetchFn).toHaveBeenCalledTimes(2);
    });
  });
});
