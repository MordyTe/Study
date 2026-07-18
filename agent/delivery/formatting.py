"""HTML card rendering for Telegram (and plain summaries for logs)."""
from __future__ import annotations

from datetime import datetime, timezone

from agent.models import Direction, Signal, SignalState, TF_LABEL


def _bar(conf: float, width: int = 10) -> str:
    filled = round(conf * width)
    return "▰" * filled + "▱" * (width - filled)


def signal_card(sig: Signal) -> str:
    arrow = "🟢 LONG" if sig.direction is Direction.LONG else "🔴 SHORT"
    lines = [
        f"<b>{arrow} · {sig.symbol} · {sig.style.value.upper()}</b>",
        f"<i>{datetime.fromtimestamp(sig.created_ts / 1000, tz=timezone.utc):%Y-%m-%d %H:%M} UTC · #{sig.id}</i>",
        "",
        f"📍 <b>Entry:</b> {sig.entry_lo:,.2f} – {sig.entry_hi:,.2f}",
        f"🛑 <b>Stop:</b> {sig.sl:,.2f}",
        f"🎯 <b>TP1:</b> {sig.tp1:,.2f} (1R)   <b>TP2:</b> {sig.tp2:,.2f} (2R)",
        f"🎯 <b>TP3:</b> {sig.tp3:,.2f}   <b>R:R→TP2:</b> {sig.rr_tp2:.1f}",
        f"📐 <b>Size:</b> {sig.qty} ETH" + (f" · <b>lev:</b> {sig.leverage}x" if sig.market == "linear" else ""),
        f"⚠️ <b>Invalidation:</b> {sig.invalidation}",
        "",
        f"<b>Confidence:</b> {_bar(sig.confidence)} {sig.confidence:.0%}",
        "<b>Confluences:</b>",
    ]
    for v in sig.votes:
        emoji = "🟩" if v.score > 0 else "🟥"
        lines.append(f"{emoji} <b>{v.strategy}</b> ({v.score:+.2f})")
        for r in v.reasons[:2]:
            lines.append(f"    · {r}")
    if sig.llm_verdict:
        icon = {"CONFIRM": "✅", "NEUTRAL": "➖", "VETO": "⛔"}.get(sig.llm_verdict, "❔")
        lines += ["", f"{icon} <b>Gemini:</b> {sig.llm_verdict} — {sig.llm_reasoning or ''}"]
    elif sig.llm_reasoning is None:
        lines += ["", "🤖 <i>LLM analysis unavailable</i>"]
    return "\n".join(lines)


def event_message(sig: Signal, frm: SignalState, to: SignalState, price: float) -> str | None:
    tag = f"#{sig.id} {sig.symbol} {sig.direction.value.upper()}"
    msgs = {
        SignalState.ACTIVE: f"▶️ <b>{tag}</b> filled @ {price:,.2f}",
        SignalState.TP1_HIT: f"🎯 <b>{tag}</b> TP1 hit @ {price:,.2f} — <b>move stop to breakeven</b>",
        SignalState.TP2_HIT: f"🎯🎯 <b>{tag}</b> TP2 hit @ {price:,.2f} — consider trailing the runner",
        SignalState.WIN: f"🏆 <b>{tag}</b> TP3 hit @ {price:,.2f} — closed, +{sig.realized_r}R",
        SignalState.WIN_PARTIAL: f"✅ <b>{tag}</b> stopped at breakeven after TP — +{sig.realized_r}R banked",
        SignalState.LOSS: f"❌ <b>{tag}</b> stopped out @ {price:,.2f} — -1R. On to the next.",
        SignalState.EXPIRED_UNFILLED: f"⏰ <b>{tag}</b> expired unfilled — setup no longer valid",
        SignalState.EXPIRED_ACTIVE: f"⏰ <b>{tag}</b> time-stopped @ {price:,.2f} ({sig.realized_r:+}R)",
        SignalState.INVALIDATED: f"🚫 <b>{tag}</b> invalidated — opposite signal fired",
    }
    return msgs.get(to)


def status_message(feed_ok: bool, biases: dict[str, str], deriv: dict | None,
                   open_signals: list[Signal], stats: dict) -> str:
    lines = [
        "<b>📡 Agent Status</b>",
        f"Feed: {'🟢 live' if feed_ok else '🔴 degraded'}",
        "",
        "<b>HTF bias:</b> " + "  ".join(f"{TF_LABEL.get(tf, tf)}:{b}" for tf, b in biases.items()),
    ]
    if deriv:
        f = deriv.get("funding_rate")
        oi = deriv.get("oi_change_1h_pct")
        ls = deriv.get("ls_ratio")
        lines.append(
            f"<b>Deriv:</b> funding {f * 100:.3f}%" + (f" · OI 1h {oi:+.1f}%" if oi is not None else "")
            + (f" · L/S {ls:.2f}" if ls else "") if f is not None else "<b>Deriv:</b> warming up"
        )
    lines.append("")
    if open_signals:
        lines.append("<b>Open signals:</b>")
        for s in open_signals:
            lines.append(f"  #{s.id} {s.direction.value.upper()} {s.style.value} · {s.state.value}")
    else:
        lines.append("No open signals — waiting for confluence.")
    if stats.get("resolved"):
        lines += ["", f"<b>Stats:</b> {stats['resolved']} resolved · "
                      f"WR {stats['win_rate']}% · {stats['total_r']:+.1f}R · "
                      f"expectancy {stats['expectancy_r']}R"]
    return "\n".join(lines)


def stats_message(stats: dict) -> str:
    if not stats.get("resolved"):
        return "No resolved signals yet — stats will appear after the first TP/SL."
    return "\n".join([
        "<b>📊 Performance</b>",
        f"Resolved: {stats['resolved']} (open: {stats['open']})",
        f"Win rate: <b>{stats['win_rate']}%</b> ({stats['wins']}W / {stats['losses']}L)",
        f"Total: <b>{stats['total_r']:+.2f}R</b>",
        f"Expectancy: {stats['expectancy_r']}R per trade",
        f"Profit factor: {stats['profit_factor']}",
    ])
