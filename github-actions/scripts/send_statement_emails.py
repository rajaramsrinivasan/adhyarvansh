"""
send_statement_emails.py — email each user their own portfolio statement (Settings → Statement email).

This is the personal email. It lists the user's own holdings, so it goes only to that user.
The market digest (send_digest_emails.py) never contains portfolio data.

Schedule: the workflow runs every Saturday at 10:00 AM IST. A user is due when:
  weekly       → every Saturday
  monthly      → the first Saturday of the month
  quarterly    → the first Saturday of Jan, Apr, Jul, Oct
  half_yearly  → the first Saturday of Jan, Jul
  annual       → the first Saturday of April (start of the financial year)
Users with no active holdings are skipped.

Secrets: CF_ACCOUNT_ID, CF_API_TOKEN, D1_DATABASE_ID, RESEND_API_KEY, SUPABASE_SERVICE_KEY
Optional: EMAIL_FROM (default "Adhyarvansh <digest@adhyarvansh.com>")
Flags:  --dry-run (write HTML previews to ./preview, send nothing)   --only you@example.com (test send)   --force (ignore schedule)
"""
import sys, asyncio, logging, argparse, os
from datetime import datetime, timezone, timedelta
import aiohttp
from send_digest_emails import sb, send, esc, SITE, INK, VIOLET, MUTED, LINE, IST

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)

GREEN, RED = "#078F5E", "#E11D48"
DISC = "Information only. Not investment advice. We are not SEBI-registered. Mutual fund investments are subject to market risks."
FREQ_LABEL = {"weekly": "Weekly", "monthly": "Monthly", "quarterly": "Quarterly", "half_yearly": "Half-yearly", "annual": "Annual"}


def inr(v):
    """Indian digit grouping, no decimals: 1234567 -> ₹12,34,567"""
    try: n = int(round(float(v)))
    except Exception: return "—"
    sign, n = ("-" if n < 0 else ""), abs(n)
    s = str(n)
    if len(s) > 3:
        head, tail = s[:-3], s[-3:]
        parts = []
        while len(head) > 2: parts.insert(0, head[-2:]); head = head[:-2]
        if head: parts.insert(0, head)
        s = ",".join(parts) + "," + tail
    return f"{sign}₹{s}"

def pct(v):
    try: return f"{float(v):+.1f}%"
    except Exception: return "—"

def col(v): return GREEN if (v or 0) >= 0 else RED


# ─────────────────────────── schedule ───────────────────────────
def due(freq, last_iso, now_utc, force):
    if force: return True
    ist = now_utc.astimezone(IST)
    if ist.weekday() != 5: return False            # Saturdays only
    last = datetime.fromisoformat(last_iso.replace("Z", "+00:00")) if last_iso else None
    age = (now_utc - last) if last else timedelta(days=999)
    first_sat = ist.day <= 7
    if freq == "weekly":      return age > timedelta(days=5)
    if freq == "monthly":     return first_sat and age > timedelta(days=20)
    if freq == "quarterly":   return first_sat and ist.month in (1, 4, 7, 10) and age > timedelta(days=60)
    if freq == "half_yearly": return first_sat and ist.month in (1, 7) and age > timedelta(days=150)
    if freq == "annual":      return first_sat and ist.month == 4 and age > timedelta(days=300)
    return False


# ─────────────────────────── data ───────────────────────────
async def load_holdings(d1q, session, uid):
    ents = await sb(session, f"/rest/v1/portfolio_entries?user_id=eq.{uid}&is_active=eq.true"
                             "&select=scheme_code,fund_name,units,purchase_nav,purchase_date,invested_amount")
    if not ents: return []
    codes = sorted({str(e["scheme_code"]) for e in ents if e.get("scheme_code")})
    navs = {}
    if codes:
        ph = ",".join("?" * len(codes))
        for r in await d1q(session, f"SELECT scheme_code, latest_nav FROM mf_cache WHERE scheme_code IN ({ph})", codes):
            navs[str(r["scheme_code"])] = r.get("latest_nav")
    # one row per fund: merge purchases of the same scheme
    funds = {}
    for e in ents:
        key = str(e.get("scheme_code") or e["fund_name"])
        f = funds.setdefault(key, {"fund_name": e["fund_name"], "units": 0.0, "invested": 0.0, "nav": navs.get(str(e.get("scheme_code")))})
        f["units"] += float(e.get("units") or 0)
        f["invested"] += float(e.get("invested_amount") or 0)
    out = []
    for f in funds.values():
        nav = f["nav"]
        value = f["units"] * float(nav) if nav is not None else f["invested"]
        gain = value - f["invested"]
        out.append({**f, "value": value, "gain": gain, "gain_pct": (gain / f["invested"] * 100) if f["invested"] else 0.0})
    return sorted(out, key=lambda x: x["value"], reverse=True)


