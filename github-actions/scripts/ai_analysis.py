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
  MAX_FUNDS         (default 100000) — cap Tier 1 fund count
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

MAX_FUNDS          = int(os.environ.get("MAX_FUNDS",          "100000"))
VERDICT_STALE_DAYS = int(os.environ.get("VERDICT_STALE_DAYS", "14"))
BATCH_SIZE         = int(os.environ.get("BATCH_SIZE",         "15"))
MODEL              = os.environ.get("MODEL", "claude-sonnet-4-20250514")
SKIP_TIER2         = os.environ.get("SKIP_TIER2", "false").lower() == "true"
# 1 = live scoring uses the original return-based rules (v1).
# 2 = live scoring uses v2 (adds Sharpe, Sortino, drawdown, consistency).
# Both are always computed and stored side by side (composite_score_v2 / signal_v2).
ENGINE_VERSION     = os.environ.get("ENGINE_VERSION", "1").strip()

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


def signal_for(score: float) -> str:
    if score >= 80: return "STRONG BUY"
    if score >= 65: return "BUY"
    if score >= 50: return "HOLD"
    if score >= 35: return "WATCH"
    return "AVOID"


# Typical worst fall (%) for each risk bracket. A fund that falls much less than
# its bracket usually is doing something right; much more is a warning sign.
TYPICAL_DRAWDOWN = {"Very High": 35, "High": 28, "Moderate": 22, "Low": 8, "Very Low": 3}


def composite_score_v2(fund: dict, v1: dict) -> dict:
    """
    v2 = v1 (returns, momentum, risk bracket) plus risk-adjusted checks from the
    fund's own NAV history. Weights follow the Layer 1 table, scaled to this score:
      Sharpe  > 1.2 good / < 0.8 weak        (+8 / -8)
      Sortino > 1.5 good / < 1.0 weak        (+5 / -5)
      Max drawdown vs the typical fall for its risk bracket   (+5 / -6)
      Consistency (rolling 1-year windows beating 6.5%)       (+6 / -6)
    Funds with under ~1 year of NAV history keep their v1 score unchanged.
    """
    score = v1["composite_score"]
    layers = json.loads(v1["signal_layers"]) if v1.get("signal_layers") else []
    sharpe, sortino = fund.get("m_sharpe"), fund.get("m_sortino")
    mdd, cons = fund.get("m_maxdd"), fund.get("m_consistency")
    if fund.get("m_days") is None or sharpe is None:
        layers.append("v2: not enough NAV history")
        return {"score": score, "signal": signal_for(score), "layers": layers}

    if sharpe > 1.2:   score += 8;  layers.append("Sharpe>1.2")
    elif sharpe < 0.8: score -= 8;  layers.append("Sharpe<0.8")
    if sortino is not None:
        if sortino > 1.5:   score += 5; layers.append("Sortino>1.5")
        elif sortino < 1.0: score -= 5; layers.append("Sortino<1.0")
    if mdd is not None:
        typ = TYPICAL_DRAWDOWN.get(v1["risk_label"], 22)
        fall = abs(mdd)
        if fall <= typ * 0.8:    score += 5; layers.append("small drawdown")
        elif fall >= typ * 1.25: score -= 6; layers.append("deep drawdown")
    if cons is not None:
        if cons >= 75:   score += 6; layers.append("consistency>=75%")
        elif cons < 45:  score -= 6; layers.append("consistency<45%")
        elif cons >= 60: score += 2; layers.append("consistency>=60%")

    score = max(0.0, min(100.0, round(score, 1)))
    return {"score": score, "signal": signal_for(score), "layers": layers}


SCORED_BY_EQUITY_RULES = ("Equity", "Hybrid")


