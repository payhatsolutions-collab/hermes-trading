"""
Macro adapter — Nifty 50 index context (index RSI, trend).
Free public endpoint via Yahoo Finance.
"""
import asyncio
from typing import Optional


async def fetch(asset: str = "NSE:NIFTY") -> dict:
    """Fetch macro context: index price, RSI, and position relative to SMA50/200."""
    import urllib.request, json

    url = "https://query1.finance.yahoo.com/v8/finance/chart/%5ENSEI?interval=1d&range=3mo"
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})

    loop = asyncio.get_event_loop()
    raw = await loop.run_in_executor(None, lambda: urllib.request.urlopen(req, timeout=15).read())
    result = json.loads(raw)["chart"]["result"][0]

    closes = [c for c in result["indicators"]["quote"][0]["close"] if c is not None]
    if len(closes) < 60:
        raise ValueError("Not enough data for SMA")

    price = result["meta"].get("regularMarketPrice", closes[-1])
    sma50 = sum(closes[-50:]) / 50
    sma200 = sum(closes[-200:]) / 200 if len(closes) >= 200 else sma50

    # Index RSI
    cs = closes
    ds = [cs[i] - cs[i - 1] for i in range(1, len(cs))]
    gains = [d for d in ds[-14:] if d > 0]
    losses = [-d for d in ds[-14:] if d < 0]
    ag = sum(gains) / 14 or 0.001
    al = sum(losses) / 14 or 0.001
    rsi = 100 - (100 / (1 + ag / al))

    # Regime
    if price > sma50 > sma200:
        regime = "BULL"
    elif price > sma200:
        regime = "RECOVERY"
    else:
        regime = "BEAR"

    return {
        "schema_version": "1.0",
        "index": "^NSEI",
        "price": float(price),
        "sma50": float(sma50),
        "sma200": float(sma200),
        "rsi": round(float(rsi), 2),
        "regime": regime,
        "source": "yfinance",
    }


# Convenience alias
fetch_macro_data = fetch