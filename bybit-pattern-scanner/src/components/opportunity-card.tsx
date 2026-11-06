'use client';

import Link from 'next/link';
import type { Opportunity } from '@/lib/engine/opportunity';
import { Chip, ScoreRing, StatusChip, formatPrice } from './ui';

export function OpportunityCard({ opp }: { opp: Opportunity }) {
  const isLong = opp.direction === 'long';

  return (
    <div className="card-3d-wrap">
      <Link
        href={`/opportunity/${opp.id}`}
        className="card-3d panel panel-hover fade-in block p-4 focus-visible:outline-none"
        aria-label={`${opp.symbol} ${opp.timeframe} ${opp.patternDisplayName}, setup quality ${opp.score} out of 100`}
      >
        <div className="flex items-start justify-between gap-3">
          <div className="card-depth-1 min-w-0">
            <div className="flex flex-wrap items-center gap-2">
              <span className="mono truncate text-base font-bold text-[#f2f5fb]">{opp.symbol}</span>
              <Chip tone={opp.category === 'linear' ? 'info' : 'muted'}>
                {opp.category === 'linear' ? 'PERP' : 'SPOT'}
              </Chip>
              <Chip tone="muted">{opp.timeframe}</Chip>
            </div>
            <p className="mt-1.5 truncate text-xs text-[#a8b3cc]">{opp.patternDisplayName}</p>
          </div>
          <div className="card-depth-2">
            <ScoreRing score={opp.score} />
          </div>
        </div>

        <div className="mt-3 flex flex-wrap items-center gap-2">
          <Chip tone={isLong ? 'bull' : 'bear'}>{isLong ? '▲ Long setup' : '▼ Short setup'}</Chip>
          <StatusChip status={opp.status} />
          <Chip tone={opp.rewardToRisk >= 2 ? 'bull' : 'warn'}>R:R {opp.rewardToRisk}</Chip>
        </div>

        <dl className="mono mt-4 grid grid-cols-3 gap-2 border-t border-white/[0.06] pt-3 text-[11px]">
          <div>
            <dt className="text-[9px] uppercase tracking-wider text-[#5c6883]">Entry zone</dt>
            <dd className="mt-0.5 text-[#d6dcea]">
              {formatPrice(opp.entryZone.from)}
              <span className="text-[#5c6883]"> – </span>
              {formatPrice(opp.entryZone.to)}
            </dd>
          </div>
          <div>
            <dt className="text-[9px] uppercase tracking-wider text-[#5c6883]">Invalidation</dt>
            <dd className="mt-0.5 text-[#fb7185]">{formatPrice(opp.invalidation)}</dd>
          </div>
          <div>
            <dt className="text-[9px] uppercase tracking-wider text-[#5c6883]">Target 1</dt>
            <dd className="mt-0.5 text-[#34d399]">{formatPrice(opp.targets[0]?.price)}</dd>
          </div>
        </dl>

        {opp.reasonsFor[0] ? (
          <p className="mt-3 line-clamp-2 text-[11px] leading-relaxed text-[#7d8aa8]">{opp.reasonsFor[0]}</p>
        ) : null}

        <div className="mt-3 flex items-center justify-between border-t border-white/[0.06] pt-2.5 text-[10px] text-[#5c6883]">
          <span>{opp.verification.source}</span>
          <span className="mono">{opp.verification.health}</span>
        </div>
      </Link>
    </div>
  );
}
