/**
 * Live smoke test. Proves the read layer works against reality rather than
 * against fixtures, and reports exactly which prerequisites are missing.
 *
 *   npm run verify-live
 */

import { assertReadOnlyEnvironment, getFeeRateBps, getOrderBook, listEvents } from '@/lib/polymarket/read';
import { getLlmProvider } from '@/lib/agents/llm';
import { rankTier1 } from '@/lib/engine/rank';
import { DEFAULT_SETTINGS, getStore } from '@/lib/store';

function line(label: string, value: string): void {
  console.log(`${label.padEnd(26)} ${value}`);
}

async function main(): Promise<void> {
  console.log('\n── Preconditions ──────────────────────────────────────────\n');

  try {
    assertReadOnlyEnvironment();
    line('credentials', 'clean — no signing key present, as required');
  } catch (err) {
    line('credentials', `REFUSED — ${(err as Error).message}`);
    process.exitCode = 1;
    return;
  }

  const store = await getStore();
  line('store', `${store.kind}${store.kind === 'memory' ? ' (NOT durable)' : ''}`);

  const llm = getLlmProvider();
  line('agent provider', llm.kind + (llm.kind === 'unavailable' ? ' — every market will abstain' : ''));

  console.log('\n── Venue reachability ─────────────────────────────────────\n');

  let events;
  try {
    events = await listEvents({ limit: 20 });
    line('gamma /events', `OK — ${events.length} events`);
  } catch (err) {
    line('gamma /events', `FAILED — ${(err as Error).message}`);
    console.log(
      '\nThe venue is unreachable from here. If this is a sandbox, the egress policy needs\n' +
        'gamma-api.polymarket.com and clob.polymarket.com allowed. Everything below is skipped.\n',
    );
    process.exitCode = 1;
    return;
  }

  const feeRate = await getFeeRateBps();
  line('clob /fee-rate', feeRate === null ? 'unavailable — will use the conservative fallback' : `${feeRate} bps`);

  console.log('\n── Tier 1 ranking ─────────────────────────────────────────\n');

  const markets = events.flatMap((e) => e.markets);
  const tier1 = rankTier1(markets, Date.now(), DEFAULT_SETTINGS);
  line('markets seen', String(markets.length));
  line('passed filters', String(tier1.considered));
  line('promoted', String(tier1.promoted.length));
  for (const [reason, count] of Object.entries(tier1.rejected)) {
    line(`  filtered: ${reason}`, String(count));
  }

  const top = tier1.promoted[0];
  if (!top) {
    console.log('\nNo market in this sample has a scheduled data source. That is a normal result.\n');
    return;
  }

  console.log('\n── Top-ranked market ──────────────────────────────────────\n');
  console.log(top.market.question);
  line('neglect', top.neglect.toFixed(4));
  line('volume', `$${Math.round(top.market.volumeNum).toLocaleString()}`);
  line('resolves in', `${top.daysToResolution?.toFixed(1)} days`);
  for (const reason of top.reasons) console.log(`  · ${reason}`);

  const tokenId = top.market.clobTokenIds[0];
  if (tokenId) {
    try {
      const book = await getOrderBook(tokenId);
      console.log('');
      line('best ask', book.asks[0] ? `${book.asks[0].price} × ${book.asks[0].size}` : 'none');
      line('ask depth', `$${book.asks.reduce((a, l) => a + l.price * l.size, 0).toFixed(2)}`);
      line('book levels', `${book.bids.length} bid / ${book.asks.length} ask`);
    } catch (err) {
      line('clob /book', `FAILED — ${(err as Error).message}`);
    }
  }

  console.log('');
}

main().catch((err) => {
  console.error(err);
  process.exitCode = 1;
});
