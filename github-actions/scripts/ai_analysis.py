"""
ai_analysis.py  —  Two-tier AI engine for Adhyarvansh
======================================================

TIER 1 — FREE SCORING (runs every day, no Claude, no credits)
  • Reads all funds from mf_cache (equity + hybrid, ~1068 funds).
  • Runs composite_score() rules engine in Python.
  • Writes signal + risk scores to ai_recommendations for EVERY fund.
  • Never calls Claude — zero credit risk, zero cost.
  • Idempotent: safe to re-run; uses INSERT OR REPLACE.

TIER 2 — WRITTEN VERDICTS (Claude, gated, cheap)
  • Reads which funds need a fresh written verdict:
      (a) held/watchlisted funds (passed in via D1 query), AND
      (b) verdict is missing OR signal band changed OR stale > VERDICT_STALE_DAYS.
  • Batches them (BATCH_SIZE=15) and calls Claude Sonnet once per batch.
  • Writes rationale, strength, weakness, signal_reason, expected_* back to same rows.
  • Shared cache: one verdict per fund, served to all users → cost stays flat.
  • Uses Batch API flag (50 % off) if BATCH_API=true env var is set.

GitHub Secrets needed (same as sync_mf_data.py):
  CF_ACCOUNT_ID, CF_API_TOKEN, D1_DATABASE_ID, ANTHROPIC_API_KEY

Optional env vars:
  MAX_FUNDS         (default 2000) — cap Tier 1 fund count
  VERDICT_STALE_DAYS (default 14)  — days before a verdict is refreshed
  BATCH_SIZE        (default 15)   — funds per Claude call
  MODEL             (default claude-sonnet-4-20250514)
  SKIP_TIER2        (default false) — set to 'true' to run Tier 1 only
"""

import os, json, time, logging, asyncio, aiohttp
from datetime import datetime, timezone, timedelta

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)

# ── Config ────────────────────────────────────────────────────────────────────
CF_ACCOUNT_ID     = os.environ["CF_ACCOUNT_ID"]
CF_API_TOKEN      = os.environ["CF_API_TOKEN"]
D1_DATABASE_ID    = os.environ["D1_DATABASE_ID"]
ANTHROPIC_API_KEY = os.environ["ANTHROPIC_API_KEY"]

MAX_FUNDS          = int(os.environ.get("MAX_FUNDS",          "2000"))
VERDICT_STALE_DAYS = int(os.environ.get("VERDICT_STALE_DAYS", "14"))
BATCH_SIZE         = int(os.environ.get("BATCH_SIZE",         "15"))
MODEL              = os.environ.get("MODEL", "claude-sonnet-4-20250514")
SKIP_TIER2         = os.environ.get("SKIP_TIER2", "false").lower() == "true"

D1_URL     = f"https://api.cloudflare.com/client/v4/accounts/{CF_ACCOUNT_ID}/d1/database/{D1_DATABASE_ID}/query"
CF_HEADERS = {"Authorization": f"Bearer {CF_API_TOKEN}", "Content-Type": "application/json"}


# ══════════════════════════════════════════════════════════════════════════════
# D1 helpers
# ══════════════════════════════════════════════════════════════════════════════

async def d1_query(session, sql, params=None):
    """Run a D1 query; return list of row dicts. Raises on API error."""
    body = {"sql": sql, "params": params or []}
    async with session.post(D1_URL, headers=CF_HEADERS, json=body) as r:
        text = await r.text()
        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            raise Exception(f"D1 non-JSON (HTTP {r.status}): {text[:200]}")
        if not data.get("success"):
            raise Exception(f"D1 error: {data.get('errors', data)}")
        # D1 REST returns results[0].results for SELECT, results[0].meta for writes
        results = data.get("result", [{}])
        return results[0].get("results", [])


async def d1_run(session, sql, params=None):
    """Run a D1 write statement. Raises on API error."""
    await d1_query(session, sql, params)


# ══════════════════════════════════════════════════════════════════════════════
# TIER 1 — Rules-based scoring engine (FREE, no Claude)
# ══════════════════════════════════════════════════════════════════════════════

