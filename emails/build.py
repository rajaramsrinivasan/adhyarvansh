"""
Brand email templates for Adhyarvansh.  Run:  python3 emails/build.py

Writes:
  supabase/email-templates/*.html   -> paste into Supabase > Authentication > Email Templates
                                        (they use Supabase's Go-template variables)
  emails/out/worker_templates.json  -> welcome + account-deleted HTML, embedded in worker.js
                                        ({{name}}, {{when}} are replaced by the Worker)
  emails/preview/*.html             -> sample renders for checking in a browser
"""
import json, os, html

SITE = "https://adhyarvansh.com"
LOGO = SITE + "/brand/email-logo.png"
INK, VIOLET, MUTED, LINE = "#0B1033", "#7C3AED", "#5E6288", "#E6E0F7"
FONT = "-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,Helvetica,Arial,sans-serif"

def layout(preheader, tagline, inner, footer):
    return f'''<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><meta name="color-scheme" content="light only">
<title>Adhyarvansh</title></head>
<body style="margin:0;padding:0;background:#F1EEFF;-webkit-text-size-adjust:100%">
<div style="display:none;max-height:0;overflow:hidden;opacity:0">{preheader}</div>
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="background:#F1EEFF"><tr><td align="center" style="padding:16px 12px">
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="max-width:600px;background:#FFFFFF;border-radius:20px;overflow:hidden;font-family:{FONT}">
  <tr><td style="background:#0B1033;background-image:linear-gradient(135deg,#0B1033 0%,#2B1A78 60%,#7C3AED 100%);padding:26px 28px">
    <a href="{SITE}" style="text-decoration:none"><img src="{LOGO}" width="210" height="44" alt="Adhyarvansh" style="display:block;border:0;outline:none;width:210px;height:auto;font-size:24px;font-weight:800;color:#FFFFFF"></a>
    <div style="font-size:14px;color:#CFC6FF;margin-top:10px">{tagline}</div>
  </td></tr>
  <tr><td style="height:4px;background:#7C3AED;background-image:linear-gradient(90deg,#7C3AED,#D946EF,#06C5F0)"></td></tr>
  <tr><td style="padding:28px 28px 12px;color:{INK}">{inner}</td></tr>
  <tr><td style="padding:18px 28px 26px;background:#FAF8FF;border-top:1px solid {LINE}">
    <div style="font-size:12.5px;line-height:1.6;color:{MUTED}">{footer}</div>
  </td></tr>
</table></td></tr></table></body></html>'''

def h1(t): return f'<div style="font-size:24px;line-height:1.25;font-weight:800;letter-spacing:-.3px;color:{INK};margin:0 0 12px">{t}</div>'
def p(t, mt=0): return f'<p style="margin:{mt}px 0 14px;font-size:16px;line-height:1.6;color:{INK}">{t}</p>'
def small(t): return f'<p style="margin:0 0 14px;font-size:14px;line-height:1.6;color:{MUTED}">{t}</p>'
def button(label, url):
    return f'''<table role="presentation" cellpadding="0" cellspacing="0" style="margin:8px 0 18px"><tr><td style="border-radius:14px;background:#7C3AED;background-image:linear-gradient(135deg,#5B21B6,#8B2FE0 55%,#D946EF)">
<a href="{url}" style="display:inline-block;padding:15px 28px;font-size:16px;font-weight:700;color:#FFFFFF;text-decoration:none;border-radius:14px">{label}</a></td></tr></table>'''
def box(t): return f'<div style="margin:6px 0 18px;padding:16px 18px;border-radius:14px;background:#F6F3FF;border:1px solid {LINE};font-size:15px;line-height:1.6;color:{INK}">{t}</div>'

SAFE = "Adhyarvansh will never ask for your code or password by email, phone or chat."
STD_FOOT = f'You are receiving this because of activity on your Adhyarvansh account. {SAFE}<br>Information on Adhyarvansh is for general information only and is not investment advice. Mutual fund investments are subject to market risks.'