# ─────────────────────────── email ───────────────────────────
def render_email(name, freq, holdings):
    ist = datetime.now(IST)
    today = ist.strftime("%A, %d %B %Y")
    title = f"Your {FREQ_LABEL.get(freq, 'Weekly').lower()} portfolio statement"
    hello = f"Hi {esc(name)}," if name else "Hi,"
    inv = sum(h["invested"] for h in holdings)
    val = sum(h["value"] for h in holdings)
    gain = val - inv
    gp = (gain / inv * 100) if inv else 0.0

    def stat(label, value, color=INK):
        return (f'<td style="padding:14px 10px;text-align:center;background:#F6F3FF;border-radius:14px">'
                f'<div style="font-size:12.5px;color:{MUTED};font-weight:600">{label}</div>'
                f'<div style="font-size:19px;font-weight:800;color:{color};margin-top:4px">{value}</div></td>')
    summary = (f'<table role="presentation" width="100%" cellpadding="0" cellspacing="6" style="margin:6px -6px 4px;width:calc(100% + 12px)"><tr>'
               + stat("Invested", inr(inv)) + stat("Current value", inr(val))
               + stat("Gain / loss", f"{inr(gain)}<br><span style='font-size:13px'>{pct(gp)}</span>", col(gain)) + '</tr></table>')

    rows = ""
    for h in holdings:
        rows += f'''<tr><td style="padding:13px 0;border-top:1px solid {LINE}">
          <div style="font-size:15px;line-height:1.35;font-weight:700;color:{INK}">{esc(h["fund_name"])}</div>
          <table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="margin-top:6px"><tr>
            <td style="font-size:13.5px;color:{MUTED}">Invested {inr(h["invested"])}<br>Value <b style="color:{INK}">{inr(h["value"])}</b></td>
            <td align="right" style="font-size:14px;font-weight:800;color:{col(h["gain"])}">{inr(h["gain"])}<br><span style="font-size:13px">{pct(h["gain_pct"])}</span></td>
          </tr></table></td></tr>'''

    return f'''<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><meta name="color-scheme" content="light only">
<title>{esc(title)}</title></head>
<body style="margin:0;padding:0;background:#F1EEFF;-webkit-text-size-adjust:100%">
<div style="display:none;max-height:0;overflow:hidden;opacity:0">Portfolio value {inr(val)} · {pct(gp)} overall</div>
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="background:#F1EEFF"><tr><td align="center" style="padding:16px 12px">
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="max-width:600px;background:#FFFFFF;border-radius:20px;overflow:hidden;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,Helvetica,Arial,sans-serif">
  <tr><td style="background:#0B1033;background-image:linear-gradient(135deg,#0B1033 0%,#2B1A78 60%,#7C3AED 100%);padding:26px 28px">
    <a href="{SITE}" style="text-decoration:none"><img src="{SITE}/brand/email-logo.png" width="210" height="44" alt="Adhyarvansh" style="display:block;border:0;outline:none;width:210px;height:auto;font-size:24px;font-weight:800;color:#FFFFFF;letter-spacing:-.4px"></a>
    <div style="font-size:14px;color:#CFC6FF;margin-top:10px">{esc(title.capitalize())} &nbsp;·&nbsp; {today}</div>
  </td></tr>
  <tr><td style="height:4px;background:#7C3AED;background-image:linear-gradient(90deg,#7C3AED,#D946EF,#06C5F0)"></td></tr>
  <tr><td style="padding:24px 28px 4px"><div style="font-size:16px;line-height:1.5;color:{INK}">{hello} here is your portfolio as of this morning, based on the latest available NAVs.</div>{summary}
    <div style="font-size:19px;font-weight:800;color:{INK};padding-top:18px">Your holdings</div></td></tr>
  <tr><td style="padding:0 28px"><table role="presentation" width="100%" cellpadding="0" cellspacing="0">{rows}</table>
    <a href="{SITE}" style="display:inline-block;margin:14px 0 8px;font-size:15px;font-weight:700;color:{VIOLET};text-decoration:none">Open your portfolio &rsaquo;</a></td></tr>
  <tr><td style="padding:18px 28px 28px;background:#FAF8FF;border-top:1px solid {LINE}">
    <div style="font-size:12.5px;line-height:1.6;color:{MUTED}">This is a personal tracker statement built from the holdings you entered. It is not an official CAS. This email was sent only to you. {esc(DISC)}</div>
    <div style="font-size:13px;margin-top:12px"><a href="{SITE}" style="color:{VIOLET};font-weight:700;text-decoration:none">Manage email preferences</a> &nbsp;·&nbsp; Settings &rsaquo; Statement email</div>
  </td></tr>
</table></td></tr></table></body></html>'''

