"""
Score a list of trades against goal.yaml.
Returns a float in [-1, +1] — composite of:
  - realised return vs target
  - drawdown vs max
  - Sharpe vs minimum
"""
import statistics
from typing import List


def score(trades: List[dict], goal: dict) -> float:
    """
    Composite score in [-1, +1].
    Positive = meeting or exceeding goal.
    Zero = neutral. Negative = failing.
    """
    if not trades:
        return 0.0

    closed = [t for t in trades if "pnl_pct" in t or "outcome" in t]
    if not closed:
        return 0.0

    returns = [t.get("pnl_pct", 0) for t in closed]
    avg_return = statistics.mean(returns)
    max_dd = min(returns)  # most negative single trade
    std = statistics.stdev(returns) if len(returns) > 1 else 0.001

    target = goal.get("target_return_30d", 0.03)
    max_drawdown = goal.get("max_drawdown", 0.05)
    min_sharpe = goal.get("min_sharpe", 1.2)

    # Annualised Sharpe (daily returns × sqrt(252))
    sharpe = (avg_return / std) * (252 ** 0.5 / 100) if std > 0 else 0

    # Normalise each component to [-1, +1]
    # Return component: target met = 0, 2× target = +1, 0 return = -1
    return_score = max(-1, min(1, avg_return / target)) if target > 0 else 0

    # Drawdown component: max_dd of -5% on a 5% limit = -1
    dd_score = max(-1, min(1, max_dd / (-max_drawdown))) if max_drawdown > 0 else 0

    # Sharpe: min_sharpe met = 0, 2× min_sharpe = +1, 0 Sharpe = -1
    sharpe_score = max(-1, min(1, sharpe / (min_sharpe * 2))) if min_sharpe > 0 else 0

    # Composite (equal weights)
    composite = (return_score + dd_score + sharpe_score) / 3

    return round(composite, 4)


def score_breakdown(trades: List[dict], goal: dict) -> dict:
    """Detailed breakdown of score components."""
    if not trades:
        return {"composite": 0, "return_score": 0, "dd_score": 0, "sharpe_score": 0}

    closed = [t for t in trades if "pnl_pct" in t]
    returns = [t.get("pnl_pct", 0) for t in closed]
    avg_return = statistics.mean(returns) if returns else 0
    max_dd = min(returns) if returns else 0
    std = statistics.stdev(returns) if len(returns) > 1 else 0.001
    sharpe = (avg_return / std) * (252 ** 0.5 / 100) if std > 0 else 0

    target = goal.get("target_return_30d", 0.03)
    max_drawdown = goal.get("max_drawdown", 0.05)
    min_sharpe = goal.get("min_sharpe", 1.2)

    return_score = max(-1, min(1, avg_return / target)) if target > 0 else 0
    dd_score = max(-1, min(1, max_dd / (-max_drawdown))) if max_drawdown > 0 else 0
    sharpe_score = max(-1, min(1, sharpe / (min_sharpe * 2))) if min_sharpe > 0 else 0
    composite = (return_score + dd_score + sharpe_score) / 3

    return {
        "composite": round(composite, 4),
        "return_score": round(return_score, 4),
        "dd_score": round(dd_score, 4),
        "sharpe_score": round(sharpe_score, 4),
        "avg_return": round(avg_return, 4),
        "max_drawdown": round(max_dd, 4),
        "sharpe": round(sharpe, 4),
        "n_trades": len(closed),
    }