"""
fetch_amc_logos.py  —  Collect sharp fund-house (AMC) logos into D1
===================================================================
Runs in GitHub Actions (full internet access). For every AMC found in
mf_cache it visits the fund house's website, looks for the best square
icon (apple-touch-icon, large <link rel="icon">, /apple-touch-icon.png,
favicon.ico frames, square og:image), resizes it to 256x256 PNG and stores
it in D1 table `amc_logos`. The Worker serves it at /logo/<domain>.

The AMC -> website map below must match AMC_DOMAINS in the frontend
(worker.js amcDomain()). AMCs with no mapping are listed in the report.

GitHub Secrets needed (same as sync_mf_data.py):
  CF_ACCOUNT_ID, CF_API_TOKEN (D1:Edit), D1_DATABASE_ID
"""

import os, io, re, json, base64, asyncio, logging
from urllib.parse import urljoin
import aiohttp
from PIL import Image

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)

CF_ACCOUNT_ID  = os.environ["CF_ACCOUNT_ID"]
CF_API_TOKEN   = os.environ["CF_API_TOKEN"]
D1_DATABASE_ID = os.environ["D1_DATABASE_ID"]
D1_URL = f"https://api.cloudflare.com/client/v4/accounts/{CF_ACCOUNT_ID}/d1/database/{D1_DATABASE_ID}/query"

OUT_SIZE   = 256
MIN_SIDE   = 64          # ignore icons smaller than this
MAX_BYTES  = 3_000_000
CONCURRENCY = 6
HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; AdhyarvanshBot/1.0; +https://adhyarvansh.com)",
    "Accept": "text/html,image/*;q=0.9,*/*;q=0.8",
}

# keyword in AMC name  ->  fund house website (first match wins)
AMC_DOMAINS = [
    ("aditya birla", "mutualfund.adityabirlacapital.com"),
    ("sbi", "sbimf.com"),
    ("hdfc", "hdfcfund.com"),
    ("icici", "icicipruamc.com"),
    ("axis", "axismf.com"),
    ("kotak", "kotakmf.com"),
    ("nippon", "mf.nipponindiaim.com"),
    ("reliance", "mf.nipponindiaim.com"),
    ("uti", "utimf.com"),
    ("dsp", "dspim.com"),
    ("franklin", "franklintempletonindia.com"),
    ("templeton", "franklintempletonindia.com"),
    ("mirae", "miraeassetmf.co.in"),
    ("tata", "tatamutualfund.com"),
    ("invesco", "invescomutualfund.com"),
    ("idfc", "bandhanmutual.com"),
    ("bandhan", "bandhanmutual.com"),
    ("canara", "canararobeco.com"),
    ("sundaram", "sundarammutual.com"),
    ("hsbc", "assetmanagement.hsbc.co.in"),
    ("edelweiss", "edelweissmf.com"),
    ("motilal", "motilaloswalmf.com"),
    ("quant", "quantmutual.com"),
    ("parag parikh", "amc.ppfas.com"),
    ("ppfas", "amc.ppfas.com"),
    ("baroda", "barodabnpparibasmf.in"),
    ("pgim", "pgimindiamf.com"),
    ("lic", "licmf.com"),
    ("mahindra", "mahindramanulife.com"),
    ("navi", "navi.com"),
    ("groww", "growwmf.in"),
    ("whiteoak", "whiteoakindia.com"),
    ("jm financial", "jmfinancialmf.com"),
    ("union", "unionmf.com"),
    ("bank of india", "boimf.in"),
    ("iti", "itiamc.com"),
    ("quantum", "quantumamc.com"),
    ("trust", "trustmf.com"),
    ("helios", "heliosmf.in"),
    ("360 one", "360.one"),
    ("old bridge", "oldbridgemf.com"),
    ("samco", "samcomf.com"),
    ("taurus", "taurusmutualfund.com"),
    ("shriram", "shriramamc.in"),
    ("nj ", "njmutualfund.com"),
    ("angel one", "angelonemf.com"),
    ("zerodha", "zerodhafundhouse.com"),
    ("bajaj", "bajajamc.com"),
    ("unifi", "unifimf.com"),
]


def amc_domain(name):
    s = " " + re.sub(r"[^a-z0-9 ]", " ", (name or "").lower()) + " "
    for k, d in AMC_DOMAINS:
        k = k.strip()
        if f" {k} " in s or (" " in k and k in s):
            return d
    return None


async def d1(session, sql, params=None):
    h = {"Authorization": f"Bearer {CF_API_TOKEN}", "Content-Type": "application/json"}
    async with session.post(D1_URL, headers=h, json={"sql": sql, "params": params or []}) as r:
        data = json.loads(await r.text())
    if not data.get("success"):
        raise RuntimeError(f"D1 error: {data.get('errors')}")
    return data["result"][0].get("results", [])


def attrs(tag):
    return {m.group(1).lower(): (m.group(3) or m.group(4) or "")
            for m in re.finditer(r"([a-zA-Z:-]+)\s*=\s*(\"([^\"]*)\"|'([^']*)')", tag)}


