# Placeholder: news adapter.
# Replace with NewsAPI / Alpha Vantage if activated.
# To activate: set NEWS_API_KEY in .env and implement fetch().
async def fetch(asset: str) -> dict:
    return {"schema_version": "1.0", "note": "news adapter not active"}