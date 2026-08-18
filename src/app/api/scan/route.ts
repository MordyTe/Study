import { NextResponse } from 'next/server';
import { assertReadOnlyEnvironment } from '@/lib/polymarket/read';
import { runScan } from '@/lib/engine/scanner';

export const dynamic = 'force-dynamic';
export const maxDuration = 60;

/**
 * Trigger a scan.
 *
 * The credential check runs as the first statement, before anything else: the
 * presence of a signing key in the environment is itself refused, not merely
 * its use.
 */
export async function POST(): Promise<NextResponse> {
  try {
    assertReadOnlyEnvironment();
  } catch (err) {
    return NextResponse.json({ ok: false, error: (err as Error).message }, { status: 500 });
  }

  try {
    const { record, candidates } = await runScan();
    return NextResponse.json({
      ok: true,
      scan: record,
      candidates: candidates.map((c) => ({
        id: c.id,
        status: c.status,
        question: c.question,
        fairProbability: c.fairProbability,
        marketPrice: c.marketPrice,
        grossEdge: c.grossEdge,
        recommendedNotional: c.sizing?.notional ?? 0,
      })),
    });
  } catch (err) {
    return NextResponse.json({ ok: false, error: (err as Error).message }, { status: 502 });
  }
}

export async function GET(): Promise<NextResponse> {
  return NextResponse.json(
    { ok: false, error: 'Use POST to trigger a scan.' },
    { status: 405 },
  );
}
