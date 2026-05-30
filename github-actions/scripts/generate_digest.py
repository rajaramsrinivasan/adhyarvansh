"""
generate_digest.py — Daily Market Digest generator (Step 2.5 in the daily-run)

DESIGN (safe + low-cost):
  • Source: FREE public RSS feeds from established Indian financial outlets.
    Reading public headlines sends NOTHING about the user or their portfolio
    outside — it is the same as opening a news website. One-way, read-only.
  • Claude: ONE small call per day to condense + tag headlines into fund-relevant
    bullets. Cost ~₹1-2/day. (Switch model to Haiku to make it even cheaper.)
  • Storage: writes a single row to D1 `market_digest`. The app reads it on login.

GitHub Secrets needed (same as your other scripts):
  CF_ACCOUNT_ID, CF_API_TOKEN, D1_DATABASE_ID, ANTHROPIC_API_KEY

─────────────────────────────────────────────────────────────────────────────
STEP 0 — Create the D1 table ONCE (run locally via wrangler, or in D1 console):

  CREATE TABLE IF NOT EXISTS market_digest (
    digest_date  TEXT PRIMARY KEY,         -- 'YYYY-MM-DD'
    headline     TEXT,
    summary      TEXT,
    items        TEXT,                      -- JSON array of {text, impact, affects[]}
    sentiment    TEXT,                      -- 'positive' | 'negative' | 'mixed'
    generated_at TEXT
  );
─────────────────────────────────────────────────────────────────────────────
"""

import os, json, time, logging, asyncio, aiohttp
import xml.etree.ElementTree as ET
from datetime import datetime, timezone, timedelta
import anthropic

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)

CF_ACCOUNT_ID     = os.environ["CF_ACCOUNT_ID"]
CF_API_TOKEN      = os.environ["CF_API_TOKEN"]
D1_DATABASE_ID    = os.environ["D1_DATABASE_ID"]
ANTHROPIC_API_KEY = os.environ["ANTHROPIC_API_KEY"]

D1_URL     = f"https://api.cloudflare.com/client/v4/accounts/{CF_ACCOUNT_ID}/d1/database/{D1_DATABASE_ID}/query"
CF_HEADERS = {"Authorization": f"Bearer {CF_API_TOKEN}", "Content-Type": "application/json"}

# Free, public, reputable Indian market/business RSS feeds (headlines only).
RSS_FEEDS = [
    "https://economictimes.indiatimes.com/markets/rssfeeds/1977021501.cms",   # ET Markets
    "https://www.moneycontrol.com/rss/MCtopnews.xml",                          # Moneycontrol top
    "https://www.business-standard.com/rss/markets-106.rss",                   # BS Markets
    "https://www.livemint.com/rss/markets",                                    # Livemint Markets
]

USER_AGENT = "Mozilla/5.0 (compatible; AdhyarvanshDigest/1.0; +https://adhyarvansh.com)"
MAX_HEADLINES = 40          # cap how much we feed Claude (cost control)
MODEL = "claude-sonnet-4-20250514"   # swap to a Haiku model id to cut cost ~3x


async def fetch_feed(session, url):
    """Fetch one RSS feed; return list of (title, description). Never raises."""
    try:
        async with session.get(url, headers={"User-Agent": USER_AGENT},
                               timeout=aiohttp.ClientTimeout(total=20)) as r:
            if r.status != 200:
                log.warning("Feed %s -> HTTP %s", url, r.status)
                return []
            text = await r.text()
        root = ET.fromstring(text)
        items = []
        for item in root.iter("item"):
            title = (item.findtext("title") or "").strip()
            desc  = (item.findtext("description") or "").strip()
            # strip crude HTML from description
            if "<" in desc:
                import re as _re
                desc = _re.sub(r"<[^>]+>", "", desc)
            if title:
                items.append((title, desc[:200]))
        return items
    except Exception as e:
        log.warning("Feed %s failed: %s", url, e)
        return []


