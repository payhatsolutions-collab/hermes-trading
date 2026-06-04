"""
Hermes Trading — NSE:NIFTY self-improving agent
Entrypoint. Parses --asset from goal.yaml (override with --asset flag).
Starts the 24/7 reliability loop.
"""
import argparse
import asyncio
import sys
from pathlib import Path
import yaml

# Add parent to path so imports work when run as: uv run python hermes_trading/run.py
sys.path.insert(0, str(Path(__file__).parent.parent))

from hermes_trading.loop import run_trading_loop
from hermes_trading.adapters.price import fetch_price_data


def load_goal():
    goal_path = Path(__file__).parent.parent / "state" / "goal.yaml"
    with open(goal_path) as f:
        return yaml.safe_load(f)


def main():
    parser = argparse.ArgumentParser(description="Hermes Trading Worker")
    parser.add_argument("--asset", default=None, help="Override asset from goal.yaml")
    args = parser.parse_args()

    goal = load_goal()
    asset = args.asset or goal.get("asset", "NSE:NIFTY")

    print(f"[Hermes Trading] Starting worker for {asset}")
    print(f"[Hermes Trading] Mode: {__import__('os').getenv('HERMES_TRADING_MODE', 'paper')}")

    try:
        asyncio.run(run_trading_loop(asset=asset, goal=goal))
    except KeyboardInterrupt:
        print("[Hermes Trading] Shutdown requested.")
    except Exception as e:
        print(f"[Hermes Trading] Fatal error: {e}")
        raise


if __name__ == "__main__":
    main()