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
from fund_metrics import compute_metrics, compute_relative

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)

CF_ACCOUNT_ID  = os.environ["CF_ACCOUNT_ID"]
CF_API_TOKEN   = os.environ["CF_API_TOKEN"]
D1_DATABASE_ID = os.environ["D1_DATABASE_ID"]

D1_URL     = f"https://api.cloudflare.com/client/v4/accounts/{CF_ACCOUNT_ID}/d1/database/{D1_DATABASE_ID}/query"
MFAPI_BASE = "https://api.mfapi.in/mf"

# Every active scheme on mfapi.in is stored. Scoring (ai_analysis.py) still covers
# only Equity and Hybrid, because its rules are built for those.
MAX_FUNDS   = 60000

# Names that mark a scheme as closed / matured (fixed-term plans, wound-up series).
# These never get a fresh NAV, so fetching them only wastes time.
CLOSED_MARKERS = ("FIXED TERM", "FIXED MATURITY", "FMP", "INTERVAL", "CAPITAL PROTECTION",
                  "SEGREGATED", "SERIES ", "DUAL ADVANTAGE", "FIXED HORIZON", "FTP ")
CONCURRENCY = 40

# mfapi.in allows 300 requests a minute per IP (it answers HTTP 429 beyond that), and
# GitHub runners share IPs with other jobs, so stay well under it. ~14k active
# schemes at 240/min is about an hour.
RATE_PER_MIN = int(os.environ.get("MFAPI_RATE_PER_MIN", "240"))
_RATE_GAP = 60.0 / RATE_PER_MIN
_next_slot = 0.0


async def _throttle():
    """Hand out request slots one every _RATE_GAP seconds across all workers."""
    global _next_slot
    loop = asyncio.get_running_loop()
    now = loop.time()
    slot = max(now, _next_slot)
    _next_slot = slot + _RATE_GAP
    if slot > now:
        await asyncio.sleep(slot - now)

# mfapi.in sometimes serves an HTML throttle/error page to the default aiohttp
# User-Agent. Sending a normal UA + Accept header makes responses reliably JSON.
MFAPI_HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; AdhyarvanshBot/1.0; +https://adhyarvansh.com)",
    "Accept": "application/json",
}


async def fetch_json(session, url, *, retries=4, base_delay=1.5, timeout=25, headers=None):
    """
    Resilient JSON GET.

    Fixes the daily-run crash:
        aiohttp.client_exceptions.ContentTypeError:
        'Attempt to decode JSON with unexpected mimetype: text/html'

    - Checks HTTP status BEFORE parsing.
    - Parses JSON manually (json.loads on the text body) so a wrong/missing
      content-type header never raises ContentTypeError.
    - Retries transient failures (429 / 5xx / timeout / non-JSON body) with
      exponential backoff.
    - Returns the parsed object, or None if every attempt failed (404 returns
      None immediately — it's permanent, not worth retrying).
    """
    hdrs = headers or MFAPI_HEADERS
    last_err = None
    for attempt in range(1, retries + 1):
        try:
            await _throttle()
            async with session.get(
                url, headers=hdrs,
                timeout=aiohttp.ClientTimeout(total=timeout),
            ) as r:
                body = await r.text()

                if r.status == 404:
                    return None                      # permanent — don't retry
                if r.status != 200:
                    last_err = f"HTTP {r.status}: {body[:160]!r}"
                    raise aiohttp.ClientError(last_err)   # transient — retry

                try:
                    return json.loads(body)          # parse regardless of mimetype
                except json.JSONDecodeError as je:
                    # 200 but HTML/garbage body (throttle page) — treat as transient
                    last_err = f"non-JSON body (len={len(body)}): {body[:160]!r}"
                    raise aiohttp.ClientError(last_err) from je

        except (aiohttp.ClientError, asyncio.TimeoutError) as e:
            last_err = str(e)
            if attempt < retries:
                if "HTTP 429" in last_err:
                    delay = 20 + 10 * attempt                # rate limited: wait it out
                else:
                    delay = base_delay * (2 ** (attempt - 1))   # 1.5, 3, 6, 12s
                await asyncio.sleep(delay)
            else:
                log.warning("fetch_json gave up after %d tries for %s: %s",
                            retries, url, last_err)
    return None


