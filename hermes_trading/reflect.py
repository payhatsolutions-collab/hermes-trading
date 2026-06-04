"""
Deterministic reflection fallback — used before Hermes is installed.
T--fallback---fallback** pattern:

  If realised return < target → loosen entry.threshold by 2.
  If drawdown > max          → tighten stop_loss_pct by 0.2.
  Always changes exactly ONE variable.

Bumps version, saves prior to state/history/v{NNNN}.yaml,
appends hypothesis to state/hypotheses.jsonl.

With --hermes flag: reads last 25 trades + current strategy,
formats as prompt, calls hermes as a subprocess, parses the hypothesis.
"""
import argparse
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

import yaml
import aiofiles

STATE_DIR = Path(__file__).parent.parent / "state"
GOAL_FILE = STATE_DIR / "goal.yaml"
STRATEGY_FILE = STATE_DIR / "strategy.yaml"
HYPOTHESES_FILE = STATE_DIR / "hypotheses.jsonl"
TRADES_FILE = STATE_DIR / "trades.jsonl"


def load_goal():
    with open(GOAL_FILE) as f:
        return yaml.safe_load(f)


def load_strategy():
    with open(STRATEGY_FILE) as f:
        return yaml.safe_load(f)


def save_strategy(strategy: dict):
    with open(STRATEGY_FILE, "w") as f:
        yaml.dump(strategy, f, sort_keys=False)


def save_history(prior_strategy: dict, version: str):
    out = STATE_DIR / "history" / f"v{version}.yaml"
    with open(out, "w") as f:
        yaml.dump(prior_strategy, f, sort_keys=False)


def append_hypothesis(hypothesis: dict):
    with open(HYPOTHESES_FILE, "a") as f:
        f.write(json.dumps(hypothesis) + "\n")


def score_trades(trades: list, goal: dict) -> dict:
    """Score the last N closed trades against goal.yaml."""
    if not trades:
        return {"avg_return": 0, "max_drawdown": 0, "sharpe": 0, "win_rate": 0}

    returns = [t.get("pnl_pct", 0) for t in trades if "pnl_pct" in t]
    if not returns:
        return {"avg_return": 0, "max_drawdown": 0, "sharpe": 0, "win_rate": 0}

    import statistics
    avg_return = statistics.mean(returns)
    max_dd = min(returns)  # most negative
    wins = sum(1 for r in returns if r > 0)
    win_rate = wins / len(returns)

    # Simple Sharpe (assume 0 risk-free, annualised on daily)
    if len(returns) > 1 and statistics.stdev(returns) > 0:
        sharpe = (avg_return / statistics.stdev(returns)) * (252 ** 0.5 / 100)
    else:
        sharpe = 0

    return {
        "avg_return": avg_return,
        "max_drawdown": max_dd,
        "sharpe": sharpe,
        "win_rate": win_rate,
        "n_trades": len(returns),
    }


def deterministic_fallback(scores: dict, goal: dict, strategy: dict) -> tuple[dict, str]:
    """
    Run the T→fallback→fallback rules.
    Returns (hypothesis_dict, reason_string).
    Changes exactly ONE variable.
    """
    avg_return = scores.get("avg_return", 0)
    max_dd = scores.get("max_drawdown", 0)
    target = goal.get("target_return_30d", 0.03)
    max_drawdown = goal.get("max_drawdown", 0.05)

    changed_var = None
    old_val = None
    new_val = None
    reason = ""

    # Priority 1: if drawdown exceeded max, tighten stop loss
    if max_dd < -max_drawdown:
        old_val = strategy.get("stop_loss_pct", 2.0)
        new_val = round(old_val - 0.2, 1)
        strategy["stop_loss_pct"] = new_val
        changed_var = "stop_loss_pct"
        reason = f"max_drawdown {max_dd:.2f}% exceeded limit {max_drawdown*100:.0f}%. Tightening stop_loss_pct {old_val}→{new_val}."

    # Priority 2: if return below target, loosen entry threshold
    elif avg_return < target:
        old_val = strategy.get("entry", {}).get("threshold", 30)
        new_val = max(10, old_val - 2)  # minimum 10 RSI
        if "entry" not in strategy:
            strategy["entry"] = {}
        strategy["entry"]["threshold"] = new_val
        changed_var = "entry.threshold"
        reason = f"avg_return {avg_return:.2f}% below target {target*100:.0f}%. Loosening entry.threshold {old_val}→{new_val}."

    else:
        reason = "No rule triggered — scores within goal parameters. No change made."

    hypothesis = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "trigger": "deterministic_fallback",
        "scores": scores,
        "goal": goal,
        "changed_variable": changed_var,
        "old_value": old_val,
        "new_value": new_val,
        "reason": reason,
    }
    return strategy, hypothesis, reason


