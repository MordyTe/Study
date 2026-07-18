"""Vercel serverless entry point — a single FastAPI (ASGI) app that serves:

- the dashboard UI + static assets
- /api/tick        the minute tick (protected by CRON_SECRET)
- /api/telegram    Telegram webhook (protected by secret token header)
- /api/*           dashboard data endpoints (Bybit REST proxy + Supabase)
- /api/health      startup diagnostics (always available)
- /settings        cloud backoffice

Deploy region must be non-US (e.g. fra1) — Bybit blocks US IPs.

Startup is crash-proof: if anything fails at import time, the app still
boots and serves the captured traceback from every route, so a broken
deploy is diagnosable from the browser instead of an opaque 500.
"""
from __future__ import annotations

import logging
import os
import sys
import traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from fastapi import FastAPI, Header, HTTPException, Request  # noqa: E402
from fastapi.responses import FileResponse, JSONResponse  # noqa: E402
from fastapi.staticfiles import StaticFiles  # noqa: E402
from pydantic import BaseModel  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
log = logging.getLogger("api")

STATIC_DIR = ROOT / "agent" / "web" / "static"
CONFIG_FILE = ROOT / "config" / "config.yaml"

# ---- guarded agent imports: never let a boot failure become an opaque 500
_boot_error: str | None = None
try:
    from agent.config import load_config
    from agent.cloud.supabase_repo import SupabaseRepo
    from agent.cloud.telegram_http import TelegramHttp
    from agent.cloud.tick import apply_runtime_overrides, run_tick
    from agent.data.bybit_rest import BybitRest
    from agent.delivery import formatting as fmt
    from agent.models import now_ms
except Exception:
    _boot_error = traceback.format_exc()
    log.error("agent import failed:\n%s", _boot_error)

app = FastAPI(title="ETH Signal Agent (cloud)")

ENV_SECRETS = ["TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID", "GEMINI_API_KEY",
               "SUPABASE_URL", "SUPABASE_SERVICE_KEY", "CRON_SECRET",
               "TELEGRAM_WEBHOOK_SECRET"]


@app.get("/api/health")
async def health():
    """Deployment diagnostics — booleans only, never secret values.

    Includes live connectivity probes so a single screenshot answers:
    which region are we in, can we reach Bybit (geo-block check),
    can we reach Supabase, and has the tick engine ever run.
    """
    config_ok, config_err = False, None
    if _boot_error is None:
        try:
            load_config(ROOT)
            config_ok = True
        except Exception as e:
            config_err = repr(e)

    out = {
        "boot_ok": _boot_error is None,
        "boot_error": _boot_error,
        "python": sys.version.split()[0],
        "region": os.environ.get("VERCEL_REGION", "unknown"),
        "commit": os.environ.get("VERCEL_GIT_COMMIT_SHA", "unknown")[:9],
        "config_loads": config_ok,
        "config_error": config_err,
        "static_dir_exists": STATIC_DIR.exists(),
        "env_set": {k: bool(os.environ.get(k)) for k in ENV_SECRETS},
    }
    if _boot_error is not None:
        return out

    # -- Bybit probe (catches US-region geo blocks) --
    try:
        cfg = load_config(ROOT)
        rest = BybitRest(cfg)
        t = await rest.get_tickers("linear", cfg.symbols["linear"])
        out["bybit"] = {"ok": True, "last_price": t.get("lastPrice"),
                        "funding": t.get("fundingRate")}
    except Exception as e:
        out["bybit"] = {"ok": False, "error": str(e)[:300],
                        "hint": "if region is a US one (iad1/sfo1/...), Bybit geo-blocks it — "
                                "set Function Region to Frankfurt (fra1) in Vercel project settings"}

    # -- Supabase probe --
    try:
        r = repo()
        tick_state = await r.get_state("tick", {}) or {}
        out["supabase"] = {"ok": True}
        out["tick_ever_ran"] = bool(tick_state.get("last_run_ms"))
        out["last_tick_ms"] = tick_state.get("last_run_ms")
        out["tick_fresh"] = bool(tick_state.get("last_run_ms")) and \
            now_ms() - int(tick_state.get("last_run_ms", 0)) < 180_000
        try:
            out["cron"] = await r.rpc("ta_tick_status")
        except Exception as e:
            out["cron"] = {"error": str(e)[:200]}
    except Exception as e:
        out["supabase"] = {"ok": False, "error": str(e)[:300]}
        out["tick_ever_ran"] = None
    return out