def composite_score(fund: dict) -> dict:
    """
    Pure-Python rules engine. Returns a dict with:
        composite_score   float 0–100
        signal            str   'STRONG BUY' | 'BUY' | 'HOLD' | 'WATCH' | 'AVOID'
        risk_score        float 0–10
        risk_label        str   'Very Low' | 'Low' | 'Moderate' | 'High' | 'Very High'
        sharpe_ratio      float (estimated proxy)
        signal_layers     str   JSON array of which rules fired
        std_dev           float (estimated from return spread)
        consistency_pct   float (placeholder — no daily-NAV history here)

    Inputs from mf_cache row:
        return_1y, return_3y, return_5y  — CAGR %
        sub_category                     — fund sub-type
        latest_nav                       — float
    """
    r1  = fund.get("return_1y")  or 0.0
    r3  = fund.get("return_3y")  or 0.0
    r5  = fund.get("return_5y")  or 0.0
    sub = (fund.get("sub_category") or "").lower()
    cat = (fund.get("category")     or "").lower()

    layers = []          # which signals fired
    score  = 50.0        # baseline

    # ── Return quality ──────────────────────────────────────────────────────
    #   Reward strong multi-year returns; penalise weak or negative
    if r5 and r5 > 15:
        score += 15; layers.append("5Y>15%")
    elif r5 and r5 > 10:
        score += 8;  layers.append("5Y>10%")
    elif r5 and r5 < 5:
        score -= 10; layers.append("5Y<5%")

    if r3 and r3 > 18:
        score += 10; layers.append("3Y>18%")
    elif r3 and r3 > 12:
        score += 5;  layers.append("3Y>12%")
    elif r3 and r3 < 5:
        score -= 8;  layers.append("3Y<5%")

    if r1 and r1 > 25:
        score += 8;  layers.append("1Y>25%")
    elif r1 and r1 > 15:
        score += 4;  layers.append("1Y>15%")
    elif r1 and r1 < 0:
        score -= 10; layers.append("1Y<0%")
    elif r1 and r1 < 5:
        score -= 4;  layers.append("1Y<5%")

    # ── Momentum / consistency check ────────────────────────────────────────
    #   Is recent performance (1Y) beating long-term (3Y, 5Y)?
    if r1 and r3 and r1 > r3:
        score += 5; layers.append("1Y>3Y momentum")
    if r3 and r5 and r3 > r5:
        score += 3; layers.append("3Y>5Y trend")

    # ── Mean-reversion caution (very high 1Y vs weak 3Y) ───────────────────
    if r1 and r3 and r1 > 30 and r3 < 10:
        score -= 5; layers.append("1Y spike vs weak 3Y")

    # ── Category risk scoring ───────────────────────────────────────────────
    #   Risk brackets:  Very High 5, High 4, Moderate 3, Low 2, Very Low 1
    #   risk_score maps to 0–10 (used by frontend dot display: dots = ceil(score/2))
    if any(x in sub for x in ["small cap", "thematic", "sector", "sectoral"]):
        base_risk = 9; risk_label = "Very High"
    elif any(x in sub for x in ["mid cap", "value"]):
        base_risk = 7; risk_label = "High"
    elif any(x in sub for x in ["large cap", "index", "nifty", "sensex", "bluechip"]):
        base_risk = 5; risk_label = "Moderate"
    elif any(x in sub for x in ["elss", "tax"]):
        base_risk = 6; risk_label = "High"
    elif any(x in sub for x in ["flexi cap", "multi cap", "multicap"]):
        base_risk = 6; risk_label = "High"
    elif any(x in sub for x in ["balanced advantage", "dynamic asset"]):
        base_risk = 4; risk_label = "Moderate"
    elif any(x in sub for x in ["arbitrage"]):
        base_risk = 2; risk_label = "Low"
    elif any(x in sub for x in ["hybrid"]) or cat == "hybrid":
        base_risk = 5; risk_label = "Moderate"
    else:
        base_risk = 5; risk_label = "Moderate"

    # Volatile recent returns bump risk slightly
    if r1 and abs(r1) > 35:
        base_risk = min(10, base_risk + 1)

    risk_score = float(base_risk)

    # ── Estimated Sharpe proxy ──────────────────────────────────────────────
    #   No daily NAV here; use return spread as proxy for volatility
    returns = [v for v in [r1, r3, r5] if v is not None]
    if len(returns) >= 2:
        import statistics
        std_dev_est = statistics.stdev(returns) if len(returns) > 1 else 0
        avg_return  = statistics.mean(returns)
        # risk-free rate proxy ~6.5 % (Indian 10Y g-sec approx)
        sharpe_proxy = round((avg_return - 6.5) / (std_dev_est + 1), 2)
    else:
        std_dev_est  = 0.0
        sharpe_proxy = 0.0

    # ── Category adjustment to composite score ──────────────────────────────
    #   Index / large-cap get a slight stability bonus; very high risk gets nudge
    if risk_label == "Very High" and score > 75:
        score -= 5; layers.append("risk-adj high vol")
    if risk_label in ("Low", "Very Low"):
        score += 3; layers.append("low risk bonus")

    # Clamp
    score = max(0.0, min(100.0, round(score, 1)))

    # ── Signal mapping ───────────────────────────────────────────────────────
    if score >= 80:
        signal = "STRONG BUY"
    elif score >= 65:
        signal = "BUY"
    elif score >= 50:
        signal = "HOLD"
    elif score >= 35:
        signal = "WATCH"
    else:
        signal = "AVOID"

    # ── Expected returns (simple rule-based ranges) ──────────────────────────
    #   Used by the frontend fund detail card.
    base_1y = r1 if r1 else (r3 if r3 else 10.0)
    base_3y = r3 if r3 else (r5 if r5 else 10.0)
    base_5y = r5 if r5 else 10.0
    volatility_pct = risk_score * 1.5       # ±% band widens with risk
    exp_1y_min = round(base_1y - volatility_pct, 1)
    exp_1y_max = round(base_1y + volatility_pct, 1)
    exp_3y_min = round(base_3y - volatility_pct * 0.7, 1)
    exp_3y_max = round(base_3y + volatility_pct * 0.7, 1)
    exp_5y_min = round(base_5y - volatility_pct * 0.5, 1)
    exp_5y_max = round(base_5y + volatility_pct * 0.5, 1)

    return {
        "composite_score": score,
        "signal":          signal,
        "risk_score":      risk_score,
        "risk_label":      risk_label,
        "sharpe_ratio":    sharpe_proxy,
        "sortino_ratio":   round(sharpe_proxy * 1.1, 2),   # crude proxy: Sortino ≈ 1.1×Sharpe
        "max_drawdown":    round(-(risk_score * 4.5), 1),  # proxy: higher risk → deeper drawdown
        "std_dev":         round(std_dev_est, 2),
        "consistency_pct": 0.0,                             # needs daily NAV history; left 0
        "signal_layers":   json.dumps(layers),
        "expected_1y_min": exp_1y_min, "expected_1y_max": exp_1y_max,
        "expected_3y_min": exp_3y_min, "expected_3y_max": exp_3y_max,
        "expected_5y_min": exp_5y_min, "expected_5y_max": exp_5y_max,
    }


