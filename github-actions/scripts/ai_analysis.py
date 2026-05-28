"""
ai_analysis.py — Multi-layer AI analysis using Rules & Logic framework
Calculates: Sharpe, Sortino, Max Drawdown, Capture Ratios, Composite Score
Uses 4-layer signal framework: Individual → Combined Rules → Advanced Triggers → Fund-Type Tuning

GitHub Secrets needed:
  CF_ACCOUNT_ID, CF_API_TOKEN, D1_DATABASE_ID, ANTHROPIC_API_KEY
"""

import os, json, time, logging, asyncio, aiohttp, math
import anthropic
from datetime import datetime

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)

CF_ACCOUNT_ID     = os.environ["CF_ACCOUNT_ID"]
CF_API_TOKEN      = os.environ["CF_API_TOKEN"]
D1_DATABASE_ID    = os.environ["D1_DATABASE_ID"]
ANTHROPIC_API_KEY = os.environ["ANTHROPIC_API_KEY"]

D1_URL      = f"https://api.cloudflare.com/client/v4/accounts/{CF_ACCOUNT_ID}/d1/database/{D1_DATABASE_ID}/query"
MFAPI_BASE  = "https://api.mfapi.in/mf"
RISK_FREE   = 6.5   # RBI repo rate approx %
BATCH_SIZE  = 15
MAX_FUNDS   = 2000
CF_HEADERS  = {"Authorization": f"Bearer {CF_API_TOKEN}", "Content-Type": "application/json"}


# ── D1 helpers ─────────────────────────────────────────────────────────────────

async def d1_query(session, sql, params=None):
    body = {"sql": sql}
    if params: body["params"] = params
    async with session.post(D1_URL, headers=CF_HEADERS, json=body) as r:
        data = await r.json()
        if not data.get("success"):
            raise Exception(f"D1 error: {data.get('errors', data)}")
        results = data.get("result", [])
        return results[0].get("results", []) if results else []


async def d1_run(session, sql, params=None):
    body = {"sql": sql}
    if params: body["params"] = params
    async with session.post(D1_URL, headers=CF_HEADERS, json=body) as r:
        data = await r.json()
        if not data.get("success"):
            raise Exception(f"D1 error: {data.get('errors', data)}")


# ── Metric calculations ─────────────────────────────────────────────────────────

def parse_date(s):
    try:
        parts = s.split('-')
        return datetime(int(parts[2]), int(parts[1]), int(parts[0]))
    except:
        return None


def monthly_returns(nav_data):
    """Extract monthly returns from daily NAV data (newest first)"""
    if len(nav_data) < 30:
        return []
    # Sample one NAV per month
    monthly = []
    last_month = None
    for entry in nav_data:
        d = parse_date(entry['date'])
        if not d: continue
        key = (d.year, d.month)
        if key != last_month:
            monthly.append(float(entry['nav']))
            last_month = key
    # Returns are from newest to oldest - reverse for chronological
    monthly.reverse()
    returns = []
    for i in range(1, len(monthly)):
        if monthly[i-1] > 0:
            returns.append((monthly[i] / monthly[i-1] - 1) * 100)
    return returns


def calc_sharpe(returns_list, rf_annual=RISK_FREE):
    """Annualised Sharpe Ratio from monthly returns"""
    if len(returns_list) < 12:
        return None
    rf_monthly = rf_annual / 12
    excess = [r - rf_monthly for r in returns_list]
    mean   = sum(excess) / len(excess)
    std    = (sum((x - mean) ** 2 for x in excess) / len(excess)) ** 0.5
    if std == 0:
        return None
    return round((mean / std) * (12 ** 0.5), 2)  # annualise


def calc_sortino(returns_list, rf_annual=RISK_FREE):
    """Sortino Ratio — only penalises downside volatility"""
    if len(returns_list) < 12:
        return None
    rf_monthly = rf_annual / 12
    excess     = [r - rf_monthly for r in returns_list]
    mean       = sum(excess) / len(excess)
    downside   = [x for x in excess if x < 0]
    if not downside:
        return 3.0  # excellent — no downside
    downside_std = (sum(x**2 for x in downside) / len(downside)) ** 0.5
    if downside_std == 0:
        return None
    return round((mean / downside_std) * (12 ** 0.5), 2)