def render_text(name, freq, holdings):
    inv = sum(h["invested"] for h in holdings); val = sum(h["value"] for h in holdings)
    lines = [f"Adhyarvansh — your {freq.replace('_', '-')} portfolio statement", "",
             f"Invested {inr(inv)} · Current value {inr(val)} · Gain {inr(val - inv)}", ""]
    lines += [f"- {h['fund_name']}: value {inr(h['value'])}, gain {inr(h['gain'])} ({pct(h['gain_pct'])})" for h in holdings]
    lines += ["", DISC, f"Manage preferences: {SITE}  (Settings > Statement email)"]
    return "\n".join(lines)


# ─────────────────────────── run ───────────────────────────
async def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true"); ap.add_argument("--only"); ap.add_argument("--force", action="store_true")
    a = ap.parse_args()
    from d1 import q as d1q
    now = datetime.now(timezone.utc)
    async with aiohttp.ClientSession() as s:
        rows = await sb(s, "/rest/v1/user_prefs?select=user_id,statement_freq,last_statement_at&statement_freq=neq.off")
        log.info("%d users have statement emails on", len(rows or []))
        sent = failed = 0
        os.makedirs("preview", exist_ok=True)
        for row in rows or []:
            try:
                if not due(row["statement_freq"], row.get("last_statement_at"), now, a.force or bool(a.only)): continue
                u = await sb(s, f"/auth/v1/admin/users/{row['user_id']}")
                email = u.get("email")
                if not email or (a.only and email.lower() != a.only.lower()): continue
                holdings = await load_holdings(d1q, s, row["user_id"])
                if not holdings: log.info("no holdings for %s, skipped", row["user_id"][:8]); continue
                meta = u.get("user_metadata") or {}
                name = (meta.get("name") or meta.get("full_name") or "").split(" ")[0]
                subject = f"Your {FREQ_LABEL.get(row['statement_freq'], 'Weekly').lower()} portfolio statement"
                body, text = render_email(name, row["statement_freq"], holdings), render_text(name, row["statement_freq"], holdings)
                if a.dry_run:
                    open(f"preview/statement_{row['user_id'][:8]}.html", "w").write(body); log.info("preview written for %s", row["user_id"][:8]); continue
                await send(s, email, subject, body, text)
                await sb(s, f"/rest/v1/user_prefs?user_id=eq.{row['user_id']}", "PATCH",
                         {"last_statement_at": now.strftime("%Y-%m-%dT%H:%M:%SZ")}, "return=minimal")
                log.info("sent to %s", email); sent += 1
            except Exception as e:
                failed += 1; log.error("user %s failed: %s", str(row.get("user_id"))[:8], e)
        log.info("done: sent=%d failed=%d", sent, failed)
        if failed and not sent: sys.exit(1)

if __name__ == "__main__":
    asyncio.run(main())
