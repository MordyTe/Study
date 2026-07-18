"""Gemini second-opinion layer.

Strictly bounded (timeout + semaphore + 1 retry) and fail-open: if the LLM
is unavailable the signal ships anyway with "LLM analysis unavailable".
Never the primary signal source.
"""
from __future__ import annotations

import asyncio
import json
import logging
import time

from agent.config import Config
from agent.engine.context import MarketContext
from agent.llm import prompts
from agent.models import Signal, now_ms
from agent.store.repo import Repo

log = logging.getLogger(__name__)


class GeminiAnalyst:
    def __init__(self, cfg: Config, repo: Repo | None = None) -> None:
        self.cfg = cfg
        self.repo = repo
        self._sem = asyncio.Semaphore(1)
        self._client = None
        if cfg.llm.enabled and cfg.secrets.gemini_api_key:
            try:
                from google import genai
                self._client = genai.Client(api_key=cfg.secrets.gemini_api_key)
            except Exception as e:
                log.warning("gemini client init failed: %s — running without LLM", e)

    @property
    def available(self) -> bool:
        return self._client is not None

    async def _generate(self, model: str, system: str, prompt: str,
                        json_schema: dict | None = None) -> str | None:
        if self._client is None:
            return None
        from google.genai import types

        config = types.GenerateContentConfig(
            system_instruction=system,
            temperature=0.3,
            **({"response_mime_type": "application/json",
                "response_schema": json_schema} if json_schema else {}),
        )
        timeout = self.cfg.llm.timeout_seconds
        async with self._sem:
            for attempt in range(2):
                t0 = time.monotonic()
                try:
                    resp = await asyncio.wait_for(
                        self._client.aio.models.generate_content(
                            model=model, contents=prompt, config=config),
                        timeout=timeout,
                    )
                    latency = int((time.monotonic() - t0) * 1000)
                    if self.repo:
                        await self.repo.log_llm_call(now_ms(), "generate", model, latency, True)
                    return resp.text
                except Exception as e:
                    latency = int((time.monotonic() - t0) * 1000)
                    if self.repo:
                        try:
                            await self.repo.log_llm_call(now_ms(), "generate", model, latency, False)
                        except Exception:
                            pass
                    if attempt == 0:
                        log.warning("gemini call failed (%s) — one retry", e)
                        await asyncio.sleep(2)
                    else:
                        log.error("gemini call failed twice: %s — failing open", e)
        return None

    async def validate_signal(self, sig: Signal, ctx: MarketContext) -> None:
        """Attach verdict + reasoning to the signal in place. Fail-open."""
        if not self.available:
            return
        ctx_json = prompts.serialize_context(ctx)
        raw = await self._generate(
            self.cfg.llm.validate_model, prompts.VALIDATE_SYSTEM,
            prompts.validate_prompt(sig, ctx_json), prompts.VALIDATE_SCHEMA,
        )
        if raw is None:
            return
        try:
            data = json.loads(raw)
            sig.llm_verdict = data.get("verdict")
            reasoning = data.get("reasoning", "")
            risks = data.get("risks") or []
            if risks:
                reasoning += " | Risks: " + "; ".join(risks[:3])
            sig.llm_reasoning = reasoning[:900]
        except (json.JSONDecodeError, TypeError) as e:
            log.warning("gemini verdict unparseable: %s", e)

    async def regime_report(self, ctx: MarketContext) -> str | None:
        if not self.available:
            return None
        ctx_json = prompts.serialize_context(ctx)
        return await self._generate(
            self.cfg.llm.report_model, prompts.REGIME_SYSTEM,
            prompts.regime_prompt(ctx_json),
        )
