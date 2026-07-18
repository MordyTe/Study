"""Cloud-mode tests that need no network: Signal <-> Supabase row roundtrip,
Telegram webhook parsing, runtime settings overrides."""
import json

from agent.cloud.supabase_repo import _signal_from_row
from agent.cloud.telegram_http import TelegramHttp
from agent.cloud.tick import apply_runtime_overrides
from agent.config import load_config
from agent.models import Direction, Signal, SignalState, StrategyVote, Style


def make_signal() -> Signal:
    return Signal(
        id="abc123", created_ts=1_745_000_000_000, symbol="ETHUSDT", market="linear",
        style=Style.INTRADAY, direction=Direction.SHORT,
        entry_lo=3000.0, entry_hi=3010.0, sl=3050.0,
        tp1=2960.0, tp2=2920.0, tp3=2880.0,
        rr_tp2=2.0, confidence=0.66,
        votes=[StrategyVote(strategy="smc", score=-0.7, timeframe="15",
                            reasons=["CHOCH bearish"], meta={"ob": {"top": 3040.0}})],
        qty=1.25, leverage=3, invalidation="close above 3060",
        state=SignalState.ACTIVE, llm_verdict="CONFIRM", llm_reasoning="coherent",
        entry_ttl_ts=1_745_000_900_000, max_duration_ts=1_745_086_400_000,
        fill_price=3005.0,
    )


def row_of(s: Signal) -> dict:
    # mirror of SupabaseRepo.save_signal payload
    return {
        "id": s.id, "created_ts": s.created_ts, "symbol": s.symbol,
        "market": s.market, "style": s.style.value, "direction": s.direction.value,
        "entry_lo": s.entry_lo, "entry_hi": s.entry_hi, "sl": s.sl,
        "tp1": s.tp1, "tp2": s.tp2, "tp3": s.tp3,
        "rr_tp2": s.rr_tp2, "confidence": s.confidence,
        "qty": s.qty, "leverage": s.leverage, "invalidation": s.invalidation,
        "votes_json": json.loads(s.votes_json()),
        "llm_verdict": s.llm_verdict, "llm_reasoning": s.llm_reasoning,
        "state": s.state.value, "fill_price": s.fill_price,
        "resolved_ts": s.resolved_ts, "realized_r": s.realized_r,
        "entry_ttl_ts": s.entry_ttl_ts, "max_duration_ts": s.max_duration_ts,
    }


def test_signal_row_roundtrip():
    orig = make_signal()
    restored = _signal_from_row(row_of(orig))
    assert restored.id == orig.id
    assert restored.style is orig.style
    assert restored.direction is orig.direction
    assert restored.state is orig.state
    assert restored.sl == orig.sl
    assert restored.fill_price == orig.fill_price
    assert restored.entry_ttl_ts == orig.entry_ttl_ts
    assert restored.max_duration_ts == orig.max_duration_ts
    assert restored.votes[0].strategy == "smc"
    assert restored.votes[0].meta["ob"]["top"] == 3040.0


def test_telegram_command_parsing():
    assert TelegramHttp.command_of({"message": {"text": "/status"}}) == "status"
    assert TelegramHttp.command_of({"message": {"text": "/Stats@MyBot extra"}}) == "stats"
    assert TelegramHttp.command_of({"message": {"text": "hello"}}) is None
    assert TelegramHttp.command_of({}) is None


def test_telegram_allowlist(monkeypatch):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "t")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "12345")
    tg = TelegramHttp()
    assert tg.allowed_update({"message": {"chat": {"id": 12345}}})
    assert not tg.allowed_update({"message": {"chat": {"id": 999}}})
    assert not tg.allowed_update({})


def test_runtime_overrides():
    cfg = load_config()
    apply_runtime_overrides(cfg, {
        "confluence_threshold": "0.7",
        "htf_gate_mode": "soft",
        "risk_pct": "0.5",
        "llm_veto_mode": "suppress",
    })
    assert cfg.confluence.threshold == 0.7
    assert cfg.confluence.htf_gate_mode == "soft"
    assert cfg.risk.risk_pct == 0.5
    assert cfg.llm.veto_mode == "suppress"


def test_runtime_overrides_empty_noop():
    cfg = load_config()
    before = cfg.confluence.threshold
    apply_runtime_overrides(cfg, {})
    assert cfg.confluence.threshold == before