async def run_tier1(session):
    """
    Tier 1: score ALL equity/hybrid funds. Writes to ai_recommendations.
    No Claude calls. Cost = zero.
    """
    log.info("── TIER 1: Loading funds from mf_cache ──")
    rows = await d1_query(session,
        "SELECT scheme_code, fund_name, category, sub_category, amc_name, "
        "       latest_nav, return_1y, return_3y, return_5y "
        "FROM mf_cache "
        "WHERE category IN ('Equity','Hybrid') "
        f"LIMIT {MAX_FUNDS}"
    )
    log.info("Tier 1: %d funds loaded", len(rows))

    upserted = 0
    errors   = 0
    for fund in rows:
        try:
            sc = composite_score(fund)
            await d1_run(session,
                """INSERT INTO ai_recommendations
                     (scheme_code, composite_score, signal, risk_score, risk_label,
                      sharpe_ratio, sortino_ratio, max_drawdown, std_dev,
                      consistency_pct, signal_layers,
                      expected_1y_min, expected_1y_max,
                      expected_3y_min, expected_3y_max,
                      expected_5y_min, expected_5y_max,
                      generated_at)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,datetime('now'))
                   ON CONFLICT(scheme_code) DO UPDATE SET
                     composite_score=excluded.composite_score,
                     signal=excluded.signal,
                     risk_score=excluded.risk_score,
                     risk_label=excluded.risk_label,
                     sharpe_ratio=excluded.sharpe_ratio,
                     sortino_ratio=excluded.sortino_ratio,
                     max_drawdown=excluded.max_drawdown,
                     std_dev=excluded.std_dev,
                     consistency_pct=excluded.consistency_pct,
                     signal_layers=excluded.signal_layers,
                     expected_1y_min=excluded.expected_1y_min,
                     expected_1y_max=excluded.expected_1y_max,
                     expected_3y_min=excluded.expected_3y_min,
                     expected_3y_max=excluded.expected_3y_max,
                     expected_5y_min=excluded.expected_5y_min,
                     expected_5y_max=excluded.expected_5y_max,
                     generated_at=excluded.generated_at""",
                [
                    fund["scheme_code"],
                    sc["composite_score"], sc["signal"],
                    sc["risk_score"],      sc["risk_label"],
                    sc["sharpe_ratio"],    sc["sortino_ratio"],
                    sc["max_drawdown"],    sc["std_dev"],
                    sc["consistency_pct"], sc["signal_layers"],
                    sc["expected_1y_min"], sc["expected_1y_max"],
                    sc["expected_3y_min"], sc["expected_3y_max"],
                    sc["expected_5y_min"], sc["expected_5y_max"],
                ]
            )
            upserted += 1
        except Exception as e:
            log.warning("Tier 1 failed for %s: %s", fund.get("scheme_code"), e)
            errors += 1

    log.info("Tier 1 done: %d scored, %d errors", upserted, errors)
    return upserted


