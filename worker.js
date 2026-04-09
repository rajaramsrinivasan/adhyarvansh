/**
 * ADHYARVANSH — Mutual Fund Intelligence System
 * Cloudflare Worker · worker.js
 *
 * Secrets required (wrangler secret put):
 *   ANTHROPIC_API_KEY  — Anthropic Claude API key
 *   RESEND_API_KEY     — Resend.com API key for email
 *   APP_PASSWORD       — Login password (single-user)
 *   SESSION_SECRET     — 32-char random string for token signing
 *
 * KV binding:
 *   KV — main storage namespace
 */

import { getHTML } from './frontend.js';

// ─────────────────────────────────────────────────────────────
// CURATED FUND LIST FOR DAILY SCAN
// Verify / update scheme codes at: https://api.mfapi.in/mf/search?q=FUND_NAME
// ─────────────────────────────────────────────────────────────
const SCAN_UNIVERSE = [
  { code: '119598', name: 'Mirae Asset Emerging Bluechip',    category: 'Mid Cap',       risk: 'Aggressive' },
  { code: '120716', name: 'Mirae Asset Large Cap Fund',       category: 'Large Cap',     risk: 'Moderate'   },
  { code: '120828', name: 'Axis Bluechip Fund',               category: 'Large Cap',     risk: 'Moderate'   },
  { code: '125354', name: 'Axis Small Cap Fund',              category: 'Small Cap',     risk: 'Aggressive' },
  { code: '118989', name: 'Parag Parikh Flexi Cap Fund',      category: 'Flexi Cap',     risk: 'Moderate'   },
  { code: '118825', name: 'HDFC Mid-Cap Opportunities',       category: 'Mid Cap',       risk: 'Aggressive' },
  { code: '120503', name: 'ICICI Pru Balanced Advantage',     category: 'Hybrid',        risk: 'Conservative'},
  { code: '119270', name: 'SBI Small Cap Fund',               category: 'Small Cap',     risk: 'Aggressive' },
  { code: '120505', name: 'ICICI Pru Bluechip Fund',          category: 'Large Cap',     risk: 'Moderate'   },
  { code: '118834', name: 'DSP Small Cap Fund',               category: 'Small Cap',     risk: 'Aggressive' },
  { code: '100356', name: 'Aditya Birla SL Frontline Equity', category: 'Large Cap',     risk: 'Moderate'   },
  { code: '100033', name: 'Nippon India Large Cap Fund',      category: 'Large Cap',     risk: 'Moderate'   },
  { code: '119271', name: 'Kotak Flexicap Fund',              category: 'Flexi Cap',     risk: 'Moderate'   },
  { code: '135781', name: 'Quant Small Cap Fund',             category: 'Small Cap',     risk: 'Aggressive' },
  { code: '101206', name: 'Franklin India Prima Fund',        category: 'Mid Cap',       risk: 'Aggressive' },
  { code: '120828', name: 'Axis Long Term Equity',            category: 'ELSS',          risk: 'Moderate'   },
  { code: '118272', name: 'HDFC Index Nifty 50',              category: 'Index',         risk: 'Moderate'   },
  { code: '120685', name: 'UTI Nifty 50 Index Fund',          category: 'Index',         risk: 'Moderate'   },
  { code: '119775', name: 'SBI Bluechip Fund',                category: 'Large Cap',     risk: 'Moderate'   },
  { code: '118551', name: 'ICICI Pru Short Term Fund',        category: 'Debt',          risk: 'Conservative'},
];

const MFAPI = 'https://api.mfapi.in/mf';
const ANTHROPIC_API = 'https://api.anthropic.com/v1/messages';
const CLAUDE_MODEL = 'claude-sonnet-4-6';

