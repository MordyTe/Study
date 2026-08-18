/**
 * Durable persistence. Loaded only via dynamic import from `getStore()`, so the
 * SDK never enters the bundle for a memory-only deployment.
 *
 * Table design is the pragmatic one: indexed columns for querying plus a full
 * JSONB `payload` for the object itself. Reads select only the payload and cast,
 * so schema evolution costs nothing.
 */

import { createClient, type SupabaseClient } from '@supabase/supabase-js';
import type { Candidate } from '@/lib/engine/assess';
import { DEFAULT_SETTINGS, type ScanRecord, type Settings, type Store } from './index';

const SETTINGS_ROW_ID = 'singleton';

export class SupabaseStore implements Store {
  readonly kind = 'supabase' as const;
  private readonly client: SupabaseClient;

  constructor() {
    const url = process.env['NEXT_PUBLIC_SUPABASE_URL'];
    const key =
      process.env['SUPABASE_SERVICE_ROLE_KEY'] ?? process.env['NEXT_PUBLIC_SUPABASE_ANON_KEY'];
    if (!url || !key) throw new Error('Supabase is not configured.');
    this.client = createClient(url, key, { auth: { persistSession: false } });
  }

  /**
   * Round-trips a real query. A missing table means the migration has not run,
   * which correctly falls back rather than throwing at request time.
   */
  async healthCheck(): Promise<boolean> {
    const { error } = await this.client.from('app_settings').select('id').limit(1);
    return !error;
  }

  async getSettings(): Promise<Settings> {
    const { data, error } = await this.client
      .from('app_settings')
      .select('payload')
      .eq('id', SETTINGS_ROW_ID)
      .maybeSingle();
    if (error || !data) return { ...DEFAULT_SETTINGS };
    return { ...DEFAULT_SETTINGS, ...(data.payload as Partial<Settings>) };
  }

  async saveSettings(settings: Settings): Promise<void> {
    await this.client
      .from('app_settings')
      .upsert({ id: SETTINGS_ROW_ID, payload: settings, updated_at: new Date().toISOString() });
  }

  async listCandidates(limit = 100): Promise<Candidate[]> {
    const { data, error } = await this.client
      .from('candidates')
      .select('payload')
      .order('decision_at', { ascending: false })
      .limit(limit);
    if (error || !data) return [];
    return data.map((row) => row.payload as Candidate);
  }

  async getCandidate(id: string): Promise<Candidate | null> {
    const { data, error } = await this.client
      .from('candidates')
      .select('payload')
      .eq('id', id)
      .maybeSingle();
    if (error || !data) return null;
    return data.payload as Candidate;
  }

  async findByFingerprint(fingerprint: string): Promise<Candidate | null> {
    const { data, error } = await this.client
      .from('candidates')
      .select('payload')
      .eq('fingerprint', fingerprint)
      .maybeSingle();
    if (error || !data) return null;
    return data.payload as Candidate;
  }

  async upsertCandidate(candidate: Candidate): Promise<void> {
    await this.client.from('candidates').upsert({
      id: candidate.id,
      fingerprint: candidate.fingerprint,
      market_id: candidate.marketId,
      status: candidate.status,
      fair_probability: candidate.fairProbability,
      market_price: candidate.marketPrice,
      decision_at: candidate.decisionAt,
      payload: candidate,
      updated_at: new Date().toISOString(),
    });
  }

  async recordScan(scan: ScanRecord): Promise<void> {
    await this.client.from('scans').insert({
      id: scan.id,
      started_at: scan.startedAt,
      finished_at: scan.finishedAt,
      payload: scan,
    });
  }

  async listScans(limit = 20): Promise<ScanRecord[]> {
    const { data, error } = await this.client
      .from('scans')
      .select('payload')
      .order('started_at', { ascending: false })
      .limit(limit);
    if (error || !data) return [];
    return data.map((row) => row.payload as ScanRecord);
  }

  async lastScan(): Promise<ScanRecord | null> {
    const scans = await this.listScans(1);
    return scans[0] ?? null;
  }
}
