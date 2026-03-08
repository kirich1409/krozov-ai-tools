import { describe, it, expect, vi, beforeEach } from "vitest";
import * as fs from "node:fs";
import { FileCache } from "../file-cache.js";

vi.mock("node:fs");

const mockedFs = vi.mocked(fs);

describe("FileCache", () => {
  const baseDir = "/tmp/test-cache";
  let cache: FileCache;

  beforeEach(() => {
    vi.resetAllMocks();
    cache = new FileCache(baseDir);
  });

  describe("get", () => {
    it("returns undefined when file does not exist", async () => {
      mockedFs.existsSync.mockReturnValue(false);

      const result = await cache.get("some-key");

      expect(result).toBeUndefined();
      expect(mockedFs.existsSync).toHaveBeenCalledWith(
        "/tmp/test-cache/some-key.json"
      );
    });

    it("returns cached data when file exists and no TTL", async () => {
      const entry = { data: { version: "1.0.0" }, timestamp: Date.now() };
      mockedFs.existsSync.mockReturnValue(true);
      mockedFs.readFileSync.mockReturnValue(JSON.stringify(entry));

      const result = await cache.get<{ version: string }>("my-key");

      expect(result).toEqual({ version: "1.0.0" });
      expect(mockedFs.readFileSync).toHaveBeenCalledWith(
        "/tmp/test-cache/my-key.json",
        "utf-8"
      );
    });

    it("returns cached data when TTL has not expired", async () => {
      const entry = { data: "hello", timestamp: Date.now() - 1000 };
      mockedFs.existsSync.mockReturnValue(true);
      mockedFs.readFileSync.mockReturnValue(JSON.stringify(entry));

      const result = await cache.get<string>("key", 5000);

      expect(result).toBe("hello");
    });

    it("returns undefined when TTL has expired", async () => {
      const entry = { data: "hello", timestamp: Date.now() - 10000 };
      mockedFs.existsSync.mockReturnValue(true);
      mockedFs.readFileSync.mockReturnValue(JSON.stringify(entry));

      const result = await cache.get<string>("key", 5000);

      expect(result).toBeUndefined();
    });

    it("returns undefined when file read throws", async () => {
      mockedFs.existsSync.mockReturnValue(true);
      mockedFs.readFileSync.mockImplementation(() => {
        throw new Error("read error");
      });

      const result = await cache.get("key");

      expect(result).toBeUndefined();
    });
  });

  describe("set", () => {
    it("creates directories and writes cache entry", async () => {
      vi.spyOn(Date, "now").mockReturnValue(1700000000000);

      await cache.set("my-key", { name: "test" });

      expect(mockedFs.mkdirSync).toHaveBeenCalledWith(baseDir, {
        recursive: true,
      });
      expect(mockedFs.writeFileSync).toHaveBeenCalledWith(
        "/tmp/test-cache/my-key.json",
        JSON.stringify({ data: { name: "test" }, timestamp: 1700000000000 })
      );
    });
  });
});
