"""
ai_analysis.py — Claude AI analysis writing to D1 via Cloudflare REST API
Reads from mf_cache in D1, sends batches to Claude, writes ai_recommendations back to D1
"""
import os, json, time, logging, asyncio, aiohttp
import anthropic

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)

CF_ACCOUNT_ID     = os.environ["CF_ACCOUNT_ID"]
CF_API_TOKEN      = os.environ["CF_API_TOKEN"]
D1_DATABASE_ID    = os.environ["D1_DATABASE_ID"]
ANTHROPIC_API_KEY = os.environ["ANTHROPIC_API_KEY"]

D1_URL     = f"https://api.cloudflare.com/client/v4/accounts/{CF_ACCOUNT_ID}/d1/database/{D1_DATABASE_ID}/query"
BATCH_SIZE = 20
MAX_FUNDS  = 2000

CF_HEADERS = {"Authorization": f"Bearer {CF_API_TOKEN}", "Content-Type": "application/json"}


# ── D1 helpers ────────────────────────────────────────────────────────────────

async def d1_query(session, sql, params=None):
    body = {"sql": sql}
    if params: body["params"] = params
    async with session.post(D1_URL, headers=CF_HEADERS, json=body) as r:
        data = await r.json()
        if not data.get("success"):
            raise Exception(f"D1 error: {data.get('errors', data)}")
        results = data.get("result", [])
        if results and isinstance(results, list):
            return results[0].get("results", [])
        return []


async def d1_run(session, sql, params=None):
    body = {"sql": sql}
    if params: body["params"] = params
    async with session.post(D1_URL, headers=CF_HEADERS, json=body) as r:
        data = await r.json()
        if not data.get("success"):
            raise Exception(f"D1 error: {data.get('errors', data)}")


# ── Claude analysis ───────────────────────────────────────────────────────────

def analyse_batch(client, funds):
    lines = []
    for f in funds:
        lines.append(
            f"- code:{f['scheme_code']} | {f['fund_name'][:55]} | "
            f"{f['category']} | {f.get('amc_name','')} | "
            f"1Y:{f.get('return_1y')}% 3Y:{f.get('return_3y')}% 5Y:{f.get('return_5y')}%"
        )

    prompt = f"""You are an expert Indian mutual fund analyst. Analyse these funds and return a JSON array.

FUNDS:
{chr(10).join(lines)}

For EACH fund return exactly:
{{
  "scheme_code": "...",
  "signal": "buy"|"hold"|"watch"|"exit",
  "risk_score": 1-5,
  "risk_label": "Very Low"|"Low"|"Moderate"|"High"|"Very High",
  "expected_1y_min": number,
  "expected_1y_max": number,
  "expected_3y_min": number,
  "expected_3y_max": number,
  "expected_5y_min": number,
  "expected_5y_max": number,
  "rationale": "1-2 sentences"
}}

Rules:
- buy = strong 1Y momentum, consistent 3Y/5Y, good category rank
- hold = steady performer, maintain position
- watch = mixed signals, monitor
- exit = underperforming peers, better alternatives exist
- risk_score 1=very low (liquid/gilt) to 5=very high (small cap)
- expected returns = realistic CAGR range % for next period

Respond ONLY with valid JSON array. No markdown, no backticks, no explanation."""

    resp = client.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=4000,
        messages=[{"role": "user", "content": prompt}]
    )
    raw = resp.content[0].text.strip()
    if raw.startswith("```"):
        raw = raw.split("```")[1]
        if raw.startswith("json"): raw = raw[4:]
    return json.loads(raw.strip())


async def save_recommendations(session, recs):
    for rec in recs:
        try:
            await d1_run(session, """
                INSERT INTO ai_recommendations
                  (scheme_code,signal,risk_score,risk_label,
                   expected_1y_min,expected_1y_max,expected_3y_min,expected_3y_max,
                   expected_5y_min,expected_5y_max,rationale,generated_at)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,datetime('now'))
                ON CONFLICT(scheme_code) DO UPDATE SET
                  signal=excluded.signal, risk_score=excluded.risk_score,
                  risk_label=excluded.risk_label,
                  expected_1y_min=excluded.expected_1y_min, expected_1y_max=excluded.expected_1y_max,
                  expected_3y_min=excluded.expected_3y_min, expected_3y_max=excluded.expected_3y_max,
                  expected_5y_min=excluded.expected_5y_min, expected_5y_max=excluded.expected_5y_max,
                  rationale=excluded.rationale, generated_at=excluded.generated_at""",
                [str(rec["scheme_code"]), rec.get("signal","watch"),
                 int(rec.get("risk_score",3)), rec.get("risk_label","Moderate"),
                 float(rec.get("expected_1y_min",0)), float(rec.get("expected_1y_max",0)),
                 float(rec.get("expected_3y_min",0)), float(rec.get("expected_3y_max",0)),
                 float(rec.get("expected_5y_min",0)), float(rec.get("expected_5y_max",0)),
                 str(rec.get("rationale",""))[:500]])
        except Exception as e:
            log.warning(f"Failed to save rec for {rec.get('scheme_code')}: {e}")


async def main():
    start  = time.time()
    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

    async with aiohttp.ClientSession() as session:
        # Fetch top funds from D1
        funds = await d1_query(session, f"""
            SELECT scheme_code, fund_name, category, amc_name,
                   return_1y, return_3y, return_5y
            FROM mf_cache
            WHERE return_1y IS NOT NULL
            ORDER BY
              CASE category WHEN 'Equity' THEN 1 WHEN 'Hybrid' THEN 2 ELSE 3 END,
              return_1y DESC
            LIMIT {MAX_FUNDS}""")

        log.info(f"Analysing {len(funds)} funds in batches of {BATCH_SIZE}...")
        saved = 0

        for i in range(0, len(funds), BATCH_SIZE):
            batch = funds[i:i+BATCH_SIZE]
            try:
                recs = analyse_batch(client, batch)
                await save_recommendations(session, recs)
                saved += len(recs)
                log.info(f"Batch {i//BATCH_SIZE+1}: saved {len(recs)} | total={saved}")
                time.sleep(0.5)
            except json.JSONDecodeError as e:
                log.error(f"Batch {i//BATCH_SIZE+1} JSON error: {e}")
                time.sleep(5)
            except Exception as e:
                log.error(f"Batch {i//BATCH_SIZE+1} error: {e}")
                time.sleep(3)

    elapsed = round(time.time()-start)
    log.info(f"✅ AI analysis done — {saved} recommendations in {elapsed//60}m {elapsed%60}s")

if __name__ == "__main__":
    asyncio.run(main())
