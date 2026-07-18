"""Asyncio orchestrator: builds every component, supervises tasks,
routes WS messages, and runs the signal pipeline.
"""
from __future__ import annotations

import asyncio
import logging

from agent.bus import Bus, CANDLE_CLOSED, RESYNC, SIGNAL_NEW
from agent.config import Config
from agent.data.bybit_rest import BybitRest
from agent.data.bybit_ws import BybitWsFeed
from agent.data.candles import CandleStore
from agent.data.derivatives import DerivativesState
from agent.data.flow import FlowTracker
from agent.delivery import formatting as fmt
from agent.delivery.telegram_bot import TelegramDelivery
from agent.engine.confluence import ConfluenceEngine, htf_bias
from agent.engine.context import ContextBuilder
from agent.engine.risk import RiskModule
from agent.engine.tracker import SignalTracker
from agent.llm.gemini import GeminiAnalyst
from agent.models import Candle, Signal, SignalState, Style, Trade, now_ms, TF_LABEL
from agent.store.db import Db
from agent.store.repo import Repo
from agent.strategies import load_strategies
from agent.web.server import Dashboard

log = logging.getLogger(__name__)


class App:
    def __init__(self, cfg: Config, dryrun: bool = False) -> None:
        self.cfg = cfg
        self.dryrun = dryrun
        self.bus = Bus()
        self.db = Db(cfg.store.db_path)
        self.repo = Repo(self.db)
        self.rest = BybitRest(cfg)
        self.store = CandleStore(self.bus, cfg.active_tfs, cfg.buffer_bars)
        self.flow = FlowTracker()
        self.deriv = DerivativesState()
        self.builder = ContextBuilder(cfg, self.store, self.flow, self.deriv)
        self.strategies = load_strategies(cfg)
        self.engine = ConfluenceEngine(cfg, self.strategies)
        self.risk = RiskModule(cfg)
        self.tracker = SignalTracker(self.bus)
        self.llm = GeminiAnalyst(cfg, self.repo)
        self.telegram = TelegramDelivery(cfg)
        self.dashboard = Dashboard(cfg, self.bus, self.store, self)
        self.ws_queue: asyncio.Queue = asyncio.Queue(maxsize=20000)
        self._styles = [(Style(name), sc) for name, sc in cfg.styles.items() if sc.enabled]
        self._last_msg_ts = 0

    # ---------------------------------------------------------------- startup
    async def _seed_candles(self) -> None:
        market = self.cfg.signal_market
        symbol = self.cfg.signal_symbol
        for tf in self.cfg.active_tfs:
            candles = await self.rest.backfill(market, symbol, tf, self.cfg.buffer_bars)
            self.store.seed(market, tf, candles)
            await self.repo.save_candles(market, tf, candles)
        log.info("startup backfill complete")

    def _build_feeds(self, loop: asyncio.AbstractEventLoop) -> list[BybitWsFeed]:
        feeds = []
        market = self.cfg.signal_market
        symbol = self.cfg.signal_symbol
        feed = BybitWsFeed(self.cfg, self.bus, loop, market, self.ws_queue)
        feed.plan_kline(symbol, self.cfg.active_tfs)
        feed.plan_trades(symbol)
        if market == "linear":
            feed.plan_tickers(symbol)
            feed.plan_liquidations(symbol)
            feeds.append(feed)
        else:
            feeds.append(feed)
            lin = BybitWsFeed(self.cfg, self.bus, loop, "linear", self.ws_queue)
            lin_symbol = self.cfg.symbols["linear"]
            lin.plan_tickers(lin_symbol)
            lin.plan_liquidations(lin_symbol)
            feeds.append(lin)
        return feeds

    # ----------------------------------------------------------- WS routing
    async def _route_ws(self) -> None:
        while True:
            market, msg = await self.ws_queue.get()
            self._last_msg_ts = now_ms()
            topic = msg.get("topic", "")
            data = msg.get("data")
            if not data:
                continue
            try:
                if topic.startswith("kline."):
                    tf = topic.split(".")[1]
                    for row in data:
                        c = Candle(
                            ts=int(row["start"]), open=float(row["open"]),
                            high=float(row["high"]), low=float(row["low"]),
                            close=float(row["close"]), volume=float(row["volume"]),
                            confirmed=bool(row["confirm"]),
                        )
                        self.store.on_kline(market, tf, c)
                elif topic.startswith("publicTrade."):
                    for row in data:
                        self.flow.on_trade(Trade(
                            ts=int(row["T"]), price=float(row["p"]),
                            size=float(row["v"]), is_buy=row["S"] == "Buy",
                        ))
                elif topic.startswith("tickers."):
                    self.deriv.on_ticker(data if isinstance(data, dict) else data[0])
                elif topic.startswith("allLiquidation."):
                    self.deriv.on_liquidation(data)
            except (KeyError, ValueError, TypeError) as e:
                log.warning("bad ws message on %s: %s", topic, e)

    # ------------------------------------------------------ signal pipeline
    async def _pipeline(self) -> None:
        market = self.cfg.signal_market
        async for m, tf, candle in self.bus.stream(CANDLE_CLOSED):
            if m != market:
                continue
            await self.repo.save_candles(m, tf, [candle])
            if tf == "1":
                await self.tracker.on_candle(candle)
            for style, sc in self._styles:
                if tf != sc.entry_tf:
                    continue
                try:
                    await self._evaluate_style(style, sc, candle)
                except Exception:
                    log.exception("pipeline evaluation failed for %s", style.value)

    async def _evaluate_style(self, style: Style, sc, candle: Candle) -> None:
        from agent.models import TF_MS
        close_ts = candle.ts + TF_MS[sc.entry_tf]
        tfs = list(dict.fromkeys([sc.entry_tf, *sc.gate_tfs, "1", "D"]))
        ctx = self.builder.build(self.cfg.signal_market, sc.entry_tf, tfs, close_ts)
        if ctx is None:
            return
        cand = self.engine.evaluate(ctx, style, sc)
        if cand is None:
            return
        sig = self.risk.build_signal(cand)
        if sig is None:
            return

        # LLM second opinion (bounded, fail-open)
        await self.llm.validate_signal(sig, ctx)
        if sig.llm_verdict == "VETO" and self.cfg.llm.veto_mode == "suppress":
            sig.state = SignalState.REJECTED
            await self.repo.save_signal(sig)
            log.info("signal %s suppressed by LLM veto", sig.id)
            return

        # Opposite-direction active signals of same style get invalidated
        for other in self.tracker.open_signals:
            if other.style is sig.style and other.direction is not sig.direction:
                other.resolved_ts = close_ts
                await self.tracker._transition(other, SignalState.INVALIDATED, ctx.price)
                await self.repo.save_signal(other)

        sig.state = SignalState.DELIVERED
        self.tracker.track(sig)
        await self.repo.save_signal(sig)
        self.bus.publish(SIGNAL_NEW, sig)
        log.info("SIGNAL %s: %s %s conf=%.2f entry=%s-%s sl=%s",
                 sig.id, sig.style.value, sig.direction.value, sig.confidence,
                 sig.entry_lo, sig.entry_hi, sig.sl)
        if self.dryrun:
            print("\n" + "-" * 50 + "\n[DRYRUN] " +
                  fmt.signal_card(sig).replace("<b>", "").replace("</b>", "")
                     .replace("<i>", "").replace("</i>", "") + "\n" + "-" * 50)
        else:
            await self.telegram.send_signal(sig)

    async def _on_tracker_event(self, sig: Signal, frm: SignalState, to: SignalState, price: float) -> None:
        await self.repo.save_signal(sig)
        await self.repo.save_event(sig.id, now_ms(), frm, to, price)
        if not self.dryrun and to is not SignalState.INVALIDATED:
            await self.telegram.notify_event(sig, frm, to, price)

    # ------------------------------------------------------------- pollers
    async def _poll_derivatives(self) -> None:
        symbol = self.cfg.symbols["linear"]
        while True:
            try:
                self.deriv.set_oi_series(await self.rest.get_open_interest(symbol))
                self.deriv.set_ls_ratio(await self.rest.get_long_short_ratio(symbol))
                self.deriv.set_funding_history(await self.rest.get_funding_history(symbol))
            except Exception as e:
                log.warning("derivatives poll failed: %s", e)
            await asyncio.sleep(300)

    async def _resync_worker(self) -> None:
        """After WS rebuilds, repair candle gaps via REST."""
        market = self.cfg.signal_market
        symbol = self.cfg.signal_symbol
        async for reason in self.bus.stream(RESYNC):
            log.info("resync triggered: %s", reason)
            await asyncio.sleep(3)  # let the socket resettle first
            for tf in self.cfg.active_tfs:
                try:
                    s = self.store.series(market, tf)
                    if not s.size:
                        continue
                    fresh = await self.rest.get_klines(market, symbol, tf, start_ms=s.last_ts)
                    complete = [c for c in fresh if c.ts > s.last_ts][:-1]  # drop forming bar
                    if complete:
                        self.store.repair(market, tf, complete)
                        await self.repo.save_candles(market, tf, complete)
                except Exception as e:
                    log.warning("gap repair failed for %s: %s", tf, e)

    async def _regime_reporter(self) -> None:
        interval = self.cfg.llm.regime_report_hours * 3600
        await asyncio.sleep(600)  # let data warm up first
        while True:
            try:
                report = await self._run_analysis()
                if report and not self.dryrun:
                    await self.telegram.send(f"<b>🧭 Market Regime Report</b>\n\n{report}")
            except Exception:
                log.exception("regime report failed")
            await asyncio.sleep(interval)

    # ------------------------------------------- services (telegram + web)
    def _biases(self) -> dict[str, str]:
        out = {}
        for tf in ("15", "60", "240", "D"):
            arr = self.store.series(self.cfg.signal_market, tf).view()
            if len(arr) < 60:
                continue
            import numpy as np
            from agent.engine.context import build_frame
            frame = build_frame(self.cfg, tf, np.asarray(arr))
            if frame:
                b = htf_bias(frame)
                out[TF_LABEL.get(tf, tf)] = "bull" if b > 0 else "bear" if b < 0 else "neutral"
        return out

    async def _run_analysis(self) -> str:
        sc = self.cfg.styles["intraday"]
        tfs = list(dict.fromkeys([sc.entry_tf, *sc.gate_tfs, "1", "D"]))
        ctx = self.builder.build(self.cfg.signal_market, sc.entry_tf, tfs, now_ms())
        if ctx is None:
            return "Not enough data yet — still warming up."
        report = await self.llm.regime_report(ctx)
        if report:
            return report
        # quantitative fallback when the LLM is unavailable
        biases = self._biases()
        d = self.deriv.snapshot()
        lines = ["<b>Quant snapshot</b> (LLM unavailable)",
                 f"Price: {ctx.price:,.2f}",
                 "Bias: " + "  ".join(f"{k}:{v}" for k, v in biases.items())]
        if d.get("funding_rate") is not None:
            lines.append(f"Funding: {d['funding_rate'] * 100:.4f}%")
        if d.get("oi_change_1h_pct") is not None:
            lines.append(f"OI 1h: {d['oi_change_1h_pct']:+.2f}%")
        return "\n".join(lines)

    # dashboard services interface
    def stats(self) -> dict:
        return self.tracker.stats()

    async def recent_signals(self, limit: int = 50) -> list[dict]:
        return await self.repo.recent_signals(limit)

    async def state(self) -> dict:
        cvd = self.flow.cvd_series(30)
        return {
            "price": self.store.last_price(self.cfg.signal_market),
            "biases": self._biases(),
            "deriv": self.deriv.snapshot(),
            "cvd_30m": (cvd[-1] - cvd[0]) if len(cvd) > 1 else None,
            "feed_ok": now_ms() - self._last_msg_ts < 30_000,
        }

    def _wire_telegram(self) -> None:
        async def status() -> str:
            return fmt.status_message(
                feed_ok=now_ms() - self._last_msg_ts < 30_000,
                biases=self._biases(), deriv=self.deriv.snapshot(),
                open_signals=self.tracker.open_signals, stats=self.tracker.stats(),
            )

        async def signals() -> str:
            rows = await self.repo.recent_signals(10)
            if not rows:
                return "No signals yet."
            lines = ["<b>Recent signals</b>"]
            for r in rows:
                lines.append(
                    f"#{r['id']} {r['style']} {r['direction'].upper()} "
                    f"{r['entry_lo']}-{r['entry_hi']} · {r['state']}"
                    + (f" · {r['realized_r']:+}R" if r["realized_r"] is not None else "")
                )
            return "\n".join(lines)

        async def stats() -> str:
            return fmt.stats_message(self.tracker.stats())

        async def settings() -> str:
            c = self.cfg
            return "\n".join([
                "<b>⚙️ Settings</b>",
                f"market: {c.signal_market} · symbol: {c.signal_symbol}",
                f"threshold: {c.confluence.threshold} · min agreeing: {c.confluence.min_agreeing}",
                f"HTF gate: {c.confluence.htf_gate_mode}",
                f"risk: {c.risk.risk_pct}% of ${c.risk.account_equity_usd:,.0f}",
                f"LLM: {'on (' + c.llm.validate_model + ')' if self.llm.available else 'off'}"
                f" · veto mode: {c.llm.veto_mode}",
                "Edit config/config.yaml and restart to change.",
            ])

        self.telegram.get_status = status
        self.telegram.get_analysis = self._run_analysis
        self.telegram.get_signals = signals
        self.telegram.get_stats = stats
        self.telegram.get_settings = settings

    # ------------------------------------------------------------------ run
    async def run(self) -> None:
        log.info("starting agent (%s mode) — %s %s",
                 "dryrun" if self.dryrun else "live",
                 self.cfg.signal_market, self.cfg.signal_symbol)
        await self.db.open()
        await self._seed_candles()
        self.tracker.add_notifier(self._on_tracker_event)
        self._wire_telegram()
        loop = asyncio.get_running_loop()
        feeds = self._build_feeds(loop)
        try:
            async with asyncio.TaskGroup() as tg:
                for feed in feeds:
                    tg.create_task(feed.run())
                tg.create_task(self._route_ws())
                tg.create_task(self._pipeline())
                tg.create_task(self._poll_derivatives())
                tg.create_task(self._resync_worker())
                if self.llm.available:
                    tg.create_task(self._regime_reporter())
                if not self.dryrun:
                    tg.create_task(self.telegram.run())
                if self.cfg.web.enabled:
                    tg.create_task(self.dashboard.run())
                log.info("all tasks started — waiting for confluence…")
        finally:
            await self.db.close()