// ─────────────────────────────────────────────────────────────
// MAIN REQUEST HANDLER
// ─────────────────────────────────────────────────────────────
export default {
  async fetch(request, env, ctx) {
    const url = new URL(request.url);
    const path = url.pathname;
    const method = request.method;

    // CORS headers
    const corsHeaders = {
      'Access-Control-Allow-Origin': '*',
      'Access-Control-Allow-Methods': 'GET, POST, PUT, DELETE, OPTIONS',
      'Access-Control-Allow-Headers': 'Content-Type, Authorization',
    };

    if (method === 'OPTIONS') {
      return new Response(null, { headers: corsHeaders });
    }

    try {
      // ── Public routes ──────────────────────────────────────
      if (path === '/' || path === '/index.html') {
        return htmlResponse(getHTML());
      }

      if (path === '/api/auth/login' && method === 'POST') {
        return handleLogin(request, env, corsHeaders);
      }

      // ── Protected routes (require auth token) ─────────────
      const authResult = await validateAuth(request, env);
      if (!authResult.ok) {
        return jsonResponse({ error: 'Unauthorized' }, 401, corsHeaders);
      }

      // Portfolio
      if (path === '/api/portfolio' && method === 'GET')    return getPortfolio(env, corsHeaders);
      if (path === '/api/portfolio' && method === 'POST')   return addHolding(request, env, corsHeaders);
      if (path.startsWith('/api/portfolio/') && method === 'DELETE') {
        const id = path.split('/').pop();
        return removeHolding(id, env, corsHeaders);
      }

      // Journal
      if (path === '/api/journal' && method === 'GET')   return getJournal(env, corsHeaders);
      if (path === '/api/journal' && method === 'POST')  return addJournalEntry(request, env, corsHeaders);

      // Fund data
      if (path === '/api/funds/search')                  return searchFunds(url, corsHeaders);
      if (path.startsWith('/api/funds/') && path.endsWith('/nav')) {
        const code = path.split('/')[3];
        return getFundNAV(code, corsHeaders);
      }

      // AI endpoints
      if (path === '/api/ai/scan'    && method === 'POST') return runAIScan(request, env, corsHeaders);
      if (path === '/api/ai/analyze' && method === 'POST') return analyzePortfolio(request, env, corsHeaders);
      if (path === '/api/ai/exit'    && method === 'POST') return exitAnalysis(request, env, corsHeaders);
      if (path === '/api/ai/journal' && method === 'POST') return analyzeJournal(request, env, corsHeaders);

      // Notifications
      if (path === '/api/notify/email' && method === 'POST') return sendEmail(request, env, corsHeaders);

      // Settings
      if (path === '/api/settings' && method === 'GET')  return getSettings(env, corsHeaders);
      if (path === '/api/settings' && method === 'POST') return saveSettings(request, env, corsHeaders);

      return jsonResponse({ error: 'Not found' }, 404, corsHeaders);

    } catch (err) {
      console.error('Worker error:', err);
      return jsonResponse({ error: err.message }, 500, corsHeaders);
    }
  },

  // Scheduled task — daily scan + email digest
  async scheduled(event, env, ctx) {
    ctx.waitUntil(dailyDigest(env));
  }
};

// ─────────────────────────────────────────────────────────────
// AUTH
// ─────────────────────────────────────────────────────────────
async function handleLogin(request, env, corsHeaders) {
  const { password } = await request.json();
  if (password !== env.APP_PASSWORD) {
    return jsonResponse({ error: 'Invalid password' }, 401, corsHeaders);
  }
  const token = await signToken({ user: 'adhyarvansh', ts: Date.now() }, env.SESSION_SECRET);
  return jsonResponse({ token, expiresIn: 86400 }, 200, corsHeaders);
}

async function validateAuth(request, env) {
  const auth = request.headers.get('Authorization') || '';
  const token = auth.replace('Bearer ', '');
  if (!token) return { ok: false };
  try {
    await verifyToken(token, env.SESSION_SECRET);
    return { ok: true };
  } catch {
    return { ok: false };
  }
}

async function signToken(payload, secret) {
  const header = btoa(JSON.stringify({ alg: 'HS256', typ: 'JWT' }));
  const body = btoa(JSON.stringify(payload));
  const sig = await hmacSign(`${header}.${body}`, secret);
  return `${header}.${body}.${sig}`;
}