if _boot_error is not None:
    # Fallback mode: every route reports the boot failure.
    @app.api_route("/{path:path}", methods=["GET", "POST"])
    async def boot_failed(path: str):
        return JSONResponse(
            {"error": "agent failed to import at startup",
             "traceback": _boot_error,
             "hint": "see /api/health"},
            status_code=500,
        )
else:
    _repo: "SupabaseRepo | None" = None

    def repo() -> "SupabaseRepo":
        global _repo
        if _repo is None:
            _repo = SupabaseRepo()
        return _repo

    _token_cache: dict = {"value": None, "ts": 0}

    async def _db_tick_token() -> str | None:
        """Auto-generated token stored in Supabase (service-role-only readable).
        Lets the built-in pg_cron scheduler authenticate without anyone ever
        typing the CRON_SECRET."""
        if _token_cache["value"] and now_ms() - _token_cache["ts"] < 60_000:
            return _token_cache["value"]
        try:
            tok = await repo().get_state("tick_token", None)
            if isinstance(tok, dict):
                tok = tok.get("token")
            _token_cache.update(value=tok, ts=now_ms())
            return tok
        except Exception:
            return None

    async def _check_cron_auth(request: Request, authorization: str | None) -> None:
        supplied = request.query_params.get("secret") or (
            authorization.removeprefix("Bearer ").strip() if authorization else ""
        )
        if not supplied:
            raise HTTPException(401, "missing secret")
        secret = os.environ.get("CRON_SECRET", "")
        if secret and supplied == secret:
            return
        db_token = await _db_tick_token()
        if db_token and supplied == db_token:
            return
        raise HTTPException(401, "bad secret")

    # ---------------------------------------------------------------- tick
    @app.get("/api/tick")
    @app.post("/api/tick")
    async def tick(request: Request, authorization: str | None = Header(None)):
        await _check_cron_auth(request, authorization)
        cfg = load_config(ROOT)
        host = request.headers.get("x-forwarded-host") or request.headers.get("host")
        try:
            return await run_tick(cfg, repo(), site_host=host)
        except Exception as e:
            log.exception("tick failed")
            return JSONResponse({"ok": False, "error": str(e)}, status_code=500)

    # --------------------------------- 24/7 scheduler (Supabase pg_cron)
    @app.get("/api/setup-cron")
    async def setup_cron(request: Request, authorization: str | None = Header(None)):
        """Enable/disable the built-in minute scheduler — no external service."""
        await _check_cron_auth(request, authorization)
        r = repo()
        if request.query_params.get("disable"):
            result = await r.rpc("ta_disable_tick")
            status = await r.rpc("ta_tick_status")
            return {"ok": True, "result": result, "status": status}
        host = request.headers.get("x-forwarded-host") or request.headers.get("host")
        secret = os.environ.get("CRON_SECRET", "")
        tick_url = f"https://{host}/api/tick?secret={secret}"
        result = await r.rpc("ta_enable_tick", {"url": tick_url})
        status = await r.rpc("ta_tick_status")
        return {"ok": result == "scheduled", "result": result, "status": status,
                "note": "the engine now runs every minute, 24/7, powered by Supabase pg_cron"}

    # --------------------------------------- on-demand analysis (site-visible)
    @app.get("/api/analyze")
    async def analyze(request: Request, authorization: str | None = Header(None)):
        await _check_cron_auth(request, authorization)
        try:
            text = await _run_analysis()
        except Exception as e:
            log.exception("analyze failed")
            return JSONResponse({"ok": False, "error": str(e)[:300]}, status_code=500)
        await repo().set_state("last_analysis", {"text": text, "ts": now_ms()})
        return {"ok": True, "analysis": text, "ts": now_ms()}

    # ------------------------------------------ one-tap telegram webhook setup
    @app.get("/api/setup-telegram")
    async def setup_telegram(request: Request, authorization: str | None = Header(None)):
        """Registers this deployment as the bot's webhook — no manual curl."""
        await _check_cron_auth(request, authorization)
        token = os.environ.get("TELEGRAM_BOT_TOKEN", "")
        hook_secret = os.environ.get("TELEGRAM_WEBHOOK_SECRET", "")
        if not token:
            return JSONResponse({"ok": False, "error": "TELEGRAM_BOT_TOKEN not set"}, 500)
        host = request.headers.get("x-forwarded-host") or request.headers.get("host")
        webhook_url = f"https://{host}/api/telegram"
        import httpx
        async with httpx.AsyncClient(timeout=15) as client:
            r = await client.get(
                f"https://api.telegram.org/bot{token}/setWebhook",
                params={"url": webhook_url, "secret_token": hook_secret,
                        "drop_pending_updates": "true"},
            )
            tg_resp = r.json()
            info = (await client.get(
                f"https://api.telegram.org/bot{token}/getWebhookInfo")).json()
        return {"ok": tg_resp.get("ok", False), "webhook_url": webhook_url,
                "telegram_response": tg_resp.get("description"),
                "webhook_info": info.get("result", {}).get("url")}

    # ------------------------------------------------------ telegram webhook
    @app.post("/api/telegram")
    async def telegram_webhook(
        request: Request,
        x_telegram_bot_api_secret_token: str | None = Header(None),
    ):
        expected = os.environ.get("TELEGRAM_WEBHOOK_SECRET", "")
        if expected and x_telegram_bot_api_secret_token != expected:
            raise HTTPException(401, "bad webhook token")
        update = await request.json()
        tg = TelegramHttp()
        if not tg.allowed_update(update):
            return {"ok": True}
        cmd = tg.command_of(update)
        if cmd is None:
            return {"ok": True}

        r = repo()
        if cmd in ("start", "help"):
            await tg.send(
                "<b>ETH/USDT Signal Agent (cloud)</b>\n"
                "/status — market state and open signals\n"
                "/analyze — on-demand Gemini analysis\n"
                "/signals — recent signals\n/stats — performance"
            )
        elif cmd == "status":
            market = await r.get_state("market", {}) or {}
            tick_state = await r.get_state("tick", {}) or {}
            stats = await r.resolved_stats()
            open_sigs = await r.load_open_signals()
            fresh = now_ms() - int(tick_state.get("last_run_ms", 0)) < 180_000
            await tg.send(fmt.status_message(
                feed_ok=fresh, biases=market.get("biases", {}),
                deriv=market.get("deriv"), open_signals=open_sigs, stats=stats,
            ))
        elif cmd == "signals":
            rows = await r.recent_signals(10)
            if not rows:
                await tg.send("No signals yet.")
            else:
                lines = ["<b>Recent signals</b>"]
                for row in rows:
                    lines.append(
                        f"#{row['id']} {row['style']} {row['direction'].upper()} "
                        f"{row['entry_lo']}-{row['entry_hi']} · {row['state']}"
                        + (f" · {row['realized_r']:+}R" if row["realized_r"] is not None else "")
                    )
                await tg.send("\n".join(lines))
        elif cmd == "stats":
            await tg.send(fmt.stats_message(await r.resolved_stats()))
        elif cmd == "analyze":
            await tg.send("🔍 Running full analysis…")
            try:
                await tg.send(await _run_analysis())
            except Exception as e:
                await tg.send(f"analysis failed: {e}")
        return {"ok": True}

    async def _run_analysis() -> str:
        from agent.bus import Bus
        from agent.data.candles import CandleStore
        from agent.data.derivatives import DerivativesState
        from agent.engine.context import ContextBuilder
        from agent.llm.gemini import GeminiAnalyst

        cfg = load_config(ROOT)
        rest = BybitRest(cfg)
        bus = Bus()
        store = CandleStore(bus, cfg.active_tfs, cfg.buffer_bars)
        sc = cfg.styles["intraday"]
        tfs = list(dict.fromkeys([sc.entry_tf, *sc.gate_tfs, "D"]))
        for tf in tfs:
            store.seed(cfg.signal_market, tf,
                       await rest.backfill(cfg.signal_market, cfg.signal_symbol, tf, 800))
        deriv = DerivativesState()
        try:
            deriv.on_ticker(await rest.get_tickers("linear", cfg.symbols["linear"]))
            deriv.set_oi_series(await rest.get_open_interest(cfg.symbols["linear"]))
        except Exception:
            pass
        builder = ContextBuilder(cfg, store, flow=None, deriv=deriv)
        ctx = builder.build(cfg.signal_market, sc.entry_tf, tfs, now_ms())
        if ctx is None:
            return "Not enough data yet."
        llm = GeminiAnalyst(cfg)
        report = await llm.regime_report(ctx)
        return report or "LLM unavailable — set GEMINI_API_KEY in Vercel env vars."

    # ------------------------------------------------------- dashboard data
    @app.get("/api/candles")
    async def candles(tf: str = "5", limit: int = 500):
        cfg = load_config(ROOT)
        rest = BybitRest(cfg)
        rows = await rest.get_klines(cfg.signal_market, cfg.signal_symbol, tf,
                                     limit=min(limit, 1000))
        return [
            {"time": int(c.ts / 1000), "open": c.open, "high": c.high,
             "low": c.low, "close": c.close, "volume": c.volume}
            for c in rows
        ]

    @app.get("/api/signals")
    async def signals(limit: int = 50):
        return await repo().recent_signals(limit)

    @app.get("/api/stats")
    async def stats():
        return await repo().resolved_stats()

    @app.get("/api/state")
    async def state():
        r = repo()
        market = await r.get_state("market", {}) or {}
        tick_state = await r.get_state("tick", {}) or {}
        analysis = await r.get_state("last_analysis", None)
        return {
            "price": market.get("price"),
            "biases": market.get("biases", {}),
            "deriv": market.get("deriv"),
            "cvd_30m": None,
            "feed_ok": now_ms() - int(tick_state.get("last_run_ms", 0)) < 180_000,
            "last_tick_ms": tick_state.get("last_run_ms"),
            "analysis": analysis,
        }

    # --------------------------------------------------- cloud backoffice
    RUNTIME_KEYS = {
        "confluence_threshold": "Confluence threshold (e.g. 0.55)",
        "htf_gate_mode": "HTF gate mode (hard/soft)",
        "risk_pct": "Risk % per trade",
        "account_equity_usd": "Account equity USD",
        "llm_veto_mode": "LLM veto mode (annotate/suppress)",
    }

    class SettingUpdate(BaseModel):
        key: str
        value: str

    @app.get("/api/secrets")
    async def cloud_secrets():
        # Cloud: secrets are Vercel env vars — report set/unset only, never values
        return [
            {"key": k, "label": k, "is_set": bool(os.environ.get(k)),
             "masked": "set via Vercel env" if os.environ.get(k) else "", "readonly": True}
            for k in ENV_SECRETS
        ]

    @app.get("/api/runtime-settings")
    async def runtime_settings():
        stored = await repo().get_settings()
        cfg = load_config(ROOT)
        apply_runtime_overrides(cfg, stored)
        return [
            {"key": k, "label": label, "value": stored.get(k, ""),
             "effective": _effective(cfg, k)}
            for k, label in RUNTIME_KEYS.items()
        ]

    def _effective(cfg, key: str):
        return {
            "confluence_threshold": cfg.confluence.threshold,
            "htf_gate_mode": cfg.confluence.htf_gate_mode,
            "risk_pct": cfg.risk.risk_pct,
            "account_equity_usd": cfg.risk.account_equity_usd,
            "llm_veto_mode": cfg.llm.veto_mode,
        }.get(key)

    @app.post("/api/runtime-settings")
    async def set_runtime_setting(update: SettingUpdate):
        if update.key not in RUNTIME_KEYS:
            raise HTTPException(400, f"unknown setting: {update.key}")
        v = update.value.strip()
        if update.key in ("confluence_threshold", "risk_pct", "account_equity_usd") and v:
            try:
                float(v)
            except ValueError:
                raise HTTPException(400, "numeric value required")
        if update.key == "htf_gate_mode" and v not in ("", "hard", "soft"):
            raise HTTPException(400, "hard or soft")
        if update.key == "llm_veto_mode" and v not in ("", "annotate", "suppress"):
            raise HTTPException(400, "annotate or suppress")
        await repo().set_setting(update.key, v)
        return {"ok": True, "applied": "next tick"}

    @app.get("/api/config")
    async def get_config():
        cfg = load_config(ROOT)
        apply_runtime_overrides(cfg, await repo().get_settings())
        return {
            "signal_market": cfg.signal_market,
            "symbol": cfg.signal_symbol,
            "confluence": cfg.confluence.model_dump(),
            "risk": cfg.risk.model_dump(),
            "llm": {"enabled": cfg.llm.enabled, "veto_mode": cfg.llm.veto_mode,
                    "validate_model": cfg.llm.validate_model},
            "styles": {k: v.model_dump() for k, v in cfg.styles.items()},
            "mode": "cloud",
        }

    # ---------------------------------------------------------------- pages
    def _page(name: str):
        path = STATIC_DIR / name
        if path.exists():
            return FileResponse(path)
        return JSONResponse(
            {"error": f"{name} missing from deployment bundle", "hint": "see /api/health"},
            status_code=500,
        )

    @app.get("/")
    async def index():
        return _page("index.html")

    @app.get("/settings")
    async def settings_page():
        return _page("settings.html")

    if STATIC_DIR.exists():
        app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
    else:
        log.error("static dir missing at %s — dashboard assets unavailable", STATIC_DIR)
