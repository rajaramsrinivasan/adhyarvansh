"""
fund_metrics.py  —  risk and consistency metrics from a fund's NAV history.

Phase 1 of the scoring engine. Uses only the daily NAV series that mfapi.in
already returns for each scheme, so no extra data source is needed.

compute_metrics(nav_data) takes mfapi's list (newest first, [{"date": "dd-mm-yyyy",
"nav": "123.45"}, ...]) and returns a dict, or None when there is not enough
history to say anything reliable (less than ~1 year of data).

Definitions (all annualised, risk-free rate 6.5%):
  std_dev          volatility of daily returns, % a year
  sharpe_ratio     (CAGR - rf) / volatility
  sortino_ratio    (CAGR - rf) / downside deviation (only falls below rf count)
  max_drawdown     worst peak-to-trough fall, in % (negative number)
  consistency_pct  share of rolling 1-year windows that beat the risk-free rate

Window: last 3 years for volatility / Sharpe / Sortino / drawdown (or all data
if shorter, minimum 1 year). Consistency needs at least 2 years and looks at up
to the last 5.
"""
import math
from datetime import datetime

RF = 6.5                  # risk-free rate proxy, % a year (≈ Indian 10Y g-sec)
TRADING_DAYS = 252
MIN_POINTS = 240          # about one year of daily NAVs
GLITCH_MOVE = 0.25        # ignore single-day moves beyond ±25% (data errors / payouts)


def _series(nav_data):
    """Return [(date, nav)] oldest → newest, skipping bad rows."""
    out = []
    for e in nav_data or []:
        try:
            d = datetime.strptime(e["date"], "%d-%m-%Y")
            v = float(e["nav"])
        except Exception:
            continue
        if v > 0:
            out.append((d, v))
    out.sort(key=lambda t: t[0])
    return out


def _window(s, years):
    if not s:
        return s
    cutoff = s[-1][0].replace(year=s[-1][0].year - years) if s[-1][0].month != 2 or s[-1][0].day != 29 \
        else s[-1][0].replace(year=s[-1][0].year - years, day=28)
    return [p for p in s if p[0] >= cutoff]


def compute_metrics(nav_data):
    s_all = _series(nav_data)
    s = _window(s_all, 3)
    if len(s) < MIN_POINTS:
        return None

    # daily returns, dropping glitches
    rets = []
    for i in range(1, len(s)):
        r = s[i][1] / s[i - 1][1] - 1
        if abs(r) <= GLITCH_MOVE:
            rets.append(r)
    if len(rets) < MIN_POINTS - 5:
        return None

    mean = sum(rets) / len(rets)
    var = sum((r - mean) ** 2 for r in rets) / (len(rets) - 1)
    vol = math.sqrt(var) * math.sqrt(TRADING_DAYS) * 100          # % a year

    years = (s[-1][0] - s[0][0]).days / 365.25
    if years <= 0:
        return None
    cagr = ((s[-1][1] / s[0][1]) ** (1 / years) - 1) * 100

    rf_daily = (1 + RF / 100) ** (1 / TRADING_DAYS) - 1
    downs = [min(r - rf_daily, 0.0) ** 2 for r in rets]
    dd_dev = math.sqrt(sum(downs) / len(downs)) * math.sqrt(TRADING_DAYS) * 100

    sharpe = (cagr - RF) / vol if vol > 0.05 else 0.0
    sortino = (cagr - RF) / dd_dev if dd_dev > 0.05 else (sharpe * 1.5 if sharpe else 0.0)

    peak, mdd = s[0][1], 0.0
    for _, v in s:
        peak = max(peak, v)
        mdd = min(mdd, v / peak - 1)

    # consistency: rolling 1Y windows (stepping about a month) over up to 5 years
    consistency = None
    s5 = _window(s_all, 5)
    if (s5[-1][0] - s5[0][0]).days >= 2 * 365:
        wins = beats = 0
        n = len(s5)
        j = 0
        for i in range(0, n, 21):
            target = s5[i][0]
            # find the NAV about one year later
            while j < n and (s5[j][0] - target).days < 365:
                j += 1
            if j >= n:
                break
            r = (s5[j][1] / s5[i][1] - 1) * 100
            wins += 1
            if r > RF:
                beats += 1
        if wins >= 12:
            consistency = round(beats / wins * 100, 1)

    return {
        "std_dev":         round(vol, 2),
        "sharpe_ratio":    round(sharpe, 2),
        "sortino_ratio":   round(sortino, 2),
        "max_drawdown":    round(mdd * 100, 1),
        "consistency_pct": consistency,
        "metrics_days":    len(s),
    }
