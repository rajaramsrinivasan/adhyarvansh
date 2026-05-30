# ─────────────────────────────────────────────────────────────────────────────
# DROP-IN FIX for github-actions/scripts/sync_mf_data.py
#
# The daily-run failed with:
#   aiohttp.client_exceptions.ContentTypeError: 0,
#   message='Attempt to decode JSON with unexpected mimetype: text/html',
#   url=URL('https://api.mfapi.in/mf')
#
# Cause: mfapi.in intermittently returns an HTML error/throttle page instead of
# JSON. aiohttp's r.json() does a STRICT mimetype check and raises instead of
# parsing. One bad response crashes the whole sync, so mf_cache and
# ai_recommendations never get updated -> blank metrics in the app.
#
# Fix: a resilient fetch helper that
#   (1) checks HTTP status first,
#   (2) parses JSON regardless of mimetype  (content_type=None),
#   (3) retries with backoff on transient errors,
#   (4) sends a normal User-Agent (some hosts block default aiohttp UA).
# ─────────────────────────────────────────────────────────────────────────────

import asyncio
import json
import logging

import aiohttp

log = logging.getLogger(__name__)

MFAPI_BASE = "https://api.mfapi.in"
HEADERS = {
    # Some endpoints serve an HTML challenge to the default aiohttp UA.
    "User-Agent": "Mozilla/5.0 (compatible; AdhyarvanshBot/1.0; +https://adhyarvansh.com)",
    "Accept": "application/json",
}


async def fetch_json(session, url, *, retries=4, base_delay=1.5, timeout=30):
    """
    Fetch JSON from `url` resiliently.

    Returns the parsed object, or None if every attempt failed (caller decides
    whether a None means "skip this fund" vs "abort"). Never raises
    ContentTypeError — it parses the body manually with content_type=None.
    """
    last_err = None
    for attempt in range(1, retries + 1):
        try:
            async with session.get(
                url,
                headers=HEADERS,
                timeout=aiohttp.ClientTimeout(total=timeout),
            ) as r:
                # 1) status check BEFORE parsing
                if r.status != 200:
                    body_preview = (await r.text())[:200]
                    last_err = f"HTTP {r.status} :: {body_preview!r}"
                    # 429/5xx are transient -> retry; 404 is permanent -> stop
                    if r.status == 404:
                        log.warning("404 (no such resource): %s", url)
                        return None
                    raise aiohttp.ClientError(last_err)

                # 2) parse JSON regardless of mimetype (this is the actual bug fix)
                text = await r.text()
                try:
                    return json.loads(text)
                except json.JSONDecodeError as je:
                    # mfapi returned HTML / non-JSON despite 200 — treat as transient
                    last_err = f"non-JSON body (len={len(text)}): {text[:200]!r}"
                    raise aiohttp.ClientError(last_err) from je

        except (aiohttp.ClientError, asyncio.TimeoutError) as e:
            last_err = str(e)
            if attempt < retries:
                delay = base_delay * (2 ** (attempt - 1))  # 1.5, 3, 6, 12s
                log.warning(
                    "fetch failed (attempt %d/%d) for %s: %s — retrying in %.1fs",
                    attempt, retries, url, last_err, delay,
                )
                await asyncio.sleep(delay)
            else:
                log.error("fetch gave up after %d attempts for %s: %s",
                          retries, url, last_err)
    return None


# ─────────────────────────────────────────────────────────────────────────────
# HOW TO USE IT IN sync_mf_data.py
# ─────────────────────────────────────────────────────────────────────────────
#
# BEFORE (the failing code, ~line 154):
#
#     async with session.get(f"{MFAPI_BASE}/mf") as r:
#         all_funds = await r.json()          # <-- crashes on text/html
#
# AFTER:
#
#     all_funds = await fetch_json(session, f"{MFAPI_BASE}/mf")
#     if not all_funds:
#         log.error("Could not load MF scheme list from mfapi.in — aborting sync")
#         raise SystemExit(1)   # or: return, to let the job exit cleanly
#
# And for per-fund NAV history (so ONE bad fund doesn't kill the whole run):
#
#     async def sync_one_fund(session, scheme_code):
#         data = await fetch_json(session, f"{MFAPI_BASE}/mf/{scheme_code}")
#         if not data or not data.get("data"):
#             log.warning("No NAV history for %s — skipping", scheme_code)
#             return None
#         navs = data["data"]          # [{date:'dd-mm-yyyy', nav:'123.45'}, ...]
#         meta = data.get("meta", {})
#         # ... compute return_1y / 3y / 5y, write to mf_cache ...
#         return navs
#
# Wrap the gather so individual failures don't abort everything:
#
#     results = await asyncio.gather(
#         *[sync_one_fund(session, c) for c in scheme_codes],
#         return_exceptions=True,      # <-- key: collect errors instead of crashing
#     )
#     ok = sum(1 for x in results if x and not isinstance(x, Exception))
#     log.info("Synced %d/%d funds", ok, len(scheme_codes))
#
# ─────────────────────────────────────────────────────────────────────────────
# OPTIONAL: be gentle on mfapi.in so it stops returning HTML throttle pages.
# Limit concurrency with a semaphore instead of firing thousands of requests:
#
#     SEM = asyncio.Semaphore(8)      # max 8 concurrent requests
#     async def sync_one_fund(session, scheme_code):
#         async with SEM:
#             data = await fetch_json(session, f"{MFAPI_BASE}/mf/{scheme_code}")
#             ...
#
# ─────────────────────────────────────────────────────────────────────────────
