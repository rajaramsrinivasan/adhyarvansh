"""
daily_digest.py — Daily email digest matching the Adhyarvansh dashboard
Sections: Portfolio Summary → Holdings with Position Signals → Top AI Picks → Market Movers
"""
import os, smtplib, logging, asyncio, aiohttp, math
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from datetime import datetime, date

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)

CF_ACCOUNT_ID      = os.environ["CF_ACCOUNT_ID"]
CF_API_TOKEN       = os.environ["CF_API_TOKEN"]
D1_DATABASE_ID     = os.environ["D1_DATABASE_ID"]
GMAIL_FROM         = os.environ.get("GMAIL_FROM", "ranjithashetty@gmail.com")
GMAIL_TO           = os.environ.get("GMAIL_TO",   "ranjithashetty@gmail.com")
GMAIL_APP_PASSWORD = os.environ["GMAIL_APP_PASSWORD"]

D1_URL     = f"https://api.cloudflare.com/client/v4/accounts/{CF_ACCOUNT_ID}/d1/database/{D1_DATABASE_ID}/query"
CF_HEADERS = {"Authorization": f"Bearer {CF_API_TOKEN}", "Content-Type": "application/json"}


# ── D1 ────────────────────────────────────────────────────────────────────────
async def q(session, sql, params=None):
    body = {"sql": sql}
    if params: body["params"] = params
    async with session.post(D1_URL, headers=CF_HEADERS, json=body) as r:
        data = await r.json()
        if not data.get("success"):
            raise Exception(f"D1: {data.get('errors')}")
        res = data.get("result", [])
        return res[0].get("results", []) if res else []


# ── Formatters ────────────────────────────────────────────────────────────────
def fmt(n):
    if n is None: return "—"
    n = float(n)
    if abs(n) >= 1e7: return f"₹{n/1e7:.2f}Cr"
    if abs(n) >= 1e5: return f"₹{n/1e5:.2f}L"
    return f"₹{n:,.2f}"

def pct(n):
    if n is None: return "—"
    return f"{float(n):+.2f}%"

def sig_color(s):
    return {"buy":"#16A34A","hold":"#1D4ED8","watch":"#CA8A04","exit":"#DC2626"}.get((s or "").lower(),"#888")

def sig_bg(s):
    return {"buy":"#F0FDF4","hold":"#EFF6FF","watch":"#FEF3C7","exit":"#FEF2F2"}.get((s or "").lower(),"#F3F4F6")

def pos_signal(h):
    """Replicates the frontend positionSignal() logic"""
    try:
        pd   = datetime.strptime(h["purchase_date"], "%Y-%m-%d").date()
        days = (date.today() - pd).days
    except:
        days = 0

    days_to_1yr = max(0, 365 - days)
    is_ltcg     = days >= 365
    near_ltcg   = 0 < days_to_1yr <= 90
    pl_pct      = 0
    try:
        nav_now = float(h.get("latest_nav") or h.get("purchase_nav", 0))
        nav_buy = float(h.get("purchase_nav", 1))
        pl_pct  = (nav_now - nav_buy) / nav_buy * 100 if nav_buy else 0
    except:
        pass

    fund_sig = (h.get("signal") or "").lower()
    is_eq    = (h.get("category") or "").lower() == "equity"

    if fund_sig == "exit" and pl_pct < -20:
        return {"label":"Exit Now",      "color":"#991B1B", "bg":"#FEF2F2",
                "advice":f"Fund fundamentally weak. Consider exiting to limit further losses."}
    if fund_sig == "exit" and near_ltcg and is_eq:
        return {"label":"Tax Wait",      "color":"#92400E", "bg":"#FEF3C7",
                "advice":f"{days_to_1yr} days to 1-year mark. Wait for LTCG benefit before exiting."}
    if fund_sig == "exit":
        return {"label":"Review",        "color":"#B45309", "bg":"#FEF3C7",
                "advice":"Fund showing weakness. Review your position and consider switching."}
    if pl_pct >= 30 and is_ltcg and fund_sig in ("watch","hold"):
        return {"label":"Book Profit",   "color":"#166534", "bg":"#F0FDF4",
                "advice":f"Strong gains ({pl_pct:.1f}%) with LTCG benefit. Good time to book partial profits."}
    if pl_pct >= 15 and near_ltcg and is_eq:
        saving = pl_pct * 0.075
        return {"label":"Tax Wait",      "color":"#92400E", "bg":"#FEF3C7",
                "advice":f"{days_to_1yr} days to LTCG threshold. Save ~{saving:.1f}% tax by waiting."}
    if fund_sig in ("buy","hold"):
        ltcg_note = f" — {days_to_1yr}d to LTCG" if not is_ltcg and is_eq else (" — LTCG ✓" if is_ltcg else "")
        return {"label":"Stay Invested", "color":"#1D4ED8", "bg":"#EFF6FF",
                "advice":f"Fund performing well. Continue holding{ltcg_note}."}
    if fund_sig == "watch":
        return {"label":"Monitor",       "color":"#B45309", "bg":"#FEF3C7",
                "advice":"Mixed signals. Watch for 1–2 quarters before deciding."}
    return     {"label":"Stay Invested", "color":"#1D4ED8", "bg":"#EFF6FF",
                "advice":"Continue holding. Review in next quarterly check."}