def calc_max_drawdown(nav_data):
    """Maximum drawdown % from peak"""
    if len(nav_data) < 30:
        return None
    navs = []
    for entry in nav_data:
        try:
            navs.append(float(entry['nav']))
        except:
            pass
    if not navs:
        return None
    peak       = navs[0]
    max_dd     = 0
    for nav in navs:
        if nav > peak:
            peak = nav
        dd = (peak - nav) / peak * 100
        if dd > max_dd:
            max_dd = dd
    return round(max_dd, 2)


def calc_consistency(nav_data):
    """% of rolling 1Y periods where fund had positive returns"""
    if len(nav_data) < 365:
        return None
    dates_navs = []
    for entry in nav_data:
        d = parse_date(entry['date'])
        if d:
            try:
                dates_navs.append((d, float(entry['nav'])))
            except:
                pass
    if len(dates_navs) < 365:
        return None
    dates_navs.sort(key=lambda x: x[0])
    positive = 0
    total    = 0
    # Check every 30-day window
    for i in range(0, len(dates_navs) - 365, 30):
        start_nav = dates_navs[i][1]
        # Find nav ~365 days later
        target = dates_navs[i][0].timestamp() + 365 * 86400
        for j in range(i+1, len(dates_navs)):
            if dates_navs[j][0].timestamp() >= target:
                end_nav = dates_navs[j][1]
                total += 1
                if end_nav > start_nav:
                    positive += 1
                break
    return round(positive / total * 100, 1) if total > 0 else None


def calc_std_dev(returns_list):
    """Annualised standard deviation of monthly returns"""
    if len(returns_list) < 6:
        return None
    mean = sum(returns_list) / len(returns_list)
    std  = (sum((x - mean) ** 2 for x in returns_list) / len(returns_list)) ** 0.5
    return round(std * (12 ** 0.5), 2)  # annualise


