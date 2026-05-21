"""
sync_mf_data.py
Fetches all Indian mutual fund NAVs from mfapi.in
Calculates 1Y / 3Y / 5Y CAGR returns
Stores everything in Neon PostgreSQL mf_cache table

Run: python sync_mf_data.py
Schedule: GitHub Actions cron — daily 8 AM IST (2:30 AM UTC)
"""

import os
import json
import time
import logging
import psycopg2
import psycopg2.extras
import requests
from datetime import datetime, date, timedelta
from dateutil.relativedelta import relativedelta

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)

DATABASE_URL = os.environ["DATABASE_URL"]
MFAPI_BASE   = "https://api.mfapi.in/mf"

# ── Helpers ───────────────────────────────────────────────────────────────────

def get_conn():
    return psycopg2.connect(DATABASE_URL, cursor_factory=psycopg2.extras.RealDictCursor)

def fetch_json(url, retries=3, delay=2):
    for i in range(retries):
        try:
            r = requests.get(url, timeout=15)
            r.raise_for_status()
            return r.json()
        except Exception as e:
            if i < retries - 1:
                log.warning(f"Retry {i+1} for {url}: {e}")
                time.sleep(delay)
            else:
                raise

def calc_cagr(nav_history, years):
    """
    Calculate CAGR over given years using NAV history.
    nav_history: list of {"date": "DD-MM-YYYY", "nav": "123.45"} sorted newest first
    Returns CAGR % rounded to 2 decimal places, or None if not enough history
    """
    if not nav_history or len(nav_history) < 2:
        return None

    try:
        latest_nav  = float(nav_history[0]["nav"])
        latest_date = datetime.strptime(nav_history[0]["date"], "%d-%m-%Y")
        target_date = latest_date - relativedelta(years=years)

        # Find the NAV closest to target_date
        past_nav = None
        for entry in nav_history:
            entry_date = datetime.strptime(entry["date"], "%d-%m-%Y")
            if entry_date <= target_date:
                past_nav = float(entry["nav"])
                break

        if past_nav is None or past_nav <= 0:
            return None

        # CAGR = (end/start)^(1/years) - 1
        cagr = ((latest_nav / past_nav) ** (1 / years) - 1) * 100
        return round(cagr, 2)
    except Exception as e:
        log.debug(f"CAGR calc error: {e}")
        return None

def infer_category(scheme_name: str) -> tuple:
    """Simple rule-based category inference from fund name."""
    name = scheme_name.upper()

    if any(x in name for x in ["LIQUID", "OVERNIGHT", "MONEY MARKET"]):
        return "Debt", "Liquid"
    if any(x in name for x in ["GILT", "G-SEC", "GOVERNMENT"]):
        return "Debt", "Gilt"
    if any(x in name for x in ["DEBT", "BOND", "INCOME", "CREDIT RISK", "SHORT TERM", "MEDIUM TERM", "LONG TERM"]):
        return "Debt", "Debt"
    if any(x in name for x in ["ARBITRAGE"]):
        return "Hybrid", "Arbitrage"
    if any(x in name for x in ["BALANCED ADVANTAGE", "DYNAMIC ASSET"]):
        return "Hybrid", "Balanced Advantage"
    if any(x in name for x in ["HYBRID", "BALANCED", "EQUITY SAVINGS", "MULTI ASSET"]):
        return "Hybrid", "Hybrid"
    if any(x in name for x in ["INDEX", "NIFTY", "SENSEX", "BSE", "NSE"]):
        return "Equity", "Index"
    if any(x in name for x in ["ELSS", "TAX SAVER", "TAX SAVING"]):
        return "Equity", "ELSS"
    if any(x in name for x in ["SMALL CAP", "SMALLCAP"]):
        return "Equity", "Small Cap"
    if any(x in name for x in ["MID CAP", "MIDCAP"]):
        return "Equity", "Mid Cap"
    if any(x in name for x in ["LARGE & MID", "LARGE AND MID"]):
        return "Equity", "Large & Mid Cap"
    if any(x in name for x in ["LARGE CAP", "LARGECAP", "BLUECHIP", "BLUE CHIP", "TOP 100", "TOP100"]):
        return "Equity", "Large Cap"
    if any(x in name for x in ["FLEXI CAP", "FLEXICAP", "MULTI CAP", "MULTICAP", "DIVERSIFIED"]):
        return "Equity", "Flexi Cap"
    if "EQUITY" in name or "GROWTH" in name:
        return "Equity", "Equity"
    if any(x in name for x in ["GOLD", "SILVER", "COMMODITY"]):
        return "Other", "Commodity"
    if "FOF" in name or "FUND OF FUND" in name:
        return "Other", "FoF"

    return "Other", "Other"

