"""
daily_digest.py
Reads portfolio data + AI signals from Neon
Builds a clean HTML email and sends via Gmail SMTP (App Password)
From: ranjithashetty@gmail.com → To: ranjithashetty@gmail.com

Run: python daily_digest.py
Schedule: GitHub Actions cron — runs after ai_analysis.py daily
"""

import os
import smtplib
import logging
import psycopg2
import psycopg2.extras
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from datetime import datetime

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)

DATABASE_URL      = os.environ["DATABASE_URL"]
GMAIL_FROM        = os.environ.get("GMAIL_FROM", "ranjithashetty@gmail.com")
GMAIL_TO          = os.environ.get("GMAIL_TO",   "ranjithashetty@gmail.com")
GMAIL_APP_PASSWORD = os.environ["GMAIL_APP_PASSWORD"]


def get_conn():
    return psycopg2.connect(DATABASE_URL, cursor_factory=psycopg2.extras.RealDictCursor)


def fetch_all_portfolio_summaries(conn):
    """Get portfolio summary for ALL users — digest covers everyone."""
    with conn.cursor() as cur:
        cur.execute("""
            SELECT
                u.name,
                u.email,
                COUNT(p.id)                                                              AS total_funds,
                ROUND(SUM(p.invested_amount)::numeric, 2)                               AS total_invested,
                ROUND(SUM(m.latest_nav * p.units)::numeric, 2)                          AS current_value,
                ROUND((SUM(m.latest_nav * p.units) - SUM(p.invested_amount))::numeric, 2) AS total_gain
            FROM users u
            JOIN portfolio_entries p ON p.user_id = u.id AND p.is_active = TRUE
            LEFT JOIN mf_cache m ON m.scheme_code = p.scheme_code
            GROUP BY u.id, u.name, u.email
        """)
        return [dict(r) for r in cur.fetchall()]


def fetch_holdings_with_signals(conn):
    """Get all active holdings with their AI signals."""
    with conn.cursor() as cur:
        cur.execute("""
            SELECT
                u.name AS user_name,
                p.fund_name,
                p.units,
                p.purchase_nav,
                p.purchase_date,
                p.invested_amount,
                m.latest_nav,
                ROUND((m.latest_nav * p.units)::numeric, 2)                       AS current_value,
                ROUND((m.latest_nav * p.units - p.invested_amount)::numeric, 2)   AS gain_loss,
                ROUND(((m.latest_nav - p.purchase_nav) / p.purchase_nav * 100)::numeric, 2) AS return_pct,
                ai.signal,
                ai.risk_label,
                ai.rationale
            FROM portfolio_entries p
            JOIN users u               ON u.id = p.user_id
            LEFT JOIN mf_cache m       ON m.scheme_code = p.scheme_code
            LEFT JOIN ai_recommendations ai ON ai.scheme_code = p.scheme_code
            WHERE p.is_active = TRUE
            ORDER BY ai.signal ASC, gain_loss DESC
        """)
        return [dict(r) for r in cur.fetchall()]


def fetch_top_funds(conn):
    """Top 5 equity funds by 1Y return with AI signals."""
    with conn.cursor() as cur:
        cur.execute("""
            SELECT m.fund_name, m.category, m.amc_name,
                   m.return_1y, m.return_3y, m.return_5y,
                   ai.signal, ai.risk_label
            FROM mf_cache m
            LEFT JOIN ai_recommendations ai ON ai.scheme_code = m.scheme_code
            WHERE m.return_1y IS NOT NULL AND m.category = 'Equity'
              AND ai.signal IN ('buy', 'hold')
            ORDER BY m.return_1y DESC
            LIMIT 5
        """)
        return [dict(r) for r in cur.fetchall()]


def signal_color(signal):
    return {
        "buy":   "#1D9E75",
        "hold":  "#185FA5",
        "watch": "#BA7517",
        "exit":  "#D85A30"
    }.get((signal or "").lower(), "#888888")