# ───────────────────────── Supabase (Go-template variables) ─────────────────────────
def otp(kind):
    new = kind == "signup"
    head = "Confirm your new account" if new else "Your sign-in code"
    lead = "Welcome! Enter this code in Adhyarvansh to confirm your email and finish creating your account." if new else "Enter this code in Adhyarvansh to sign in. No password needed."
    code = f'''<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="margin:6px 0 16px"><tr><td align="center" style="padding:22px 12px;border-radius:16px;background:#F6F3FF;border:1.5px solid #D9CCFA">
<div style="font-family:'SF Mono',Menlo,Consolas,monospace;font-size:38px;line-height:1;font-weight:800;letter-spacing:10px;color:{INK};padding-left:10px">{{{{ .Token }}}}</div></td></tr></table>'''
    inner = h1(head) + p(lead) + code + small("This code can be used once and expires soon. Enter it on the same screen where you asked for it.") + small("Didn't ask for this? You can safely ignore this email. Nobody can sign in without the code.")
    return layout(("Your Adhyarvansh code is {{ .Token }}"), "Secure sign-in", inner, f'Sent to {{{{ .Email }}}}. {SAFE}')

def change_email():
    inner = (h1("Confirm your new email address") +
        p("You asked to change the email on your Adhyarvansh account.") +
        box('<span style="color:#5E6288">From</span> &nbsp;<b>{{ .Email }}</b><br><span style="color:#5E6288">To</span> &nbsp;&nbsp;&nbsp;&nbsp;<b>{{ .NewEmail }}</b>') +
        button("Confirm new email", "{{ .ConfirmationURL }}") +
        small("Until you confirm, you keep signing in with your current email. The link works once and expires soon.") +
        small("Didn't ask for this? Don't click the button. Your account stays as it is, and you can ignore this email."))
    return layout("Confirm your new email address for Adhyarvansh", "Account security", inner, f"Sent because a change of email was requested on your account. {SAFE}")

# ───────────────────────── Worker-sent (Resend) ─────────────────────────
def welcome():
    def tile(title, text):
        return f'''<tr><td style="padding:12px 0;border-top:1px solid {LINE}"><div style="font-size:16px;font-weight:800;color:{INK}">{title}</div><div style="font-size:14.5px;line-height:1.55;color:{MUTED};margin-top:3px">{text}</div></td></tr>'''
    inner = (h1("Welcome to Adhyarvansh, {{name}}") +
        p("Your personal mutual fund intelligence platform is ready. Here is what you can do first:") +
        f'<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="margin:0 0 10px">' +
        tile("Add your investments", "Track every fund in one place with live value, gains and tax position.") +
        tile("See AI signals", "Each fund carries a Buy, Hold, Watch or Exit signal with the reasoning behind it.") +
        tile("Get picks that fit you", "Answer six quick questions and see funds that suit your goal and risk comfort.") +
        tile("Stay informed", "Choose a daily or weekly digest of industry headlines in Settings.") +
        '</table>' + button("Open Adhyarvansh", SITE) +
        small("Adhyarvansh is a research and tracking tool. Nothing in it is investment advice."))
    return layout("Welcome to Adhyarvansh. Here is how to get started.", "Welcome", inner, STD_FOOT)

def deleted():
    inner = (h1("Your account has been deleted") +
        p("Hi {{name}}, as you asked, we deleted your Adhyarvansh account on <b>{{when}}</b>.") +
        box("<b>Removed</b><br>Your portfolio entries and exits<br>Your journal and watchlist<br>Your email and fund preferences<br>Your sign-in") +
        p("You will not receive any more emails from us, including the digest.") +
        small("Changed your mind? You are welcome to create a new account any time, though your old data cannot be restored.") +
        small("Didn't ask for this? Reply to this email right away so we can look into it."))
    return layout("Your Adhyarvansh account has been deleted.", "Account deleted", inner, "This is the last email you will get from us about this account. Information on Adhyarvansh is for general information only and is not investment advice.")

def sample(s):
    return (s.replace("{{ .Token }}", "482916").replace("{{ .Email }}", "raja@example.com").replace("{{ .NewEmail }}", "raja.new@example.com")
             .replace("{{ .ConfirmationURL }}", "#").replace("{{name}}", "Raja").replace("{{when}}", "24 Nov 2026, 2:30 PM IST"))

if __name__ == "__main__":
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    os.makedirs(f"{root}/supabase/email-templates", exist_ok=True)
    os.makedirs(f"{root}/emails/out", exist_ok=True); os.makedirs(f"{root}/emails/preview", exist_ok=True)
    sup = {"magic-link-sign-in": otp("signin"), "confirm-signup": otp("signup"), "change-email-address": change_email()}
    for k, v in sup.items():
        open(f"{root}/supabase/email-templates/{k}.html", "w").write(v)
    wk = {"welcome": welcome(), "deleted": deleted()}
    json.dump(wk, open(f"{root}/emails/out/worker_templates.json", "w"))
    for k, v in {**sup, **wk}.items():
        open(f"{root}/emails/preview/{k}.html", "w").write(sample(v))
    print("built", list(sup) + list(wk))