async function verifyToken(token, secret) {
  const parts = token.split('.');
  if (parts.length !== 3) throw new Error('Invalid token');
  const sig = await hmacSign(`${parts[0]}.${parts[1]}`, secret);
  if (sig !== parts[2]) throw new Error('Invalid signature');
  const payload = JSON.parse(atob(parts[1]));
  if (Date.now() - payload.ts > 86400000) throw new Error('Token expired');
  return payload;
}

async function hmacSign(data, secret) {
  const key = await crypto.subtle.importKey(
    'raw', new TextEncoder().encode(secret),
    { name: 'HMAC', hash: 'SHA-256' }, false, ['sign']
  );
  const sig = await crypto.subtle.sign('HMAC', key, new TextEncoder().encode(data));
  return btoa(String.fromCharCode(...new Uint8Array(sig)));
}

// ─────────────────────────────────────────────────────────────
// PORTFOLIO — KV CRUD
// ─────────────────────────────────────────────────────────────
async function getPortfolio(env, corsHeaders) {
  const raw = await env.KV.get('portfolio');
  const holdings = raw ? JSON.parse(raw) : [];
  // Enrich with current NAV
  const enriched = await Promise.all(holdings.map(async (h) => {
    try {
      const nav = await fetchLatestNAV(h.schemeCode);
      const currentValue = nav * h.units;
      const pnl = currentValue - h.amountInvested;
      const pnlPct = ((pnl / h.amountInvested) * 100).toFixed(2);
      const daysSinceBuy = Math.floor((Date.now() - new Date(h.buyDate)) / 86400000);
      return { ...h, currentNAV: nav, currentValue, pnl, pnlPct, daysSinceBuy,
               taxType: daysSinceBuy >= 365 ? 'LTCG' : 'STCG' };
    } catch {
      return { ...h, currentNAV: h.buyNAV, currentValue: h.amountInvested, pnl: 0, pnlPct: '0.00' };
    }
  }));
  return jsonResponse(enriched, 200, corsHeaders);
}

async function addHolding(request, env, corsHeaders) {
  const body = await request.json();
  const { schemeCode, schemeName, amountInvested, units, buyDate, buyNAV, category } = body;
  if (!schemeCode || !amountInvested || !units || !buyDate) {
    return jsonResponse({ error: 'Missing required fields' }, 400, corsHeaders);
  }
  const raw = await env.KV.get('portfolio');
  const holdings = raw ? JSON.parse(raw) : [];
  const newHolding = {
    id: crypto.randomUUID(),
    schemeCode, schemeName, amountInvested: Number(amountInvested),
    units: Number(units), buyDate, buyNAV: Number(buyNAV || 0),
    category: category || 'Equity', addedAt: new Date().toISOString()
  };
  holdings.push(newHolding);
  await env.KV.put('portfolio', JSON.stringify(holdings));
  return jsonResponse(newHolding, 201, corsHeaders);
}

async function removeHolding(id, env, corsHeaders) {
  const raw = await env.KV.get('portfolio');
  const holdings = raw ? JSON.parse(raw) : [];
  const updated = holdings.filter(h => h.id !== id);
  await env.KV.put('portfolio', JSON.stringify(updated));
  return jsonResponse({ deleted: id }, 200, corsHeaders);
}

// ─────────────────────────────────────────────────────────────
// JOURNAL — KV CRUD
// ─────────────────────────────────────────────────────────────
async function getJournal(env, corsHeaders) {
  const raw = await env.KV.get('journal');
  const entries = raw ? JSON.parse(raw) : [];
  return jsonResponse(entries.reverse(), 200, corsHeaders);  // newest first
}

async function addJournalEntry(request, env, corsHeaders) {
  const body = await request.json();
  const { schemeCode, fundName, amount, sentiment, notes, entryType } = body;
  const raw = await env.KV.get('journal');
  const entries = raw ? JSON.parse(raw) : [];
  const entry = {
    id: crypto.randomUUID(),
    date: new Date().toISOString(),
    schemeCode, fundName, amount: Number(amount || 0),
    sentiment: sentiment || 'Neutral',   // Confident | Nervous | Optimistic | Neutral
    entryType: entryType || 'Buy',       // Buy | Sell | Review | Note
    notes: notes || '',
    aiValidated: false
  };
  entries.push(entry);
  await env.KV.put('journal', JSON.stringify(entries));
  return jsonResponse(entry, 201, corsHeaders);
}

