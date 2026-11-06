/**
 * Supabase-backed store. Activated automatically when NEXT_PUBLIC_SUPABASE_URL
 * plus a key are present. Schema: supabase/migrations/0001_init.sql
 */

import { createClient, type SupabaseClient } from '@supabase/supabase-js';
import type { Opportunity } from '@/lib/engine/opportunity';
import { DEFAULT_SETTINGS, mergeSettings, type Settings } from '@/lib/config/settings';
import type { AlertDelivery, ScanRecord, Store } from './index';

const SETTINGS_ROW_ID = 'default';

export class SupabaseStore implements Store {
  readonly kind = 'supabase' as const;
  private client: SupabaseClient;

  constructor() {
    const url = process.env.NEXT_PUBLIC_SUPABASE_URL!;
    const key = process.env.SUPABASE_SERVICE_ROLE_KEY || process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY!;
    this.client = createClient(url, key, { auth: { persistSession: false } });
  }

  async healthCheck(): Promise<boolean> {
    const { error } = await this.client.from('app_settings').select('id').limit(1);
    // Missing-table errors mean the migration has not been run yet.
    return !error;
  }

  async getSettings(): Promise<Settings> {
    const { data, error } = await this.client
      .from('app_settings')
      .select('value')
      .eq('id', SETTINGS_ROW_ID)
      .maybeSingle();
    if (error || !data) return { ...DEFAULT_SETTINGS };
    return mergeSettings(data.value);
  }

  async saveSettings(settings: Settings): Promise<void> {
    await this.client
      .from('app_settings')
      .upsert({ id: SETTINGS_ROW_ID, value: settings, updated_at: new Date().toISOString() });
  }

  async listOpportunities(limit = 200): Promise<Opportunity[]> {
    const { data, error } = await this.client
      .from('opportunities')
      .select('payload')
      .order('detected_at', { ascending: false })
      .limit(limit);
    if (error || !data) return [];
    return data.map((r) => r.payload as Opportunity);
  }

  async getOpportunity(id: string): Promise<Opportunity | null> {
    const { data, error } = await this.client
      .from('opportunities')
      .select('payload')
      .eq('id', id)
      .maybeSingle();
    if (error || !data) return null;
    return data.payload as Opportunity;
  }

  async findByFingerprint(fingerprint: string): Promise<Opportunity | null> {
    const { data, error } = await this.client
      .from('opportunities')
      .select('payload')
      .eq('fingerprint', fingerprint)
      .maybeSingle();
    if (error || !data) return null;
    return data.payload as Opportunity;
  }

  async upsertOpportunity(opp: Opportunity): Promise<void> {
    await this.client.from('opportunities').upsert({
      id: opp.id,
      fingerprint: opp.fingerprint,
      instrument_id: opp.instrumentId,
      category: opp.category,
      symbol: opp.symbol,
      timeframe: opp.timeframe,
      detector_name: opp.detectorName,
      direction: opp.direction,
      status: opp.status,
      score: opp.score,
      reward_to_risk: opp.rewardToRisk,
      detected_at: new Date(opp.detectedAt).toISOString(),
      updated_at: new Date(opp.updatedAt).toISOString(),
      payload: opp,
    });
  }

  async recordScan(scan: ScanRecord): Promise<void> {
    await this.client.from('scan_runs').insert({
      id: scan.id,
      started_at: new Date(scan.startedAt).toISOString(),
      finished_at: new Date(scan.finishedAt).toISOString(),
      instruments_scanned: scan.instrumentsScanned,
      candidates_evaluated: scan.candidatesEvaluated,
      confirmed: scan.confirmed,
      forming: scan.forming,
      alerts_sent: scan.alertsSent,
      duration_ms: scan.durationMs,
      errors: scan.errors,
    });
  }

  async listScans(limit = 20): Promise<ScanRecord[]> {
    const { data, error } = await this.client
      .from('scan_runs')
      .select('*')
      .order('started_at', { ascending: false })
      .limit(limit);
    if (error || !data) return [];
    return data.map((r) => ({
      id: r.id as string,
      startedAt: new Date(r.started_at as string).getTime(),
      finishedAt: new Date(r.finished_at as string).getTime(),
      instrumentsScanned: (r.instruments_scanned as number) ?? 0,
      candidatesEvaluated: (r.candidates_evaluated as number) ?? 0,
      confirmed: (r.confirmed as number) ?? 0,
      forming: (r.forming as number) ?? 0,
      alertsSent: (r.alerts_sent as number) ?? 0,
      durationMs: (r.duration_ms as number) ?? 0,
      errors: (r.errors as string[]) ?? [],
    }));
  }

  async lastScan(): Promise<ScanRecord | null> {
    const rows = await this.listScans(1);
    return rows[0] ?? null;
  }

  async recordDelivery(delivery: AlertDelivery): Promise<void> {
    await this.client.from('alert_deliveries').insert({
      id: delivery.id,
      opportunity_id: delivery.opportunityId,
      idempotency_key: delivery.idempotencyKey,
      channel: delivery.channel,
      status: delivery.status,
      detail: delivery.detail,
      created_at: new Date(delivery.at).toISOString(),
    });
  }

  async listDeliveries(limit = 50): Promise<AlertDelivery[]> {
    const { data, error } = await this.client
      .from('alert_deliveries')
      .select('*')
      .order('created_at', { ascending: false })
      .limit(limit);
    if (error || !data) return [];
    return data.map((r) => ({
      id: r.id as string,
      opportunityId: r.opportunity_id as string,
      idempotencyKey: r.idempotency_key as string,
      channel: 'telegram' as const,
      status: r.status as AlertDelivery['status'],
      detail: (r.detail as string) ?? '',
      at: new Date(r.created_at as string).getTime(),
    }));
  }

  async hasDelivery(idempotencyKey: string): Promise<boolean> {
    const { data } = await this.client
      .from('alert_deliveries')
      .select('id')
      .eq('idempotency_key', idempotencyKey)
      .eq('status', 'sent')
      .limit(1);
    return Boolean(data && data.length > 0);
  }
}
