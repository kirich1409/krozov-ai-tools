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
    it("creates directories and writes cache entry", async () => {
      vi.spyOn(Date, "now").mockReturnValue(1700000000000);
      mockedFsp.mkdir.mockResolvedValue(undefined);
      mockedFsp.writeFile.mockResolvedValue();

      await cache.set("my-key", { name: "test" });

      expect(mockedFsp.mkdir).toHaveBeenCalledWith("/fixtures/maven-cache", {
        recursive: true,
        mode: 0o700,
      });
      expect(mockedFsp.writeFile).toHaveBeenCalledWith(
        "/fixtures/maven-cache/my-key.json",
        JSON.stringify({ data: { name: "test" }, timestamp: 1700000000000 }),
        { mode: 0o600 },
      );
    });
    it("creates nested directories for keys with path separators", async () => {
      vi.spyOn(Date, "now").mockReturnValue(1700000000000);
      mockedFsp.mkdir.mockResolvedValue(undefined);
      mockedFsp.writeFile.mockResolvedValue();

      await cache.set("scm/io.ktor/ktor-core", { owner: "ktorio", repo: "ktor" });

      expect(mockedFsp.mkdir).toHaveBeenCalledWith("/fixtures/maven-cache/scm/io.ktor", {
        recursive: true,
        mode: 0o700,
      });
      expect(mockedFsp.writeFile).toHaveBeenCalledWith(
        "/fixtures/maven-cache/scm/io.ktor/ktor-core.json",
        expect.any(String),
        { mode: 0o600 },
      );
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
      const fetchFn = vi.fn().mockResolvedValue({ name: "fetched" });

      const result = await cache.getOrFetch("key", undefined, fetchFn);

      expect(result).toEqual({ name: "fetched" });
      expect(fetchFn).toHaveBeenCalledOnce();
      expect(mockedFsp.writeFile).toHaveBeenCalled();
    });

    it("does not cache null results from fetchFn", async () => {
      mockedFsp.readFile.mockRejectedValue(new Error("ENOENT"));
      const fetchFn = vi.fn().mockResolvedValue(null);

      const result = await cache.getOrFetch("key", undefined, fetchFn);

      expect(result).toBeNull();
      expect(mockedFsp.writeFile).not.toHaveBeenCalled();
    });
  });
});