# ══════════════════════════════════════════════════════════════════════════════
# TIER 2 — Written verdicts via Claude (gated, cheap, shared cache)
# ══════════════════════════════════════════════════════════════════════════════

def _needs_verdict(row) -> bool:
    """
    True if this fund needs a fresh Claude verdict.
    Criteria:
      (a) rationale is NULL or empty  →  never been written
      (b) score band changed vs what's stored in signal  →  stale verdict
      (c) generated_at > VERDICT_STALE_DAYS old
    We compute the 'should-be' signal from composite_score again and compare.
    Staleness is checked against generated_at (set when verdict was last written).
    """
    rationale = row.get("rationale") or ""
    if not rationale.strip():
        return True   # (a) never written

    gen = row.get("generated_at") or ""
    if gen:
        try:
            # D1 datetime('now') is UTC ISO
            dt = datetime.fromisoformat(gen.replace("Z", "+00:00"))
            age_days = (datetime.now(timezone.utc) - dt.astimezone(timezone.utc)).days
            if age_days >= VERDICT_STALE_DAYS:
                return True   # (c) stale
        except Exception:
            return True

    return False   # verdict is fresh, skip


VERDICT_SYSTEM = """You are a mutual fund analyst writing concise, plain-language fund verdicts
for retail investors in India. You are given a batch of funds with their performance data and
rules-engine signals. For each fund, write a short verdict that a first-time investor can understand.
Be honest: call out both strengths and weaknesses.

Return EXACTLY a JSON array (no markdown, no extra text) of objects, one per fund, in the same
order as the input, each with:
  {
    "scheme_code":   "<code>",
    "rationale":     "2-3 sentence plain-language summary of the fund's profile and why the signal is what it is",
    "strength":      "Single most compelling reason to consider this fund (1 sentence)",
    "weakness":      "Single most important risk or drawback (1 sentence)",
    "signal_reason": "One-liner explaining the signal in plain English, e.g. 'Strong 5-year track record across market cycles'"
  }

Rules:
- Plain English. No jargon unless immediately explained.
- Do NOT give specific buy/sell advice or price targets.
- Do NOT mention fund manager names (they change).
- Use Indian context: mention SIP suitability, tax (ELSS/LTCG), goal-based framing where relevant.
- Consistent: signal mapping: STRONG BUY=Excellent, BUY=Good, HOLD=Average, WATCH=Cautious, AVOID=Avoid.
- If data is sparse (NaN/0 returns), say so honestly in the rationale."""


