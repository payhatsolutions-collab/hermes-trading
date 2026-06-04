# Placeholder: on-chain data adapter (for crypto; not used for NSE:NIFTY)
# Replace with Glassnode / CryptoQuant if adding crypto legs.
# To activate: set ONCHAIN_API_KEY in .env and implement fetch()
async def fetch(asset: str) -> dict:
    return {"schema_version": "1.0", "note": "on-chain adapter not active for NSE:NIFTY"}