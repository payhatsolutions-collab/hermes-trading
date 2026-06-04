"""
24/7 reliability loop. Every minute: pull data, evaluate strategy,
decide (paper trade if entry fires), log outcome, write heartbeat.
Per-adapter retries (3, exponential backoff). Circuit-break after
5 consecutive failures.
"""
import asyncio
import json
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml
import aiofiles

from hermes_trading.adapters.price import fetch_price_data
from hermes_trading.adapters.macro import fetch_macro_data
from hermes_trading import score as score_module


TRADES_FILE = Path(__file__).parent.parent / "state" / "trades.jsonl"
HEARTBEAT_FILE = Path(__file__).parent.parent / "state" / "heartbeat.json"
STRATEGY_FILE = Path(__file__).parent.parent / "state" / "strategy.yaml"
GOAL_FILE = Path(__file__).parent.parent / "state" / "goal.yaml"

MAX_RETRIES = 3
CIRCUIT_BREAK_THRESHOLD = 5


async def log_trade(trade: dict):
    async with aiofiles.open(TRADES_FILE, "a") as f:
        await f.write(json.dumps(trade) + "\n")


async def write_heartbeat(data: dict):
    async with aiofiles.open(HEARTBEAT_FILE, "w") as f:
        await f.write(json.dumps(data, indent=2))


def load_strategy() -> dict:
    with open(STRATEGY_FILE) as f:
        return yaml.safe_load(f)


def load_goal() -> dict:
    with open(GOAL_FILE) as f:
        return yaml.safe_load(f)


async def fetch_with_retry(adapters: list, asset: str) -> tuple[dict | None, list[str]]:
    """
    Fetch from adapters in order. Retry each up to MAX_RETRIES with exponential backoff.
    Returns (data, errors). Halts after CIRCUIT_BREAK_THRESHOLD consecutive failures.
    """
    results = {}
    errors = []
    consecutive_failures = 0

    for adapter_fn, name in adapters:
        for attempt in range(MAX_RETRIES):
            try:
                data = await adapter_fn(asset)
                if data and data.get("price") is not None:
                    results[name] = data
                    consecutive_failures = 0
                    break
            except Exception as e:
                await asyncio.sleep(2 ** attempt)  # exponential backoff
                consecutive_failures += 1
                errors.append(f"[{name}] attempt {attempt+1} failed: {e}")
                if consecutive_failures >= CIRCUIT_BREAK_THRESHOLD:
                    errors.append(f"CIRCUIT BREAK triggered after {CIRCUIT_BREAK_THRESHOLD} consecutive failures")
                    return None, errors
        else:
            errors.append(f"[{name}] all {MAX_RETRIES} attempts failed")

    return results if results else None, errors


def decide_entry(price_data: dict, strategy: dict, prior_trades: list) -> dict | None:
    """
    Evaluate entry condition. Returns trade signal dict or None.
    Uses RSI threshold from strategy.yaml.
    """
    rsi = price_data.get("rsi", 50)
    price = price_data.get("price", 0)
    threshold = strategy.get("entry", {}).get("threshold", 30)
    direction = strategy.get("entry", {}).get("direction", "long")

    if direction == "long" and rsi <= threshold:
        stop_loss_pct = strategy.get("stop_loss_pct", 2.0)
        position_size_r = strategy.get("position_size_r", 0.5)
        stop_price = price * (1 - stop_loss_pct / 100)
        return {
            "direction": "long",
            "entry_price": price,
            "stop_price": stop_price,
            "position_size_r": position_size_r,
            "signal": "entry",
            "rsi_at_entry": rsi,
        }
    return None


async def run_trading_loop(asset: str, goal: dict):
    """Main async loop. Runs forever, sleeping 60s between cycles."""
    print(f"[Loop] Starting for {asset}. Mode: paper. Ctrl-C to stop.")

    adapters = [
        (lambda a: fetch_price_data(a), "price"),
        (lambda a: fetch_macro_data(a), "macro"),
    ]

    trade_open = None

    while True:
        cycle_start = time.time()
        print(f"[Loop] Cycle {datetime.now(timezone.utc):%H:%M:%S} UTC — fetching data...")

        all_data, errors = await fetch_with_retry(adapters, asset)

        for err in errors:
            print(f"  {err}")

        if not all_data:
            print("[Loop] No data fetched. Sleeping 60s.")
            await asyncio.sleep(60)
            continue

        price_data = all_data.get("price", {})
        strategy = load_strategy()
        goal_cfg = load_goal()

        # Evaluate entry
        if trade_open is None:
            signal = decide_entry(price_data, strategy, [])
            if signal:
                print(f"[Loop] 🟢 ENTRY SIGNAL — {signal}")
                trade_open = {
                    **signal,
                    "opened_at": datetime.now(timezone.utc).isoformat(),
                    "asset": asset,
                }
                await log_trade(trade_open)
        else:
            # Check stop loss
            current_price = price_data.get("price", 0)
            stop_price = trade_open["stop_price"]
            if current_price > 0 and current_price <= stop_price:
                pnl_pct = (current_price - trade_open["entry_price"]) / trade_open["entry_price"] * 100
                trade_open.update({
                    "closed_at": datetime.now(timezone.utc).isoformat(),
                    "exit_price": current_price,
                    "pnl_pct": pnl_pct,
                    "outcome": "stopped_out",
                })
                print(f"[Loop] 🔴 STOPPED OUT at ₹{current_price:.2f} — PnL {pnl_pct:.2f}%")
                await log_trade(trade_open)
                trade_open = None
            elif current_price > 0:
                unrealised_pnl = (current_price - trade_open["entry_price"]) / trade_open["entry_price"] * 100
                print(f"[Loop] Position open: entry ₹{trade_open['entry_price']:.2f} | current ₹{current_price:.2f} | unrealised {unrealised_pnl:+.2f}%")

        # Heartbeat
        await write_heartbeat({
            "last_cycle": datetime.now(timezone.utc).isoformat(),
            "asset": asset,
            "price": price_data.get("price"),
            "rsi": price_data.get("rsi"),
            "position_open": trade_open is not None,
            "strategy_version": strategy.get("version"),
        })

        elapsed = time.time() - cycle_start
        sleep_time = max(0, 60 - elapsed)
        print(f"[Loop] Cycle done in {elapsed:.1f}s. Sleeping {sleep_time:.0f}s.")
        await asyncio.sleep(sleep_time)