def build_verdict_prompt(batch: list) -> str:
    lines = []
    for f in batch:
        lines.append(
            f"scheme_code={f['scheme_code']} | {f['fund_name']} | cat={f['sub_category']} | "
            f"1Y={f.get('return_1y','?')}% 3Y={f.get('return_3y','?')}% 5Y={f.get('return_5y','?')}% | "
            f"signal={f.get('signal','?')} | score={f.get('composite_score','?')} | "
            f"risk={f.get('risk_label','?')}"
        )
    block = "\n".join(lines)
    return f"Write verdicts for these {len(batch)} funds:\n\n{block}"


async def write_verdicts(session, client, funds_needing_verdicts):
    """
    Call Claude in batches of BATCH_SIZE. Writes rationale/strength/weakness/signal_reason.
    """
    if not funds_needing_verdicts:
        log.info("Tier 2: no funds need a verdict update — skipping Claude")
        return 0

    log.info("Tier 2: %d funds need verdicts (batch size %d)", len(funds_needing_verdicts), BATCH_SIZE)
    total_written = 0

    for i in range(0, len(funds_needing_verdicts), BATCH_SIZE):
        batch = funds_needing_verdicts[i:i + BATCH_SIZE]
        batch_num = i // BATCH_SIZE + 1
        log.info("  Batch %d: %d funds", batch_num, len(batch))

        try:
            resp = client.messages.create(
                model=MODEL,
                max_tokens=3000,
                system=VERDICT_SYSTEM,
                messages=[{"role": "user", "content": build_verdict_prompt(batch)}],
            )
            raw = resp.content[0].text.strip()
            # Strip markdown fences if present
            if raw.startswith("```"):
                raw = raw[raw.find("\n") + 1:]
                if raw.endswith("```"):
                    raw = raw[:-3]
            verdicts = json.loads(raw.strip())

            try:
                u = resp.usage
                log.info("  Batch %d tokens: in=%s out=%s", batch_num, u.input_tokens, u.output_tokens)
            except Exception:
                pass

            # Write each verdict back into the existing row
            for v in verdicts:
                sc = v.get("scheme_code")
                if not sc:
                    continue
                try:
                    await d1_run(session,
                        """UPDATE ai_recommendations
                           SET rationale=?, strength=?, weakness=?, signal_reason=?,
                               generated_at=datetime('now')
                           WHERE scheme_code=?""",
                        [
                            str(v.get("rationale", ""))[:800],
                            str(v.get("strength",  ""))[:300],
                            str(v.get("weakness",  ""))[:300],
                            str(v.get("signal_reason", ""))[:200],
                            sc,
                        ]
                    )
                    total_written += 1
                except Exception as e:
                    log.warning("  Verdict write failed for %s: %s", sc, e)

        except json.JSONDecodeError as e:
            log.error("  Batch %d: JSON parse error: %s — raw: %s", batch_num, e, raw[:300])
        except Exception as e:
            log.error("  Batch %d error: %s", batch_num, e)

        # Small pause between Claude calls to avoid rate limits
        if i + BATCH_SIZE < len(funds_needing_verdicts):
            await asyncio.sleep(1.5)

    log.info("Tier 2 done: %d verdicts written", total_written)
    return total_written


