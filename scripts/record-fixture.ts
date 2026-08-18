/**
 * Record one agent extraction as a replayable fixture.
 *
 * This is the bridge that lets a Claude session act as the agent tier on a
 * subscription instead of an API key: Claude reads the market, performs the
 * extraction, and records it here; the scan then replays it deterministically.
 * The payload is validated against THE SAME zod schema the production agent
 * extracts against, so a fixture that would not satisfy the agent cannot be
 * written at all.
 *
 *   npm run record-fixture -- <agent-name> <cache-key> <payload.json|->
 *
 * Example:
 *   npm run record-fixture -- resolution-parser 'resolution-parser:v1:0xabc' spec.json
 */

import { mkdirSync, readFileSync, writeFileSync } from 'node:fs';
import path from 'node:path';
import { AGENT_SCHEMAS } from '@/lib/agents/schemas';
import { FIXTURE_DIR, fixtureKey } from '@/lib/agents/llm';

function fail(message: string): never {
  console.error(`record-fixture: ${message}`);
  process.exit(1);
}

const [agentName, cacheKey, payloadPath] = process.argv.slice(2);

if (!agentName || !cacheKey || !payloadPath) {
  fail('usage: record-fixture <agent-name> <cache-key> <payload.json|->');
}

const schema = AGENT_SCHEMAS[agentName];
if (!schema) {
  fail(
    `unknown agent "${agentName}". Known LLM-backed agents: ${Object.keys(AGENT_SCHEMAS).join(', ')}.`,
  );
}

if (!cacheKey.startsWith(`${agentName}:`)) {
  fail(
    `cache key "${cacheKey}" does not belong to ${agentName} — keys are prefixed with the ` +
      'agent name, exactly as the agent builds them.',
  );
}

let rawText: string;
try {
  rawText = payloadPath === '-' ? readFileSync(0, 'utf8') : readFileSync(payloadPath, 'utf8');
} catch (err) {
  fail(`could not read payload: ${(err as Error).message}`);
}

let payload: unknown;
try {
  payload = JSON.parse(rawText);
} catch (err) {
  fail(`payload is not valid JSON: ${(err as Error).message}`);
}

const parsed = schema.safeParse(payload);
if (!parsed.success) {
  fail(
    `payload does not satisfy the ${agentName} schema — the production agent would reject it:\n` +
      parsed.error.issues
        .map((issue) => `  · ${issue.path.join('.') || '(root)'}: ${issue.message}`)
        .join('\n'),
  );
}

mkdirSync(FIXTURE_DIR, { recursive: true });
const file = path.join(FIXTURE_DIR, fixtureKey(cacheKey));
writeFileSync(file, `${JSON.stringify({ cacheKey, response: parsed.data }, null, 2)}\n`, 'utf8');
console.log(`record-fixture: wrote ${path.relative(process.cwd(), file)}`);
console.log('The next scan with fixtures present (or FORCE_LLM_REPLAY=1) will replay it.');
