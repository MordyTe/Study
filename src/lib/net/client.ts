/**
 * Generic outbound HTTP client shared by every boundary adapter.
 *
 * This module deliberately knows nothing about any specific host. It cannot be
 * called without an `assertPath` callback, so an adapter physically cannot use
 * it to reach an endpoint its own allowlist has not approved. That inversion is
 * what lets `tests/no-execution-guard.test.ts` prove, by static scan, that every
 * outbound request in the codebase passes through an allowlist.
 *
 * Cross-cutting concerns live here rather than in each adapter, for the reason
 * the previous project recorded in ADR-003: a future adapter cannot forget a
 * rule it does not have to remember.
 */

export class HttpError extends Error {
  constructor(
    message: string,
    readonly status: number,
    readonly body: string,
    readonly correlationId: string,
  ) {
    super(message);
    this.name = 'HttpError';
  }
}

export interface AdapterStats {
  /** Total requests attempted, including retries. */
  requests: number;
  /** Requests that exhausted their retries and threw. */
  errors: number;
  lastLatencyMs: number | null;
  lastSuccessAt: number | null;
  lastErrorAt: number | null;
  lastError: string | null;
}

const STATS = new Map<string, AdapterStats>();

function statsFor(adapter: string): AdapterStats {
  let s = STATS.get(adapter);
  if (!s) {
    s = {
      requests: 0,
      errors: 0,
      lastLatencyMs: null,
      lastSuccessAt: null,
      lastErrorAt: null,
      lastError: null,
    };
    STATS.set(adapter, s);
  }
  return s;
}

export function getAdapterStats(adapter: string): AdapterStats {
  return { ...statsFor(adapter) };
}

export function listAdapterStats(): Record<string, AdapterStats> {
  const out: Record<string, AdapterStats> = {};
  for (const [name, s] of STATS) out[name] = { ...s };
  return out;
}

/** Test hook. Never called in production paths. */
export function resetAdapterStats(): void {
  STATS.clear();
}

/**
 * Status codes that will never succeed on retry. Retrying them wastes the
 * request budget and, on a rate-limited host, deepens the hole.
 */
const NON_RETRYABLE = new Set([400, 401, 403, 404, 405, 409, 422]);

export interface FetchOptions {
  /** Adapter name, used only for stats attribution. */
  adapter: string;
  /** Scheme + host, no trailing slash. */
  baseUrl: string;
  /** Path beginning with `/`. Passed to `assertPath` before anything else. */
  path: string;
  /**
   * The adapter's own allowlist assertion. Called as the first statement, before
   * the URL is even built, so a forbidden path cannot leak into a log line.
   */
  assertPath: (path: string) => void;
  query?: Record<string, string | number | boolean | undefined>;
  headers?: Record<string, string>;
  timeoutMs?: number;
  retries?: number;
  /** Injected for tests. Defaults to global fetch. */
  fetchImpl?: typeof fetch;
  /** Injected for tests so backoff does not actually sleep. */
  sleepImpl?: (ms: number) => Promise<void>;
}

const defaultSleep = (ms: number): Promise<void> =>
  new Promise((resolve) => setTimeout(resolve, ms));

let correlationCounter = 0;
function nextCorrelationId(): string {
  correlationCounter = (correlationCounter + 1) % 1_000_000;
  return `req_${correlationCounter.toString(36).padStart(4, '0')}`;
}

/**
 * GET a JSON document. Throws `HttpError` on a non-2xx response that survives
 * retries, and a plain `Error` on transport failure or timeout.
 */
export async function fetchJson<T>(options: FetchOptions): Promise<T> {
  // FIRST statement: the allowlist decides before anything else happens.
  options.assertPath(options.path);

  const {
    adapter,
    baseUrl,
    path,
    query,
    headers = {},
    timeoutMs = 12_000,
    retries = 2,
    fetchImpl = fetch,
    sleepImpl = defaultSleep,
  } = options;

  const url = new URL(baseUrl + path);
  for (const [key, value] of Object.entries(query ?? {})) {
    if (value !== undefined) url.searchParams.set(key, String(value));
  }

  const stats = statsFor(adapter);
  const correlationId = nextCorrelationId();
  let lastError: Error | null = null;

  for (let attempt = 0; attempt <= retries; attempt++) {
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), timeoutMs);
    const startedAt = Date.now();
    stats.requests += 1;

    try {
      const response = await fetchImpl(url.toString(), {
        method: 'GET',
        signal: controller.signal,
        headers: { accept: 'application/json', ...headers },
      });
      const latency = Date.now() - startedAt;

      if (!response.ok) {
        const body = (await response.text().catch(() => '')).slice(0, 512);
        const err = new HttpError(
          `${adapter} ${path} returned ${response.status}`,
          response.status,
          body,
          correlationId,
        );
        if (NON_RETRYABLE.has(response.status) || attempt === retries) throw err;
        lastError = err;
        // Rate limiting on these hosts carries no Retry-After header, so the
        // only safe response is exponential backoff with jitter.
        await sleepImpl(2 ** attempt * 250 + Math.floor(Math.random() * 200));
        continue;
      }

      const parsed = (await response.json()) as T;
      stats.lastLatencyMs = latency;
      stats.lastSuccessAt = Date.now();
      return parsed;
    } catch (err) {
      const error = err instanceof Error ? err : new Error(String(err));
      lastError = error;
      const isLastAttempt = attempt === retries;
      const isFatal = error instanceof HttpError && NON_RETRYABLE.has(error.status);
      if (isLastAttempt || isFatal) break;
      await sleepImpl(2 ** attempt * 250 + Math.floor(Math.random() * 200));
    } finally {
      clearTimeout(timer);
    }
  }

  stats.errors += 1;
  stats.lastErrorAt = Date.now();
  stats.lastError = lastError?.message ?? 'unknown error';
  throw lastError ?? new Error(`${adapter} ${path} failed with no recorded error`);
}
