"""
fetch_industry_news.py — collect mutual-fund industry headlines for the digest email.

Reads public RSS feeds (headline + short excerpt + link only; no article text is
copied), scores each item for mutual-fund relevance, de-duplicates, and upserts
into D1 table `industry_news`. Safe to run daily; old rows (>45 days) are pruned.

Secrets: CF_ACCOUNT_ID, CF_API_TOKEN, D1_DATABASE_ID
"""
import os, re, html, json, asyncio, logging, hashlib
from datetime import datetime, timezone, timedelta
from email.utils import parsedate_to_datetime
from urllib.parse import quote_plus
import xml.etree.ElementTree as ET
import aiohttp

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)

UA = "Mozilla/5.0 (compatible; AdhyarvanshDigest/2.0; +https://adhyarvansh.com)"

def gnews(q):
    return f"https://news.google.com/rss/search?q={quote_plus(q)}&hl=en-IN&gl=IN&ceid=IN:en"

# (source label, url, general?)  general=True means the feed is broad, so keyword scoring must pass.
FEEDS = [
    ("Economic Times", "https://economictimes.indiatimes.com/markets/rssfeeds/1977021501.cms", True),
    ("Mint",           "https://www.livemint.com/rss/money", True),
    ("Google News",    gnews("mutual funds India when:7d"), False),
    ("Google News",    gnews("AMFI SIP inflows when:7d"), False),
    ("Google News",    gnews("SEBI mutual fund rules when:7d"), False),
    ("Google News",    gnews("AMC NFO launch India when:7d"), False),
]

# keyword -> weight (case-insensitive, whole-word-ish)
KEYWORDS = {
    "mutual fund": 5, "mutual funds": 5, "amfi": 6, "sebi": 4, "sip": 4, "nfo": 5, "aum": 4,
    "nav": 2, "expense ratio": 4, "elss": 4, "index fund": 4, "etf": 3, "debt fund": 4,
    "equity fund": 4, "hybrid fund": 3, "fund house": 5, "asset management": 4, "amc": 4,
    "fund manager": 3, "folio": 3, "redemption": 2, "gold fund": 3, "liquid fund": 3,
    "large cap": 2, "mid cap": 2, "small cap": 2, "flexi cap": 3, "rbi": 2, "repo rate": 2,
    "inflation": 1, "fii": 1, "dii": 1, "sensex": 1, "nifty": 1,
}
NEGATIVE = ["horoscope", "cricket", "bollywood", "ipl ", "stock tip", "buy or sell", "target price", "intraday"]

def clean(s, n=None):
    s = html.unescape(re.sub(r"<[^>]+>", " ", s or ""))
    s = re.sub(r"\s+", " ", s).strip()
    if n and len(s) > n:
        s = s[:n].rsplit(" ", 1)[0].rstrip(",;:- ") + "…"
    return s

def score(title, desc):
    t = f"{title} {desc}".lower()
    if any(n in t for n in NEGATIVE):
        return 0
    sc = 0
    for k, w in KEYWORDS.items():
        if re.search(r"\b" + re.escape(k) + r"\b", t):
            sc += w
    if re.search(r"\b(mutual fund|amfi|sebi|nfo|sip)\b", title.lower()):
        sc += 4
    return sc

def parse(xml_text, source, general):
    out = []
    root = ET.fromstring(xml_text)
    for it in root.iter("item"):
        title = clean(it.findtext("title"))
        link = (it.findtext("link") or "").strip()
        if not title or not link:
            continue
        src = source
        s_el = it.find("source")
        if s_el is not None and (s_el.text or "").strip():
            src = s_el.text.strip()
            title = re.sub(r"\s+-\s+" + re.escape(src) + r"$", "", title)   # Google News appends " - Source"
        desc = clean(it.findtext("description"))
        if source == "Google News":
            desc = ""      # Google News descriptions are just link lists
        try:
            pub = parsedate_to_datetime(it.findtext("pubDate")).astimezone(timezone.utc)
        except Exception:
            pub = datetime.now(timezone.utc)
        sc = score(title, desc)
        if general and sc < 4:
            continue
        if sc <= 0:
            continue
        out.append(dict(url=link, title=title, summary=clean(desc, 220), source=src,
                        published_at=pub.strftime("%Y-%m-%dT%H:%M:%SZ"), score=sc))
    return out

async def fetch(session, source, url, general):
    try:
        async with session.get(url, headers={"User-Agent": UA}, timeout=aiohttp.ClientTimeout(total=25)) as r:
            if r.status != 200:
                log.warning("%s -> HTTP %s (%s)", source, r.status, url); return []
            items = parse(await r.text(), source, general)
            log.info("%s: %d relevant items (%s)", source, len(items), url[:70]); return items
    except Exception as e:
        log.warning("%s failed: %s", url[:70], e); return []

def dedupe(items):
    best = {}
    for it in items:
        key = re.sub(r"[^a-z0-9]+", " ", it["title"].lower()).strip()[:70]
        if key not in best or it["score"] > best[key]["score"]:
            best[key] = it
    return list(best.values())

async def main():
    from d1 import q
    async with aiohttp.ClientSession() as s:
        results = await asyncio.gather(*[fetch(s, *f) for f in FEEDS])
        items = dedupe([i for r in results for i in r])
        log.info("%d unique items", len(items))
        if not items:
            log.error("No items fetched from any feed"); return
        await q(s, """CREATE TABLE IF NOT EXISTS industry_news (
            url TEXT PRIMARY KEY, title TEXT, summary TEXT, source TEXT,
            published_at TEXT, score INTEGER, fetched_at TEXT)""")
        now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        for it in items:
            await q(s, "INSERT INTO industry_news (url,title,summary,source,published_at,score,fetched_at) VALUES (?,?,?,?,?,?,?) "
                       "ON CONFLICT(url) DO UPDATE SET title=excluded.title, summary=excluded.summary, score=excluded.score, fetched_at=excluded.fetched_at",
                    [it["url"], it["title"], it["summary"], it["source"], it["published_at"], it["score"], now])
        cutoff = (datetime.now(timezone.utc) - timedelta(days=45)).strftime("%Y-%m-%dT%H:%M:%SZ")
        await q(s, "DELETE FROM industry_news WHERE published_at < ?", [cutoff])
        log.info("Saved %d items", len(items))

if __name__ == "__main__":
    asyncio.run(main())
