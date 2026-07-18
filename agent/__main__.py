"""CLI entry point: python -m agent {run|dryrun|backfill|backtest}"""
from __future__ import annotations

import argparse
import asyncio
import logging
import sys


def main() -> None:
    parser = argparse.ArgumentParser(prog="agent", description="ETH/USDT private signal agent")
    sub = parser.add_subparsers(dest="cmd", required=True)

    sub.add_parser("run", help="Run the live agent (signals + telegram + dashboard)")
    sub.add_parser("dryrun", help="Run live analysis but log signals to console only")

    p_bf = sub.add_parser("backfill", help="Backfill historical klines into SQLite")
    p_bf.add_argument("--days", type=int, default=180, help="How many days back (default 180)")

    p_bt = sub.add_parser("backtest", help="Replay cached klines through the strategy engine")
    p_bt.add_argument("--from", dest="date_from", type=str, default=None, help="YYYY-MM-DD")
    p_bt.add_argument("--to", dest="date_to", type=str, default=None, help="YYYY-MM-DD")

    args = parser.parse_args()

    from agent.config import load_config

    cfg = load_config()
    logging.basicConfig(
        level=getattr(logging, str(cfg.logging.get("level", "INFO")).upper(), logging.INFO),
        format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
    )
    logging.getLogger("httpx").setLevel(logging.WARNING)

    try:
        if args.cmd in ("run", "dryrun"):
            from agent.app import App

            asyncio.run(App(cfg, dryrun=(args.cmd == "dryrun")).run())
        elif args.cmd == "backfill":
            from agent.backtest.runner import backfill_history

            asyncio.run(backfill_history(cfg, days=args.days))
        elif args.cmd == "backtest":
            from agent.backtest.runner import run_backtest

            asyncio.run(run_backtest(cfg, date_from=args.date_from, date_to=args.date_to))
    except KeyboardInterrupt:
        print("\nshutdown requested — bye")
        sys.exit(0)


if __name__ == "__main__":
    main()
