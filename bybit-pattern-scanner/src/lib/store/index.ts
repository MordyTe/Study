/**
 * Storage abstraction.
 *
 * The app ships usable with ZERO configuration: without Supabase credentials it
 * uses a process-local in-memory store. Add Supabase env vars and the same
 * interface transparently persists across deploys and serverless invocations.
 */

import type { Opportunity } from '@/lib/engine/opportunity';
import { DEFAULT_SETTINGS, mergeSettings, type Settings } from '@/lib/config/settings';

export interface ScanRecord {
  id: string;
  startedAt: number;
  finishedAt: number;
  instrumentsScanned: number;
  candidatesEvaluated: number;
  confirmed: number;
  forming: number;
  alertsSent: number;
  errors: string[];
  durationMs: number;
}

export interface AlertDelivery {
  id: string;
  opportunityId: string;
  idempotencyKey: string;
  channel: 'telegram';
  status: 'sent' | 'failed' | 'skipped';
  detail: string;
  at: number;
}

export interface Store {
  readonly kind: 'memory' | 'supabase';
  getSettings(): Promise<Settings>;
  saveSettings(settings: Settings): Promise<void>;

  listOpportunities(limit?: number): Promise<Opportunity[]>;
  getOpportunity(id: string): Promise<Opportunity | null>;
  findByFingerprint(fingerprint: string): Promise<Opportunity | null>;
  upsertOpportunity(opp: Opportunity): Promise<void>;

  recordScan(scan: ScanRecord): Promise<void>;
  listScans(limit?: number): Promise<ScanRecord[]>;
  lastScan(): Promise<ScanRecord | null>;

  recordDelivery(delivery: AlertDelivery): Promise<void>;
  listDeliveries(limit?: number): Promise<AlertDelivery[]>;
  hasDelivery(idempotencyKey: string): Promise<boolean>;
}

// ── In-memory implementation ──────────────────────────────────────────────
// Module-scope so it survives across requests in a warm serverless container.

interface MemoryState {
  settings: Settings;
  opportunities: Map<string, Opportunity>;
  fingerprints: Map<string, string>;
  scans: ScanRecord[];
  deliveries: AlertDelivery[];
}

const globalKey = '__bybit_scanner_memory_store__';
type GlobalWithStore = typeof globalThis & { [globalKey]?: MemoryState };

function memoryState(): MemoryState {
  const g = globalThis as GlobalWithStore;
  if (!g[globalKey]) {
    g[globalKey] = {
      settings: { ...DEFAULT_SETTINGS },
      opportunities: new Map(),
      fingerprints: new Map(),
      scans: [],
      deliveries: [],
    };
  }
  return g[globalKey]!;
}

const MAX_OPPORTUNITIES = 500;
const MAX_SCANS = 100;
const MAX_DELIVERIES = 300;

export class MemoryStore implements Store {
  readonly kind = 'memory' as const;

  async getSettings(): Promise<Settings> {
    return memoryState().settings;
  }

  async saveSettings(settings: Settings): Promise<void> {
    memoryState().settings = settings;
  }

  async listOpportunities(limit = 200): Promise<Opportunity[]> {
    return [...memoryState().opportunities.values()]
      .sort((a, b) => b.detectedAt - a.detectedAt)
      .slice(0, limit);
  }

  async getOpportunity(id: string): Promise<Opportunity | null> {
    return memoryState().opportunities.get(id) ?? null;
  }

  async findByFingerprint(fingerprint: string): Promise<Opportunity | null> {
    const state = memoryState();
    const id = state.fingerprints.get(fingerprint);
    return id ? (state.opportunities.get(id) ?? null) : null;
  }

  async upsertOpportunity(opp: Opportunity): Promise<void> {
    const state = memoryState();
    state.opportunities.set(opp.id, opp);
    state.fingerprints.set(opp.fingerprint, opp.id);

    if (state.opportunities.size > MAX_OPPORTUNITIES) {
      const sorted = [...state.opportunities.values()].sort((a, b) => a.detectedAt - b.detectedAt);
      for (const stale of sorted.slice(0, state.opportunities.size - MAX_OPPORTUNITIES)) {
        state.opportunities.delete(stale.id);
        state.fingerprints.delete(stale.fingerprint);
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

  async recordDelivery(delivery: AlertDelivery): Promise<void> {
    const state = memoryState();
    state.deliveries.unshift(delivery);
    if (state.deliveries.length > MAX_DELIVERIES) state.deliveries.length = MAX_DELIVERIES;
  }

  async listDeliveries(limit = 50): Promise<AlertDelivery[]> {
    return memoryState().deliveries.slice(0, limit);
  }

  async hasDelivery(idempotencyKey: string): Promise<boolean> {
    return memoryState().deliveries.some((d) => d.idempotencyKey === idempotencyKey && d.status === 'sent');
  }
}

// ── Store resolution ──────────────────────────────────────────────────────

let cached: Store | null = null;

export function isSupabaseConfigured(): boolean {
  return Boolean(
    process.env.NEXT_PUBLIC_SUPABASE_URL &&
      (process.env.SUPABASE_SERVICE_ROLE_KEY || process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY),
  );
}

export async function getStore(): Promise<Store> {
  if (cached) return cached;

  if (isSupabaseConfigured()) {
    try {
      const { SupabaseStore } = await import('./supabase-store');
      const store = new SupabaseStore();
      const ok = await store.healthCheck();
      if (ok) {
        cached = store;
        return cached;
      }
      console.warn('[store] Supabase configured but unreachable — falling back to in-memory store.');
    } catch (err) {
      console.warn('[store] Supabase init failed, using in-memory store:', err);
    }
  }

  cached = new MemoryStore();
  return cached;
}

/** Test hook — forces re-resolution on the next getStore() call. */
export function resetStoreCache(): void {
  cached = null;
}

export { mergeSettings };