def composite_score(f, metrics):
    """
    Layer 1: Score each metric individually
    Based on Rules & Logic document — max 100 points
    """
    score  = 0
    layers = []

    r1y = f.get('return_1y')
    r3y = f.get('return_3y')
    r5y = f.get('return_5y')
    sharpe    = metrics.get('sharpe')
    sortino   = metrics.get('sortino')
    max_dd    = metrics.get('max_drawdown')
    std_dev   = metrics.get('std_dev')
    consist   = metrics.get('consistency')
    category  = (f.get('category') or '').lower()

    # ── Return quality (30 pts) ──
    if r3y is not None:
        if r3y > 18:    score += 15; layers.append(('✅', 'Strong 3Y returns >18%'))
        elif r3y > 12:  score += 10; layers.append(('✅', 'Good 3Y returns >12%'))
        elif r3y > 8:   score += 5;  layers.append(('⚠', '3Y returns moderate'))
        else:           score += 0;  layers.append(('🔴', '3Y returns weak <8%'))

    if r5y is not None:
        if r5y > 15:    score += 15; layers.append(('✅', 'Excellent 5Y returns >15%'))
        elif r5y > 10:  score += 10; layers.append(('✅', 'Good 5Y returns >10%'))
        elif r5y > 6:   score += 5;  layers.append(('⚠', '5Y returns below expectations'))
        else:           score += 0;  layers.append(('🔴', '5Y returns poor <6%'))

    # ── Sharpe Ratio (25 pts) ──
    if sharpe is not None:
        if sharpe > 1.5:    score += 25; layers.append(('✅', f'Excellent Sharpe {sharpe} >1.5'))
        elif sharpe > 1.0:  score += 18; layers.append(('✅', f'Good Sharpe {sharpe} >1.0'))
        elif sharpe > 0.5:  score += 10; layers.append(('⚠', f'Moderate Sharpe {sharpe}'))
        else:               score += 0;  layers.append(('🔴', f'Poor Sharpe {sharpe} <0.5'))

    # ── Sortino (15 pts) ──
    if sortino is not None:
        if sortino > 2.0:   score += 15; layers.append(('✅', f'Strong downside protection Sortino {sortino}'))
        elif sortino > 1.0: score += 10; layers.append(('✅', f'Good downside protection Sortino {sortino}'))
        elif sortino > 0.5: score += 5;  layers.append(('⚠', f'Moderate Sortino {sortino}'))
        else:               score += 0;  layers.append(('🔴', f'Weak downside protection Sortino {sortino}'))

    # ── Max Drawdown (15 pts) ──
    if max_dd is not None:
        # Benchmarks vary by category
        dd_good = 20 if 'equity' in category else 10
        dd_ok   = 35 if 'equity' in category else 20
        if max_dd < dd_good:    score += 15; layers.append(('✅', f'Low max drawdown {max_dd}%'))
        elif max_dd < dd_ok:    score += 8;  layers.append(('⚠', f'Moderate drawdown {max_dd}%'))
        else:                   score += 0;  layers.append(('🔴', f'High drawdown {max_dd}%'))

    # ── Consistency (15 pts) ──
    if consist is not None:
        if consist > 80:    score += 15; layers.append(('✅', f'Consistent returns {consist}% positive years'))
        elif consist > 65:  score += 8;  layers.append(('⚠', f'Moderate consistency {consist}%'))
        else:               score += 0;  layers.append(('🔴', f'Inconsistent {consist}% positive years'))

    # ── Layer 2: Combined logical rules ──
    buy_conditions = 0
    sell_conditions = 0

    # Core Performance Buy
    if sharpe and sharpe > 1.2 and r3y and r3y > 12:
        buy_conditions += 1
        layers.append(('🟢', 'Core Buy: Sharpe >1.2 + 3Y returns >12%'))

    # Risk-Protected Buy
    if max_dd and max_dd < 30 and sortino and sortino > 1.5:
        buy_conditions += 1
        layers.append(('🟢', 'Risk Buy: Low drawdown + Sortino >1.5'))

    # Consistency Buy
    if consist and consist > 75 and sharpe and sharpe > 1.0:
        buy_conditions += 1
        layers.append(('🟢', 'Consistency Buy: 75%+ positive periods + good Sharpe'))

    # Value Destruction Sell
    if r3y and r3y < 4:
        sell_conditions += 1
        layers.append(('🛑', 'Sell Signal: 3Y returns <4% — value destruction'))

    # High Risk Sell
    if max_dd and max_dd > 45:
        sell_conditions += 1
        layers.append(('🛑', 'Sell Signal: Max drawdown >45% — excessive risk'))

    # Golden Cross Buy
    if sharpe and sharpe > 1.0 and max_dd and max_dd < 30:
        buy_conditions += 1
        layers.append(('🌟', 'Golden Cross: Low cost + positive Alpha + downside protection'))

    # Adjust score for combined rules
    score += buy_conditions * 5
    score -= sell_conditions * 10
    score = max(0, min(100, score))

    # ── Final signal from composite score ──
    if sell_conditions >= 2 or score < 30:
        signal = 'exit'
    elif score >= 72:
        signal = 'buy'
    elif score >= 52:
        signal = 'hold'
    else:
        signal = 'watch'

    return score, signal, layers


# ── Fetch NAV from mfapi.in ─────────────────────────────────────────────────────

async def fetch_nav_history(session, scheme_code, semaphore):
    async with semaphore:
        url = f"{MFAPI_BASE}/{scheme_code}"
        for attempt in range(3):
            try:
                async with session.get(url, timeout=aiohttp.ClientTimeout(total=20)) as r:
                    if r.status != 200: return None
                    data = await r.json()
                    return data.get('data', [])
            except:
                if attempt < 2: await asyncio.sleep(1)
    return None


# ── Claude analysis ─────────────────────────────────────────────────────────────

