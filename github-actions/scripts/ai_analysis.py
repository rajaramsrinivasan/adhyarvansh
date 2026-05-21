"""
ai_analysis.py
Reads funds from mf_cache, calls Claude API for each batch
Stores risk scores, signals and expected returns in ai_recommendations table

Run: python ai_analysis.py
Schedule: GitHub Actions cron — runs after sync_mf_data.py daily
"""

import os
import json
import time
import logging
import psycopg2
import psycopg2.extras
import anthropic

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)

DATABASE_URL      = os.environ["DATABASE_URL"]
ANTHROPIC_API_KEY = os.environ["ANTHROPIC_API_KEY"]

# Only analyse funds with sufficient return history
# and prioritise equity/hybrid over debt for AI analysis
# (debt funds have simpler signals)
BATCH_SIZE  = 20   # funds per Claude API call
MAX_FUNDS   = 2000  # analyse top 2000 funds by AUM / returns daily


def get_conn():
    return psycopg2.connect(DATABASE_URL, cursor_factory=psycopg2.extras.RealDictCursor)


def analyse_batch(client, funds: list) -> list:
    """
    Send a batch of funds to Claude and get structured JSON recommendations back.
    Returns list of recommendation dicts.
    """
    fund_lines = []
    for f in funds:
        line = (
            f"- scheme_code: {f['scheme_code']} | {f['fund_name'][:60]} | "
            f"Category: {f['category']} | AMC: {f['amc_name']} | "
            f"NAV: {f['latest_nav']} | "
            f"1Y: {f['return_1y']}% | 3Y: {f['return_3y']}% | 5Y: {f['return_5y']}%"
        )
        fund_lines.append(line)

    funds_text = "\n".join(fund_lines)

    prompt = f"""You are an expert Indian mutual fund analyst. Analyse the following mutual funds and provide investment signals.

FUNDS TO ANALYSE:
{funds_text}

For each fund, provide a JSON object with these exact fields:
- scheme_code: (copy from input)
- signal: one of "buy", "hold", "watch", "exit"
  * buy = strong momentum, good risk-adjusted returns, suitable to add
  * hold = currently held funds performing well, maintain position
  * watch = mixed signals, monitor closely
  * exit = underperforming peers, better alternatives available
- risk_score: integer 1-5 (1=very low risk, 5=very high risk)
- risk_label: "Very Low" / "Low" / "Moderate" / "High" / "Very High"
- expected_1y_min: conservative expected return % next 1 year
- expected_1y_max: optimistic expected return % next 1 year
- expected_3y_min: conservative expected CAGR % next 3 years
- expected_3y_max: optimistic expected CAGR % next 3 years
- expected_5y_min: conservative expected CAGR % next 5 years
- expected_5y_max: optimistic expected CAGR % next 5 years
- rationale: 1-2 sentence plain English explanation of the signal

Base your analysis on:
1. Historical returns trend (1Y vs 3Y vs 5Y) — is performance consistent?
2. Category benchmarks — how does it compare to peers?
3. Risk profile — volatility implied by category and returns variance
4. Momentum — recent 1Y vs longer term

Respond ONLY with a valid JSON array — no markdown, no explanation, no backticks.
Example: [{{"scheme_code":"100001","signal":"hold","risk_score":3,...}}, ...]"""

    response = client.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=4000,
        messages=[{"role": "user", "content": prompt}]
    )

    raw = response.content[0].text.strip()

    # Strip any accidental markdown fences
    if raw.startswith("```"):
        raw = raw.split("```")[1]
        if raw.startswith("json"):
            raw = raw[4:]
    raw = raw.strip()

    return json.loads(raw)


def save_recommendations(conn, recommendations: list):
    cur = conn.cursor()
    for rec in recommendations:
        try:
            cur.execute("""
                INSERT INTO ai_recommendations
                    (scheme_code, signal, risk_score, risk_label,
                     expected_1y_min, expected_1y_max,
                     expected_3y_min, expected_3y_max,
                     expected_5y_min, expected_5y_max,
                     rationale, generated_at)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s, NOW())
                ON CONFLICT (scheme_code) DO UPDATE SET
                    signal          = EXCLUDED.signal,
                    risk_score      = EXCLUDED.risk_score,
                    risk_label      = EXCLUDED.risk_label,
                    expected_1y_min = EXCLUDED.expected_1y_min,
                    expected_1y_max = EXCLUDED.expected_1y_max,
                    expected_3y_min = EXCLUDED.expected_3y_min,
                    expected_3y_max = EXCLUDED.expected_3y_max,
                    expected_5y_min = EXCLUDED.expected_5y_min,
                    expected_5y_max = EXCLUDED.expected_5y_max,
                    rationale       = EXCLUDED.rationale,
                    generated_at    = NOW()
            """, (
                str(rec["scheme_code"]),
                rec.get("signal", "watch"),
                int(rec.get("risk_score", 3)),
                rec.get("risk_label", "Moderate"),
                float(rec.get("expected_1y_min", 0)),
                float(rec.get("expected_1y_max", 0)),
                float(rec.get("expected_3y_min", 0)),
                float(rec.get("expected_3y_max", 0)),
                float(rec.get("expected_5y_min", 0)),
                float(rec.get("expected_5y_max", 0)),
                rec.get("rationale", "")[:500]
            ))
        except Exception as e:
            log.warning(f"Failed to save rec for {rec.get('scheme_code')}: {e}")
    conn.commit()
    cur.close()


def run_ai_analysis():
    conn   = get_conn()
    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

    # Fetch funds that need analysis — prioritise equity, then hybrid, then debt
    # Focus on funds with at least 1Y return history
    with conn.cursor() as cur:
        cur.execute("""
            SELECT m.scheme_code, m.fund_name, m.category, m.amc_name,
                   m.latest_nav, m.return_1y, m.return_3y, m.return_5y
            FROM mf_cache m
            WHERE m.return_1y IS NOT NULL
            ORDER BY
                CASE m.category
                    WHEN 'Equity'  THEN 1
                    WHEN 'Hybrid'  THEN 2
                    WHEN 'Debt'    THEN 3
                    ELSE 4
                END,
                m.return_1y DESC NULLS LAST
            LIMIT %s
        """, (MAX_FUNDS,))
        funds = [dict(r) for r in cur.fetchall()]

    log.info(f"Analysing {len(funds)} funds in batches of {BATCH_SIZE} ...")

    total_saved = 0
    for i in range(0, len(funds), BATCH_SIZE):
        batch = funds[i:i + BATCH_SIZE]
        batch_num = i // BATCH_SIZE + 1

        try:
            recs = analyse_batch(client, batch)
            save_recommendations(conn, recs)
            total_saved += len(recs)
            log.info(f"Batch {batch_num}: saved {len(recs)} recommendations")

            # Respect Claude API rate limits
            time.sleep(1)

        except json.JSONDecodeError as e:
            log.error(f"Batch {batch_num}: JSON parse error — {e}")
            time.sleep(5)
        except anthropic.RateLimitError:
            log.warning(f"Batch {batch_num}: rate limited — waiting 60s")
            time.sleep(60)
        except Exception as e:
            log.error(f"Batch {batch_num}: error — {e}")
            time.sleep(3)

    conn.close()
    log.info(f"✅ AI analysis complete — {total_saved} recommendations saved")
    return total_saved


if __name__ == "__main__":
    start = time.time()
    saved = run_ai_analysis()
    elapsed = round(time.time() - start, 1)
    log.info(f"Total time: {elapsed}s")