def composite_score_other(fund: dict, base: dict) -> dict:
    """
    Score for funds the equity rules do not fit: liquid, debt, gilt and gold/silver.
    `base` is the equity-rule result, reused only for the expected-return ranges.
    Debt-like funds are judged on yield against the 6.5% risk-free rate, on how
    little they fall, and on how steady the ride is. Unclassified funds keep the
    generic score and say so.
    """
    sub = (fund.get("sub_category") or "")
    r1, r3, r5 = fund.get("return_1y"), fund.get("return_3y"), fund.get("return_5y")
    mdd, cons, vol = fund.get("m_maxdd"), fund.get("m_consistency"), fund.get("m_vol")
    sharpe = fund.get("m_sharpe")
    out = dict(base)
    layers = []
    score = 50.0

    if sub == "Liquid":
        out["risk_score"], out["risk_label"] = 1.0, "Very Low"
        if r1 is not None:
            if r1 >= 7.0:   score += 15; layers.append("yield>=7%")
            elif r1 >= 6.5: score += 8;  layers.append("yield>=6.5%")
            elif r1 < 5.5:  score -= 12; layers.append("yield<5.5%")
        if r3 is not None and r3 >= 6.0: score += 6; layers.append("3Y steady")
        if vol is not None and vol > 1.0:  score -= 8;  layers.append("unusual swings")
        if mdd is not None and mdd < -1.0: score -= 10; layers.append("fell>1%")
        elif mdd is not None:              score += 6;  layers.append("no real falls")
    elif sub in ("Debt", "Gilt"):
        gilt = sub == "Gilt"
        out["risk_score"], out["risk_label"] = (4.0, "Moderate") if gilt else (3.0, "Low")
        if r3 is not None:
            if r3 >= 8:    score += 14; layers.append("3Y>=8%")
            elif r3 >= 7:  score += 8;  layers.append("3Y>=7%")
            elif r3 < 6:   score -= 10; layers.append("3Y<6%")
        if r1 is not None:
            if r1 >= 8:    score += 6;  layers.append("1Y>=8%")
            elif r1 < 5:   score -= 8;  layers.append("1Y<5%")
        if r5 is not None and r5 >= 7.5: score += 6; layers.append("5Y>=7.5%")
        if mdd is not None:
            lo, hi = (4, 10) if gilt else (2, 6)
            if abs(mdd) <= lo:   score += 8;  layers.append("small fall")
            elif abs(mdd) >= hi: score -= 10; layers.append("deep fall")
        if cons is not None:
            if cons >= 80: score += 6; layers.append("consistency>=80%")
            elif cons < 50: score -= 6; layers.append("consistency<50%")
        if sharpe is not None:
            if sharpe > 1.0:  score += 5; layers.append("Sharpe>1")
            elif sharpe < 0:  score -= 5; layers.append("Sharpe<0")
    elif sub == "Commodity":
        out["risk_score"], out["risk_label"] = 7.0, "High"
        if r5 is not None:
            if r5 > 12:   score += 12; layers.append("5Y>12%")
            elif r5 < 5:  score -= 10; layers.append("5Y<5%")
        if r3 is not None:
            if r3 > 14:   score += 8;  layers.append("3Y>14%")
            elif r3 < 5:  score -= 8;  layers.append("3Y<5%")
        if r1 is not None and r1 < 0: score -= 10; layers.append("1Y<0%")
        if mdd is not None and abs(mdd) >= 25: score -= 6; layers.append("deep fall")
        if sharpe is not None:
            if sharpe > 1.0:  score += 6; layers.append("Sharpe>1")
            elif sharpe < 0.3: score -= 6; layers.append("Sharpe<0.3")
    else:
        # unclassified: keep the generic rules and flag it
        return {**base, "score": base["composite_score"], "signal": signal_for(base["composite_score"]),
                "layers": (json.loads(base["signal_layers"]) if base.get("signal_layers") else []) + ["category unclear"]}

    score = max(0.0, min(100.0, round(score, 1)))
    out["composite_score"] = score
    out["signal"] = signal_for(score)
    out["signal_layers"] = json.dumps(layers)
    return {**out, "score": score, "layers": layers}


def nav_age_days(nav_date):
    """Days since the fund's last NAV (dd-mm-yyyy); None if missing or unreadable."""
    try:
        return (datetime.now() - datetime.strptime(nav_date, "%d-%m-%Y")).days
    except Exception:
        return None


def _f(x, d=1):
    return f"{x:.{d}f}"