// ─────────────────────────────────────────────────────────────
// MFAPI.IN — FUND DATA
// ─────────────────────────────────────────────────────────────
async function searchFunds(url, corsHeaders) {
  const q = url.searchParams.get('q') || '';
  if (q.length < 2) return jsonResponse([], 200, corsHeaders);
  const res = await fetch(`${MFAPI}/search?q=${encodeURIComponent(q)}`);
  if (!res.ok) return jsonResponse([], 200, corsHeaders);
  const data = await res.json();
  // Return top 10 results with scheme code & name
  const results = (data || []).slice(0, 10).map(f => ({
    schemeCode: f.schemeCode,
    schemeName: f.schemeName,
    fundHouse: f.fundHouse || '',
  }));
  return jsonResponse(results, 200, corsHeaders);
}

async function getFundNAV(code, corsHeaders) {
  const { nav, history, schemeName } = await fetchNAVHistory(code, 365);
  return jsonResponse({ schemeCode: code, schemeName, latestNAV: nav, history }, 200, corsHeaders);
}

async function fetchLatestNAV(code) {
  const res = await fetch(`${MFAPI}/${code}`);
  if (!res.ok) throw new Error('NAV fetch failed');
  const data = await res.json();
  return parseFloat(data.data?.[0]?.nav || '0');
}

async function fetchNAVHistory(code, days = 365) {
  const res = await fetch(`${MFAPI}/${code}`);
  if (!res.ok) throw new Error(`MFapi error for ${code}`);
  const data = await res.json();
  const history = (data.data || []).slice(0, days).map(d => ({
    date: d.date, nav: parseFloat(d.nav)
  }));
  return {
    schemeName: data.meta?.scheme_name || '',
    nav: history[0]?.nav || 0,
    history
  };
}

// Calculate fund metrics from NAV history
function calcMetrics(history) {
  if (!history || history.length < 2) return null;
  const latest = history[0].nav;
  const get = (n) => history[Math.min(n, history.length - 1)]?.nav;

  const r1m  = pctChange(latest, get(21));
  const r3m  = pctChange(latest, get(63));
  const r6m  = pctChange(latest, get(126));
  const r1y  = pctChange(latest, get(252));

  // Volatility: std dev of daily returns (annualised)
  const dailyReturns = history.slice(0, 60).map((d, i) => {
    if (i === history.length - 1) return 0;
    return (d.nav - history[i + 1].nav) / history[i + 1].nav;
  }).filter((_, i) => i < 59);
  const mean = dailyReturns.reduce((a, b) => a + b, 0) / dailyReturns.length;
  const variance = dailyReturns.reduce((a, b) => a + (b - mean) ** 2, 0) / dailyReturns.length;
  const volatility = (Math.sqrt(variance) * Math.sqrt(252) * 100).toFixed(2);

  // Simplified Sharpe (using 6.5% risk-free rate)
  const sharpe = r1y !== null ? ((r1y - 6.5) / parseFloat(volatility)).toFixed(2) : null;

  return { r1m, r3m, r6m, r1y, volatility: parseFloat(volatility), sharpe: parseFloat(sharpe) };
}

function pctChange(current, base) {
  if (!base || base === 0) return null;
  return parseFloat(((current - base) / base * 100).toFixed(2));
}

