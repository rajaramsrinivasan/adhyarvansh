"""
daily_digest.py — Reads from D1 via Cloudflare REST API, sends Gmail digest
"""
import os, smtplib, logging, asyncio, aiohttp
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from datetime import datetime

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)

CF_ACCOUNT_ID     = os.environ["CF_ACCOUNT_ID"]
CF_API_TOKEN      = os.environ["CF_API_TOKEN"]
D1_DATABASE_ID    = os.environ["D1_DATABASE_ID"]
GMAIL_FROM        = os.environ.get("GMAIL_FROM", "ranjithashetty@gmail.com")
GMAIL_TO          = os.environ.get("GMAIL_TO",   "ranjithashetty@gmail.com")
GMAIL_APP_PASSWORD = os.environ["GMAIL_APP_PASSWORD"]

D1_URL     = f"https://api.cloudflare.com/client/v4/accounts/{CF_ACCOUNT_ID}/d1/database/{D1_DATABASE_ID}/query"
CF_HEADERS = {"Authorization": f"Bearer {CF_API_TOKEN}", "Content-Type": "application/json"}


async def d1_query(session, sql, params=None):
    body = {"sql": sql}
    if params: body["params"] = params
    async with session.post(D1_URL, headers=CF_HEADERS, json=body) as r:
        data = await r.json()
        if not data.get("success"):
            raise Exception(f"D1 error: {data.get('errors')}")
        results = data.get("result", [])
        return results[0].get("results", []) if results else []


def fmt(n):
    if n is None: return "—"
    n = float(n)
    if abs(n) >= 1e7: return f"₹{n/1e7:.2f}Cr"
    if abs(n) >= 1e5: return f"₹{n/1e5:.2f}L"
    return f"₹{n:,.2f}"

def pct(n):
    if n is None: return "—"
    v = float(n)
    return f"{v:+.2f}%"

def sig_color(s):
    return {"buy":"#16A34A","hold":"#185FA5","watch":"#CA8A04","exit":"#DC2626"}.get((s or "").lower(),"#888")


