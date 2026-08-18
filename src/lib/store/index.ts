/**
 * Persistence.
 *
 * Zero-configuration first run: with no environment variables at all, the whole
 * application works against an in-memory store. That store is honestly labelled
 * as non-durable in the UI, on the health page, and in every API response — it
 * is never silently presented as persistence.
 *
 * Four concerns, no generic escape hatch. That constraint is what makes swapping
 * the backend safe.
 */

import type { Candidate } from '@/lib/engine/assess';

export interface Settings {
  bankrollUsd: number;
  kellyMultiplier: number;
  maxPositionFraction: number;
  minExpectedReturn: number;
  /** How many markets Tier 1 promotes to the expensive agent stage. */
  tier2Candidates: number;
  /** Wall-clock budget for one scan, ms. */
  scanTimeBudgetMs: number;
  /** Markets whose volume is below this are ignored entirely. */
  minVolumeUsd: number;
  /** Markets resolving sooner than this are ignored — no time to act. */
  minDaysToResolution: number;
  /** Markets resolving later than this are ignored — the estimate decays. */
  maxDaysToResolution: number;
}

export const DEFAULT_SETTINGS: Settings = {
  bankrollUsd: 1000,
  kellyMultiplier: 0.25,
  maxPositionFraction: 0.05,
  minExpectedReturn: 0.03,
  tier2Candidates: 25,
  scanTimeBudgetMs: 45_000,
  minVolumeUsd: 500,
  minDaysToResolution: 1,
  maxDaysToResolution: 120,
};

export interface ScanRecord {
  id: string;
  startedAt: number;
  finishedAt: number;
  /** Markets seen in Tier 1. */
  universeSize: number;
  /** Markets promoted to the agent stage. */
  promoted: number;
  /** Candidates produced, by status. */
  actionable: number;
  watch: number;
  abstain: number;
  /** Never silent: budget exhaustion and per-market failures land here. */
  errors: string[];
  storeKind: StoreKind;
  llmProviderKind: string;
}

export type StoreKind = 'memory' | 'supabase';

export interface Store {
  readonly kind: StoreKind;

  getSettings(): Promise<Settings>;
  saveSettings(settings: Settings): Promise<void>;

  listCandidates(limit?: number): Promise<Candidate[]>;
  getCandidate(id: string): Promise<Candidate | null>;
  findByFingerprint(fingerprint: string): Promise<Candidate | null>;
  upsertCandidate(candidate: Candidate): Promise<void>;

  recordScan(scan: ScanRecord): Promise<void>;
  listScans(limit?: number): Promise<ScanRecord[]>;
  lastScan(): Promise<ScanRecord | null>;
}

// ---------------------------------------------------------------------------

const MAX_CANDIDATES = 500;
const MAX_SCANS = 100;

interface MemoryState {
  settings: Settings;
  candidates: Map<string, Candidate>;
  scans: ScanRecord[];
}

/**
 * State is parked on globalThis so a warm serverless container keeps it across
 * invocations, with hard caps so it cannot grow without bound.
 */
const GLOBAL_KEY = '__sde_memory_store__';

function memoryState(): MemoryState {
  const g = globalThis as Record<string, unknown>;
  if (!g[GLOBAL_KEY]) {
    g[GLOBAL_KEY] = {
      settings: { ...DEFAULT_SETTINGS },
      candidates: new Map<string, Candidate>(),
      scans: [],
    } satisfies MemoryState;
  }
  return g[GLOBAL_KEY] as MemoryState;
}

export class MemoryStore implements Store {
  readonly kind = 'memory' as const;

  async getSettings(): Promise<Settings> {
    return { ...memoryState().settings };
  }

  async saveSettings(settings: Settings): Promise<void> {
    memoryState().settings = { ...settings };
  }

  async listCandidates(limit = 100): Promise<Candidate[]> {
    return [...memoryState().candidates.values()]
      .sort((a, b) => b.decisionAt - a.decisionAt)
      .slice(0, limit);
  }

  async getCandidate(id: string): Promise<Candidate | null> {
    return memoryState().candidates.get(id) ?? null;
  }

  async findByFingerprint(fingerprint: string): Promise<Candidate | null> {
    for (const c of memoryState().candidates.values()) {
      if (c.fingerprint === fingerprint) return c;
    }
    return null;
  }

  async upsertCandidate(candidate: Candidate): Promise<void> {
    const state = memoryState();
    state.candidates.set(candidate.id, candidate);
    if (state.candidates.size > MAX_CANDIDATES) {
      const oldest = [...state.candidates.values()].sort((a, b) => a.decisionAt - b.decisionAt);
      for (const c of oldest.slice(0, state.candidates.size - MAX_CANDIDATES)) {
        state.candidates.delete(c.id);
      }
    }
  }

  async recordScan(scan: ScanRecord): Promise<void> {
    const state = memoryState();
    state.scans.unshift(scan);
    if (state.scans.length > MAX_SCANS) state.scans.length = MAX_SCANS;
  }

  async listScans(limit = 20): Promise<ScanRecord[]> {
    return memoryState().scans.slice(0, limit);
  }

  async lastScan(): Promise<ScanRecord | null> {
    return memoryState().scans[0] ?? null;
  }
}

// ---------------------------------------------------------------------------

export function isSupabaseConfigured(env: NodeJS.ProcessEnv = process.env): boolean {
  return Boolean(
    env['NEXT_PUBLIC_SUPABASE_URL'] &&
      (env['SUPABASE_SERVICE_ROLE_KEY'] || env['NEXT_PUBLIC_SUPABASE_ANON_KEY']),
  );
}

let cached: Store | null = null;

export async function getStore(): Promise<Store> {
  if (cached) return cached;

  if (isSupabaseConfigured()) {
    try {
      // Dynamic import so the Supabase SDK is never bundled for memory-only runs.
      const { SupabaseStore } = await import('./supabase-store');
      const store = new SupabaseStore();
      if (await store.healthCheck()) {
        cached = store;
        return cached;
      }
      console.warn('[store] Supabase configured but unreachable — falling back to in-memory.');
    } catch (err) {
      console.warn('[store] Supabase init failed, using in-memory store:', err);
    }
  }

  cached = new MemoryStore();
  return cached;
}

/** Test hook. */
export function resetStoreCache(): void {
  cached = null;
}
