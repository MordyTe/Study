/**
 * Run one scan from the command line and print what it found.
 *
 *   npm run scan
 */

import { runScan } from '@/lib/engine/scanner';

async function main(): Promise<void> {
  const { record, candidates } = await runScan();

  console.log('\n── Scan ───────────────────────────────────────────────────\n');
  console.log(`universe    ${record.universeSize}`);
  console.log(`promoted    ${record.promoted}`);
  console.log(`actionable  ${record.actionable}`);
  console.log(`watch       ${record.watch}`);
  console.log(`abstain     ${record.abstain}`);
  console.log(`store       ${record.storeKind}`);
  console.log(`agents      ${record.llmProviderKind}`);
  console.log(`duration    ${record.finishedAt - record.startedAt}ms`);

  if (record.errors.length > 0) {
    console.log('\n── Recorded notes ─────────────────────────────────────────\n');
    for (const error of record.errors) console.log(`· ${error}`);
  }

  const interesting = candidates.filter((c) => c.status !== 'ABSTAIN');
  if (interesting.length > 0) {
    console.log('\n── Candidates ─────────────────────────────────────────────\n');
    for (const c of interesting) {
      console.log(`[${c.status}] ${c.question}`);
      console.log(
        `  ours ${((c.fairProbability ?? 0) * 100).toFixed(1)}%  ` +
          `market ${((c.marketPrice ?? 0) * 100).toFixed(1)}%  ` +
          `edge ${((c.grossEdge ?? 0) * 100).toFixed(2)}c  ` +
          `size $${(c.sizing?.notional ?? 0).toFixed(2)}`,
      );
    }
  }

  const abstained = candidates.filter((c) => c.status === 'ABSTAIN');
  if (abstained.length > 0) {
    console.log(`\n${abstained.length} market(s) abstained. Most common reasons:\n`);
    const counts = new Map<string, number>();
    for (const c of abstained) {
      for (const reason of c.abstentionReasons) {
        counts.set(reason, (counts.get(reason) ?? 0) + 1);
      }
    }
    for (const [reason, count] of [...counts].sort((a, b) => b[1] - a[1]).slice(0, 5)) {
      console.log(`  ${String(count).padStart(3)}  ${reason}`);
    }
  }

  console.log('');
}

main().catch((err) => {
  console.error(err);
  process.exitCode = 1;
});
