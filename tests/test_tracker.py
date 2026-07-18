"""Signal lifecycle tests on synthetic price paths."""
import pytest

from agent.engine.tracker import SignalTracker
from agent.models import Candle, Direction, Signal, SignalState, Style


def make_signal(direction=Direction.LONG) -> Signal:
    long = direction is Direction.LONG
    return Signal(
        id="t1", created_ts=0, symbol="ETHUSDT", market="linear",
        style=Style.SCALP, direction=direction,
        entry_lo=99.0 if long else 101.0, entry_hi=101.0 if long else 103.0,
        sl=95.0 if long else 107.0,
        tp1=105.0 if long else 97.0,
        tp2=110.0 if long else 92.0,
        tp3=115.0 if long else 87.0,
        rr_tp2=2.0, confidence=0.7,
        state=SignalState.DELIVERED,
        entry_ttl_ts=30 * 60_000, max_duration_ts=240 * 60_000,
    )


def bar(ts_min: int, o: float, h: float, l: float, c: float) -> Candle:
    return Candle(ts=ts_min * 60_000, open=o, high=h, low=l, close=c, volume=1.0)


async def feed(tracker: SignalTracker, bars: list[Candle]) -> None:
    for b in bars:
        await tracker.on_candle(b)


@pytest.mark.asyncio
async def test_fill_then_full_win():
    tr = SignalTracker()
    sig = make_signal()
    tr.track(sig)
    await feed(tr, [
        bar(1, 102, 103, 100, 100.5),   # fills in zone
        bar(2, 100.5, 106, 100, 105.5), # TP1
        bar(3, 105, 111, 104, 110.5),   # TP2
        bar(4, 110, 116, 109, 115.5),   # TP3 -> WIN
    ])
    assert sig.state is SignalState.WIN
    assert sig.realized_r and sig.realized_r > 2


@pytest.mark.asyncio
async def test_straight_loss():
    tr = SignalTracker()
    sig = make_signal()
    tr.track(sig)
    await feed(tr, [
        bar(1, 100, 101, 99, 100),
        bar(2, 100, 100.5, 94, 94.5),   # SL 95 broken
    ])
    assert sig.state is SignalState.LOSS
    assert sig.realized_r == -1.0


@pytest.mark.asyncio
async def test_same_bar_sl_and_tp_resolves_as_loss():
    tr = SignalTracker()
    sig = make_signal()
    tr.track(sig)
    await feed(tr, [
        bar(1, 100, 100.5, 99.5, 100),
        bar(2, 100, 106, 94, 100),      # spans both SL(95) and TP1(105)
    ])
    assert sig.state is SignalState.LOSS


@pytest.mark.asyncio
async def test_breakeven_after_tp1():
    tr = SignalTracker()
    sig = make_signal()
    tr.track(sig)
    await feed(tr, [
        bar(1, 100, 101, 99.5, 100),    # fill ~100
        bar(2, 100, 106, 99.8, 105.5),  # TP1
        bar(3, 105, 105.5, 99.9, 100),  # back to entry -> BE tag-out
    ])
    assert sig.state is SignalState.WIN_PARTIAL
    assert sig.realized_r and sig.realized_r > 0


@pytest.mark.asyncio
async def test_expiry_unfilled():
    tr = SignalTracker()
    sig = make_signal()
    tr.track(sig)
    # price never trades into 99-101
    bars = [bar(i, 104, 105, 103, 104) for i in range(1, 35)]
    await feed(tr, bars)
    assert sig.state is SignalState.EXPIRED_UNFILLED


@pytest.mark.asyncio
async def test_short_side_win_path():
    tr = SignalTracker()
    sig = make_signal(Direction.SHORT)
    tr.track(sig)
    await feed(tr, [
        bar(1, 101, 102.5, 100.5, 102),  # fill in 101-103
        bar(2, 102, 102.5, 96.5, 97),    # TP1 97
        bar(3, 97, 97.5, 91.5, 92),      # TP2 92
        bar(4, 92, 92.5, 86.5, 87),      # TP3 -> WIN
    ])
    assert sig.state is SignalState.WIN


@pytest.mark.asyncio
async def test_stats_rollup():
    tr = SignalTracker()
    win = make_signal(); win.id = "w"
    loss = make_signal(); loss.id = "l"
    tr.track(win); tr.track(loss)
    win.state = SignalState.WIN; win.realized_r = 3.0
    loss.state = SignalState.LOSS; loss.realized_r = -1.0
    s = tr.stats()
    assert s["resolved"] == 2
    assert s["win_rate"] == 50.0
    assert s["total_r"] == 2.0
    assert s["profit_factor"] == 3.0