// ─────────────────────────────────────────────────────────────
// AI — DAILY SCAN (Top 20 Recommendations)
// ─────────────────────────────────────────────────────────────
async function runAIScan(request, env, corsHeaders) {
  // Check for cached scan (refresh every 4 hours)
  const cached = await env.KV.get('ai_scan_cache', { type: 'json' });
  if (cached && (Date.now() - cached.timestamp < 4 * 60 * 60 * 1000)) {
    return jsonResponse({ ...cached, fromCache: true }, 200, corsHeaders);
  }

  const body = await request.json().catch(() => ({}));
  const riskFilter = body.riskFilter || 'all'; // all | Aggressive | Moderate | Conservative

  const universe = riskFilter === 'all'
    ? SCAN_UNIVERSE
    : SCAN_UNIVERSE.filter(f => f.risk === riskFilter);

  // Fetch NAV data for all funds (with rate limiting)
  const fundData = [];
  for (const fund of universe) {
    try {
      const { history } = await fetchNAVHistory(fund.code, 380);
      const metrics = calcMetrics(history);
      if (metrics) {
        fundData.push({ ...fund, metrics, latestNAV: history[0]?.nav });
      }
    } catch (e) {
      console.warn(`Skip ${fund.code}: ${e.message}`);
    }
  }

  if (fundData.length === 0) {
    return jsonResponse({ error: 'No fund data available' }, 500, corsHeaders);
  }

  // Build data summary for Claude
  const fundSummary = fundData.map(f => ({
    name: f.name, category: f.category, risk: f.risk,
    r1m: f.metrics.r1m, r3m: f.metrics.r3m, r1y: f.metrics.r1y,
    volatility: f.metrics.volatility, sharpe: f.metrics.sharpe,
    nav: f.latestNAV
  }));

  const prompt = `You are an expert Indian mutual fund analyst. Analyze the following fund performance data and provide structured investment recommendations.

FUND PERFORMANCE DATA (returns are percentage):
${JSON.stringify(fundSummary, null, 2)}

Based on this data, provide:
1. Top 5 AGGRESSIVE picks (small/mid-cap with high momentum)
2. Top 5 MODERATE picks (large/flexi-cap with good risk-adjusted returns)  
3. Top 5 CONSERVATIVE picks (debt/hybrid with stability)

For each fund provide:
- "why": 2-sentence "Stitch Insight" explaining exactly why this fund is recommended (cite specific metric values)
- "idealDuration": recommended holding period with rationale
- "exitSignal": what data point would trigger an exit review
- "caution": any specific risk to watch
- "conviction": score 1-10

Rules:
- Only recommend funds from the provided data
- Cite actual metric values (e.g., "Sharpe ratio of 1.8 indicates superior risk-adjusted return")
- Be specific about Indian market context (Nifty 50, SEBI categories)
- Flag any fund with negative 3M return even if 1Y is positive

Respond ONLY with valid JSON in this exact structure:
{
  "scanDate": "YYYY-MM-DD",
  "marketContext": "2-sentence market overview",
  "aggressive": [...],
  "moderate": [...],
  "conservative": [...],
  "topPick": { "name": "...", "reason": "..." }
}

Each item in array: { "name": "...", "category": "...", "r1y": 0, "sharpe": 0, "why": "...", "idealDuration": "...", "exitSignal": "...", "caution": "...", "conviction": 0 }`;

  const aiResponse = await callClaude(prompt, env, 2000);
  const recommendations = parseJSON(aiResponse);

  // Merge with scheme codes for portfolio add functionality
  const codeMap = Object.fromEntries(SCAN_UNIVERSE.map(f => [f.name, f.code]));
  ['aggressive', 'moderate', 'conservative'].forEach(tier => {
    if (recommendations[tier]) {
      recommendations[tier] = recommendations[tier].map(f => ({
        ...f, schemeCode: codeMap[f.name] || null
      }));
    }
  });

  const result = { ...recommendations, timestamp: Date.now(), fundCount: fundData.length };
  await env.KV.put('ai_scan_cache', JSON.stringify(result));
  return jsonResponse(result, 200, corsHeaders);
}