async def gather_headlines(session):
    feeds = await asyncio.gather(*[fetch_feed(session, u) for u in RSS_FEEDS])
    seen, headlines = set(), []
    for feed in feeds:
        for title, desc in feed:
            key = title.lower()[:80]
            if key in seen:
                continue
            seen.add(key)
            headlines.append((title, desc))
    return headlines[:MAX_HEADLINES]


def build_digest_with_claude(client, headlines):
    """ONE Claude call: condense headlines into fund-relevant bullets + tags."""
    lines = "\n".join(f"- {t} :: {d}" for t, d in headlines)
    prompt = f"""You are a mutual-fund-focused market analyst writing a daily digest for retail investors in India.

Below are today's market/business headlines from public Indian financial news.

HEADLINES:
{lines}

Produce a concise daily digest that helps a mutual fund investor understand what
matters today. Focus ONLY on items relevant to mutual fund investors: sector moves,
index trends, interest rates, macro data, regulatory/SEBI/AMFI news, gold/commodity
moves, FII/DII flows, and notable industry shifts. Ignore individual stock tips,
celebrity/sports/unrelated news.

Return EXACTLY this JSON (no markdown, no extra text):
{{
  "headline": "one punchy line summarising today's market mood (max 10 words)",
  "summary": "2-3 sentence plain-language overview a beginner can understand",
  "sentiment": "positive | negative | mixed",
  "items": [
    {{
      "text": "one clear, jargon-free bullet (max 25 words)",
      "impact": "positive | negative | neutral",
      "affects": ["which fund categories this touches, e.g. Large Cap, Gold, Debt, IT Sector, Banking"]
    }}
  ]
}}

Rules:
- 5 to 7 items maximum. Quality over quantity.
- Plain language. Explain WHY it matters for fund investors in the bullet itself.
- "affects" should use fund-investor-friendly category names.
- This is informational only. Do NOT give buy/sell advice or price targets.
- If headlines are sparse, return fewer items rather than inventing news."""

    resp = client.messages.create(
        model=MODEL,
        max_tokens=1500,
        messages=[{"role": "user", "content": prompt}],
    )
    raw = resp.content[0].text.strip()
    if raw.startswith("```"):
        raw = raw[raw.find("\n") + 1:]
        if raw.endswith("```"):
            raw = raw[:-3]
    data = json.loads(raw.strip())
    # log token usage so you can see the real per-run cost
    try:
        u = resp.usage
        log.info("Claude usage: input=%s output=%s tokens", u.input_tokens, u.output_tokens)
    except Exception:
        pass
    return data


async def save_digest(session, digest):
    # IST date so the digest is dated correctly for Indian users
    ist = timezone(timedelta(hours=5, minutes=30))
    today = datetime.now(ist).strftime("%Y-%m-%d")
    body = {
        "sql": """INSERT INTO market_digest
                    (digest_date, headline, summary, items, sentiment, generated_at)
                  VALUES (?,?,?,?,?,datetime('now'))
                  ON CONFLICT(digest_date) DO UPDATE SET
                    headline=excluded.headline, summary=excluded.summary,
                    items=excluded.items, sentiment=excluded.sentiment,
                    generated_at=excluded.generated_at""",
        "params": [
            today,
            str(digest.get("headline", ""))[:120],
            str(digest.get("summary", ""))[:600],
            json.dumps(digest.get("items", []))[:4000],
            str(digest.get("sentiment", "mixed"))[:20],
        ],
    }
    async with session.post(D1_URL, headers=CF_HEADERS, json=body) as r:
        text = await r.text()
        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            raise Exception(f"D1 non-JSON (HTTP {r.status}): {text[:160]}")
        if not data.get("success"):
            raise Exception(str(data.get("errors", "")))
    log.info("Digest saved for %s", today)


async def main():
    start = time.time()
    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
    async with aiohttp.ClientSession() as session:
        headlines = await gather_headlines(session)
        log.info("Collected %d unique headlines", len(headlines))
        if len(headlines) < 3:
            log.warning("Too few headlines — skipping digest generation today.")
            return
        digest = build_digest_with_claude(client, headlines)
        await save_digest(session, digest)
    log.info("Done in %.1fs", time.time() - start)


if __name__ == "__main__":
    asyncio.run(main())