METRIC_COLS = [("m_sharpe", "REAL"), ("m_sortino", "REAL"), ("m_maxdd", "REAL"),
               ("m_vol", "REAL"), ("m_consistency", "REAL"), ("m_days", "INTEGER"),
               ("m_alpha", "REAL"), ("m_beta", "REAL"), ("m_r2", "REAL"),
               ("m_upcap", "REAL"), ("m_downcap", "REAL"), ("m_info", "REAL"),
               ("m_te", "REAL"), ("m_bench", "TEXT")]

# Benchmarks: a plain Direct-Growth index fund per index. mfapi.in has no index
# series of its own, and an index fund tracks its index closely enough for this.
BENCH_MATCH = {
    "NIFTY50":  ["NIFTY 50 INDEX"],
    "NIFTY500": ["NIFTY 500 INDEX"],
    "MID150":   ["MIDCAP 150 INDEX"],
    "SMALL250": ["SMALLCAP 250 INDEX"],
}
BENCH_LABEL = {"NIFTY50": "Nifty 50", "NIFTY500": "Nifty 500",
               "MID150": "Nifty Midcap 150", "SMALL250": "Nifty Smallcap 250"}
BENCH_SKIP = ("IDCW", "DIVIDEND", "REGULAR", "ETF", "FOF", "NEXT", "EQUAL", "MOMENTUM",
              "QUALITY", "VALUE", "LOW VOL", "ALPHA", "ENHANCED", "FUND OF FUND", "PAYOUT")
BENCH_FOR_SUB = {"Large Cap": "NIFTY50", "Flexi Cap": "NIFTY500", "ELSS": "NIFTY500",
                 "Equity": "NIFTY500", "Mid Cap": "MID150", "Small Cap": "SMALL250"}


def benchmark_key(sub_category, fund_name):
    """Which benchmark applies to a fund; for index funds, only the index it tracks."""
    n = fund_name.upper()
    if sub_category == "Index":
        for key, pats in (("MID150", ["MIDCAP 150"]), ("SMALL250", ["SMALLCAP 250"]),
                          ("NIFTY500", ["NIFTY 500"]), ("NIFTY50", ["NIFTY 50 ", "NIFTY50"])):
            if any(p in n + " " for p in pats):
                return key
        return None
    return BENCH_FOR_SUB.get(sub_category)


async def load_benchmarks(session, all_funds):
    """Pick, for each benchmark, the Direct-Growth index fund with the longest history."""
    out = {}
    for key, pats in BENCH_MATCH.items():
        cands = []
        for f in all_funds:
            nm = f["schemeName"].upper()
            if all(p in nm for p in pats) and "DIRECT" in nm and "GROWTH" in nm \
                    and not any(x in nm for x in BENCH_SKIP):
                cands.append(f)
        best = None
        for f in cands[:6]:
            d = await fetch_json(session, f"{MFAPI_BASE}/{f['schemeCode']}", retries=3, timeout=20)
            nav = (d or {}).get("data") or []
            if len(nav) > 500 and (best is None or len(nav) > len(best[2])):
                best = (f["schemeCode"], f["schemeName"], nav)
        if best:
            log.info("Benchmark %s -> %s (%s, %d NAVs)", BENCH_LABEL[key], best[1], best[0], len(best[2]))
            out[key] = best[2]
        else:
            log.warning("Benchmark %s: no usable index fund found (%d candidates)", BENCH_LABEL[key], len(cands))
    return out


async def d1_exec(session, sql, params=None):
    headers = {"Authorization": f"Bearer {CF_API_TOKEN}", "Content-Type": "application/json"}
    async with session.post(D1_URL, headers=headers, json={"sql": sql, "params": params or []}) as r:
        text = await r.text()
        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            raise Exception(f"D1 non-JSON response (HTTP {r.status}): {text[:160]}")
        if not data.get("success"):
            raise Exception(str(data.get("errors", "")))


async def ensure_metric_columns(session):
    """Add the metric columns to mf_cache if they are missing (safe to repeat)."""
    for name, typ in METRIC_COLS:
        try:
            await d1_exec(session, f"ALTER TABLE mf_cache ADD COLUMN {name} {typ}")
        except Exception as e:
            if "duplicate column" not in str(e).lower():
                raise


