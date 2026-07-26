import { NextResponse } from 'next/server';
import { listDetectorMeta } from '@/lib/patterns/registry';
import { getStore } from '@/lib/store';

export const dynamic = 'force-dynamic';

export async function GET() {
  const store = await getStore();
  const settings = await store.getSettings();
  const opportunities = await store.listOpportunities(300);

  const detectors = listDetectorMeta().map((d) => {
    const produced = opportunities.filter((o) => o.detectorName === d.name);
    const resolved = produced.filter((o) =>
      ['TARGET_1_REACHED', 'TARGET_2_REACHED', 'INVALIDATED', 'CLOSED_TRACKING'].includes(o.status),
    );
    const wins = resolved.filter((o) => o.status !== 'INVALIDATED');

    return {
      ...d,
      enabled: !settings.mutedDetectors.includes(d.name),
      signalsProduced: produced.length,
      resolved: resolved.length,
      // Only meaningful once a real sample exists — the UI states this explicitly.
      hitRate: resolved.length >= 5 ? Number(((wins.length / resolved.length) * 100).toFixed(1)) : null,
      avgScore: produced.length
        ? Number((produced.reduce((a, o) => a + o.score, 0) / produced.length).toFixed(1))
        : null,
    };
  });

  return NextResponse.json({ ok: true, detectors, sampleSizeNote: 'Hit rate is withheld until at least 5 signals from a detector have resolved.' });
}
