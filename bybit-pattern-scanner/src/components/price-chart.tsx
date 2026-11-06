'use client';

import { useEffect, useRef } from 'react';
import type { UTCTimestamp } from 'lightweight-charts';
import type { Candle } from '@/lib/bybit/types';
import type { Overlay } from '@/lib/patterns/types';

interface Props {
  candles: Candle[];
  overlays?: Overlay[];
  height?: number;
  ariaSummary?: string;
}

const COLORS: Record<string, string> = {
  bull: '#10b981',
  bear: '#f43f5e',
  warn: '#f59e0b',
  neutral: '#7d8aa8',
};

/**
 * Candlestick chart backed by TradingView Lightweight Charts.
 * Overlays render from the SAME evidence model the Telegram message uses, so
 * the two can never disagree.
 */
export function PriceChart({ candles, overlays = [], height = 420, ariaSummary }: Props) {
  const containerRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const el = containerRef.current;
    if (!el || candles.length === 0) return;

    let disposed = false;
    let cleanup: (() => void) | null = null;

    void (async () => {
      const lw = await import('lightweight-charts');
      if (disposed || !containerRef.current) return;

      const chart = lw.createChart(containerRef.current, {
        height,
        layout: {
          background: { color: 'transparent' },
          textColor: '#7d8aa8',
          fontFamily: 'ui-monospace, monospace',
          fontSize: 11,
        },
        grid: {
          vertLines: { color: 'rgba(148,163,184,0.06)' },
          horzLines: { color: 'rgba(148,163,184,0.06)' },
        },
        rightPriceScale: { borderColor: 'rgba(148,163,184,0.12)' },
        timeScale: { borderColor: 'rgba(148,163,184,0.12)', timeVisible: true, secondsVisible: false },
        crosshair: {
          mode: lw.CrosshairMode.Normal,
          vertLine: { color: 'rgba(34,211,238,0.4)', labelBackgroundColor: '#0f1420' },
          horzLine: { color: 'rgba(34,211,238,0.4)', labelBackgroundColor: '#0f1420' },
        },
        autoSize: false,
        width: containerRef.current.clientWidth,
      });

      const candleSeries = chart.addSeries(lw.CandlestickSeries, {
        upColor: '#10b981',
        downColor: '#f43f5e',
        borderUpColor: '#10b981',
        borderDownColor: '#f43f5e',
        wickUpColor: 'rgba(16,185,129,0.6)',
        wickDownColor: 'rgba(244,63,94,0.6)',
      });

      candleSeries.setData(
        candles.map((c) => ({
          time: (c.time / 1000) as UTCTimestamp,
          open: c.open,
          high: c.high,
          low: c.low,
          close: c.close,
        })),
      );

      const volumeSeries = chart.addSeries(lw.HistogramSeries, {
        priceFormat: { type: 'volume' },
        priceScaleId: 'volume',
      });
      chart.priceScale('volume').applyOptions({ scaleMargins: { top: 0.82, bottom: 0 } });
      volumeSeries.setData(
        candles.map((c) => ({
          time: (c.time / 1000) as UTCTimestamp,
          value: c.volume,
          color: c.close >= c.open ? 'rgba(16,185,129,0.28)' : 'rgba(244,63,94,0.28)',
        })),
      );

      // ── Overlay primitives ──
      for (const overlay of overlays) {
        if (overlay.type === 'horizontal_line' || overlay.type === 'target_line' || overlay.type === 'invalidation_line') {
          const color =
            overlay.type === 'target_line'
              ? COLORS.bull!
              : overlay.type === 'invalidation_line'
                ? COLORS.bear!
                : COLORS[overlay.color] ?? COLORS.neutral!;
          candleSeries.createPriceLine({
            price: overlay.price,
            color,
            lineWidth: 1,
            lineStyle: overlay.type === 'horizontal_line' ? lw.LineStyle.Solid : lw.LineStyle.Dashed,
            axisLabelVisible: true,
            title: overlay.label,
          });
        } else if (overlay.type === 'price_zone') {
          for (const [price, label] of [
            [overlay.from, `${overlay.label} ↓`],
            [overlay.to, `${overlay.label} ↑`],
          ] as [number, string][]) {
            candleSeries.createPriceLine({
              price,
              color: COLORS[overlay.color] ?? COLORS.neutral!,
              lineWidth: 1,
              lineStyle: lw.LineStyle.Dotted,
              axisLabelVisible: false,
              title: label,
            });
          }
        } else if (overlay.type === 'trend_line') {
          const line = chart.addSeries(lw.LineSeries, {
            color: COLORS[overlay.color] ?? COLORS.neutral!,
            lineWidth: 1,
            lineStyle: lw.LineStyle.Dashed,
            priceLineVisible: false,
            lastValueVisible: false,
            crosshairMarkerVisible: false,
          });
          const points = [
            { time: (overlay.from.time / 1000) as UTCTimestamp, value: overlay.from.price },
            { time: (overlay.to.time / 1000) as UTCTimestamp, value: overlay.to.price },
          ].sort((a, b) => (a.time as number) - (b.time as number));
          if (points[0]!.time !== points[1]!.time) line.setData(points);
        }
      }

      const markers = overlays.filter((o) => o.type === 'marker');
      if (markers.length > 0) {
        lw.createSeriesMarkers(
          candleSeries,
          markers
            .map((m) => {
              const marker = m as Extract<Overlay, { type: 'marker' }>;
              return {
                time: (marker.time / 1000) as UTCTimestamp,
                position: 'aboveBar' as const,
                color: COLORS[marker.color] ?? COLORS.neutral!,
                shape: 'circle' as const,
                text: marker.label,
              };
            })
            .sort((a, b) => (a.time as number) - (b.time as number)),
        );
      }

      chart.timeScale().fitContent();

      const onResize = () => {
        if (containerRef.current) chart.applyOptions({ width: containerRef.current.clientWidth });
      };
      window.addEventListener('resize', onResize);

      cleanup = () => {
        window.removeEventListener('resize', onResize);
        chart.remove();
      };
    })();

    return () => {
      disposed = true;
      cleanup?.();
    };
  }, [candles, overlays, height]);

  if (candles.length === 0) {
    return (
      <div
        className="flex items-center justify-center rounded-xl border border-white/[0.06] bg-white/[0.02] text-xs text-[#5c6883]"
        style={{ height }}
      >
        No candle data available for this instrument and timeframe.
      </div>
    );
  }

  const first = candles[0];
  const last = candles[candles.length - 1];
  const summary =
    ariaSummary ??
    `Candlestick chart with ${candles.length} candles. Opening price ${first?.open}, latest close ${last?.close}.`;

  return (
    <div>
      <div ref={containerRef} className="w-full" role="img" aria-label={summary} />
      <p className="sr-only">{summary}</p>
    </div>
  );
}
