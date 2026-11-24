# Adhyarvansh email templates

Edit `emails/build.py`, then run `python3 emails/build.py`.

## Sent by Supabase (paste in Supabase → Authentication → Email Templates)
| Supabase template | File | Subject |
|---|---|---|
| Magic Link (sign-in code) | `supabase/email-templates/magic-link-sign-in.html` | Your Adhyarvansh sign-in code |
| Confirm signup (new account code) | `supabase/email-templates/confirm-signup.html` | Confirm your Adhyarvansh account |
| Change Email Address | `supabase/email-templates/change-email-address.html` | Confirm your new email address |

Both code templates show `{{ .Token }}`. For sending from your own domain, set
Authentication → SMTP Settings to Resend (host `smtp.resend.com`, port 465, user `resend`, password = Resend API key,
sender `Adhyarvansh <no-reply@adhyarvansh.com>`).

## Sent by the Worker through Resend
- **Welcome**: sent once, the first time a new user opens the app (when their preferences row is created).
- **Account deleted**: sent after Delete account succeeds.

Worker secrets: `RESEND_API_KEY` (required), `EMAIL_FROM_WORKER` (optional, default `Adhyarvansh <hello@adhyarvansh.com>`).
The built HTML is embedded in `worker.js` as `EMAIL_TPL`.