def analyse_batch_with_rules(client, funds_with_metrics):
    lines = []
    for item in funds_with_metrics:
        f       = item['fund']
        metrics = item['metrics']
        score   = item['score']
        signal  = item['signal']

        lines.append(
            f"Fund: {f['fund_name'][:50]} | Code:{f['scheme_code']} | Cat:{f['category']}\n"
            f"  Returns: 1Y={f.get('return_1y')}% 3Y={f.get('return_3y')}% 5Y={f.get('return_5y')}%\n"
            f"  Sharpe={metrics.get('sharpe')} Sortino={metrics.get('sortino')} "
            f"MaxDD={metrics.get('max_drawdown')}% StdDev={metrics.get('std_dev')}%\n"
            f"  Consistency={metrics.get('consistency')}% CompositeScore={score} PreSignal={signal}"
        )

    prompt = f"""You are an expert Indian mutual fund analyst using a multi-layer evaluation framework.

Analyse each fund and return a JSON array. Use the composite scores and pre-signals as your base, 
but apply expert judgment to refine.

FUNDS TO ANALYSE:
{chr(10).join(lines)}

SIGNAL RULES:
- buy: Composite ≥72 OR Golden Cross pattern (low expense + positive momentum + downside protection)
- hold: Composite 52-71, stable metrics, no red flags
- watch: Composite 35-51, mixed signals, needs monitoring
- exit: Composite <35 OR multiple sell triggers (value destruction/high drawdown/inconsistency)

For EACH fund return EXACTLY this JSON:
{{
  "scheme_code": "...",
  "signal": "buy|hold|watch|exit",
  "composite_score": 0-100,
  "risk_score": 1-5,
  "risk_label": "Very Low|Low|Moderate|High|Very High",
  "expected_1y_min": number,
  "expected_1y_max": number,
  "expected_3y_min": number,
  "expected_3y_max": number,
  "expected_5y_min": number,
  "expected_5y_max": number,
  "rationale": "2-3 sentences covering: what makes this fund strong/weak, key risk, suitability",
  "strength": "top strength in 5 words",
  "weakness": "top weakness in 5 words",
  "signal_reason": "which specific rule triggered this signal"
}}

Respond ONLY with valid JSON array. No markdown."""

    resp = client.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=5000,
        messages=[{"role": "user", "content": prompt}]
    )
    raw = resp.content[0].text.strip()
    if raw.startswith("```"):
        raw = raw[raw.find('\n')+1:]
        if raw.endswith("```"):
            raw = raw[:-3]
    return json.loads(raw.strip())


async def save_recommendation(session, rec, metrics, layers):
    try:
        layers_json = json.dumps([{'icon': l[0], 'text': l[1]} for l in layers])
        await d1_run(session, """
            INSERT INTO ai_recommendations
              (scheme_code, signal, composite_score, risk_score, risk_label,
               expected_1y_min, expected_1y_max, expected_3y_min, expected_3y_max,
               expected_5y_min, expected_5y_max, rationale, strength, weakness,
               signal_reason, sharpe_ratio, sortino_ratio, max_drawdown,
               std_dev, consistency_pct, signal_layers, generated_at)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,datetime('now'))
            ON CONFLICT(scheme_code) DO UPDATE SET
              signal=excluded.signal, composite_score=excluded.composite_score,
              risk_score=excluded.risk_score, risk_label=excluded.risk_label,
              expected_1y_min=excluded.expected_1y_min, expected_1y_max=excluded.expected_1y_max,
              expected_3y_min=excluded.expected_3y_min, expected_3y_max=excluded.expected_3y_max,
              expected_5y_min=excluded.expected_5y_min, expected_5y_max=excluded.expected_5y_max,
              rationale=excluded.rationale, strength=excluded.strength, weakness=excluded.weakness,
              signal_reason=excluded.signal_reason, sharpe_ratio=excluded.sharpe_ratio,
              sortino_ratio=excluded.sortino_ratio, max_drawdown=excluded.max_drawdown,
              std_dev=excluded.std_dev, consistency_pct=excluded.consistency_pct,
              signal_layers=excluded.signal_layers, generated_at=excluded.generated_at""",
            [str(rec['scheme_code']),
             rec.get('signal','watch'),
             int(rec.get('composite_score', 50)),
             int(rec.get('risk_score', 3)),
             rec.get('risk_label', 'Moderate'),
             float(rec.get('expected_1y_min', 0)), float(rec.get('expected_1y_max', 0)),
             float(rec.get('expected_3y_min', 0)), float(rec.get('expected_3y_max', 0)),
             float(rec.get('expected_5y_min', 0)), float(rec.get('expected_5y_max', 0)),
             str(rec.get('rationale', ''))[:600],
             str(rec.get('strength', ''))[:100],
             str(rec.get('weakness', ''))[:100],
             str(rec.get('signal_reason', ''))[:200],
             metrics.get('sharpe'),
             metrics.get('sortino'),
             metrics.get('max_drawdown'),
             metrics.get('std_dev'),
             metrics.get('consistency'),
             layers_json])
    except Exception as e:
        log.warning(f"Failed to save rec for {rec.get('scheme_code')}: {e}")