def format_inr(amount):
    if amount is None:
        return "—"
    try:
        amount = float(amount)
        if abs(amount) >= 10_000_000:
            return f"₹{amount/10_000_000:.2f}Cr"
        if abs(amount) >= 100_000:
            return f"₹{amount/100_000:.2f}L"
        return f"₹{amount:,.2f}"
    except:
        return "—"


def build_email_html(summaries, holdings, top_funds):
    today = datetime.now().strftime("%A, %d %B %Y")

    # ── Portfolio summary rows ────────────────────────────────────────────────
    if summaries:
        total_invested = sum(float(s["total_invested"] or 0) for s in summaries)
        total_current  = sum(float(s["current_value"]  or 0) for s in summaries)
        total_gain     = total_current - total_invested
        gain_pct       = (total_gain / total_invested * 100) if total_invested else 0
        gain_color     = "#1D9E75" if total_gain >= 0 else "#D85A30"
        total_funds    = sum(int(s["total_funds"] or 0) for s in summaries)
    else:
        total_invested = total_current = total_gain = gain_pct = 0
        gain_color = "#888"
        total_funds = 0

    # ── Holdings rows ─────────────────────────────────────────────────────────
    holding_rows = ""
    exit_alerts  = [h for h in holdings if (h.get("signal") or "").lower() == "exit"]

    for h in holdings:
        sc    = signal_color(h.get("signal"))
        gl    = float(h.get("gain_loss") or 0)
        gc    = "#1D9E75" if gl >= 0 else "#D85A30"
        rp    = float(h.get("return_pct") or 0)
        holding_rows += f"""
        <tr>
          <td style="padding:9px 12px;border-bottom:1px solid #f0f0f0;font-size:13px">{h['fund_name'][:45]}</td>
          <td style="padding:9px 12px;border-bottom:1px solid #f0f0f0;font-size:13px;text-align:right">{format_inr(h['invested_amount'])}</td>
          <td style="padding:9px 12px;border-bottom:1px solid #f0f0f0;font-size:13px;text-align:right">{format_inr(h['current_value'])}</td>
          <td style="padding:9px 12px;border-bottom:1px solid #f0f0f0;font-size:13px;text-align:right;color:{gc};font-weight:500">{'+' if gl>=0 else ''}{format_inr(gl)} ({rp:+.1f}%)</td>
          <td style="padding:9px 12px;border-bottom:1px solid #f0f0f0;text-align:center">
            <span style="background:{sc};color:#fff;padding:2px 9px;border-radius:10px;font-size:11px;font-weight:600;text-transform:uppercase">{h.get('signal','—')}</span>
          </td>
        </tr>"""

    holding_rows = holding_rows or '<tr><td colspan="5" style="padding:16px;color:#bbb;text-align:center;font-size:13px">No active holdings yet — add your first fund on the dashboard</td></tr>'

    # ── Exit alert banner ─────────────────────────────────────────────────────
    exit_banner = ""
    if exit_alerts:
        names = ", ".join(h["fund_name"][:30] for h in exit_alerts[:3])
        exit_banner = f"""
        <div style="background:#FEF3CD;border-left:4px solid #D85A30;border-radius:6px;padding:14px 16px;margin-bottom:16px">
          <strong style="color:#D85A30">⚠️ Exit signal detected</strong>
          <p style="margin:4px 0 0;font-size:13px;color:#555">
            AI recommends reviewing: <strong>{names}</strong>
            {"and " + str(len(exit_alerts)-3) + " more" if len(exit_alerts) > 3 else ""}
          </p>
        </div>"""

    # ── Top funds rows ────────────────────────────────────────────────────────
    top_rows = ""
    for f in top_funds:
        sc   = signal_color(f.get("signal"))
        r1   = float(f.get("return_1y") or 0)
        top_rows += f"""
        <tr>
          <td style="padding:9px 12px;border-bottom:1px solid #f0f0f0;font-size:13px">{f['fund_name'][:45]}</td>
          <td style="padding:9px 12px;border-bottom:1px solid #f0f0f0;font-size:12px;color:#888">{f['amc_name']}</td>
          <td style="padding:9px 12px;border-bottom:1px solid #f0f0f0;font-size:13px;text-align:right;color:#1D9E75;font-weight:500">{r1:+.1f}%</td>
          <td style="padding:9px 12px;border-bottom:1px solid #f0f0f0;font-size:13px;text-align:right">{float(f.get('return_3y') or 0):+.1f}%</td>
          <td style="padding:9px 12px;border-bottom:1px solid #f0f0f0;font-size:13px;text-align:right">{float(f.get('return_5y') or 0):+.1f}%</td>
          <td style="padding:9px 12px;border-bottom:1px solid #f0f0f0;text-align:center">
            <span style="background:{sc};color:#fff;padding:2px 9px;border-radius:10px;font-size:11px;font-weight:600;text-transform:uppercase">{f.get('signal','—')}</span>
          </td>
        </tr>"""

    top_rows = top_rows or '<tr><td colspan="6" style="padding:16px;color:#bbb;text-align:center;font-size:13px">Run sync_mf_data.py first to populate fund data</td></tr>'

    return f"""<!DOCTYPE html>
<html>
<head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1"></head>
<body style="font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Arial,sans-serif;max-width:700px;margin:0 auto;background:#f4f4f4;padding:20px">

  <!-- Header -->
  <div style="background:linear-gradient(135deg,#1a1a2e,#16213e);border-radius:12px;padding:24px 28px;margin-bottom:16px;color:#fff">
    <div style="display:flex;justify-content:space-between;align-items:center">
      <div>
        <h1 style="margin:0;font-size:20px;font-weight:600;letter-spacing:-0.3px">Adhyarvansh</h1>
        <p style="margin:4px 0 0;font-size:12px;color:#aaa">Daily Portfolio Digest</p>
      </div>
      <div style="text-align:right;font-size:12px;color:#aaa">{today}</div>
    </div>
  </div>

  {exit_banner}

  <!-- Portfolio snapshot -->
  <div style="background:#fff;border-radius:12px;padding:24px;margin-bottom:16px">
    <h2 style="margin:0 0 16px;font-size:15px;font-weight:600;color:#1a1a1a">Portfolio snapshot</h2>
    <div style="display:grid;grid-template-columns:repeat(4,1fr);gap:12px">
      <div style="background:#f8f8f8;border-radius:8px;padding:14px">
        <div style="font-size:11px;color:#888;margin-bottom:4px;text-transform:uppercase;letter-spacing:0.5px">Funds</div>
        <div style="font-size:24px;font-weight:600;color:#1a1a1a">{total_funds}</div>
      </div>
      <div style="background:#f8f8f8;border-radius:8px;padding:14px">
        <div style="font-size:11px;color:#888;margin-bottom:4px;text-transform:uppercase;letter-spacing:0.5px">Invested</div>
        <div style="font-size:20px;font-weight:600;color:#1a1a1a">{format_inr(total_invested)}</div>
      </div>
      <div style="background:#f8f8f8;border-radius:8px;padding:14px">
        <div style="font-size:11px;color:#888;margin-bottom:4px;text-transform:uppercase;letter-spacing:0.5px">Current</div>
        <div style="font-size:20px;font-weight:600;color:#1a1a1a">{format_inr(total_current)}</div>
      </div>
      <div style="background:#f8f8f8;border-radius:8px;padding:14px">
        <div style="font-size:11px;color:#888;margin-bottom:4px;text-transform:uppercase;letter-spacing:0.5px">Gain / Loss</div>
        <div style="font-size:20px;font-weight:600;color:{gain_color}">{'+' if total_gain>=0 else ''}{format_inr(total_gain)}</div>
        <div style="font-size:12px;color:{gain_color}">{gain_pct:+.2f}%</div>
      </div>
    </div>
  </div>

  <!-- Holdings with signals -->
  <div style="background:#fff;border-radius:12px;padding:24px;margin-bottom:16px">
    <h2 style="margin:0 0 16px;font-size:15px;font-weight:600;color:#1a1a1a">Your holdings — AI signals</h2>
    <table style="width:100%;border-collapse:collapse">
      <thead>
        <tr style="background:#f8f8f8">
          <th style="padding:8px 12px;text-align:left;font-size:12px;font-weight:600;color:#666;text-transform:uppercase">Fund</th>
          <th style="padding:8px 12px;text-align:right;font-size:12px;font-weight:600;color:#666;text-transform:uppercase">Invested</th>
          <th style="padding:8px 12px;text-align:right;font-size:12px;font-weight:600;color:#666;text-transform:uppercase">Current</th>
          <th style="padding:8px 12px;text-align:right;font-size:12px;font-weight:600;color:#666;text-transform:uppercase">P&amp;L</th>
          <th style="padding:8px 12px;text-align:center;font-size:12px;font-weight:600;color:#666;text-transform:uppercase">Signal</th>
        </tr>
      </thead>
      <tbody>{holding_rows}</tbody>
    </table>
  </div>

  <!-- Top funds today -->
  <div style="background:#fff;border-radius:12px;padding:24px;margin-bottom:16px">
    <h2 style="margin:0 0 16px;font-size:15px;font-weight:600;color:#1a1a1a">Top equity funds today</h2>
    <table style="width:100%;border-collapse:collapse">
      <thead>
        <tr style="background:#f8f8f8">
          <th style="padding:8px 12px;text-align:left;font-size:12px;font-weight:600;color:#666;text-transform:uppercase">Fund</th>
          <th style="padding:8px 12px;text-align:left;font-size:12px;font-weight:600;color:#666;text-transform:uppercase">AMC</th>
          <th style="padding:8px 12px;text-align:right;font-size:12px;font-weight:600;color:#666;text-transform:uppercase">1Y</th>
          <th style="padding:8px 12px;text-align:right;font-size:12px;font-weight:600;color:#666;text-transform:uppercase">3Y</th>
          <th style="padding:8px 12px;text-align:right;font-size:12px;font-weight:600;color:#666;text-transform:uppercase">5Y</th>
          <th style="padding:8px 12px;text-align:center;font-size:12px;font-weight:600;color:#666;text-transform:uppercase">Signal</th>
        </tr>
      </thead>
      <tbody>{top_rows}</tbody>
    </table>
  </div>

  <!-- Footer -->
  <p style="text-align:center;color:#bbb;font-size:11px;margin-top:20px">
    Adhyarvansh · adhyarvansh.com · Private &amp; Confidential · Not financial advice
  </p>

</body>
</html>"""


def send_email(subject, html_body):
    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"]    = GMAIL_FROM
    msg["To"]      = GMAIL_TO
    msg.attach(MIMEText(html_body, "html"))

    with smtplib.SMTP("smtp.gmail.com", 587) as server:
        server.ehlo()
        server.starttls()
        server.login(GMAIL_FROM, GMAIL_APP_PASSWORD)
        server.sendmail(GMAIL_FROM, GMAIL_TO, msg.as_string())

    log.info(f"Email sent to {GMAIL_TO}")


def run_digest():
    conn       = get_conn()
    summaries  = fetch_all_portfolio_summaries(conn)
    holdings   = fetch_holdings_with_signals(conn)
    top_funds  = fetch_top_funds(conn)
    conn.close()

    today_str  = datetime.now().strftime("%d %b %Y")
    subject    = f"Adhyarvansh · Daily Digest · {today_str}"
    html       = build_email_html(summaries, holdings, top_funds)

    send_email(subject, html)
    log.info("✅ Daily digest sent")


if __name__ == "__main__":
    run_digest()
