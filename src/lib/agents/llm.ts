/**
 * LLM providers.
 *
 * Three implementations behind one interface, resolved with the same
 * zero-configuration discipline the store uses:
 *
 *   - `anthropic`   — a real call. Used in production and when recording fixtures.
 *   - `replay`      — serves a recorded response from disk. This is what makes
 *                     the test suite deterministic even though production is not.
 *   - `unavailable` — no credentials and no fixture. Returns null, which the
 *                     agent layer turns into an abstention rather than a crash.
 *
 * The replay tier is not a testing afterthought; it was decided before the first
 * agent was written, because it constrains the interface shape. An agent that
 * streams, or that depends on conversation state, cannot be replayed — so agents
 * here are single-shot, schema-constrained extractions and nothing else.
 */

import { existsSync, mkdirSync, readFileSync, writeFileSync } from 'node:fs';
import path from 'node:path';
import Anthropic from '@anthropic-ai/sdk';
import { zodOutputFormat } from '@anthropic-ai/sdk/helpers/zod';
import type { ExtractRequest, ExtractResult, LlmProvider } from './types';

/** Extraction accuracy is the whole job here, so the strongest model is the default. */
export const AGENT_MODEL = 'claude-opus-5';

export const FIXTURE_DIR = path.resolve(process.cwd(), 'tests/fixtures/llm');

/**
 * FNV-1a. A filename needs to be stable and collision-resistant enough to key a
 * fixture, not cryptographically secure — and avoiding a crypto import keeps
 * this module usable from any runtime.
 */
export function fixtureKey(cacheKey: string): string {
  let hash = 0x811c9dc5;
  for (let i = 0; i < cacheKey.length; i++) {
    hash ^= cacheKey.charCodeAt(i);
    hash = Math.imul(hash, 0x01000193) >>> 0;
  }
  const slug = cacheKey
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, '-')
    .replace(/^-|-$/g, '')
    .slice(0, 60);
  return `${slug}.${hash.toString(36)}.json`;
}

// ---------------------------------------------------------------------------

export class ReplayProvider implements LlmProvider {
  readonly kind = 'replay' as const;

  constructor(private readonly dir: string = FIXTURE_DIR) {}

  async extract<T>(request: ExtractRequest<T>): Promise<ExtractResult<T>> {
    const file = path.join(this.dir, fixtureKey(request.cacheKey));
    if (!existsSync(file)) {
      return {
        data: null,
        replayed: true,
        detail: `No recorded response for "${request.cacheKey}". Record one with RECORD_LLM=1.`,
      };
    }
    try {
      const raw: unknown = JSON.parse(readFileSync(file, 'utf8'));
      const envelope = raw as { response?: unknown };
      // Validate the fixture against the CURRENT schema. A fixture recorded
      // before a schema change must fail loudly rather than silently supply a
      // shape the code no longer expects.
      const parsed = request.schema.safeParse(envelope.response);
      if (!parsed.success) {
        return {
          data: null,
          replayed: true,
          detail: `Recorded response for "${request.cacheKey}" no longer matches the schema: ${parsed.error.message}`,
        };
      }
      return { data: parsed.data, replayed: true, detail: `Replayed from ${file}.` };
    } catch (err) {
      return {
        data: null,
        replayed: true,
        detail: `Could not read fixture ${file}: ${(err as Error).message}`,
      };
    }
  }
}

export class UnavailableProvider implements LlmProvider {
  readonly kind = 'unavailable' as const;

  async extract<T>(request: ExtractRequest<T>): Promise<ExtractResult<T>> {
    return {
      data: null,
      replayed: false,
      detail:
        `No LLM provider configured, so "${request.cacheKey}" could not run. ` +
        'Set ANTHROPIC_API_KEY for live calls, or record fixtures for replay. ' +
        'The scan continues and this market abstains.',
    };
  }
}

export class AnthropicProvider implements LlmProvider {
  readonly kind = 'anthropic' as const;
  private readonly client: Anthropic;

  constructor(
    private readonly options: { record?: boolean; fixtureDir?: string; model?: string } = {},
  ) {
    this.client = new Anthropic();
  }

  async extract<T>(request: ExtractRequest<T>): Promise<ExtractResult<T>> {
    try {
      const response = await this.client.messages.parse({
        model: this.options.model ?? AGENT_MODEL,
        max_tokens: request.maxTokens ?? 8000,
        thinking: { type: 'adaptive' },
        output_config: {
          effort: request.effort ?? 'high',
          format: zodOutputFormat(request.schema),
        },
        system: request.system,
        messages: [{ role: 'user', content: request.user }],
      });

      if (response.stop_reason === 'refusal') {
        return {
          data: null,
          replayed: false,
          detail: `Model declined: ${response.stop_details?.explanation ?? 'no explanation given'}.`,
        };
      }

      const parsed = response.parsed_output as T | null;
      if (parsed === null || parsed === undefined) {
        return {
          data: null,
          replayed: false,
          detail: 'Model produced no output matching the schema.',
        };
      }

      if (this.options.record) this.record(request.cacheKey, parsed);

      return { data: parsed, replayed: false, detail: 'Live extraction.' };
    } catch (err) {
      // A failed agent call is an abstention, never a failed scan.
      if (err instanceof Anthropic.RateLimitError) {
        return { data: null, replayed: false, detail: 'Rate limited by the API.' };
      }
      if (err instanceof Anthropic.APIError) {
        return {
          data: null,
          replayed: false,
          detail: `API error ${err.status}: ${err.message}`,
        };
      }
      return { data: null, replayed: false, detail: `Call failed: ${(err as Error).message}` };
    }
  }

  private record(cacheKey: string, response: unknown): void {
    const dir = this.options.fixtureDir ?? FIXTURE_DIR;
    try {
      mkdirSync(dir, { recursive: true });
      writeFileSync(
        path.join(dir, fixtureKey(cacheKey)),
        `${JSON.stringify({ cacheKey, response }, null, 2)}\n`,
        'utf8',
      );
    } catch {
      // Recording is a developer convenience; failing to record must not fail
      // the call that produced a perfectly good answer.
    }
  }
}

let cached: LlmProvider | null = null;

/**
 * Zero-config resolution, in priority order:
 *   FORCE_LLM_REPLAY=1     → replay, always (what CI uses)
 *   ANTHROPIC_API_KEY set  → live, recording when RECORD_LLM=1
 *   fixtures on disk       → replay
 *   otherwise              → unavailable, and every market abstains
 */
export function getLlmProvider(env: NodeJS.ProcessEnv = process.env): LlmProvider {
  if (cached) return cached;

  if (env['FORCE_LLM_REPLAY'] === '1') {
    cached = new ReplayProvider();
    return cached;
  }

  const hasKey =
    typeof env['ANTHROPIC_API_KEY'] === 'string' && env['ANTHROPIC_API_KEY'].trim().length > 0;

  if (hasKey) {
    cached = new AnthropicProvider({ record: env['RECORD_LLM'] === '1' });
    return cached;
  }

  if (existsSync(FIXTURE_DIR)) {
    cached = new ReplayProvider();
    return cached;
  }

  cached = new UnavailableProvider();
  return cached;
}

/** Test hook. */
export function resetLlmProvider(): void {
  cached = null;
}