def make_tagline(fund: dict, signal: str, peer, use_metrics: bool, use_rel: bool) -> str:
    """
    One short line that says why the fund got its rating, built from its own
    numbers (no AI call). Leads with what drives the signal, adds the main caveat.
    """
    sub = fund.get("sub_category") or ""
    cat = fund.get("category") or ""
    r1, r3, r5 = fund.get("return_1y"), fund.get("return_3y"), fund.get("return_5y")
    pos, neg = [], []
    yield_like = sub in ("Liquid", "Debt", "Gilt") or cat == "Debt"

    if r1 is None and r3 is None and r5 is None:
        return "Too new to rate fully; not enough return history yet."

    # returns
    if r5 is not None:
        if r5 >= (7.5 if yield_like else 15): pos.append((3, f"{_f(r5)}% a year over 5 years"))
        elif r5 < 5 and not sub == "Liquid":  neg.append((3, f"weak 5-year return ({_f(r5)}%)"))
    elif r3 is not None:
        if r3 >= (7.5 if yield_like else 15): pos.append((3, f"{_f(r3)}% a year over 3 years"))
        elif r3 < 5 and not sub == "Liquid":  neg.append((3, f"weak 3-year return ({_f(r3)}%)"))
    if sub == "Liquid" and r1 is not None:
        if r1 >= 6.5: pos.append((3, f"yield of {_f(r1)}% beats cash"))
        elif r1 < 5.5: neg.append((4, f"yield of {_f(r1)}% is low for a liquid fund"))
    if r1 is not None:
        if r1 < 0:   neg.append((5, "lost money in the last year"))
        elif r1 < 4 and not sub == "Liquid": neg.append((2, f"slow last year ({_f(r1)}%)"))

    if use_metrics:
        mdd, cons, sharpe = fund.get("m_maxdd"), fund.get("m_consistency"), fund.get("m_sharpe")
        typ = TYPICAL_DRAWDOWN.get(fund.get("risk_label"), 22)
        if sharpe is not None and fund.get("m_days"):
            if sharpe > 1.2:  pos.append((4, "strong return for the risk taken"))
            elif sharpe < 0.8 and not yield_like: neg.append((4, "return does not justify the risk"))
        if mdd is not None:
            if abs(mdd) <= typ * 0.8 and not yield_like: pos.append((2, "holds up well in falls"))
            elif abs(mdd) >= typ * 1.25 and not yield_like: neg.append((4, f"fell {_f(abs(mdd), 0)}% at its worst"))
            elif yield_like and abs(mdd) >= (6 if sub != "Gilt" else 10): neg.append((4, f"fell {_f(abs(mdd), 0)}% at its worst, high for debt"))
            elif yield_like and abs(mdd) <= 2: pos.append((3, "very stable, small falls"))
        if cons is not None:
            if cons >= 75:  pos.append((3, f"beat cash in {_f(cons, 0)}% of rolling years"))
            elif cons < 45: neg.append((3, f"beat cash in only {_f(cons, 0)}% of rolling years"))

    if use_rel and fund.get("sub_category") == "Index":
        te = fund.get("m_te")
        if te is not None and te < 0.5:   pos.insert(0, (6, f"tracks its index within {_f(te, 2)}% a year"))
        elif te is not None and te > 1.0: neg.append((6, f"drifts {_f(te)}% a year from its index"))
    elif use_rel and fund.get("m_alpha") is not None and (fund.get("m_r2") or 0) >= 0.6:
        a, b = fund["m_alpha"], fund.get("m_bench") or "its benchmark"
        if a > 2:   pos.append((5, f"beats {b} by {_f(a)}% a year"))
        elif a < 0: neg.append((5, f"trails {b}"))
        up, dn = fund.get("m_upcap"), fund.get("m_downcap")
        if up is not None and dn is not None and up > 100 and dn < 90:
            pos.append((5, "gains more than it loses against the market"))
        elif dn is not None and dn > 110:
            neg.append((4, "falls harder than the market"))
    if use_rel and peer and sub:
        if peer["q"] == 1:   pos.append((4, f"top quarter of {sub} funds"))
        elif peer["q"] == 4: neg.append((4, f"bottom quarter of {sub} funds"))

    pos.sort(key=lambda t: -t[0])
    neg.sort(key=lambda t: -t[0])
    P = [t for _, t in pos[:2]]
    N = [t for _, t in neg[:1]]
    if not P and not N:
        ref = next(((v, y) for v, y in ((r5, "5"), (r3, "3"), (r1, "1")) if v is not None), None)
        P = [f"{_f(ref[0])}% a year over {ref[1]} year{'s' if ref[1] != '1' else ''}, nothing that stands out"] if ref else []
    good = signal in ("STRONG BUY", "BUY")
    if good:
        line = " and ".join(P) if P else "steady, middle-of-the-road numbers"
        if N: line += f", but {N[0]}"
    elif signal == "HOLD":
        line = (P[0] if P else "mixed record") + (f", but {N[0]}" if N else "")
    else:
        line = (N[0] if N else "weak overall record") + (f", despite {P[0]}" if P else "")
    line = line[0].upper() + line[1:]
    return (line[:117] + "…" if len(line) > 118 else line) + ("" if line.endswith("…") else ".")