def candidates(html, base):
    out = []
    for tag in re.findall(r"<link\b[^>]*>", html, flags=re.I):
        a = attrs(tag)
        rel = a.get("rel", "").lower()
        if "icon" in rel and a.get("href"):
            out.append(urljoin(base, a["href"]))
    for tag in re.findall(r"<meta\b[^>]*>", html, flags=re.I):
        a = attrs(tag)
        if a.get("property", "").lower() in ("og:image", "twitter:image") and a.get("content"):
            out.append(urljoin(base, a["content"]))
    return out


async def get_bytes(session, url):
    try:
        async with session.get(url, headers=HEADERS, timeout=aiohttp.ClientTimeout(total=25), allow_redirects=True) as r:
            if r.status != 200:
                return None
            body = await r.content.read(MAX_BYTES + 1)
            return body if 0 < len(body) <= MAX_BYTES else None
    except Exception:
        return None


def best_frame(raw):
    """Return (PIL image RGBA, side) for the largest usable square-ish frame, or None."""
    try:
        im = Image.open(io.BytesIO(raw))
        if im.format == "ICO" and getattr(im, "ico", None):
            size = max(im.ico.sizes(), key=lambda s: s[0])
            im = im.ico.getimage(size)
        im.load()
        im = im.convert("RGBA")
    except Exception:
        return None
    w, h = im.size
    if min(w, h) < MIN_SIDE or not (0.8 <= w / h <= 1.25):
        return None
    return im, min(w, h)


def to_png256(im):
    im.thumbnail((OUT_SIZE, OUT_SIZE), Image.LANCZOS)
    canvas = Image.new("RGBA", (OUT_SIZE, OUT_SIZE), (0, 0, 0, 0))
    canvas.paste(im, ((OUT_SIZE - im.width) // 2, (OUT_SIZE - im.height) // 2), im)
    buf = io.BytesIO()
    canvas.save(buf, "PNG", optimize=True)
    return buf.getvalue()


async def find_logo(session, domain):
    base = f"https://{domain}/"
    html = ""
    try:
        async with session.get(base, headers=HEADERS, timeout=aiohttp.ClientTimeout(total=25), allow_redirects=True) as r:
            if r.status == 200:
                html = (await r.content.read(1_500_000)).decode("utf-8", "ignore")
                base = str(r.url)
    except Exception as e:
        log.warning("%s: homepage failed (%s)", domain, e)
    urls = candidates(html, base) + [urljoin(base, p) for p in (
        "/apple-touch-icon.png", "/apple-touch-icon-precomposed.png", "/favicon.ico")]
    best = None
    seen = set()
    for u in urls:
        if u in seen or u.lower().split("?")[0].endswith(".svg"):
            continue
        seen.add(u)
        raw = await get_bytes(session, u)
        if not raw:
            continue
        got = best_frame(raw)
        if got and (best is None or got[1] > best[1]):
            best = (got[0], got[1], u)
    return best


async def main():
    conn = aiohttp.TCPConnector(limit=CONCURRENCY)
    async with aiohttp.ClientSession(connector=conn) as session:
        await d1(session, """CREATE TABLE IF NOT EXISTS amc_logos (
            domain TEXT PRIMARY KEY, mime TEXT, data TEXT, src_side INTEGER,
            source TEXT, updated_at TEXT)""")
        rows = await d1(session, "SELECT DISTINCT amc_name FROM mf_cache WHERE amc_name IS NOT NULL")
        by_domain, unmapped = {}, []
        for r in rows:
            d = amc_domain(r["amc_name"])
            (by_domain.setdefault(d, []).append(r["amc_name"]) if d else unmapped.append(r["amc_name"]))
        log.info("%d AMCs -> %d websites (%d AMCs unmapped)", len(rows), len(by_domain), len(unmapped))

        sem = asyncio.Semaphore(CONCURRENCY)
        results = {}

        async def work(domain):
            async with sem:
                results[domain] = await find_logo(session, domain)

        await asyncio.gather(*(work(d) for d in by_domain))

        saved, missing = 0, []
        for domain, best in sorted(results.items()):
            if not best:
                missing.append(domain)
                continue
            im, side, src = best
            png = to_png256(im)
            await d1(session,
                """INSERT INTO amc_logos (domain, mime, data, src_side, source, updated_at)
                   VALUES (?,?,?,?,?,datetime('now'))
                   ON CONFLICT(domain) DO UPDATE SET mime=excluded.mime, data=excluded.data,
                   src_side=excluded.src_side, source=excluded.source, updated_at=excluded.updated_at""",
                [domain, "image/png", base64.b64encode(png).decode(), side, src])
            saved += 1
            log.info("saved %-45s %4dpx  %s", domain, side, src)

        print("\n===== AMC LOGO REPORT =====")
        print(f"saved: {saved}   no good icon found: {len(missing)}   unmapped AMC names: {len(unmapped)}")
        if missing:
            print("No icon >= %dpx (will use fallback): %s" % (MIN_SIDE, ", ".join(missing)))
        if unmapped:
            print("AMC names with no website mapping: " + " | ".join(sorted(unmapped)))


if __name__ == "__main__":
    asyncio.run(main())
