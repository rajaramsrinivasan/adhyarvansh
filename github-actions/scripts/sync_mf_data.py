"""
sync_mf_data.py  —  Fast async MF sync
Uses 40 parallel requests — syncs ~6000 equity/hybrid funds in ~10-15 minutes
Writes to Cloudflare D1 via REST API

GitHub Secrets needed:
  CF_ACCOUNT_ID   — Cloudflare account ID
  CF_API_TOKEN    — Cloudflare API token (D1:Edit permission)
  D1_DATABASE_ID  — D1 database ID
"""

import os, json, time, logging, asyncio, aiohttp
from datetime import datetime
from dateutil.relativedelta import relativedelta

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)

CF_ACCOUNT_ID  = os.environ["CF_ACCOUNT_ID"]
CF_API_TOKEN   = os.environ["CF_API_TOKEN"]
D1_DATABASE_ID = os.environ["D1_DATABASE_ID"]

D1_URL     = f"https://api.cloudflare.com/client/v4/accounts/{CF_ACCOUNT_ID}/d1/database/{D1_DATABASE_ID}/query"
MFAPI_BASE = "https://api.mfapi.in/mf"

TARGET_CATEGORIES = {"Equity", "Hybrid"}
MAX_FUNDS   = 6000
CONCURRENCY = 40


async def d1_upsert(session, row):
    headers = {"Authorization": f"Bearer {CF_API_TOKEN}", "Content-Type": "application/json"}
    body = {
        "sql": """INSERT INTO mf_cache
            (scheme_code,fund_name,category,sub_category,amc_name,
             latest_nav,nav_date,return_1y,return_3y,return_5y,last_synced)
          VALUES (?,?,?,?,?,?,?,?,?,?,datetime('now'))
          ON CONFLICT(scheme_code) DO UPDATE SET
            fund_name=excluded.fund_name, category=excluded.category,
            sub_category=excluded.sub_category, amc_name=excluded.amc_name,
            latest_nav=excluded.latest_nav, nav_date=excluded.nav_date,
            return_1y=excluded.return_1y, return_3y=excluded.return_3y,
            return_5y=excluded.return_5y, last_synced=excluded.last_synced""",
        "params": [row["scheme_code"], row["fund_name"], row["category"],
                   row["sub_category"], row["amc_name"], row["latest_nav"],
                   row["nav_date"], row["return_1y"], row["return_3y"], row["return_5y"]]
    }
    async with session.post(D1_URL, headers=headers, json=body) as r:
        data = await r.json()
        if not data.get("success"):
            raise Exception(str(data.get("errors", "")))


def calc_cagr(nav_data, years):
    if not nav_data or len(nav_data) < 2:
        return None
    try:
        latest_nav  = float(nav_data[0]["nav"])
        latest_date = datetime.strptime(nav_data[0]["date"], "%d-%m-%Y")
        target_date = latest_date - relativedelta(years=years)
        for entry in nav_data:
            d = datetime.strptime(entry["date"], "%d-%m-%Y")
            if d <= target_date:
                past_nav = float(entry["nav"])
                if past_nav <= 0: return None
                return round(((latest_nav / past_nav) ** (1 / years) - 1) * 100, 2)
        return None
    except Exception:
        return None


def infer_category(name):
    n = name.upper()
    if any(x in n for x in ["LIQUID","OVERNIGHT","MONEY MARKET","ULTRA SHORT"]): return "Debt","Liquid"
    if any(x in n for x in ["GILT","G-SEC"]): return "Debt","Gilt"
    if any(x in n for x in ["DEBT","BOND","INCOME","CREDIT RISK","SHORT TERM","MEDIUM TERM"]): return "Debt","Debt"
    if "ARBITRAGE" in n: return "Hybrid","Arbitrage"
    if any(x in n for x in ["BALANCED ADVANTAGE","DYNAMIC ASSET"]): return "Hybrid","Balanced Advantage"
    if any(x in n for x in ["HYBRID","BALANCED","EQUITY SAVINGS","MULTI ASSET"]): return "Hybrid","Hybrid"
    if any(x in n for x in ["INDEX","NIFTY","SENSEX"]): return "Equity","Index"
    if any(x in n for x in ["ELSS","TAX SAVER","TAX SAVING"]): return "Equity","ELSS"
    if any(x in n for x in ["SMALL CAP","SMALLCAP"]): return "Equity","Small Cap"
    if any(x in n for x in ["MID CAP","MIDCAP"]): return "Equity","Mid Cap"
    if any(x in n for x in ["LARGE CAP","LARGECAP","BLUECHIP","TOP 100"]): return "Equity","Large Cap"
    if any(x in n for x in ["FLEXI CAP","FLEXICAP","MULTI CAP","MULTICAP"]): return "Equity","Flexi Cap"
    if "EQUITY" in n or "GROWTH" in n: return "Equity","Equity"
    if any(x in n for x in ["GOLD","SILVER"]): return "Other","Commodity"
    return "Debt","Other"