// ─────────────────────────────────────────────────────────────
// AI — PORTFOLIO ANALYSIS
// ─────────────────────────────────────────────────────────────
async function analyzePortfolio(request, env, corsHeaders) {
  const body = await request.json();
  const { holdings } = body; // enriched portfolio from /api/portfolio

  if (!holdings || holdings.length === 0) {
    return jsonResponse({ error: 'No holdings to analyze' }, 400, corsHeaders);
  }

  const holdingsSummary = holdings.map(h => ({
    fund: h.schemeName, invested: h.amountInvested, currentValue: h.currentValue,
    pnlPct: h.pnlPct, daysSinceBuy: h.daysSinceBuy, taxType: h.taxType, category: h.category
  }));

  const totalInvested = holdings.reduce((s, h) => s + h.amountInvested, 0);
  const totalCurrent = holdings.reduce((s, h) => s + (h.currentValue || h.amountInvested), 0);
  const overallPnl = ((totalCurrent - totalInvested) / totalInvested * 100).toFixed(2);

  const prompt = `You are an expert Indian mutual fund portfolio auditor. Analyze this portfolio and provide actionable intelligence.

PORTFOLIO HOLDINGS:
${JSON.stringify(holdingsSummary, null, 2)}

PORTFOLIO SUMMARY:
- Total Invested: ₹${totalInvested.toLocaleString('en-IN')}
- Current Value: ₹${totalCurrent.toLocaleString('en-IN')}
- Overall P&L: ${overallPnl}%
- Number of funds: ${holdings.length}

Provide a comprehensive audit covering:
1. Portfolio concentration risk (fund overlap potential, sector exposure)
2. Tax harvest opportunities (LTCG vs STCG positions)
3. Rebalancing suggestions if equity/debt is off by >5%
4. Top 2 funds to review for exit
5. Behavioral observation (e.g., over-diversification, concentration in one category)
6. One-line portfolio health verdict

Respond ONLY with valid JSON:
{
  "healthScore": 0-100,
  "verdict": "one-line verdict",
  "overallPnl": "...",
  "concentration": { "risk": "Low|Medium|High", "detail": "..." },
  "taxHarvest": [{ "fund": "...", "action": "...", "saving": "..." }],
  "rebalance": { "needed": true/false, "suggestion": "..." },
  "exitReview": [{ "fund": "...", "reason": "...", "signal": "SELL|WATCH" }],
  "behavioral": "...",
  "suggestions": ["...","...","..."]
}`;

  const aiResponse = await callClaude(prompt, env, 1500);
  const analysis = parseJSON(aiResponse);
  return jsonResponse(analysis, 200, corsHeaders);
}

// ─────────────────────────────────────────────────────────────
// AI — EXIT ANALYSIS (Decision Matrix)
// ─────────────────────────────────────────────────────────────
async function exitAnalysis(request, env, corsHeaders) {
  const body = await request.json();
  const { holding, reason } = body;

  // Fetch current metrics for this fund
  let metrics = null;
  try {
    const { history } = await fetchNAVHistory(holding.schemeCode, 380);
    metrics = calcMetrics(history);
  } catch (e) {
    console.warn('NAV fetch for exit analysis failed:', e.message);
  }

  const prompt = `You are an expert Indian mutual fund analyst. Provide a complete exit decision matrix for this holding.

HOLDING DETAILS:
${JSON.stringify({ ...holding, metrics }, null, 2)}

USER'S EXIT REASON: "${reason || 'Not specified'}"

Evaluate using the 4-factor Exit Protocol:
1. PERFORMANCE: Is this fund in the bottom quartile of its category for 3M/1Y returns?
2. COST: Comment on typical expense ratio for this fund category (direct growth plans should be <0.5% for index, <1.5% for active)
3. TAX IMPACT: Calculate estimated STCG (15%) or LTCG (10% above ₹1L) on the profit
4. EXIT LOAD: Standard exit load rules (most equity funds: 1% if redeemed before 1 year)

Then validate the user's exit reason against market data — is it justified or emotional?

Respond ONLY with valid JSON:
{
  "decision": "SELL|HOLD|WATCH",
  "confidence": 0-100,
  "factors": {
    "performance": { "status": "Good|Concern|Poor", "detail": "..." },
    "cost": { "status": "Good|Concern|Poor", "detail": "..." },
    "taxImpact": { "type": "LTCG|STCG", "estimatedTax": 0, "detail": "..." },
    "exitLoad": { "applicable": true/false, "detail": "..." }
  },
  "reasonValidation": { "type": "Rational|Emotional|Mixed", "detail": "..." },
  "recommendation": "2-sentence final recommendation",
  "alternativeAction": "What to do instead if not selling"
}`;

  const aiResponse = await callClaude(prompt, env, 1200);
  const matrix = parseJSON(aiResponse);
  return jsonResponse(matrix, 200, corsHeaders);
}