async def hermes_mode(trades: list, strategy: dict, goal: dict) -> tuple[dict, str]:
    """
    Production mode. Format last 25 trades + strategy as a prompt,
    call hermes as subprocess, parse the single variable change.
    """
    recent = trades[-25:] if len(trades) >= 25 else trades

    prompt = f"""You are the reflection brain of a self-improving trading agent.

Current goal.yaml:
{yaml.dump(goal)}

Current strategy.yaml (version {strategy.get('version','?')}):
{yaml.dump(strategy)}

Last {len(recent)} closed trades:
{json.dumps(recent, indent=2)}

Task: Score these trades against goal.yaml.
  - target_return_30d: {goal.get('target_return_30d')*100:.0f}%
  - max_drawdown: {goal.get('max_drawdown')*100:.0f}%
  - min_sharpe: {goal.get('min_sharpe')}

Generate exactly ONE hypothesis. Name the ONE variable in strategy.yaml to change,
predict the score direction, and explain in one sentence.

Output format (JSON only, no markdown):
{{"changed_variable": "entry.threshold", "old_value": 30, "new_value": 26, "reason": "RSI 30 is too tight for this regime"}}
"""

    try:
        result = subprocess.run(
            ["hermes", "--think", prompt],
            capture_output=True,
            text=True,
            timeout=30,
        )
        output = result.stdout.strip()
        # Try to parse JSON from output
        import re
        match = re.search(r"\{.*\}", output, re.DOTALL)
        if match:
            parsed = json.loads(match.group())
            hypothesis = {
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "trigger": "hermes",
                "scores": {},
                "goal": goal,
                **parsed,
            }
            # Apply change
            parts = parsed.get("changed_variable", "").split(".")
            if len(parts) == 2:
                if parts[0] not in strategy:
                    strategy[parts[0]] = {}
                strategy[parts[0]][parts[1]] = parsed.get("new_value")
            elif len(parts) == 1:
                strategy[parts[0]] = parsed.get("new_value")
            reason = parsed.get("reason", "")
            return strategy, hypothesis, reason
        else:
            return strategy, {}, f"Hermes output unparseable: {output[:200]}"
    except FileNotFoundError:
        return strategy, {}, "hermes command not found — falling back to deterministic"
    except Exception as e:
        return strategy, {}, f"hermes error: {e}"


def bump_version(strategy: dict) -> str:
    v = strategy.get("version", "01")
    num = int(v)
    return f"{num + 1:02d}"


async def run_reflection(hermes: bool = False):
    goal = load_goal()
    strategy = load_strategy()
    prior_version = strategy.get("version", "01")

    # Load all closed trades
    trades = []
    if TRADES_FILE.exists():
        with open(TRADES_FILE) as f:
            for line in f:
                t = json.loads(line)
                if "closed_at" in t or "outcome" in t:
                    trades.append(t)

    scores = score_trades(trades, goal)
    print(f"[Reflect] Scoring {len(trades)} closed trades: {scores}")

    if hermes:
        strategy, hypothesis, reason = await hermes_mode(trades, strategy, goal)
    else:
        strategy, hypothesis, reason = deterministic_fallback(scores, goal, strategy)

    new_version = bump_version(strategy)
    strategy["version"] = new_version

    if hypothesis:
        # Save prior version to history
        save_history({"version": prior_version, **strategy.copy()}, prior_version)
        # Write new strategy
        save_strategy(strategy)
        # Append hypothesis
        append_hypothesis(hypothesis)
        print(f"[Reflect] ✅ Version {prior_version} → v{new_version}")
        print(f"[Reflect] Changed: {hypothesis.get('changed_variable')} {hypothesis.get('old_value')} → {hypothesis.get('new_value')}")
        print(f"[Reflect] Reason: {reason}")
    else:
        print(f"[Reflect] No change needed: {reason}")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--fallback", action="store_true", help="Force deterministic fallback (no Hermes)")
    parser.add_argument("--hermes", action="store_true", help="Use Hermes for reflection")
    args = parser.parse_args()

    import asyncio
    asyncio.run(run_reflection(hermes=args.hermes and not args.fallback))


if __name__ == "__main__":
    main()