async def d1_upsert(session, row):
    m = row.get("metrics") or {}
    rel = row.get("relative") or {}
    await d1_exec(session, """INSERT INTO mf_cache
            (scheme_code,fund_name,category,sub_category,amc_name,
             latest_nav,nav_date,return_1y,return_3y,return_5y,
             m_sharpe,m_sortino,m_maxdd,m_vol,m_consistency,m_days,
             m_alpha,m_beta,m_r2,m_upcap,m_downcap,m_info,m_te,m_bench,last_synced)
          VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,datetime('now'))
          ON CONFLICT(scheme_code) DO UPDATE SET
            fund_name=excluded.fund_name, category=excluded.category,
            sub_category=excluded.sub_category, amc_name=excluded.amc_name,
            latest_nav=excluded.latest_nav, nav_date=excluded.nav_date,
            return_1y=excluded.return_1y, return_3y=excluded.return_3y,
            return_5y=excluded.return_5y,
            m_sharpe=excluded.m_sharpe, m_sortino=excluded.m_sortino,
            m_maxdd=excluded.m_maxdd, m_vol=excluded.m_vol,
            m_consistency=excluded.m_consistency, m_days=excluded.m_days,
            m_alpha=excluded.m_alpha, m_beta=excluded.m_beta, m_r2=excluded.m_r2,
            m_upcap=excluded.m_upcap, m_downcap=excluded.m_downcap,
            m_info=excluded.m_info, m_te=excluded.m_te, m_bench=excluded.m_bench,
            last_synced=excluded.last_synced""",
        [row["scheme_code"], row["fund_name"], row["category"],
         row["sub_category"], row["amc_name"], row["latest_nav"],
         row["nav_date"], row["return_1y"], row["return_3y"], row["return_5y"],
         m.get("sharpe_ratio"), m.get("sortino_ratio"), m.get("max_drawdown"),
         m.get("std_dev"), m.get("consistency_pct"), m.get("metrics_days"),
         rel.get("alpha"), rel.get("beta"), rel.get("r2"), rel.get("upside_capture"),
         rel.get("downside_capture"), rel.get("info_ratio"), rel.get("tracking_error"),
         row.get("bench_label") if rel else None])


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
    if any(x in n for x in ["LIQUID","OVERNIGHT","MONEY MARKET","ULTRA SHORT","CASH FUND","TREASURY"]): return "Debt","Liquid"
    if any(x in n for x in ["GILT","G-SEC"]): return "Debt","Gilt"
    if any(x in n for x in ["DEBT","BOND","INCOME","CREDIT RISK","SHORT TERM","MEDIUM TERM","LOW DURATION",
                            "DURATION","FLOATING","FLOATER","BANKING & PSU","BANKING AND PSU","SDL",
                            "TARGET MATURITY","ROLLING","CORPORATE BOND"]): return "Debt","Debt"
    if "ARBITRAGE" in n: return "Hybrid","Arbitrage"
    if any(x in n for x in ["BALANCED ADVANTAGE","DYNAMIC ASSET"]): return "Hybrid","Balanced Advantage"
    if any(x in n for x in ["HYBRID","BALANCED","EQUITY SAVINGS","MULTI ASSET"]): return "Hybrid","Hybrid"
    # gold / silver funds; miners are equity, not the metal
    if any(x in n for x in ["GOLD","SILVER"]):
        return ("Equity","Thematic") if "MINING" in n else ("Other","Commodity")
    if any(x in n for x in ["INDEX","NIFTY","SENSEX"]): return "Equity","Index"
    if any(x in n for x in ["ELSS","TAX SAVER","TAX SAVING"]): return "Equity","ELSS"
    if any(x in n for x in ["SMALL CAP","SMALLCAP"]): return "Equity","Small Cap"
    if any(x in n for x in ["MID CAP","MIDCAP"]): return "Equity","Mid Cap"
    if any(x in n for x in ["LARGE CAP","LARGECAP","BLUECHIP","TOP 100"]): return "Equity","Large Cap"
    if any(x in n for x in ["FLEXI CAP","FLEXICAP","MULTI CAP","MULTICAP"]): return "Equity","Flexi Cap"
    # sector, theme and overseas equity funds that do not say "equity" in the name
    if any(x in n for x in ["PHARMA","HEALTHCARE","HEALTH CARE","BANKING","FINANCIAL SERVICES","TECHNOLOGY",
                            "DIGITAL","INFRASTRUCTURE","INFRA ","CONSUMPTION","ENERGY","MANUFACTURING",
                            "AUTOMOBILE","FMCG","PSU","DIVIDEND YIELD","FOCUSED","CONTRA","VALUE",
                            "OPPORTUNITIES","ESG","MOMENTUM","QUALITY","LOW VOLATILITY","ALPHA","NASDAQ",
                            "S&P 500","TAIWAN","OVERSEAS","GLOBAL","INTERNATIONAL","CHINA","JAPAN","EUROPE",
                            "US ","INNOVATION","DEFENCE","REALTY","MNC","CAPITAL MARKET","COMMODITIES",
                            "TRANSPORTATION","SERVICES","BUSINESS CYCLE","STRATEGY","SPECIAL SITUATIONS"]):
        return "Equity","Thematic"
    if "EQUITY" in n or "GROWTH" in n: return "Equity","Equity"
    return "Other","Other"