async def build_and_send():
    async with aiohttp.ClientSession() as session:
        # Portfolio summary across all users
        summary = await d1_query(session, """
            SELECT COUNT(p.id) as total_funds,
                   SUM(p.invested_amount) as total_invested,
                   SUM(COALESCE(m.latest_nav, p.purchase_nav) * p.units) as current_value
            FROM portfolio_entries p
            LEFT JOIN mf_cache m ON m.scheme_code = p.scheme_code
            WHERE p.is_active = 1""")
        s = summary[0] if summary else {}
        invested = float(s.get("total_invested") or 0)
        current  = float(s.get("current_value") or 0)
        gain     = current - invested
        gain_pct = (gain / invested * 100) if invested else 0
        n_funds  = int(s.get("total_funds") or 0)

        # Holdings with signals
        holdings = await d1_query(session, """
            SELECT p.fund_name, p.invested_amount,
                   COALESCE(m.latest_nav, p.purchase_nav) * p.units as current_value,
                   COALESCE(m.latest_nav, p.purchase_nav) * p.units - p.invested_amount as gain_loss,
                   ai.signal, ai.rationale
            FROM portfolio_entries p
            LEFT JOIN mf_cache m ON m.scheme_code = p.scheme_code
            LEFT JOIN ai_recommendations ai ON ai.scheme_code = p.scheme_code
            WHERE p.is_active = 1
            ORDER BY ai.signal ASC, gain_loss DESC
            LIMIT 20""")

        # Top funds
        top = await d1_query(session, """
            SELECT m.fund_name, m.amc_name, m.return_1y, m.return_3y, m.return_5y,
                   ai.signal, ai.risk_label
            FROM mf_cache m
            LEFT JOIN ai_recommendations ai ON ai.scheme_code = m.scheme_code
            WHERE m.return_1y IS NOT NULL AND m.category = 'Equity'
              AND ai.signal IN ('buy','hold')
            ORDER BY m.return_1y DESC LIMIT 5""")

    # Build HTML
    gc    = "#16A34A" if gain >= 0 else "#DC2626"
    today = datetime.now().strftime("%A, %d %B %Y")

    hold_rows = ""
    for h in holdings:
        g  = float(h.get("gain_loss") or 0)
        sc = sig_color(h.get("signal"))
        hold_rows += f"""<tr>
          <td style="padding:8px 12px;border-bottom:1px solid #f0f0f0;font-size:13px">{str(h.get('fund_name',''))[:50]}</td>
          <td style="padding:8px 12px;border-bottom:1px solid #f0f0f0;font-size:13px;text-align:right">{fmt(h.get('invested_amount'))}</td>
          <td style="padding:8px 12px;border-bottom:1px solid #f0f0f0;font-size:13px;text-align:right;color:{'#16A34A' if g>=0 else '#DC2626'}">{fmt(g)}</td>
          <td style="padding:8px 12px;border-bottom:1px solid #f0f0f0;text-align:center">
            <span style="background:{sc};color:#fff;padding:2px 9px;border-radius:10px;font-size:11px;font-weight:600;text-transform:uppercase">{h.get('signal','—')}</span>
          </td></tr>"""

    top_rows = ""
    for f in top:
        sc = sig_color(f.get("signal"))
        top_rows += f"""<tr>
          <td style="padding:8px 12px;border-bottom:1px solid #f0f0f0;font-size:13px">{str(f.get('fund_name',''))[:50]}</td>
          <td style="padding:8px 12px;border-bottom:1px solid #f0f0f0;font-size:12px;color:#888">{f.get('amc_name','')}</td>
          <td style="padding:8px 12px;border-bottom:1px solid #f0f0f0;font-size:13px;text-align:right;color:#16A34A;font-weight:500">{pct(f.get('return_1y'))}</td>
          <td style="padding:8px 12px;border-bottom:1px solid #f0f0f0;font-size:13px;text-align:right">{pct(f.get('return_3y'))}</td>
          <td style="padding:8px 12px;border-bottom:1px solid #f0f0f0;font-size:13px;text-align:right">{pct(f.get('return_5y'))}</td>
          <td style="padding:8px 12px;border-bottom:1px solid #f0f0f0;text-align:center">
            <span style="background:{sc};color:#fff;padding:2px 9px;border-radius:10px;font-size:11px;font-weight:600">{f.get('signal','—').upper()}</span>
          </td></tr>"""

    html = f"""<!DOCTYPE html><html><body style="font-family:Arial,sans-serif;max-width:680px;margin:0 auto;background:#f4f4f4;padding:20px">
<div style="background:linear-gradient(135deg,#1a1a2e,#16213e);border-radius:12px;padding:24px 28px;margin-bottom:16px;color:#fff">
  <h1 style="margin:0;font-size:20px">Adhyarvansh Daily Digest</h1>
  <p style="margin:4px 0 0;font-size:12px;color:#aaa">{today}</p>
</div>
<div style="background:#fff;border-radius:12px;padding:24px;margin-bottom:16px">
  <h2 style="margin:0 0 16px;font-size:15px;font-weight:600">Portfolio snapshot</h2>
  <div style="display:grid;grid-template-columns:repeat(4,1fr);gap:12px">
    <div style="background:#f8f8f8;border-radius:8px;padding:14px"><div style="font-size:11px;color:#888;margin-bottom:4px;text-transform:uppercase">Funds</div><div style="font-size:24px;font-weight:600">{n_funds}</div></div>
    <div style="background:#f8f8f8;border-radius:8px;padding:14px"><div style="font-size:11px;color:#888;margin-bottom:4px;text-transform:uppercase">Invested</div><div style="font-size:20px;font-weight:600">{fmt(invested)}</div></div>
    <div style="background:#f8f8f8;border-radius:8px;padding:14px"><div style="font-size:11px;color:#888;margin-bottom:4px;text-transform:uppercase">Current</div><div style="font-size:20px;font-weight:600">{fmt(current)}</div></div>
    <div style="background:#f8f8f8;border-radius:8px;padding:14px"><div style="font-size:11px;color:#888;margin-bottom:4px;text-transform:uppercase">Gain/Loss</div><div style="font-size:20px;font-weight:600;color:{gc}">{fmt(gain)}</div><div style="font-size:12px;color:{gc}">{pct(gain_pct)}</div></div>
  </div>
</div>
<div style="background:#fff;border-radius:12px;padding:24px;margin-bottom:16px">
  <h2 style="margin:0 0 16px;font-size:15px;font-weight:600">Holdings — AI signals</h2>
  <table style="width:100%;border-collapse:collapse">
    <thead><tr style="background:#f8f8f8"><th style="padding:8px 12px;text-align:left;font-size:12px;color:#666">Fund</th><th style="padding:8px 12px;text-align:right;font-size:12px;color:#666">Invested</th><th style="padding:8px 12px;text-align:right;font-size:12px;color:#666">P&L</th><th style="padding:8px 12px;text-align:center;font-size:12px;color:#666">Signal</th></tr></thead>
    <tbody>{hold_rows or '<tr><td colspan="4" style="padding:16px;color:#bbb;text-align:center">No holdings yet</td></tr>'}</tbody>
  </table>
</div>
<div style="background:#fff;border-radius:12px;padding:24px;margin-bottom:16px">
  <h2 style="margin:0 0 16px;font-size:15px;font-weight:600">Top equity funds today</h2>
  <table style="width:100%;border-collapse:collapse">
    <thead><tr style="background:#f8f8f8"><th style="padding:8px 12px;text-align:left;font-size:12px;color:#666">Fund</th><th style="padding:8px 12px;text-align:left;font-size:12px;color:#666">AMC</th><th style="padding:8px 12px;text-align:right;font-size:12px;color:#666">1Y</th><th style="padding:8px 12px;text-align:right;font-size:12px;color:#666">3Y</th><th style="padding:8px 12px;text-align:right;font-size:12px;color:#666">5Y</th><th style="padding:8px 12px;text-align:center;font-size:12px;color:#666">Signal</th></tr></thead>
    <tbody>{top_rows or '<tr><td colspan="6" style="padding:16px;color:#bbb;text-align:center">Run sync first</td></tr>'}</tbody>
  </table>
</div>
<p style="text-align:center;color:#bbb;font-size:11px">Adhyarvansh · adhyarvansh.com · Private & Confidential</p>
</body></html>"""

    msg = MIMEMultipart("alternative")
    msg["Subject"] = f"Adhyarvansh Digest · {datetime.now().strftime('%d %b %Y')}"
    msg["From"]    = GMAIL_FROM
    msg["To"]      = GMAIL_TO
    msg.attach(MIMEText(html, "html"))

    with smtplib.SMTP("smtp.gmail.com", 587) as s:
        s.ehlo(); s.starttls()
        s.login(GMAIL_FROM, GMAIL_APP_PASSWORD)
        s.sendmail(GMAIL_FROM, GMAIL_TO, msg.as_string())

    log.info(f"✅ Digest sent to {GMAIL_TO}")


if __name__ == "__main__":
    asyncio.run(build_and_send())
