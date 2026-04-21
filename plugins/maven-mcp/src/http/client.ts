import { PACKAGE_VERSION } from "../version.js";

export const USER_AGENT = `maven-central-mcp/${PACKAGE_VERSION}`;

export interface FetchOptions extends Omit<RequestInit, "signal"> {
  /** Abort after this many ms. Default 10_000. */
  timeoutMs?: number;
  /** Additional retry attempts on transient failures (5xx, 429, network). Default 1. */
  retries?: number;
}

function isRetriableStatus(status: number): boolean {
  return status === 429 || (status >= 500 && status < 600);
}

function isRetriableError(err: unknown): boolean {
  if (!(err instanceof Error)) return false;
  // AbortSignal.timeout rejects with a TimeoutError; retrying after a timeout
  // usually just wastes more time, so we don't.
  if (err.name === "TimeoutError" || err.name === "AbortError") return false;
  return true;
}

function backoffDelay(): number {
  return 200 + Math.floor(Math.random() * 300);
}

/**
 * fetch wrapper that adds a User-Agent, enforces a timeout, and retries
 * transient failures (5xx, 429, network errors) once by default. Returns the
 * final Response — callers still decide how to treat non-ok responses.
 */
export async function fetchWithRetry(
  url: string,
  options: FetchOptions = {},
): Promise<Response> {
  // Validate the URL at the entry point. Many callers pass a URL that was
  // ultimately derived from file content (e.g. <scm><url> in a pom.xml);
  // restrict to http(s) so a malicious POM cannot point us at `file:`,
  // `data:`, or other non-network schemes.
  const parsed = new URL(url);
  if (parsed.protocol !== "http:" && parsed.protocol !== "https:") {
    throw new Error(
      `fetchWithRetry: unsupported URL protocol "${parsed.protocol}"`,
    );
  }

  const { timeoutMs = 10_000, retries = 1, headers, ...rest } = options;
  const mergedHeaders: Record<string, string> = {
    "User-Agent": USER_AGENT,
    ...(headers as Record<string, string> | undefined),
  };

  let attempt = 0;
  for (;;) {
    try {
      const response = await fetch(url, {
        ...rest,
        headers: mergedHeaders,
        signal: AbortSignal.timeout(timeoutMs),
      });
      if (response.ok || attempt >= retries || !isRetriableStatus(response.status)) {
        return response;
      }
    } catch (err) {
      if (attempt >= retries || !isRetriableError(err)) throw err;
    }
    attempt++;
    await new Promise((resolve) => setTimeout(resolve, backoffDelay()));
  }
}