// ─────────────────────────────────────────────────────────────
// AI — JOURNAL PATTERN ANALYSIS
// ─────────────────────────────────────────────────────────────
async function analyzeJournal(request, env, corsHeaders) {
  const raw = await env.KV.get('journal');
  const entries = raw ? JSON.parse(raw) : [];

  if (entries.length < 3) {
    return jsonResponse({ message: 'Log at least 3 journal entries for pattern analysis.' }, 200, corsHeaders);
  }

  const prompt = `You are a behavioral finance analyst. Analyze this investor's mutual fund journal for emotional patterns and biases.

JOURNAL ENTRIES (chronological):
${JSON.stringify(entries.slice(-30), null, 2)}

Identify:
1. Emotional biases (panic selling, FOMO buying, loss aversion, overconfidence)
2. Timing patterns (do they buy after market highs? sell after dips?)
3. Sentiment correlations (which sentiment leads to which action?)
4. Behavioral correction advice

Respond ONLY with valid JSON:
{
  "overallPattern": "...",
  "biases": [{ "bias": "...", "evidence": "...", "correction": "..." }],
  "timingBehavior": "...",
  "sentimentAnalysis": { "Confident": "...", "Nervous": "...", "Optimistic": "..." },
  "keyInsight": "one key behavioral insight",
  "actionableAdvice": ["...", "...", "..."]
}`;

  const aiResponse = await callClaude(prompt, env, 1000);
  const analysis = parseJSON(aiResponse);
  return jsonResponse(analysis, 200, corsHeaders);
}

// ─────────────────────────────────────────────────────────────
// SETTINGS
// ─────────────────────────────────────────────────────────────
async function getSettings(env, corsHeaders) {
  const raw = await env.KV.get('settings');
  const settings = raw ? JSON.parse(raw) : {
    name: 'Vikram Adhyarvansh', email: '', mobile: '',
    notifications: { warnings: true, goalProximity: true, taxHarvest: true, dailyDigest: true },
    riskProfile: 'Moderate'
  };
  return jsonResponse(settings, 200, corsHeaders);
}

async function saveSettings(request, env, corsHeaders) {
  const body = await request.json();
  await env.KV.put('settings', JSON.stringify(body));
  return jsonResponse({ saved: true }, 200, corsHeaders);
}

// ─────────────────────────────────────────────────────────────
// EMAIL — RESEND.COM
// ─────────────────────────────────────────────────────────────
async function sendEmail(request, env, corsHeaders) {
  const body = await request.json();
  const settingsRaw = await env.KV.get('settings');
  const settings = settingsRaw ? JSON.parse(settingsRaw) : {};
  const toEmail = body.email || settings.email;
  if (!toEmail) return jsonResponse({ error: 'No email configured' }, 400, corsHeaders);

  const res = await fetch('https://api.resend.com/emails', {
    method: 'POST',
    headers: {
      'Authorization': `Bearer ${env.RESEND_API_KEY}`,
      'Content-Type': 'application/json',
    },
    body: JSON.stringify({
      from: 'alerts@adhyarvansh.com',
      to: toEmail,
      subject: body.subject || 'Adhyarvansh Alert',
      html: body.html || `<p>${body.message}</p>`
    })
  });
  const result = await res.json();
  return jsonResponse(result, res.status, corsHeaders);
}

