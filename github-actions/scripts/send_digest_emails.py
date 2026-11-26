"""
send_digest_emails.py — send the industry digest to users who opted in (Settings → Market digest email).

Who gets it: rows in Supabase `user_prefs` with digest_freq 'daily' or 'weekly'.
  daily  → sent every run if last_digest_at is older than 12h  (news from the last 2 days)
  weekly → sent on Mondays (or if more than 8 days late)       (news from the last 7 days)
Content: market and industry headlines only (from D1 `industry_news`). No personal portfolio data is ever added.
Schedule: the workflow runs at 7:00 PM IST; the 12-hour guard below keeps it to one email a day.

Secrets: CF_ACCOUNT_ID, CF_API_TOKEN, D1_DATABASE_ID, RESEND_API_KEY, SUPABASE_SERVICE_KEY
Optional: EMAIL_FROM (default "Adhyarvansh <digest@adhyarvansh.com>")
Flags:  --dry-run (write HTML previews to ./preview, send nothing)   --only you@example.com (test send)   --force (ignore schedule)
"""
import os, sys, html, json, asyncio, logging, argparse
from datetime import datetime, timezone, timedelta
import aiohttp

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)

SUPABASE_URL = os.environ.get("SUPABASE_URL", "https://ybctubrwzostmaslrlxz.supabase.co")
SITE = "https://adhyarvansh.com"
FROM = os.environ.get("EMAIL_FROM") or "Adhyarvansh <digest@adhyarvansh.com>"
IST = timezone(timedelta(hours=5, minutes=30))

INK, VIOLET, MUTED, LINE = "#0B1033", "#7C3AED", "#5E6288", "#E6E0F7"
def esc(s): return html.escape(str(s or ""), quote=True)

def pct(v):
    try: v = float(v)
    except Exception: return "—"
    return f"{v:+.1f}%"

def when(iso):
    try:
        d = datetime.strptime(iso, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc).astimezone(IST)
        return d.strftime("%d %b")
    except Exception:
        return ""

# ─────────────────────────── email template ───────────────────────────
def render_email(name, freq, news):
    today = datetime.now(IST).strftime("%A, %d %B %Y")
    title = "Your weekly mutual fund digest" if freq == "weekly" else "Your daily mutual fund digest"
    hello = f"Hi {esc(name)}," if name else "Hi,"

    items = ""
    for n in news:
        meta = " · ".join(x for x in [esc(n.get("source")), when(n.get("published_at"))] if x)
        summ = f'<p style="margin:6px 0 0;font-size:15px;line-height:1.5;color:{MUTED}">{esc(n["summary"])}</p>' if n.get("summary") else ""
        items += f'''<tr><td style="padding:18px 0;border-top:1px solid {LINE}">
          <div style="font-size:13px;color:{MUTED};margin-bottom:4px">{meta}</div>
          <div><a href="{esc(n["url"])}" style="font-size:18px;line-height:1.35;font-weight:700;color:{INK};text-decoration:none">{esc(n["title"])}</a></div>
          {summ}
          <div style="margin-top:10px"><a href="{esc(n["url"])}" style="font-size:15px;font-weight:700;color:{VIOLET};text-decoration:none">Read more &rsaquo;</a></div>
        </td></tr>'''
    if not items:
        items = f'<tr><td style="padding:18px 0;border-top:1px solid {LINE};font-size:15px;color:{MUTED}">No major industry headlines this time. We will be back with the next digest.</td></tr>'

    return f'''<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><meta name="color-scheme" content="light only">
<title>{esc(title)}</title></head>
<body style="margin:0;padding:0;background:#F1EEFF;-webkit-text-size-adjust:100%">
<div style="display:none;max-height:0;overflow:hidden;opacity:0">{esc(news[0]["title"]) if news else title}</div>
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="background:#F1EEFF"><tr><td align="center" style="padding:16px 12px">
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="max-width:600px;background:#FFFFFF;border-radius:20px;overflow:hidden;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,Helvetica,Arial,sans-serif">
  <tr><td style="background:#0B1033;background-image:linear-gradient(135deg,#0B1033 0%,#2B1A78 60%,#7C3AED 100%);padding:26px 28px">
    <a href="{SITE}" style="text-decoration:none"><img src="{SITE}/brand/email-logo.png" width="210" height="44" alt="Adhyarvansh" style="display:block;border:0;outline:none;width:210px;height:auto;font-size:24px;font-weight:800;color:#FFFFFF;letter-spacing:-.4px"></a>
    <div style="font-size:14px;color:#CFC6FF;margin-top:10px">{esc(title)} &nbsp;·&nbsp; {today}</div>
  </td></tr>
  <tr><td style="height:4px;background:#7C3AED;background-image:linear-gradient(90deg,#7C3AED,#D946EF,#06C5F0)"></td></tr>
  <tr><td style="padding:24px 28px 4px"><div style="font-size:16px;line-height:1.5;color:{INK}">{hello} here is what moved in the markets and the fund industry{" this week" if freq == "weekly" else " today"}.</div>
    <div style="font-size:19px;font-weight:800;color:{INK};padding-top:20px">Market and industry headlines</div></td></tr>
  <tr><td style="padding:0 28px"><table role="presentation" width="100%" cellpadding="0" cellspacing="0">{items}</table></td></tr>
  <tr><td style="padding:18px 28px 28px;background:#FAF8FF;border-top:1px solid {LINE}">
    <div style="font-size:12.5px;line-height:1.6;color:{MUTED}">Headlines link to their original publishers. This digest contains market news only. Information only. Not investment advice. We are not SEBI-registered. Mutual fund investments are subject to market risks.</div>
    <div style="font-size:13px;margin-top:12px"><a href="{SITE}" style="color:{VIOLET};font-weight:700;text-decoration:none">Manage email preferences</a> &nbsp;·&nbsp; Settings &rsaquo; Market digest email</div>
  </td></tr>
</table></td></tr></table></body></html>'''

