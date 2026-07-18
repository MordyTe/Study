"""Config loading: config/config.yaml for tunables + .env for secrets."""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import yaml
from dotenv import load_dotenv
from pydantic import BaseModel, Field


class StyleCfg(BaseModel):
    enabled: bool = True
    entry_tf: str
    trigger_tf: str | None = None
    gate_tfs: list[str]
    entry_ttl_minutes: int
    max_duration_minutes: int
    cooldown_minutes: int


class ConfluenceCfg(BaseModel):
    threshold: float = 0.55
    min_agreeing: int = 3
    htf_gate_mode: str = "hard"
    improve_delta: float = 0.15


class RiskCfg(BaseModel):
    account_equity_usd: float = 10000
    risk_pct: float = 1.0
    atr_stop_mult: float = 1.2
    stop_buffer_atr: float = 0.1
    min_rr_tp2: float = 1.5
    tp3_max_r: float = 3.5
    max_leverage: int = 5


class LlmCfg(BaseModel):
    enabled: bool = True
    validate_model: str = "gemini-2.5-flash"
    report_model: str = "gemini-2.5-pro"
    timeout_seconds: float = 12
    veto_mode: str = "annotate"
    regime_report_hours: int = 4


class WebCfg(BaseModel):
    enabled: bool = True
    host: str = "127.0.0.1"
    port: int = 8000


class StoreCfg(BaseModel):
    db_path: str = "data/agent.db"
    backtest_db_path: str = "data/backtest.db"


class WsCfg(BaseModel):
    watchdog_timeout_seconds: int = 30
    testnet: bool = False


class Secrets(BaseModel):
    telegram_bot_token: str = ""
    telegram_chat_id: str = ""
    gemini_api_key: str = ""
    bybit_api_key: str = ""
    bybit_api_secret: str = ""


class Config(BaseModel):
    symbols: dict[str, str]
    signal_market: str = "linear"
    timeframes: dict[str, Any]
    styles: dict[str, StyleCfg]
    confluence: ConfluenceCfg = ConfluenceCfg()
    strategy_weights: dict[str, float]
    strategies: dict[str, dict[str, Any]]
    risk: RiskCfg = RiskCfg()
    llm: LlmCfg = LlmCfg()
    telegram: dict[str, Any] = Field(default_factory=lambda: {"enabled": True})
    web: WebCfg = WebCfg()
    store: StoreCfg = StoreCfg()
    ws: WsCfg = WsCfg()
    logging: dict[str, Any] = Field(default_factory=lambda: {"level": "INFO"})
    secrets: Secrets = Secrets()

    @property
    def active_tfs(self) -> list[str]:
        return list(self.timeframes["active"])

    @property
    def buffer_bars(self) -> int:
        return int(self.timeframes.get("buffer_bars", 1500))

    @property
    def signal_symbol(self) -> str:
        return self.symbols[self.signal_market]

    def strategy_params(self, name: str) -> dict[str, Any]:
        return self.strategies.get(name, {})


def load_config(root: Path | None = None) -> Config:
    root = root or Path(__file__).resolve().parent.parent
    load_dotenv(root / ".env")
    with open(root / "config" / "config.yaml") as f:
        raw = yaml.safe_load(f)
    raw["secrets"] = Secrets(
        telegram_bot_token=os.getenv("TELEGRAM_BOT_TOKEN", ""),
        telegram_chat_id=os.getenv("TELEGRAM_CHAT_ID", ""),
        gemini_api_key=os.getenv("GEMINI_API_KEY", ""),
        bybit_api_key=os.getenv("BYBIT_API_KEY", ""),
        bybit_api_secret=os.getenv("BYBIT_API_SECRET", ""),
    )
    return Config(**raw)