// ─────────────────────────────────────────────────────────────
// SCHEDULED DAILY DIGEST
// ─────────────────────────────────────────────────────────────
async function dailyDigest(env) {
  try {
    const settingsRaw = await env.KV.get('settings');
    const settings = settingsRaw ? JSON.parse(settingsRaw) : {};
    if (!settings.email || !settings.notifications?.dailyDigest) return;

    // Get portfolio
    const portfolioRaw = await env.KV.get('portfolio');
    const holdings = portfolioRaw ? JSON.parse(portfolioRaw) : [];

    // Check for triggers
    const alerts = [];
    for (const h of holdings) {
      try {
        const { history } = await fetchNAVHistory(h.schemeCode, 7);
        const current = history[0]?.nav;
        const week = history[6]?.nav;
        if (current && week) {
          const drop = ((current - week) / week * 100);
          if (drop < -5) alerts.push(`⚠️ ${h.schemeName}: NAV dropped ${drop.toFixed(1)}% this week`);
        }
        const days = Math.floor((Date.now() - new Date(h.buyDate)) / 86400000);
        if (days === 365) alerts.push(`🎯 ${h.schemeName}: Completes 1 year today — LTCG now applicable`);
      } catch { /* skip */ }
    }

    const html = `
      <div style="font-family:Inter,sans-serif;max-width:600px;margin:0 auto;">
        <div style="background:#001b44;color:white;padding:24px;border-radius:12px 12px 0 0;">
          <h1 style="margin:0;font-size:24px;">ADHYARVANSH Daily Brief</h1>
          <p style="margin:8px 0 0;opacity:0.6;">${new Date().toDateString()}</p>
        </div>
        <div style="background:#f7f9ff;padding:24px;">
          <h2 style="color:#001b44;margin-top:0;">Portfolio Summary</h2>
          <p>You have <strong>${holdings.length} active holdings</strong>.</p>
          ${alerts.length > 0 ? `<h3>🔔 Action Alerts</h3><ul>${alerts.map(a => `<li>${a}</li>`).join('')}</ul>` : '<p>✅ No critical alerts today.</p>'}
          <p>Visit <a href="https://adhyarvansh.com">adhyarvansh.com</a> for full AI recommendations.</p>
        </div>
      </div>`;

    await fetch('https://api.resend.com/emails', {
      method: 'POST',
      headers: { 'Authorization': `Bearer ${env.RESEND_API_KEY}`, 'Content-Type': 'application/json' },
      body: JSON.stringify({
        from: 'daily@adhyarvansh.com',
        to: settings.email,
        subject: `Adhyarvansh Daily Brief — ${new Date().toDateString()}`,
        html
      })
    });
  } catch (e) {
    console.error('Daily digest failed:', e);
  }
}

// ─────────────────────────────────────────────────────────────
// CLAUDE API HELPER
// ─────────────────────────────────────────────────────────────
async function callClaude(prompt, env, maxTokens = 1000) {
  const res = await fetch(ANTHROPIC_API, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      'x-api-key': env.ANTHROPIC_API_KEY,
      'anthropic-version': '2023-06-01',
    },
    body: JSON.stringify({
      model: CLAUDE_MODEL,
      max_tokens: maxTokens,
      messages: [{ role: 'user', content: prompt }]
    })
  });
  if (!res.ok) {
    const err = await res.text();
    throw new Error(`Claude API error: ${err}`);
  }
  const data = await res.json();
  return data.content?.[0]?.text || '';
}

// ─────────────────────────────────────────────────────────────
// UTILITIES
// ─────────────────────────────────────────────────────────────
function parseJSON(text) {
  // Strip markdown fences if present
  const clean = text.replace(/```json\n?/g, '').replace(/```\n?/g, '').trim();
  try {
    return JSON.parse(clean);
  } catch (e) {
    console.error('JSON parse failed:', clean.substring(0, 200));
    return { error: 'AI response parse failed', raw: clean.substring(0, 500) };
  }
}

function jsonResponse(data, status = 200, corsHeaders = {}) {
  return new Response(JSON.stringify(data), {
    status,
    headers: { 'Content-Type': 'application/json', ...corsHeaders }
  });
}

function htmlResponse(html) {
  return new Response(html, {
    headers: { 'Content-Type': 'text/html; charset=utf-8' }
  });
}