def extract_amc(name):
    for amc in ["SBI","HDFC","ICICI Prudential","Axis","Kotak","Nippon India",
                "Mirae Asset","Canara Robeco","DSP","Franklin Templeton","Tata",
                "UTI","Aditya Birla Sun Life","Sundaram","Motilal Oswal","Quant",
                "WhiteOak","Parag Parikh","Groww","Bandhan","Edelweiss","Invesco","PGIM India"]:
        if amc.upper() in name.upper(): return amc
    return name.split()[0] if name else "Unknown"


async def fetch_and_store(session, scheme_code, fund_name, semaphore, benchmarks=None):
    async with semaphore:
        cat, sub = infer_category(fund_name)

        url = f"{MFAPI_BASE}/{scheme_code}"
        # fetch_json already retries internally; one call is enough.
        data = await fetch_json(session, url, retries=6, timeout=30)
        if not data:
            return False
        nav_data = data.get("data", [])
        if not nav_data:
            return False

        # Skip funds with stale NAV (no update in 90 days)
        try:
            latest_date = datetime.strptime(nav_data[0]["date"], "%d-%m-%Y")
            days_old = (datetime.now() - latest_date).days
            if days_old > 90:
                return False  # Skip stale closed-ended funds
        except Exception:
            pass

        try:
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
                "metrics":      compute_metrics(nav_data),
            }
            bkey = benchmark_key(sub, fund_name)
            if bkey and benchmarks and bkey in benchmarks:
                row["relative"] = compute_relative(nav_data, benchmarks[bkey])
                row["bench_label"] = BENCH_LABEL[bkey]
            await d1_upsert(session, row)
            return True
        except Exception as e:
            log.warning(f"Store failed {scheme_code}: {e}")
            return False


async def main():
    start = time.time()
    log.info("Starting fast async MF sync...")

    connector = aiohttp.TCPConnector(limit=CONCURRENCY, ttl_dns_cache=300)
    async with aiohttp.ClientSession(connector=connector) as session:
        await ensure_metric_columns(session)
        # ── Load the full scheme list (this is the call that was crashing) ──
        all_funds = await fetch_json(session, MFAPI_BASE, retries=5, timeout=40)
        if not all_funds:
            log.error("Could not load MF scheme list from mfapi.in after retries — aborting.")
            raise SystemExit(1)
        log.info(f"Total funds: {len(all_funds)} — dropping closed series...")

        # Pre-filter by name to avoid fetching unwanted funds
        target = [(f["schemeCode"], f["schemeName"]) for f in all_funds
                  if not any(m in f["schemeName"].upper() for m in CLOSED_MARKERS)][:MAX_FUNDS]
        # If a run is cut short, the funds people actually use should already be in:
        # Direct-Growth first, then other Direct, then Regular-Growth, then the rest.
        def _prio(item):
            n = item[1].upper()
            direct, growth = "DIRECT" in n, "GROWTH" in n and "IDCW" not in n and "DIVIDEND" not in n
            return 0 if direct and growth else 1 if direct else 2 if growth else 3
        target.sort(key=_prio)
        log.info(f"Skipped {len(all_funds) - len(target)} closed/matured series by name")
        log.info(f"Processing {len(target)} funds with {CONCURRENCY} parallel workers")

        benchmarks = await load_benchmarks(session, all_funds)
        semaphore = asyncio.Semaphore(CONCURRENCY)
        tasks     = [fetch_and_store(session, code, name, semaphore, benchmarks) for code, name in target]

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
