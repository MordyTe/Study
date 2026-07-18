"""Local dashboard: FastAPI REST + WebSocket push, static frontend.

Runs inside the same asyncio loop as the agent (uvicorn Server as a task).
Bound to 127.0.0.1 only.
"""
from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import asdict
from pathlib import Path

import numpy as np
import uvicorn
from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from agent.bus import Bus, CANDLE, SIGNAL_EVENT, SIGNAL_NEW
from agent.config import Config
from agent.data.candles import CandleStore
from agent.models import Signal
from agent.web.backoffice import EnvStore, SecretUpdate

log = logging.getLogger(__name__)

STATIC_DIR = Path(__file__).parent / "static"


class Dashboard:
    def __init__(self, cfg: Config, bus: Bus, store: CandleStore, services) -> None:
        self.cfg = cfg
        self.bus = bus
        self.store = store
        self.services = services  # AppServices duck-type: stats(), recent_signals(), state()
        self.app = FastAPI(title="ETH Signal Agent")
        self._clients: set[WebSocket] = set()
        self.env_store = EnvStore(Path(__file__).resolve().parent.parent.parent)
        self._setup_routes()

    def _setup_routes(self) -> None:
        app = self.app

        @app.get("/")
        async def index():
            return FileResponse(STATIC_DIR / "index.html")

        @app.get("/api/candles")
        async def candles(tf: str = "5", limit: int = 500):
            market = self.cfg.signal_market
            arr = self.store.series(market, tf).view()
            rows = np.asarray(arr)[-limit:]
            return [
                {"time": int(r[0] / 1000), "open": r[1], "high": r[2], "low": r[3], "close": r[4], "volume": r[5]}
                for r in rows
            ]

        @app.get("/api/signals")
        async def signals(limit: int = 50):
            return await self.services.recent_signals(limit)

        @app.get("/api/stats")
        async def stats():
            return self.services.stats()

        @app.get("/api/state")
        async def state():
            return await self.services.state()

        # ---- backoffice: API key management (localhost-only by binding) ----
        @app.get("/settings")
        async def settings_page():
            return FileResponse(STATIC_DIR / "settings.html")

        @app.get("/api/secrets")
        async def get_secrets():
            return self.env_store.read_masked()

        @app.post("/api/secrets")
        async def set_secret(update: SecretUpdate):
            try:
                self.env_store.set_secret(update.key, update.value)
            except ValueError as e:
                raise HTTPException(status_code=400, detail=str(e))
            return {"ok": True, "restart_required": True}

        @app.get("/api/config")
        async def get_config():
            c = self.cfg
            return {
                "signal_market": c.signal_market,
                "symbol": c.signal_symbol,
                "confluence": c.confluence.model_dump(),
                "risk": c.risk.model_dump(),
                "llm": {"enabled": c.llm.enabled, "veto_mode": c.llm.veto_mode,
                        "validate_model": c.llm.validate_model},
                "styles": {k: v.model_dump() for k, v in c.styles.items()},
            }

        @app.websocket("/ws")
        async def ws_endpoint(ws: WebSocket):
            await ws.accept()
            self._clients.add(ws)
            try:
                while True:
                    await ws.receive_text()  # keepalive/no-op
            except WebSocketDisconnect:
                pass
            finally:
                self._clients.discard(ws)

        app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

    async def _broadcast(self, payload: dict) -> None:
        dead = []
        for ws in self._clients:
            try:
                await ws.send_text(json.dumps(payload, default=str))
            except Exception:
                dead.append(ws)
        for ws in dead:
            self._clients.discard(ws)

    async def _pump_candles(self) -> None:
        async for market, tf, c in self.bus.stream(CANDLE):
            if market != self.cfg.signal_market or not self._clients:
                continue
            await self._broadcast({
                "type": "candle", "tf": tf,
                "bar": {"time": int(c.ts / 1000), "open": c.open, "high": c.high,
                        "low": c.low, "close": c.close, "volume": c.volume},
                "confirmed": c.confirmed,
            })

    async def _pump_signals(self) -> None:
        async for sig in self.bus.stream(SIGNAL_NEW):
            await self._broadcast({"type": "signal", "signal": _sig_dict(sig)})

    async def _pump_events(self) -> None:
        async for sig, frm, to, price in self.bus.stream(SIGNAL_EVENT):
            await self._broadcast({
                "type": "signal_event", "id": sig.id,
                "from": frm.value, "to": to.value, "price": price,
            })

    async def run(self) -> None:
        if not self.cfg.web.enabled:
            return
        config = uvicorn.Config(
            self.app, host=self.cfg.web.host, port=self.cfg.web.port,
            log_level="warning", loop="asyncio",
        )
        server = uvicorn.Server(config)
        log.info("dashboard at http://%s:%d", self.cfg.web.host, self.cfg.web.port)
        async with asyncio.TaskGroup() as tg:
            tg.create_task(server.serve())
            tg.create_task(self._pump_candles())
            tg.create_task(self._pump_signals())
            tg.create_task(self._pump_events())


def _sig_dict(sig: Signal) -> dict:
    return {
        "id": sig.id, "created_ts": sig.created_ts, "style": sig.style.value,
        "direction": sig.direction.value, "entry_lo": sig.entry_lo, "entry_hi": sig.entry_hi,
        "sl": sig.sl, "tp1": sig.tp1, "tp2": sig.tp2, "tp3": sig.tp3,
        "rr": sig.rr_tp2, "confidence": sig.confidence, "state": sig.state.value,
        "llm_verdict": sig.llm_verdict, "llm_reasoning": sig.llm_reasoning,
        "votes": [{"strategy": v.strategy, "score": v.score, "reasons": v.reasons} for v in sig.votes],
    }