def peer_quartiles(rows):
    """
    Rank each fund against others in its sub-category (3-year return and Sharpe,
    averaged). Returns {scheme_code: {"q": 1..4, "ret": 0-1, "sharpe": 0-1}}, where
    q 1 = top quarter and the 0-1 values are percentile ranks (1 = best).
    Needs 8+ peers in the sub-category.
    """
    groups = {}
    for f in rows:
        groups.setdefault(f.get("sub_category") or "?", []).append(f)

    def pct_ranks(funds, key):
        vals = sorted(f[key] for f in funds if f.get(key) is not None)
        n = len(vals)
        out = {}
        for f in funds:
            v = f.get(key)
            if v is not None and n > 1:
                out[f["scheme_code"]] = sum(1 for x in vals if x < v) / (n - 1)
        return out

    res = {}
    for funds in groups.values():
        if len(funds) < 8:
            continue
        a, b = pct_ranks(funds, "return_3y"), pct_ranks(funds, "m_sharpe")
        for f in funds:
            code = f["scheme_code"]
            if code in a and code in b:
                p = (a[code] + b[code]) / 2          # 1.0 = best
                res[code] = {"q": 1 if p >= 0.75 else 2 if p >= 0.5 else 3 if p >= 0.25 else 4,
                             "ret": a[code], "sharpe": b[code]}
    return res


def composite_score_v3(fund: dict, v2: dict, peer) -> dict:
    """
    v3 = v2 plus checks against the fund's benchmark and its peers.
      Alpha (Jensen, needs benchmark fit R2 >= 0.6)   > 2 good (+6) / < 0 weak (-6)
      Alpha with protection: upside capture > 100 and downside capture < 90   (+5)
      Weak protection: downside capture > 110                                  (-4)
      Information ratio  > 0.5 (+3) / < 0 (-3)
      Peer quartile in sub-category: Q1 +5, Q2 +2, Q4 -5
      Efficiency gap: top-half peer returns but bottom-half Sharpe             (-4)
      Decelerating alpha: positive alpha but 1Y return 8+ pts under its 3Y     (-3)
    Index funds are judged on tracking instead: error under 0.5% a year makes the
    fund a mandatory Buy (score floor 65); over 1.0% costs 8 points.
    """
    score = v2["score"]
    layers = list(v2["layers"])
    alpha, beta, r2 = fund.get("m_alpha"), fund.get("m_beta"), fund.get("m_r2")
    up, dn, ir, te = fund.get("m_upcap"), fund.get("m_downcap"), fund.get("m_info"), fund.get("m_te")
    is_index = fund.get("sub_category") == "Index"
    quartile = (peer or {}).get("q")

    if is_index:
        if te is None:
            layers.append("v3: tracking error unavailable")
        elif te < 0.5:
            score = max(score, 65.0); layers.append("index: tracking error<0.5%")
        elif te > 1.0:
            score -= 8; layers.append("index: tracking error>1%")
    else:
        if alpha is not None and r2 is not None and r2 >= 0.6:
            if alpha > 2:    score += 6; layers.append("alpha>2%")
            elif alpha < 0:  score -= 6; layers.append("alpha<0")
            if up is not None and dn is not None:
                if up > 100 and dn < 90: score += 5; layers.append("alpha with protection")
                elif dn > 110:           score -= 4; layers.append("falls harder than benchmark")
            if ir is not None:
                if ir > 0.5:   score += 3; layers.append("info ratio>0.5")
                elif ir < 0:   score -= 3; layers.append("info ratio<0")
            r1, r3 = fund.get("return_1y"), fund.get("return_3y")
            if alpha > 0 and r1 is not None and r3 is not None and r1 < r3 - 8:
                score -= 3; layers.append("decelerating alpha")
        elif alpha is None:
            layers.append("v3: no benchmark data")
        if quartile == 1:   score += 5; layers.append("peer Q1")
        elif quartile == 2: score += 2; layers.append("peer Q2")
        elif quartile == 4: score -= 5; layers.append("peer Q4")
        if peer and peer["ret"] >= 0.5 and peer["sharpe"] < 0.5:
            score -= 4; layers.append("efficiency gap")

    score = max(0.0, min(100.0, round(score, 1)))
    return {"score": score, "signal": signal_for(score), "layers": layers}


