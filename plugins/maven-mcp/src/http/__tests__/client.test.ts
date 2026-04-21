import { describe, it, expect, vi, afterEach } from "vitest";
import { fetchWithRetry, USER_AGENT } from "../client.js";

describe("fetchWithRetry", () => {
  const originalFetch = globalThis.fetch;

  afterEach(() => {
    vi.restoreAllMocks();
    globalThis.fetch = originalFetch;
  });

  it("attaches a default User-Agent", async () => {
    const fetchMock = vi.fn(async () =>
      new Response("ok", { status: 200 }),
    );
    vi.stubGlobal("fetch", fetchMock);

    await fetchWithRetry("https://example.com");

    const init = fetchMock.mock.calls[0][1] as RequestInit;
    expect((init.headers as Record<string, string>)["User-Agent"]).toBe(USER_AGENT);
    expect(USER_AGENT).toMatch(/^maven-central-mcp\/\d+\.\d+\.\d+/);
  });

  it("preserves caller-provided headers while injecting User-Agent", async () => {
    const fetchMock = vi.fn(async () => new Response("ok", { status: 200 }));
    vi.stubGlobal("fetch", fetchMock);

    await fetchWithRetry("https://example.com", {
      headers: { Accept: "application/json" },
    });

    const init = fetchMock.mock.calls[0][1] as RequestInit;
    const headers = init.headers as Record<string, string>;
    expect(headers["Accept"]).toBe("application/json");
    expect(headers["User-Agent"]).toBe(USER_AGENT);
  });

  it("retries once on 5xx responses", async () => {
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(new Response("fail", { status: 503 }))
      .mockResolvedValueOnce(new Response("ok", { status: 200 }));
    vi.stubGlobal("fetch", fetchMock);

    const res = await fetchWithRetry("https://example.com");

    expect(res.ok).toBe(true);
    expect(fetchMock).toHaveBeenCalledTimes(2);
  });

  it("retries once on 429 rate limit", async () => {
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(new Response("slow down", { status: 429 }))
      .mockResolvedValueOnce(new Response("ok", { status: 200 }));
    vi.stubGlobal("fetch", fetchMock);

    const res = await fetchWithRetry("https://example.com");

    expect(res.ok).toBe(true);
    expect(fetchMock).toHaveBeenCalledTimes(2);
  });

  it("does not retry on 4xx (non-429) responses", async () => {
    const fetchMock = vi.fn().mockResolvedValue(new Response("nope", { status: 404 }));
    vi.stubGlobal("fetch", fetchMock);

    const res = await fetchWithRetry("https://example.com");

    expect(res.status).toBe(404);
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });

  it("retries once on network errors", async () => {
    const fetchMock = vi.fn()
      .mockRejectedValueOnce(new TypeError("network"))
      .mockResolvedValueOnce(new Response("ok", { status: 200 }));
    vi.stubGlobal("fetch", fetchMock);

    const res = await fetchWithRetry("https://example.com");

    expect(res.ok).toBe(true);
    expect(fetchMock).toHaveBeenCalledTimes(2);
  });

  it("does not retry on AbortSignal timeouts", async () => {
    const timeoutErr = Object.assign(new Error("timed out"), { name: "TimeoutError" });
    const fetchMock = vi.fn().mockRejectedValue(timeoutErr);
    vi.stubGlobal("fetch", fetchMock);

    await expect(fetchWithRetry("https://example.com")).rejects.toMatchObject({
      name: "TimeoutError",
    });
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });

  it("stops after exceeding retries", async () => {
    const fetchMock = vi.fn().mockResolvedValue(new Response("fail", { status: 503 }));
    vi.stubGlobal("fetch", fetchMock);

    const res = await fetchWithRetry("https://example.com", { retries: 2 });

    expect(res.status).toBe(503);
    expect(fetchMock).toHaveBeenCalledTimes(3);
  });

  it("rejects non-http(s) URLs without issuing a network request", async () => {
    const fetchMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock);

    await expect(fetchWithRetry("file:///etc/passwd")).rejects.toThrow(
      /unsupported URL protocol "file:"/,
    );
    await expect(fetchWithRetry("data:text/plain,hi")).rejects.toThrow(
      /unsupported URL protocol "data:"/,
    );
    expect(fetchMock).not.toHaveBeenCalled();
  });
});