def render_text(name, freq, news):
    lines = [f"Adhyarvansh — your {freq} mutual fund digest", ""]
    for n in news:
        lines += [n["title"], (n.get("summary") or ""), n["url"], ""]
    lines.append("Information only. Not investment advice. We are not SEBI-registered. Mutual fund investments are subject to market risks.")
    lines.append(f"Manage preferences: {SITE}  (Settings > Market digest email)")
    return "\n".join(lines)

# ─────────────────────────── data access ───────────────────────────
async def sb(session, path, method="GET", body=None, prefer=None):
    key = os.environ["SUPABASE_SERVICE_KEY"]
    h = {"apikey": key, "Authorization": f"Bearer {key}", "Content-Type": "application/json"}
    if prefer: h["Prefer"] = prefer
    async with session.request(method, SUPABASE_URL + path, headers=h, json=body) as r:
        t = await r.text()
        if r.status >= 300:
            raise RuntimeError(f"Supabase {r.status} {path[:60]}: {t[:200]}")
        return json.loads(t) if t else None

def due(row, now, force):
    if force: return True
    last = row.get("last_digest_at")
    last_dt = datetime.fromisoformat(last.replace("Z", "+00:00")) if last else None
    age = (now - last_dt) if last_dt else timedelta(days=999)
    if row["digest_freq"] == "daily":
        return age > timedelta(hours=12)
    return (now.astimezone(IST).weekday() == 0 and age > timedelta(days=5)) or age > timedelta(days=8)

async def load_news(d1q, session, freq, limit=7):
    days = 7 if freq == "weekly" else 2
    since = (datetime.now(timezone.utc) - timedelta(days=days)).strftime("%Y-%m-%dT%H:%M:%SZ")
    rows = await d1q(session, "SELECT url,title,summary,source,published_at,score FROM industry_news "
                              "WHERE published_at >= ? ORDER BY score DESC, published_at DESC LIMIT 40", [since])
    # keep a mix: at most 2 per source so one publisher does not dominate
    out, per = [], {}
    for r in rows:
        if per.get(r["source"], 0) >= 2: continue
        per[r["source"]] = per.get(r["source"], 0) + 1
        out.append(r)
        if len(out) >= limit: break
    return sorted(out, key=lambda r: r["published_at"], reverse=True)

async def send(session, to, subject, html_body, text_body):
    async with session.post("https://api.resend.com/emails",
        headers={"Authorization": "Bearer " + os.environ["RESEND_API_KEY"], "Content-Type": "application/json"},
        json={"from": FROM, "to": [to], "subject": subject, "html": html_body, "text": text_body,
              "headers": {"List-Unsubscribe": f"<{SITE}>"}}) as r:
        t = await r.text()
        if r.status >= 300: raise RuntimeError(f"Resend {r.status}: {t[:200]}")

async def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true"); ap.add_argument("--only"); ap.add_argument("--force", action="store_true")
    a = ap.parse_args()
    from d1 import q as d1q
    now = datetime.now(timezone.utc)
    async with aiohttp.ClientSession() as s:
        rows = await sb(s, "/rest/v1/user_prefs?select=user_id,digest_freq,last_digest_at&digest_freq=in.(daily,weekly)")
        total = await sb(s, "/rest/v1/user_prefs?select=user_id")
        log.info("user_prefs rows: %d total, %d opted in to the digest", len(total or []), len(rows or []))
        if a.only and not any(True for _ in rows or []):
            # test mode: find the user by email even if they have no preferences row yet
            page = await sb(s, "/auth/v1/admin/users?per_page=200")
            for u in (page or {}).get("users", []):
                if (u.get("email") or "").lower() == a.only.lower():
                    log.info("test mode: no prefs row for %s, using weekly defaults", a.only)
                    rows = [{"user_id": u["id"], "digest_freq": "weekly", "last_digest_at": None}]
            if not rows:
                log.error("test mode: no account found with email %s", a.only)
        sent = failed = 0
        os.makedirs("preview", exist_ok=True)
        for row in rows or []:
            try:
                if not due(row, now, a.force or bool(a.only)): continue
                u = await sb(s, f"/auth/v1/admin/users/{row['user_id']}")
                email = u.get("email")
                if not email or (a.only and email.lower() != a.only.lower()): continue
                name = ((u.get("user_metadata") or {}).get("name") or (u.get("user_metadata") or {}).get("full_name") or "").split(" ")[0]
                news = await load_news(d1q, s, row["digest_freq"])
                subject = ("Your weekly mutual fund digest" if row["digest_freq"] == "weekly" else "Your daily mutual fund digest") + (f": {news[0]['title'][:60]}" if news else "")
                body, text = render_email(name, row["digest_freq"], news), render_text(name, row["digest_freq"], news)
                if a.dry_run:
                    open(f"preview/{row['user_id'][:8]}.html", "w").write(body); log.info("preview written for %s", row["user_id"][:8]); continue
                await send(s, email, subject, body, text)
                log.info("Resend accepted the email for %s", email)
                await sb(s, f"/rest/v1/user_prefs?user_id=eq.{row['user_id']}", "PATCH", {"last_digest_at": now.strftime("%Y-%m-%dT%H:%M:%SZ")}, "return=minimal")
                log.info("sent to %s", email)
                sent += 1
            except Exception as e:
                failed += 1; log.error("user %s failed: %s", str(row.get("user_id"))[:8], e)
        log.info("done: sent=%d failed=%d", sent, failed)
        if failed and not sent: sys.exit(1)

if __name__ == "__main__":
    asyncio.run(main())
