"""Tiny Cloudflare D1 HTTP helper shared by the digest scripts."""
import os

def _cfg():
    acct, tok, db = os.environ["CF_ACCOUNT_ID"], os.environ["CF_API_TOKEN"], os.environ["D1_DATABASE_ID"]
    return (f"https://api.cloudflare.com/client/v4/accounts/{acct}/d1/database/{db}/query",
            {"Authorization": f"Bearer {tok}", "Content-Type": "application/json"})

async def q(session, sql, params=None):
    url, headers = _cfg()
    body = {"sql": sql}
    if params:
        body["params"] = params
    async with session.post(url, headers=headers, json=body) as r:
        data = await r.json()
    if not data.get("success"):
        raise RuntimeError(f"D1: {data.get('errors')}")
    res = data.get("result", [])
    return res[0].get("results", []) if res else []