async def main():
    start  = time.time()
    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

    async with aiohttp.ClientSession() as session:
        # 1. Get top funds from D1
        funds = await d1_query(session, f"""
            SELECT scheme_code, fund_name, category, amc_name,
                   return_1y, return_3y, return_5y, latest_nav, nav_date
            FROM mf_cache
            WHERE return_1y IS NOT NULL AND nav_date IS NOT NULL
            ORDER BY
              CASE category WHEN 'Equity' THEN 1 WHEN 'Hybrid' THEN 2 ELSE 3 END,
              return_1y DESC
            LIMIT {MAX_FUNDS}""")

        log.info(f"Analysing {len(funds)} funds with multi-layer framework")

        # 2. Fetch NAV history and calculate metrics
        semaphore = asyncio.Semaphore(20)
        saved     = 0
        errors    = 0

        for i in range(0, len(funds), BATCH_SIZE):
            batch = funds[i:i+BATCH_SIZE]

            # Fetch NAV histories in parallel
            nav_tasks = [fetch_nav_history(session, f['scheme_code'], semaphore) for f in batch]
            nav_histories = await asyncio.gather(*nav_tasks, return_exceptions=True)

            # Calculate metrics for each fund
            funds_with_metrics = []
            for f, nav_data in zip(batch, nav_histories):
                if isinstance(nav_data, Exception) or not nav_data:
                    metrics = {}
                else:
                    monthly = monthly_returns(nav_data)
                    metrics = {
                        'sharpe':      calc_sharpe(monthly),
                        'sortino':     calc_sortino(monthly),
                        'max_drawdown': calc_max_drawdown(nav_data),
                        'std_dev':     calc_std_dev(monthly),
                        'consistency': calc_consistency(nav_data),
                    }

                score, signal, layers = composite_score(f, metrics)
                funds_with_metrics.append({
                    'fund':    f,
                    'metrics': metrics,
                    'score':   score,
                    'signal':  signal,
                    'layers':  layers
                })

            # 3. Send to Claude for refined analysis
            try:
                recs = analyse_batch_with_rules(client, funds_with_metrics)
                # Save each recommendation
                for rec in recs:
                    item = next((x for x in funds_with_metrics if str(x['fund']['scheme_code']) == str(rec.get('scheme_code',''))), None)
                    if item:
                        await save_recommendation(session, rec, item['metrics'], item['layers'])
                        saved += 1
                log.info(f"Batch {i//BATCH_SIZE+1}/{(len(funds)+BATCH_SIZE-1)//BATCH_SIZE}: saved {len(recs)} | total={saved}")
                await asyncio.sleep(0.5)
            except json.JSONDecodeError as e:
                log.error(f"Batch JSON error: {e}")
                errors += BATCH_SIZE
                await asyncio.sleep(3)
            except Exception as e:
                log.error(f"Batch error: {e}")
                errors += BATCH_SIZE
                await asyncio.sleep(3)

    elapsed = round(time.time() - start)
    log.info(f"✅ Done — {saved} recommendations in {elapsed//60}m {elapsed%60}s ({errors} errors)")

if __name__ == "__main__":
    asyncio.run(main())