def extract_amc(name):
    for amc in ["SBI","HDFC","ICICI Prudential","Axis","Kotak","Nippon India",
                "Mirae Asset","Canara Robeco","DSP","Franklin Templeton","Tata",
                "UTI","Aditya Birla Sun Life","Sundaram","Motilal Oswal","Quant",
                "WhiteOak","Parag Parikh","Groww","Bandhan","Edelweiss","Invesco","PGIM India"]:
        if amc.upper() in name.upper(): return amc
    return name.split()[0] if name else "Unknown"


async def fetch_and_store(session, scheme_code, fund_name, semaphore):
    async with semaphore:
        cat, sub = infer_category(fund_name)
        if cat not in TARGET_CATEGORIES:
            return False

        url = f"{MFAPI_BASE}/{scheme_code}"
        for attempt in range(3):
            try:
                async with session.get(url, timeout=aiohttp.ClientTimeout(total=20)) as r:
                    if r.status != 200: return False
                    data = await r.json()
                nav_data = data.get("data", [])
                if not nav_data: return False

                row = {
                    "scheme_code":  str(scheme_code),
                    "fund_name":    fund_name,
                    "category":     cat,
                    "sub_category": sub,
                    "amc_name":     extract_amc(fund_name),
                    "latest_nav":   float(nav_data[0]["nav"]),
                    "nav_date":     nav_data[0]["date"],
                    "return_1y":    calc_cagr(nav_data, 1),
                    "return_3y":    calc_cagr(nav_data, 3),
                    "return_5y":    calc_cagr(nav_data, 5),
                }
                await d1_upsert(session, row)
                return True
            except asyncio.TimeoutError:
                if attempt < 2: await asyncio.sleep(2)
            except Exception as e:
                if attempt < 2: await asyncio.sleep(1)
                else: log.warning(f"Failed {scheme_code}: {e}")
        return False


async def main():
    start = time.time()
    log.info("Starting fast async MF sync...")

    connector = aiohttp.TCPConnector(limit=CONCURRENCY, ttl_dns_cache=300)
    async with aiohttp.ClientSession(connector=connector) as session:
        async with session.get(MFAPI_BASE) as r:
            all_funds = await r.json()
        log.info(f"Total funds: {len(all_funds)} — filtering to equity/hybrid...")

        # Pre-filter by name to avoid fetching unwanted funds
        target = [(f["schemeCode"], f["schemeName"]) for f in all_funds
                  if infer_category(f["schemeName"])[0] in TARGET_CATEGORIES][:MAX_FUNDS]
        log.info(f"Processing {len(target)} equity/hybrid funds with {CONCURRENCY} parallel workers")

        semaphore = asyncio.Semaphore(CONCURRENCY)
        tasks     = [fetch_and_store(session, code, name, semaphore) for code, name in target]

        synced = 0
        errors = 0
        batch  = 500
        for i in range(0, len(tasks), batch):
            results = await asyncio.gather(*tasks[i:i+batch], return_exceptions=True)
            synced += sum(1 for r in results if r is True)
            errors += sum(1 for r in results if r is False or isinstance(r, Exception))
            elapsed = round(time.time() - start)
            log.info(f"Progress: {min(i+batch,len(tasks))}/{len(target)} | synced={synced} | {elapsed}s")

    total = round(time.time() - start)
    log.info(f"✅ Done — {synced} funds synced in {total//60}m {total%60}s")
    return synced


if __name__ == "__main__":
    asyncio.run(main())