def extract_amc(scheme_name: str) -> str:
    """Extract AMC name from fund name."""
    amcs = [
        "SBI", "HDFC", "ICICI Prudential", "Axis", "Kotak", "Nippon India",
        "Mirae Asset", "Canara Robeco", "DSP", "Franklin Templeton", "Tata",
        "UTI", "Aditya Birla Sun Life", "Sundaram", "Motilal Oswal", "Edelweiss",
        "Invesco", "PGIM India", "Quant", "WhiteOak", "Parag Parikh", "Navi",
        "Groww", "Bandhan", "Union", "LIC", "Mahindra Manulife", "JM Financial",
        "BOI", "Baroda BNP Paribas", "ITI", "360 ONE"
    ]
    name_upper = scheme_name.upper()
    for amc in amcs:
        if amc.upper() in name_upper:
            return amc
    # Try first word as fallback
    return scheme_name.split()[0] if scheme_name else "Unknown"


# ── Main sync ─────────────────────────────────────────────────────────────────

def sync_all_funds():
    log.info("Fetching full fund list from mfapi.in ...")
    all_funds = fetch_json(MFAPI_BASE)
    log.info(f"Total funds: {len(all_funds)}")

    conn   = get_conn()
    cur    = conn.cursor()
    synced = 0
    errors = 0

    for i, fund in enumerate(all_funds):
        scheme_code = str(fund["schemeCode"])
        scheme_name = fund["schemeName"]

        try:
            # Fetch NAV history for this fund
            detail = fetch_json(f"{MFAPI_BASE}/{scheme_code}")
            nav_data = detail.get("data", [])   # newest first

            if not nav_data:
                continue

            latest_nav  = float(nav_data[0]["nav"])
            nav_date_str = nav_data[0]["date"]
            nav_date    = datetime.strptime(nav_date_str, "%d-%m-%Y").date()

            # Calculate returns
            return_1y = calc_cagr(nav_data, 1)
            return_3y = calc_cagr(nav_data, 3)
            return_5y = calc_cagr(nav_data, 5)

            category, sub_category = infer_category(scheme_name)
            amc_name               = extract_amc(scheme_name)

            # Upsert into mf_cache
            cur.execute("""
                INSERT INTO mf_cache
                    (scheme_code, fund_name, category, sub_category, amc_name,
                     latest_nav, nav_date, return_1y, return_3y, return_5y, last_synced)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s, NOW())
                ON CONFLICT (scheme_code) DO UPDATE SET
                    fund_name    = EXCLUDED.fund_name,
                    category     = EXCLUDED.category,
                    sub_category = EXCLUDED.sub_category,
                    amc_name     = EXCLUDED.amc_name,
                    latest_nav   = EXCLUDED.latest_nav,
                    nav_date     = EXCLUDED.nav_date,
                    return_1y    = EXCLUDED.return_1y,
                    return_3y    = EXCLUDED.return_3y,
                    return_5y    = EXCLUDED.return_5y,
                    last_synced  = NOW()
            """, (scheme_code, scheme_name, category, sub_category, amc_name,
                  latest_nav, nav_date, return_1y, return_3y, return_5y))

            synced += 1

            # Commit every 500 funds to avoid huge transactions
            if synced % 500 == 0:
                conn.commit()
                log.info(f"Progress: {synced}/{len(all_funds)} synced ...")

            # Small delay to be polite to mfapi.in
            time.sleep(0.05)

        except Exception as e:
            errors += 1
            log.warning(f"Error syncing {scheme_code} ({scheme_name[:40]}): {e}")
            conn.rollback()
            continue

    conn.commit()
    cur.close()
    conn.close()

    log.info(f"✅ Sync complete — {synced} funds synced, {errors} errors")
    return synced, errors


if __name__ == "__main__":
    start = time.time()
    synced, errors = sync_all_funds()
    elapsed = round(time.time() - start, 1)
    log.info(f"Total time: {elapsed}s")
    if errors > synced * 0.1:   # fail if >10% error rate
        raise SystemExit(f"Too many errors: {errors}")

