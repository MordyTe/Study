/**
 * The agent registry and its middleware.
 *
 * Registration is a hand-written array, not a dynamic glob. Import order is
 * therefore fixed, which makes the pipeline's output order deterministic, and
 * adding an agent is a diff a reviewer can see.
 *
 * `runAgent` is the slot where cross-cutting rules live, for the reason the
 * previous project recorded in ADR-003: a future agent cannot forget a rule it
 * does not have to remember. Four rules are enforced here for every agent, on
 * every run:
 *
 *   1. **No-lookahead.** Any claim observed after `decisionAt` is dropped. This
 *      is the invariant that makes a backtest over recorded evidence mean
 *      something; without it, historical results silently include the future.
 *   2. **Failure is an abstention.** A thrown agent contributes nothing and the
 *      pipeline continues. One broken agent never fails a scan.
 *   3. **Timeout.** An agent that hangs cannot hold the scan budget hostage.
 *   4. **Attribution.** Every run is recorded with name, version, duration and
 *      outcome, so a bundle explains how it was assembled.
 */

import { resolutionParser } from './resolution-parser';
import type { Agent, AgentContext, AgentRun, Claim, EvidenceBundle } from './types';

/**
 * The production agent list. Order is meaningful: later agents see what earlier
 * ones produced, and the resolution spec gates everything downstream of it.
 */
export const AGENTS: Agent[] = [resolutionParser];

export const AGENT_BY_NAME = new Map(AGENTS.map((a) => [a.name, a]));

export function listAgentMeta(): Array<Pick<Agent, 'name' | 'version' | 'displayName' | 'description'>> {
  return AGENTS.map(({ name, version, displayName, description }) => ({
    name,
    version,
    displayName,
    description,
  }));
}

export const DEFAULT_AGENT_TIMEOUT_MS = 90_000;

function withTimeout<T>(promise: Promise<T>, ms: number, label: string): Promise<T> {
  return new Promise<T>((resolve, reject) => {
    const timer = setTimeout(() => reject(new Error(`${label} exceeded ${ms}ms`)), ms);
    promise.then(
      (value) => {
        clearTimeout(timer);
        resolve(value);
      },
      (err: unknown) => {
        clearTimeout(timer);
        reject(err instanceof Error ? err : new Error(String(err)));
      },
    );
  });
}

/**
 * Drop anything the agent claims to have observed after the decision instant.
 * Returns the surviving claims and a note naming what was removed, because a
 * silently-dropped claim is indistinguishable from an agent that found nothing.
 */
function enforceNoLookahead(
  claims: Claim[],
  decisionAt: number,
  agentName: string,
): { kept: Claim[]; notes: string[] } {
  const kept: Claim[] = [];
  let dropped = 0;
  for (const claim of claims) {
    if (claim.observedAt > decisionAt) dropped += 1;
    else kept.push(claim);
  }
  return {
    kept,
    notes:
      dropped > 0
        ? [
            `${agentName}: dropped ${dropped} claim(s) observed after the decision time ` +
              `(no-lookahead invariant).`,
          ]
        : [],
  };
}

/**
 * Run one agent and merge its patch into the bundle. Never throws.
 */
export async function runAgent(
  agent: Agent,
  bundle: EvidenceBundle,
  context: AgentContext,
  timeoutMs: number = DEFAULT_AGENT_TIMEOUT_MS,
): Promise<EvidenceBundle> {
  const startedAt = Date.now();

  let patch: Partial<EvidenceBundle> | null = null;
  let run: AgentRun;

  try {
    patch = await withTimeout(agent.run(bundle, context), timeoutMs, agent.name);
    run = {
      name: agent.name,
      version: agent.version,
      ok: true,
      durationMs: Date.now() - startedAt,
      detail: patch ? 'contributed' : 'contributed nothing',
    };
  } catch (err) {
    run = {
      name: agent.name,
      version: agent.version,
      ok: false,
      durationMs: Date.now() - startedAt,
      detail: (err as Error).message,
    };
    return { ...bundle, agentsRun: [...bundle.agentsRun, run] };
  }

  if (!patch) return { ...bundle, agentsRun: [...bundle.agentsRun, run] };

  const incoming = (patch.claims ?? []).map((c) => ({ ...c, fetchedAt: c.fetchedAt ?? Date.now() }));
  const { kept, notes: lookaheadNotes } = enforceNoLookahead(
    incoming,
    bundle.decisionAt,
    agent.name,
  );

  // A point estimate is evidence too, and is held to the same invariant.
  const estimate =
    patch.pointEstimate && patch.pointEstimate.observedAt > bundle.decisionAt
      ? null
      : (patch.pointEstimate ?? bundle.pointEstimate);
  const estimateNote =
    patch.pointEstimate && patch.pointEstimate.observedAt > bundle.decisionAt
      ? [`${agent.name}: rejected a point estimate observed after the decision time.`]
      : [];

  return {
    ...bundle,
    spec: patch.spec ?? bundle.spec,
    pointEstimate: estimate,
    claims: [...bundle.claims, ...kept],
    observations: [...bundle.observations, ...(patch.observations ?? [])],
    notes: [...bundle.notes, ...(patch.notes ?? []), ...lookaheadNotes, ...estimateNote],
    agentsRun: [...bundle.agentsRun, run],
  };
}

/** Run the whole registry in order, threading the bundle through. */
export async function runAllAgents(
  bundle: EvidenceBundle,
  context: AgentContext,
  timeoutMs: number = DEFAULT_AGENT_TIMEOUT_MS,
): Promise<EvidenceBundle> {
  let current = bundle;
  for (const agent of AGENTS) {
    current = await runAgent(agent, current, context, timeoutMs);
  }
  return current;
}
