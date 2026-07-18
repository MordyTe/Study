"""Backtest report: headline metrics + per-strategy attribution."""
from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timezone

from agent.models import Signal, SignalState


def print_report(signals: list[Signal], stats: dict, live_strategies: list[str],
                 elapsed_s: float) -> None:
    print("\n" + "=" * 62)
    print("BACKTEST REPORT")
    print("=" * 62)
    if signals:
        first = datetime.fromtimestamp(signals[0].created_ts / 1000, tz=timezone.utc)
        last = datetime.fromtimestamp(signals[-1].created_ts / 1000, tz=timezone.utc)
        print(f"window          : {first:%Y-%m-%d} .. {last:%Y-%m-%d}")
    print(f"signals fired   : {len(signals)}")
    print(f"resolved        : {stats['resolved']}  (open at end: {stats['open']})")
    print(f"win rate        : {stats['win_rate']}%")
    print(f"total R         : {stats['total_r']}")
    print(f"expectancy      : {stats['expectancy_r']} R/trade")
    print(f"profit factor   : {stats['profit_factor']}")
    print(f"strategies live : {', '.join(live_strategies) or '-'}")
    print(f"(flow/derivatives strategies are inactive in backtest — no historical stream)")

    # per-style breakdown
    by_style: dict[str, list[Signal]] = defaultdict(list)
    for s in signals:
        by_style[s.style.value].append(s)
    print("-" * 62)
    for style, group in by_style.items():
        resolved = [s for s in group if s.state.terminal
                    and s.state not in (SignalState.REJECTED, SignalState.EXPIRED_UNFILLED)]
        wins = [s for s in resolved if (s.realized_r or 0) > 0]
        wr = f"{len(wins) / len(resolved) * 100:.0f}%" if resolved else "-"
        tot = sum(s.realized_r or 0 for s in resolved)
        print(f"  {style:<10} signals={len(group):<4} resolved={len(resolved):<4} "
              f"win_rate={wr:<5} total_R={tot:+.1f}")

    # per-strategy attribution: how often each strategy appears in winners vs losers
    print("-" * 62)
    print("confluence attribution (appearances in winners / losers):")
    attr: dict[str, list[int]] = defaultdict(lambda: [0, 0])
    for s in signals:
        if not s.state.terminal or s.state in (SignalState.REJECTED, SignalState.EXPIRED_UNFILLED):
            continue
        won = (s.realized_r or 0) > 0
        for v in s.votes:
            attr[v.strategy][0 if won else 1] += 1
    for name, (w, l) in sorted(attr.items(), key=lambda kv: -(kv[1][0] - kv[1][1])):
        edge = f"{w / (w + l) * 100:.0f}%" if (w + l) else "-"
        print(f"  {name:<24} winners={w:<4} losers={l:<4} hit={edge}")
    print(f"\nreplay time: {elapsed_s:.1f}s")
    print("=" * 62)
