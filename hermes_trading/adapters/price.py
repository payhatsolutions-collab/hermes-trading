"""
Price adapter for NSE:NIFTY (and other NSE stocks) via yfinance.
Free, no API key. Falls back to Yahoo Finance REST.
"""
import asyncio
from typing import Optional


async def fetch(asset: str) -> dict:
    """
    Fetch price + RSI for asset.
    asset format: "NSE:NIFTY" or "RELIANCE.NS" etc.
    Returns dict with: price, rsi(14), schema_version.
    """
    import urllib.request, json

    # Normalise ticker for yfinance
    ticker = asset.replace("NSE:", "").replace("NS", "").strip()
    if "." not in ticker:
        ticker = f"{ticker}.NS"

    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{ticker}?interval=1d&range=3mo"
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})

    loop = asyncio.get_event_loop()
    raw = await loop.run_in_executor(None, lambda: urllib.request.urlopen(req, timeout=15).read())
    result = json.loads(raw)["chart"]["result"][0]

    closes = [c for c in result["indicators"]["quote"][0]["close"] if c is not None]
    if not closes:
        raise ValueError(f"No price data for {ticker}")

    price = result["meta"].get("regularMarketPrice", closes[-1])

    # RSI-14
    cs = closes
    ds = [cs[i] - cs[i - 1] for i in range(1, len(cs))]
    gains = [d for d in ds[-14:] if d > 0]
    losses = [-d for d in ds[-14:] if d < 0]
    ag = sum(gains) / 14 or 0.001
    al = sum(losses) / 14 or 0.001
    rsi = 100 - (100 / (1 + ag / al))

    return {
        "schema_version": "1.0",
        "ticker": ticker,
        "price": float(price),
        "rsi": round(float(rsi), 2),
        "close_0": closes[-1] if closes else None,
        "source": "yfinance",
    }


# Convenience alias
fetch_price_data = fetch