# ── HTML helpers ──────────────────────────────────────────────────────────────
def card(title, value, sub="", color="#111"):
    return f"""<div style="flex:1;background:#F8FAFC;border-radius:10px;padding:16px 18px;min-width:120px">
      <div style="font-size:10px;font-weight:600;text-transform:uppercase;letter-spacing:.5px;color:#64748B;margin-bottom:6px">{title}</div>
      <div style="font-size:22px;font-weight:700;color:{color}">{value}</div>
      {f'<div style="font-size:12px;color:#64748B;margin-top:2px">{sub}</div>' if sub else ''}
    </div>"""


# ── Main ──────────────────────────────────────────────────────────────────────
async def build_and_send():
    async with aiohttp.ClientSession() as session:

        # ── 1. Portfolio summary ───────────────────────────────────────────────
        summary = await q(session, """
            SELECT COUNT(p.id) as funds,
                   ROUND(SUM(p.invested_amount),2) as invested,
                   ROUND(SUM(COALESCE(m.latest_nav,p.purchase_nav)*p.units),2) as current_val
            FROM portfolio_entries p
            LEFT JOIN mf_cache m ON m.scheme_code=p.scheme_code
            WHERE p.is_active=1""")
        s         = summary[0] if summary else {}
        invested  = float(s.get("invested")    or 0)
        curr_val  = float(s.get("current_val") or 0)
        gain      = curr_val - invested
        gain_pct  = (gain / invested * 100) if invested else 0
        n_funds   = int(s.get("funds") or 0)
        gain_clr  = "#16A34A" if gain >= 0 else "#DC2626"

        # ── 2. Holdings with position signals ─────────────────────────────────
        holdings = await q(session, """
            SELECT p.id, p.fund_name, p.category, p.amc_name,
                   p.units, p.purchase_nav, p.purchase_date, p.invested_amount,
                   ROUND(COALESCE(m.latest_nav,p.purchase_nav)*p.units,2) as current_value,
                   ROUND(COALESCE(m.latest_nav,p.purchase_nav)*p.units-p.invested_amount,2) as gain_loss,
                   m.latest_nav, ai.signal, ai.rationale
            FROM portfolio_entries p
            LEFT JOIN mf_cache m ON m.scheme_code=p.scheme_code
            LEFT JOIN ai_recommendations ai ON ai.scheme_code=p.scheme_code
            WHERE p.is_active=1
            ORDER BY p.purchase_date DESC""")

        # ── 3. Top AI picks (Buy signals) ──────────────────────────────────────
        top_buy = await q(session, """
            SELECT m.fund_name, m.amc_name, m.category,
                   m.return_1y, m.return_3y, m.return_5y,
                   m.latest_nav, ai.signal, ai.rationale, ai.risk_label
            FROM mf_cache m
            LEFT JOIN ai_recommendations ai ON ai.scheme_code=m.scheme_code
            WHERE ai.signal='buy' AND m.return_1y IS NOT NULL
              AND substr(m.nav_date,7,4) >= '2024'
            ORDER BY m.return_1y DESC LIMIT 5""")

        # ── 4. Funds to watch (Exit/Watch signals with high return) ────────────
        watch_funds = await q(session, """
            SELECT m.fund_name, m.amc_name, m.return_1y, ai.signal, ai.rationale
            FROM mf_cache m
            LEFT JOIN ai_recommendations ai ON ai.scheme_code=m.scheme_code
            WHERE ai.signal IN ('exit','watch') AND m.return_1y IS NOT NULL
              AND substr(m.nav_date,7,4) >= '2024'
            ORDER BY m.return_1y DESC LIMIT 5""")

    # ── Build HTML email ───────────────────────────────────────────────────────
    today = datetime.now().strftime("%A, %d %B %Y")

    # Portfolio summary cards
    summary_cards = "".join([
        card("Funds Held",    str(n_funds)),
        card("Total Invested", fmt(invested)),
        card("Current Value",  fmt(curr_val)),
        card("Total Gain/Loss", fmt(gain), pct(gain_pct), gain_clr),
    ])

    # Holdings rows
    holding_rows = ""
    if holdings:
        for h in holdings:
            gl     = float(h.get("gain_loss") or 0)
            gl_pct = (gl / float(h.get("invested_amount",1))) * 100 if h.get("invested_amount") else 0
            gl_clr = "#16A34A" if gl >= 0 else "#DC2626"
            ps     = pos_signal(h)
            try:
                pd   = datetime.strptime(h["purchase_date"], "%Y-%m-%d").date()
                days = (date.today() - pd).days
                ltcg = " · LTCG ✓" if days >= 365 else f" · {max(0,365-days)}d to LTCG"
            except:
                days = 0; ltcg = ""

            holding_rows += f"""
            <tr>
              <td style="padding:12px 14px;border-bottom:1px solid #F1F5F9;vertical-align:top">
                <div style="font-weight:600;font-size:13px;color:#0F172A">{(h.get('fund_name') or '')[:50]}</div>
                <div style="font-size:11px;color:#64748B;margin-top:2px">{h.get('category','')} · {h.get('amc_name','')}</div>
                <div style="font-size:11px;color:#94A3B8;margin-top:1px">{days} days held{ltcg}</div>
              </td>
              <td style="padding:12px 14px;border-bottom:1px solid #F1F5F9;text-align:right;font-size:13px">{fmt(h.get('invested_amount'))}</td>
              <td style="padding:12px 14px;border-bottom:1px solid #F1F5F9;text-align:right;font-size:13px">{fmt(h.get('current_value'))}</td>
              <td style="padding:12px 14px;border-bottom:1px solid #F1F5F9;text-align:right;font-size:13px;font-weight:600;color:{gl_clr}">{fmt(gl)}<br><span style="font-size:11px;font-weight:400">({pct(gl_pct)})</span></td>
              <td style="padding:12px 14px;border-bottom:1px solid #F1F5F9;text-align:center">
                <span style="padding:3px 10px;border-radius:20px;font-size:11px;font-weight:600;background:{ps['bg']};color:{ps['color']}">{ps['label']}</span>
              </td>
              <td style="padding:12px 14px;border-bottom:1px solid #F1F5F9;font-size:11.5px;color:#64748B;max-width:180px">{ps['advice']}</td>
            </tr>"""
    else:
        holding_rows = '<tr><td colspan="6" style="padding:20px;text-align:center;color:#94A3B8">No holdings yet</td></tr>'

    # Top buy picks
    buy_rows = ""
    for f in top_buy:
        sc = sig_color(f.get("signal",""))
        sb = sig_bg(f.get("signal",""))
        buy_rows += f"""
        <tr>
          <td style="padding:10px 14px;border-bottom:1px solid #F1F5F9;vertical-align:top">
            <div style="font-weight:500;font-size:13px;color:#0F172A">{(f.get('fund_name') or '')[:50]}</div>
            <div style="font-size:11px;color:#64748B">{f.get('amc_name','')} · {f.get('category','')}</div>
          </td>
          <td style="padding:10px 14px;border-bottom:1px solid #F1F5F9;text-align:right;font-size:13px;font-weight:600;color:#16A34A">{pct(f.get('return_1y'))}</td>
          <td style="padding:10px 14px;border-bottom:1px solid #F1F5F9;text-align:right;font-size:13px;color:#475569">{pct(f.get('return_3y'))}</td>
          <td style="padding:10px 14px;border-bottom:1px solid #F1F5F9;text-align:right;font-size:13px;color:#475569">{pct(f.get('return_5y'))}</td>
          <td style="padding:10px 14px;border-bottom:1px solid #F1F5F9;text-align:center">
            <span style="padding:3px 10px;border-radius:20px;font-size:11px;font-weight:600;background:{sb};color:{sc}">{(f.get('signal') or '').upper()}</span>
          </td>
          <td style="padding:10px 14px;border-bottom:1px solid #F1F5F9;font-size:11px;color:#64748B">{(f.get('risk_label') or '')}</td>
        </tr>"""

    # Watch/Exit alerts
    alert_rows = ""
    for f in watch_funds:
        sc = sig_color(f.get("signal",""))
        sb = sig_bg(f.get("signal",""))
        alert_rows += f"""
        <tr>
          <td style="padding:10px 14px;border-bottom:1px solid #F1F5F9">
            <div style="font-weight:500;font-size:13px;color:#0F172A">{(f.get('fund_name') or '')[:50]}</div>
            <div style="font-size:11px;color:#64748B">{f.get('amc_name','')}</div>
          </td>
          <td style="padding:10px 14px;border-bottom:1px solid #F1F5F9;text-align:right;font-size:13px;font-weight:500;color:#16A34A">{pct(f.get('return_1y'))}</td>
          <td style="padding:10px 14px;border-bottom:1px solid #F1F5F9;text-align:center">
            <span style="padding:3px 10px;border-radius:20px;font-size:11px;font-weight:600;background:{sb};color:{sc}">{(f.get('signal') or '').upper()}</span>
          </td>
          <td style="padding:10px 14px;border-bottom:1px solid #F1F5F9;font-size:11px;color:#64748B">{(f.get('rationale') or '')[:80]}</td>
        </tr>"""

    html = f"""<!DOCTYPE html>
<html><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1"></head>
<body style="margin:0;padding:0;background:#F8FAFC;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif">
<div style="max-width:680px;margin:0 auto;padding:24px 16px">

  <!-- Header -->
  <div style="background:linear-gradient(135deg,#0F172A,#1E3A5F);border-radius:14px;padding:24px 28px;margin-bottom:20px">
    <div style="display:flex;justify-content:space-between;align-items:center">
      <div>
        <div style="font-size:22px;font-weight:700;color:#fff;letter-spacing:-0.5px">Adhy<span style="color:#60A5FA;font-style:italic">arvansh</span></div>
        <div style="font-size:12px;color:#94A3B8;margin-top:4px">Daily Intelligence Digest · {today}</div>
      </div>
      <div style="text-align:right">
        <div style="font-size:28px;font-weight:700;color:{gain_clr}">{fmt(gain)}</div>
        <div style="font-size:12px;color:#94A3B8">Total P&L ({pct(gain_pct)})</div>
      </div>
    </div>
  </div>

  <!-- Portfolio Summary Cards -->
  <div style="background:#fff;border-radius:12px;padding:20px;margin-bottom:16px;border:1px solid #E2E8F0">
    <div style="font-size:11px;font-weight:600;text-transform:uppercase;letter-spacing:.6px;color:#64748B;margin-bottom:14px">Portfolio Snapshot</div>
    <div style="display:flex;gap:10px;flex-wrap:wrap">
      {summary_cards}
    </div>
  </div>

  <!-- Holdings with Position Signals -->
  <div style="background:#fff;border-radius:12px;padding:20px;margin-bottom:16px;border:1px solid #E2E8F0">
    <div style="font-size:11px;font-weight:600;text-transform:uppercase;letter-spacing:.6px;color:#64748B;margin-bottom:14px">Holdings — Position Intelligence</div>
    <table style="width:100%;border-collapse:collapse">
      <thead>
        <tr style="background:#F8FAFC">
          <th style="padding:8px 14px;text-align:left;font-size:10px;font-weight:600;color:#64748B;text-transform:uppercase;letter-spacing:.4px">Fund</th>
          <th style="padding:8px 14px;text-align:right;font-size:10px;font-weight:600;color:#64748B;text-transform:uppercase;letter-spacing:.4px">Invested</th>
          <th style="padding:8px 14px;text-align:right;font-size:10px;font-weight:600;color:#64748B;text-transform:uppercase;letter-spacing:.4px">Current</th>
          <th style="padding:8px 14px;text-align:right;font-size:10px;font-weight:600;color:#64748B;text-transform:uppercase;letter-spacing:.4px">P&amp;L</th>
          <th style="padding:8px 14px;text-align:center;font-size:10px;font-weight:600;color:#64748B;text-transform:uppercase;letter-spacing:.4px">Signal</th>
          <th style="padding:8px 14px;font-size:10px;font-weight:600;color:#64748B;text-transform:uppercase;letter-spacing:.4px">Advice</th>
        </tr>
      </thead>
      <tbody>{holding_rows}</tbody>
    </table>
  </div>

  <!-- Top AI Buy Picks -->
  <div style="background:#fff;border-radius:12px;padding:20px;margin-bottom:16px;border:1px solid #E2E8F0">
    <div style="display:flex;align-items:center;gap:8px;margin-bottom:14px">
      <span style="font-size:11px;font-weight:600;text-transform:uppercase;letter-spacing:.6px;color:#64748B">Top AI Buy Picks Today</span>
      <span style="padding:2px 8px;background:#F0FDF4;color:#16A34A;border-radius:10px;font-size:10px;font-weight:600">BUY SIGNAL</span>
    </div>
    <table style="width:100%;border-collapse:collapse">
      <thead>
        <tr style="background:#F8FAFC">
          <th style="padding:8px 14px;text-align:left;font-size:10px;font-weight:600;color:#64748B;text-transform:uppercase">Fund</th>
          <th style="padding:8px 14px;text-align:right;font-size:10px;font-weight:600;color:#64748B;text-transform:uppercase">1Y</th>
          <th style="padding:8px 14px;text-align:right;font-size:10px;font-weight:600;color:#64748B;text-transform:uppercase">3Y</th>
          <th style="padding:8px 14px;text-align:right;font-size:10px;font-weight:600;color:#64748B;text-transform:uppercase">5Y</th>
          <th style="padding:8px 14px;text-align:center;font-size:10px;font-weight:600;color:#64748B;text-transform:uppercase">Signal</th>
          <th style="padding:8px 14px;font-size:10px;font-weight:600;color:#64748B;text-transform:uppercase">Risk</th>
        </tr>
      </thead>
      <tbody>{buy_rows if buy_rows else '<tr><td colspan="6" style="padding:16px;text-align:center;color:#94A3B8;font-size:13px">Run sync to populate AI picks</td></tr>'}</tbody>
    </table>
  </div>

  <!-- Watch / Exit Alerts -->
  <div style="background:#fff;border-radius:12px;padding:20px;margin-bottom:16px;border:1px solid #E2E8F0">
    <div style="display:flex;align-items:center;gap:8px;margin-bottom:14px">
      <span style="font-size:11px;font-weight:600;text-transform:uppercase;letter-spacing:.6px;color:#64748B">Watch &amp; Exit Alerts</span>
      <span style="padding:2px 8px;background:#FEF3C7;color:#CA8A04;border-radius:10px;font-size:10px;font-weight:600">REVIEW NEEDED</span>
    </div>
    <table style="width:100%;border-collapse:collapse">
      <thead>
        <tr style="background:#F8FAFC">
          <th style="padding:8px 14px;text-align:left;font-size:10px;font-weight:600;color:#64748B;text-transform:uppercase">Fund</th>
          <th style="padding:8px 14px;text-align:right;font-size:10px;font-weight:600;color:#64748B;text-transform:uppercase">1Y Return</th>
          <th style="padding:8px 14px;text-align:center;font-size:10px;font-weight:600;color:#64748B;text-transform:uppercase">Signal</th>
          <th style="padding:8px 14px;font-size:10px;font-weight:600;color:#64748B;text-transform:uppercase">AI Reason</th>
        </tr>
      </thead>
      <tbody>{alert_rows if alert_rows else '<tr><td colspan="4" style="padding:16px;text-align:center;color:#94A3B8;font-size:13px">No watch/exit alerts today</td></tr>'}</tbody>
    </table>
  </div>

  <!-- Footer -->
  <div style="text-align:center;padding:16px 0">
    <a href="https://adhyarvansh.com" style="color:#60A5FA;font-size:12px;text-decoration:none;font-weight:500">Open Adhyarvansh →</a>
    <div style="font-size:11px;color:#94A3B8;margin-top:6px">Adhyarvansh · Private &amp; Confidential · Sent daily at 8 AM IST</div>
  </div>

</div>
</body></html>"""

    msg = MIMEMultipart("alternative")
    msg["Subject"] = f"Adhyarvansh · {datetime.now().strftime('%d %b')} · P&L {fmt(gain)} ({pct(gain_pct)})"
    msg["From"]    = GMAIL_FROM
    msg["To"]      = GMAIL_TO
    msg.attach(MIMEText(html, "html"))

    with smtplib.SMTP("smtp.gmail.com", 587) as s:
        s.ehlo(); s.starttls()
        s.login(GMAIL_FROM, GMAIL_APP_PASSWORD)
        s.sendmail(GMAIL_FROM, GMAIL_TO, msg.as_string())

    log.info(f"✅ Digest sent to {GMAIL_TO} | P&L: {fmt(gain)} ({pct(gain_pct)})")


if __name__ == "__main__":
    asyncio.run(build_and_send())