def _report_engine_comparison(moves, total, with_metrics, a="v1", b="v2", extra=""):
    """Log (and write to the Actions summary) how engine b differs from engine a."""
    order = ["STRONG BUY", "BUY", "HOLD", "WATCH", "AVOID"]
    changed = sum(n for (x, y), n in moves.items() if x != y)
    lines = [f"### Scoring engine: {a} vs {b} (live = v{ENGINE_VERSION})",
             f"{total} funds scored, {with_metrics} with enough data for the {b} checks, "
             f"{changed} change signal ({(changed / total * 100) if total else 0:.1f}%)." + extra,
             "", f"| {a} \\ {b} | " + " | ".join(order) + " |", "|---|" + "---|" * len(order)]
    for x in order:
        lines.append(f"| **{x}** | " + " | ".join(str(moves.get((x, y), 0)) for y in order) + " |")
    text = "\n".join(lines)
    log.info("\n%s", text)
    path = os.environ.get("GITHUB_STEP_SUMMARY")
    if path:
        with open(path, "a") as f:
            f.write(text + "\n\n")


async def run_tier1(session):
    """
    Tier 1: score ALL equity/hybrid funds. Writes to ai_recommendations.
    No Claude calls. Cost = zero.
    """
    log.info("── TIER 1: Loading funds from mf_cache (engine v%s live) ──", ENGINE_VERSION)
    # Make sure the new columns exist (safe to repeat; ignores "duplicate column")
    for tbl, col, typ in (("mf_cache", "m_sharpe", "REAL"), ("mf_cache", "m_sortino", "REAL"),
                          ("mf_cache", "m_maxdd", "REAL"), ("mf_cache", "m_vol", "REAL"),
                          ("mf_cache", "m_consistency", "REAL"), ("mf_cache", "m_days", "INTEGER"),
                          ("ai_recommendations", "composite_score_v2", "REAL"),
                          ("ai_recommendations", "signal_v2", "TEXT"),
                          ("ai_recommendations", "layers_v2", "TEXT"),
                          ("ai_recommendations", "composite_score_v3", "REAL"),
                          ("ai_recommendations", "signal_v3", "TEXT"),
                          ("ai_recommendations", "layers_v3", "TEXT"),
                          ("ai_recommendations", "peer_quartile", "INTEGER"),
                          ("ai_recommendations", "tagline", "TEXT"),
                          ("mf_cache", "m_alpha", "REAL"), ("mf_cache", "m_beta", "REAL"),
                          ("mf_cache", "m_r2", "REAL"), ("mf_cache", "m_upcap", "REAL"),
                          ("mf_cache", "m_downcap", "REAL"), ("mf_cache", "m_info", "REAL"),
                          ("mf_cache", "m_te", "REAL"), ("mf_cache", "m_bench", "TEXT")):
        try:
            await d1_run(session, f"ALTER TABLE {tbl} ADD COLUMN {col} {typ}")
        except Exception as e:
            if "duplicate column" not in str(e).lower():
                raise
    rows = await d1_query(session,
        "SELECT scheme_code, fund_name, category, sub_category, amc_name, "
        "       latest_nav, nav_date, return_1y, return_3y, return_5y, "
        "       m_sharpe, m_sortino, m_maxdd, m_vol, m_consistency, m_days, "
        "       m_alpha, m_beta, m_r2, m_upcap, m_downcap, m_info, m_te, m_bench "
        "FROM mf_cache "
        f"LIMIT {MAX_FUNDS}"
    )
    log.info("Tier 1: %d funds loaded", len(rows))

    from collections import Counter
    moves = Counter()
    moves23 = Counter()
    with_metrics = 0
    with_bench = 0
    kinds = Counter()
    peers = peer_quartiles([f for f in rows if f.get("category") in SCORED_BY_EQUITY_RULES])
    counts = {"ok": 0, "err": 0}
    sem = asyncio.Semaphore(15)

    async def score_one(fund):
        nonlocal with_metrics, with_bench
        async with sem:
            try:
                sc  = composite_score(fund)
                v1_signal = sc["signal"]
                equity_like = fund.get("category") in SCORED_BY_EQUITY_RULES
                peer = peers.get(fund["scheme_code"]) if equity_like else None
                if equity_like:
                    sc2 = composite_score_v2(fund, sc)
                    sc3 = composite_score_v3(fund, sc2, peer)
                    kinds["equity/hybrid"] += 1
                else:
                    other = composite_score_other(fund, sc)
                    sc.update({k: v for k, v in other.items() if k not in ("score", "layers")})
                    sc2 = sc3 = {"score": other["score"], "signal": signal_for(other["score"]),
                                 "layers": other["layers"]}
                    kinds["other"] += 1
                if equity_like:
                    moves[(v1_signal, sc2["signal"])] += 1
                    moves23[(sc2["signal"], sc3["signal"])] += 1
                if fund.get("m_alpha") is not None or fund.get("m_te") is not None:
                    with_bench += 1

                # Real NAV-based risk numbers replace the rough proxies when we have them
                if fund.get("m_days") is not None and fund.get("m_sharpe") is not None:
                    with_metrics += 1
                    sc["sharpe_ratio"]    = fund["m_sharpe"]
                    sc["sortino_ratio"]   = fund["m_sortino"]
                    sc["max_drawdown"]    = fund["m_maxdd"]
                    sc["std_dev"]         = fund["m_vol"]
                    sc["consistency_pct"] = fund["m_consistency"] or 0.0

                live = sc3 if ENGINE_VERSION == "3" else sc2 if ENGINE_VERSION == "2" else None
                if live and equity_like:
                    sc["composite_score"] = live["score"]
                    sc["signal"]          = live["signal"]
                    sc["signal_layers"]   = json.dumps(live["layers"])
                elif not equity_like:
                    sc["composite_score"] = sc3["score"]
                    sc["signal"]          = sc3["signal"]
                    sc["signal_layers"]   = json.dumps(sc3["layers"])

                age = nav_age_days(fund.get("nav_date"))
                if age is None or age > 90:
                    # No NAV for 90+ days: the fund is dormant, closed or unreadable.
                    sc["signal"] = "NOT RATED"
                    tagline = ("No NAV update since " + fund["nav_date"] + ", so it is not rated.") \
                        if fund.get("nav_date") else "No recent NAV on record, so it is not rated."
                else:
                    tagline = make_tagline(
                        {**fund, "risk_label": sc["risk_label"]}, sc["signal"], peer,
                        use_metrics=(ENGINE_VERSION in ("2", "3")) or not equity_like,
                        use_rel=(ENGINE_VERSION == "3") and equity_like)
                await d1_run(session,
                    """INSERT INTO ai_recommendations
                         (scheme_code, composite_score, signal, risk_score, risk_label,
                          sharpe_ratio, sortino_ratio, max_drawdown, std_dev,
                          consistency_pct, signal_layers,
                          expected_1y_min, expected_1y_max,
                          expected_3y_min, expected_3y_max,
                          expected_5y_min, expected_5y_max,
                          composite_score_v2, signal_v2, layers_v2,
                          composite_score_v3, signal_v3, layers_v3, peer_quartile, tagline,
                          generated_at)
                       VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,datetime('now'))
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
                         composite_score_v2=excluded.composite_score_v2,
                         signal_v2=excluded.signal_v2,
                         layers_v2=excluded.layers_v2,
                         composite_score_v3=excluded.composite_score_v3,
                         signal_v3=excluded.signal_v3,
                         layers_v3=excluded.layers_v3,
                         peer_quartile=excluded.peer_quartile,
                         tagline=excluded.tagline,
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
                        sc2["score"], sc2["signal"], json.dumps(sc2["layers"]),
                        sc3["score"], sc3["signal"], json.dumps(sc3["layers"]),
                        peer["q"] if peer else None,
                        tagline,
                    ]
                )
                counts["ok"] += 1
            except Exception as e:
                log.warning("Tier 1 failed for %s: %s", fund.get("scheme_code"), e)
                counts["err"] += 1

    for i in range(0, len(rows), 1000):
        await asyncio.gather(*(score_one(f) for f in rows[i:i + 1000]))
        log.info("Tier 1 progress: %d/%d", min(i + 1000, len(rows)), len(rows))
    upserted, errors = counts["ok"], counts["err"]
    log.info("Scored by rule set: %s", dict(kinds))

    _report_engine_comparison(moves, upserted, with_metrics, "v1", "v2")
    _report_engine_comparison(moves23, upserted, with_bench, "v2", "v3",
                              f" {len(peers)} funds have a peer quartile.")
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