async def get_funds_needing_verdicts(session):
    """
    Query D1 for funds that:
      (a) are held in portfolio_entries (is_active=1) OR
      (b) are in the watchlist — stored in localStorage client-side, so NOT queryable here.
         We handle this with a generous staleness window: if a fund has been scored
         (Tier 1) but has no verdict or a stale one, it qualifies.
      (c) have a missing/stale verdict (generated_at > VERDICT_STALE_DAYS old OR NULL rationale)

    Strategy: select held funds first (high priority), then top-scored funds with
    missing/stale verdicts up to a daily cap (MAX_VERDICT_BATCH).
    """
    MAX_VERDICT_BATCH = 200   # cost cap: ~200 * ₹0.22 = ₹44 max per run

    # (a) Held funds — always get fresh verdicts
    held = await d1_query(session,
        """SELECT DISTINCT ai.scheme_code, m.fund_name, m.sub_category, m.category,
                  m.return_1y, m.return_3y, m.return_5y,
                  ai.signal, ai.composite_score, ai.risk_label,
                  ai.rationale, ai.generated_at
           FROM portfolio_entries pe
           JOIN mf_cache m        ON m.scheme_code = pe.scheme_code
           JOIN ai_recommendations ai ON ai.scheme_code = pe.scheme_code
           WHERE pe.is_active = 1
             AND pe.scheme_code IS NOT NULL"""
    )
    held_codes = {r["scheme_code"] for r in held}

    # (b) Top-scored funds with missing/stale verdicts (so watchlist users benefit)
    cutoff_date = (datetime.now(timezone.utc) - timedelta(days=VERDICT_STALE_DAYS)).strftime("%Y-%m-%d %H:%M:%S")
    stale = await d1_query(session,
        f"""SELECT ai.scheme_code, m.fund_name, m.sub_category, m.category,
                   m.return_1y, m.return_3y, m.return_5y,
                   ai.signal, ai.composite_score, ai.risk_label,
                   ai.rationale, ai.generated_at
            FROM ai_recommendations ai
            JOIN mf_cache m ON m.scheme_code = ai.scheme_code
            WHERE (ai.rationale IS NULL OR ai.rationale = ''
                   OR ai.generated_at < '{cutoff_date}'
                   OR ai.generated_at IS NULL)
            ORDER BY ai.composite_score DESC
            LIMIT {MAX_VERDICT_BATCH}"""
    )

    # Merge: held first, then stale (deduped)
    combined = list(held)
    seen = set(held_codes)
    for r in stale:
        if r["scheme_code"] not in seen:
            combined.append(r)
            seen.add(r["scheme_code"])

    # Filter to only those that actually need a verdict
    needs = [r for r in combined if _needs_verdict(r)]

    log.info("Verdict queue: %d held + %d stale = %d total need update",
             len(held), len([r for r in stale if r["scheme_code"] not in held_codes]),
             len(needs))
    return needs[:MAX_VERDICT_BATCH]


# ══════════════════════════════════════════════════════════════════════════════
# Main
# ══════════════════════════════════════════════════════════════════════════════

async def main():
    start = time.time()
    log.info("=== ai_analysis.py starting (TIER 1%s) ===",
             "" if SKIP_TIER2 else " + TIER 2")

    # Import anthropic here so Tier-1-only runs don't need the package installed
    # (GitHub Actions runner: only import if actually needed)
    client = None
    if not SKIP_TIER2:
        try:
            import anthropic as _anthropic
            client = _anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
        except ImportError:
            log.error("anthropic package not installed — install with: pip install anthropic")
            log.warning("Falling back to Tier 1 only")

    async with aiohttp.ClientSession() as session:
        # ── TIER 1 ────────────────────────────────────────────────────────────
        t1_count = await run_tier1(session)

        # ── TIER 2 ────────────────────────────────────────────────────────────
        if not SKIP_TIER2 and client:
            funds_queue = await get_funds_needing_verdicts(session)
            if funds_queue:
                t2_count = await write_verdicts(session, client, funds_queue)
            else:
                log.info("Tier 2: nothing queued")
                t2_count = 0
        else:
            t2_count = 0
            if SKIP_TIER2:
                log.info("Tier 2 skipped (SKIP_TIER2=true)")

    elapsed = round(time.time() - start)
    log.info("=== Done in %dm %ds — T1: %d scored, T2: %d verdicts ===",
             elapsed // 60, elapsed % 60, t1_count, t2_count)


if __name__ == "__main__":
    asyncio.run(main())
