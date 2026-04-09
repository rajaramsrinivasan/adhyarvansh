// frontend.js — exported as a function so worker.js can import it
export function getHTML() {
  return `<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1.0"/>
<title>ADHYARVANSH | Mutual Fund Intelligence</title>
<script src="https://cdn.tailwindcss.com?plugins=forms"></script>
<script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
<link href="https://fonts.googleapis.com/css2?family=Manrope:wght@400;600;700;800;900&family=Inter:wght@400;500;600;700&display=swap" rel="stylesheet"/>
<link href="https://fonts.googleapis.com/css2?family=Material+Symbols+Outlined:opsz,wght,FILL,GRAD@20..48,100..700,0..1,-50..200" rel="stylesheet"/>
<script>
tailwind.config = {
  theme: { extend: {
    colors: {
      "surface-container-low":"#ecf4ff","surface":"#f7f9ff","surface-bright":"#f7f9ff",
      "surface-container":"#e2efff","surface-container-high":"#d9eafc",
      "surface-container-highest":"#d4e4f6","surface-container-lowest":"#ffffff",
      "surface-dim":"#cbdcee","surface-variant":"#d4e4f6",
      "primary-container":"#001b44","on-primary":"#ffffff","on-primary-container":"#7084b3",
      "secondary":"#006d37","secondary-container":"#00fa85","on-secondary-container":"#006e37",
      "secondary-fixed":"#60ff99","secondary-fixed-dim":"#00e479",
      "on-surface":"#0d1d2a","on-surface-variant":"#44474f",
      "outline-variant":"#c5c6d0","error":"#ba1a1a","error-container":"#ffdad6",
      "on-tertiary-container":"#00984f",
    },
    fontFamily: { headline:["Manrope","sans-serif"], body:["Inter","sans-serif"] }
  }}
}
</script>
<style>
* { box-sizing:border-box; }
body { font-family:'Inter',sans-serif; background:#f7f9ff; color:#0d1d2a; }
h1,h2,h3,h4,h5 { font-family:'Manrope',sans-serif; }
.material-symbols-outlined { font-variation-settings:'FILL' 0,'wght' 400,'GRAD' 0,'opsz' 24; vertical-align:middle; line-height:1; }
.fi { font-variation-settings:'FILL' 1,'wght' 400,'GRAD' 0,'opsz' 24; }
.view { display:none; }
.view.active { display:block; animation:fadeIn .25s ease; }
@keyframes fadeIn { from { opacity:0; transform:translateY(6px); } to { opacity:1; transform:translateY(0); } }
.nav-link { transition:all .2s ease; }
.nav-link.active { background:#fff; color:#001b44; transform:translateX(4px); box-shadow:0 2px 12px rgba(0,27,68,.08); }
.nav-link:not(.active):hover { background:#f7f9ff; color:#001b44; }
.shadow-card { box-shadow:0 4px 20px rgba(0,27,68,.04); }
.shadow-hero { box-shadow:0 10px 40px rgba(0,27,68,.10); }
.glass-card { background:rgba(212,228,246,.60); backdrop-filter:blur(24px); }
.ghost-border { border:1px solid rgba(197,198,208,.20); }
::-webkit-scrollbar { width:4px; height:4px; }
::-webkit-scrollbar-thumb { background:rgba(0,27,68,.15); border-radius:2px; }
@keyframes spin { to { transform:rotate(360deg); } }
.spinner { animation:spin 1s linear infinite; }
@keyframes pulse-glow { 0%,100%{box-shadow:0 0 0 0 rgba(0,250,133,.4);} 50%{box-shadow:0 0 0 8px rgba(0,250,133,0);} }
.sparkle-pulse { animation:pulse-glow 2.5s ease-in-out infinite; }
.chip-hold { background:rgba(0,250,133,.18); color:#006d37; }
.chip-watch { background:rgba(203,220,238,.6); color:#44474f; }
.chip-sell { background:rgba(186,26,26,.12); color:#ba1a1a; }
.loading-overlay { display:none; position:fixed; inset:0; background:rgba(247,249,255,.8); backdrop-filter:blur(4px); z-index:100; align-items:center; justify-content:center; flex-direction:column; gap:12px; }
.loading-overlay.active { display:flex; }
input[type=range] { accent-color:#001b44; }
.toast { position:fixed; bottom:24px; left:50%; transform:translateX(-50%); background:#001b44; color:white; padding:12px 24px; border-radius:12px; font-size:13px; font-weight:600; z-index:200; opacity:0; transition:opacity .3s; pointer-events:none; }
.toast.show { opacity:1; }
</style>
</head>
<body class="min-h-screen">

<!-- Loading overlay -->
<div id="loadingOverlay" class="loading-overlay">
  <svg class="spinner w-8 h-8 text-primary-container" viewBox="0 0 24 24" fill="none">
    <circle cx="12" cy="12" r="10" stroke="currentColor" stroke-width="2" opacity=".2"/>
    <path d="M12 2a10 10 0 0 1 10 10" stroke="currentColor" stroke-width="2" stroke-linecap="round"/>
  </svg>
  <p id="loadingMsg" class="text-sm font-semibold text-on-surface-variant">Loading…</p>
</div>

<!-- Toast -->
<div id="toast" class="toast"></div>

<!-- ═══════════════════════════════════════════════════
     LOGIN SCREEN
════════════════════════════════════════════════════ -->
<div id="loginScreen" class="min-h-screen flex items-center justify-center" style="background:linear-gradient(135deg,#001b44 0%,#00020a 100%);">
  <div class="w-full max-w-sm mx-4">
    <div class="text-center mb-10">
      <div class="w-16 h-16 bg-secondary-container rounded-2xl flex items-center justify-center mx-auto mb-4">
        <span class="material-symbols-outlined fi text-3xl" style="color:#001b44;">account_balance_wallet</span>
      </div>
      <h1 class="text-3xl font-headline font-black text-white tracking-tight">ADHYARVANSH</h1>
      <p class="text-white/50 text-sm mt-1">Mutual Fund Intelligence</p>
    </div>
    <div class="bg-white/5 backdrop-blur-xl rounded-2xl p-8" style="border:1px solid rgba(255,255,255,.1);">
      <label class="block text-white/60 text-xs font-black uppercase tracking-widest mb-2">Password</label>
      <input id="loginPassword" type="password" placeholder="Enter your password"
             class="w-full bg-white/10 border-none rounded-xl px-4 py-3.5 text-white placeholder-white/30 focus:ring-2 focus:ring-secondary-container mb-5"
             onkeydown="if(event.key==='Enter')doLogin()"/>
      <button onclick="doLogin()"
              class="w-full py-3.5 rounded-xl font-black text-sm uppercase tracking-wider"
              style="background:linear-gradient(135deg,#00fa85,#00e479);color:#001b44;">
        Access Portfolio
      </button>
      <p id="loginError" class="text-error text-xs mt-3 text-center hidden">Invalid password. Please try again.</p>
    </div>
  </div>
</div>

<!-- ═══════════════════════════════════════════════════
     MAIN APP (hidden until login)
════════════════════════════════════════════════════ -->
<div id="mainApp" class="hidden flex min-h-screen">

  <!-- SIDEBAR -->
  <aside style="width:256px;min-height:100vh;position:fixed;top:0;left:0;background:#ecf4ff;box-shadow:10px 0 40px rgba(0,27,68,.04);z-index:50;display:flex;flex-direction:column;padding:24px;gap:20px;">
    <div>
      <div class="w-10 h-10 bg-primary-container rounded-xl flex items-center justify-center mb-3">
        <span class="material-symbols-outlined fi text-white text-lg">account_balance_wallet</span>
      </div>
      <h1 class="font-headline font-black text-on-surface text-lg tracking-tighter leading-none">ADHYARVANSH</h1>
      <p class="text-[10px] font-black uppercase tracking-[.18em] text-on-surface opacity-40 mt-0.5">Private Banking Tier</p>
    </div>
    <nav class="flex flex-col gap-1.5 flex-grow">
      <a href="#" class="nav-link active flex items-center gap-3 px-4 py-3 rounded-xl font-semibold text-sm"
         onclick="navigate('dashboard',this);return false;">
        <span class="material-symbols-outlined fi">grid_view</span> Executive Dashboard
      </a>
      <a href="#" class="nav-link flex items-center gap-3 px-4 py-3 rounded-xl font-medium text-sm text-on-surface opacity-70"
         onclick="navigate('journal',this);return false;">
        <span class="material-symbols-outlined">auto_stories</span> Trade Journal
      </a>
      <a href="#" class="nav-link flex items-center gap-3 px-4 py-3 rounded-xl font-medium text-sm text-on-surface opacity-70"
         onclick="navigate('discovery',this);return false;">
        <span class="material-symbols-outlined">explore</span> AI Discovery
      </a>
      <a href="#" class="nav-link flex items-center gap-3 px-4 py-3 rounded-xl font-medium text-sm text-on-surface opacity-70"
         onclick="navigate('profile',this);return false;">
        <span class="material-symbols-outlined">account_circle</span> Profile & Sovereignty
      </a>
    </nav>
    <div class="flex flex-col gap-2 border-t border-primary-container/5 pt-4">
      <a href="#" class="flex items-center gap-3 px-4 py-2 text-on-surface/60 hover:text-primary-container text-sm transition-colors rounded-lg hover:bg-surface-bright"
         onclick="navigate('profile',document.querySelector('.nav-link:last-of-type'));return false;">
        <span class="material-symbols-outlined text-[18px]">settings</span> Settings
      </a>
      <a href="#" onclick="doLogout();return false;"
         class="flex items-center gap-3 px-4 py-2 text-on-surface/60 hover:text-error text-sm transition-colors rounded-lg">
        <span class="material-symbols-outlined text-[18px]">logout</span> Sign Out
      </a>
    </div>
  </aside>

  <!-- MAIN CONTENT -->
  <main style="margin-left:256px;flex:1;min-height:100vh;background:#f7f9ff;">

    <!-- TOPBAR -->
    <header class="sticky top-0 z-40 flex justify-between items-center px-8 h-16 bg-surface-bright/90 backdrop-blur-xl"
            style="box-shadow:0 1px 0 rgba(0,27,68,.06);">
      <div class="flex items-center gap-4">
        <div class="relative">
          <span class="material-symbols-outlined absolute left-3 top-1/2 -translate-y-1/2 text-on-surface/30 text-[18px]">search</span>
          <input type="text" placeholder="Search mutual funds…" id="fundSearchInput"
                 class="bg-surface-container-low border-none rounded-xl pl-10 pr-4 py-2 text-sm w-64 focus:ring-2 focus:ring-primary-container/20"
                 oninput="onFundSearch(this.value)"/>
          <div id="fundSearchResults" class="hidden absolute top-full left-0 mt-2 w-80 bg-white rounded-xl shadow-hero z-50 overflow-hidden max-h-64 overflow-y-auto"></div>
        </div>
      </div>
      <div class="flex items-center gap-3">
        <div class="hidden sm:flex items-center gap-2 bg-secondary-container/15 px-3 py-1.5 rounded-full">
          <span class="w-2 h-2 rounded-full bg-secondary-container animate-pulse"></span>
          <span class="text-[10px] font-black text-secondary uppercase tracking-widest">AI Live</span>
        </div>
        <button onclick="sendDailyBrief()" title="Send Daily Brief Email"
                class="relative p-2 rounded-xl hover:bg-surface-container-low transition-colors text-primary-container">
          <span class="material-symbols-outlined">notifications</span>
        </button>
        <div class="w-9 h-9 rounded-full bg-primary-container flex items-center justify-center text-white font-bold text-sm cursor-pointer">VA</div>
      </div>
    </header>

    <!-- ════════════════════════
         DASHBOARD VIEW
    ════════════════════════════ -->
    <div id="view-dashboard" class="view active px-8 py-8 max-w-7xl mx-auto space-y-8">
      <div class="flex justify-between items-start">
        <div>
          <p class="text-[10px] font-black uppercase tracking-[.2em] text-on-surface/40 mb-1">Good morning</p>
          <h2 class="text-3xl font-headline font-black text-primary-container tracking-tight">Executive Dashboard</h2>
          <p id="dashboardDate" class="text-sm text-on-surface/60 mt-1">Loading portfolio…</p>
        </div>
        <div class="flex gap-3">
          <button onclick="refreshPortfolio()"
                  class="px-4 py-2 rounded-xl bg-surface-container-low text-on-surface text-xs font-bold hover:bg-surface-container transition-colors flex items-center gap-2">
            <span class="material-symbols-outlined text-[16px]">refresh</span> Refresh
          </button>
          <button onclick="exportPortfolioCSV()"
                  class="px-4 py-2 rounded-xl bg-primary-container text-white text-xs font-bold flex items-center gap-2">
            <span class="material-symbols-outlined text-[16px]">download</span> Export CSV
          </button>
        </div>
      </div>

      <!-- KPI Banner -->
      <section class="grid grid-cols-1 md:grid-cols-3 gap-5">
        <div class="bg-surface-container-lowest rounded-xl p-6 shadow-card">
          <div class="flex justify-between items-start mb-4">
            <span class="text-[10px] font-black uppercase tracking-[.18em] text-on-surface/50">Total Invested</span>
            <span class="material-symbols-outlined text-primary-container bg-surface-container-low p-2 rounded-lg text-[18px]">account_balance</span>
          </div>
          <h2 id="kpiInvested" class="text-4xl font-headline font-black text-primary-container tracking-tight">₹—</h2>
          <p id="kpiInvestedNote" class="text-xs text-secondary font-semibold mt-2">Loading…</p>
        </div>
        <div class="bg-primary-container rounded-xl p-6 shadow-hero text-white relative overflow-hidden">
          <div class="absolute -right-6 -bottom-6 w-32 h-32 bg-secondary-container/10 rounded-full blur-3xl"></div>
          <div class="relative z-10">
            <div class="flex justify-between items-start mb-4">
              <span class="text-[10px] font-black uppercase tracking-[.18em] text-white/50">Current Value & P&L</span>
              <span class="material-symbols-outlined fi text-secondary-container bg-white/10 p-2 rounded-lg text-[18px]">payments</span>
            </div>
            <h2 id="kpiValue" class="text-4xl font-headline font-black tracking-tight">₹—</h2>
            <p id="kpiPnl" class="text-xs text-secondary-container font-semibold mt-2">—</p>
          </div>
        </div>
        <div class="bg-surface-container-lowest rounded-xl p-6 shadow-card">
          <div class="flex justify-between items-start mb-4">
            <span class="text-[10px] font-black uppercase tracking-[.18em] text-on-surface/50">Overall Return %</span>
            <span class="material-symbols-outlined text-primary-container bg-surface-container-low p-2 rounded-lg text-[18px]">pie_chart</span>
          </div>
          <h2 id="kpiReturn" class="text-4xl font-headline font-black text-primary-container tracking-tight">—%</h2>
          <p id="kpiReturnNote" class="text-xs text-on-surface/50 mt-2">—</p>
        </div>
      </section>

      <!-- AI Portfolio Audit -->
      <section>
        <div class="flex justify-between items-center mb-4">
          <h3 class="text-lg font-headline font-bold text-primary-container">AI Portfolio Audit</h3>
          <button onclick="runPortfolioAnalysis()"
                  class="bg-secondary-container text-on-secondary-container px-4 py-2 rounded-xl text-xs font-black uppercase tracking-wider flex items-center gap-2 hover:brightness-95 sparkle-pulse">
            <span class="material-symbols-outlined fi text-[16px]">colors_spark</span> Run AI Audit
          </button>
        </div>
        <div id="aiAuditResult" class="hidden bg-surface-container-lowest rounded-xl p-6 shadow-card space-y-4">
          <div class="flex justify-between items-center">
            <div>
              <p class="text-[10px] font-black uppercase tracking-widest text-on-surface-variant">Portfolio Health Score</p>
              <p id="auditScore" class="text-4xl font-headline font-black text-primary-container mt-1">—</p>
            </div>
            <div id="auditVerdict" class="text-sm text-on-surface/70 max-w-xs text-right italic"></div>
          </div>
          <div id="auditDetails" class="grid grid-cols-1 md:grid-cols-2 gap-4"></div>
          <div id="auditSuggestions" class="space-y-2"></div>
        </div>
      </section>

      <!-- Holdings Table -->
      <section>
        <div class="flex justify-between items-center mb-4">
          <h3 class="text-lg font-headline font-bold text-primary-container">Current Holdings</h3>
          <button onclick="openAddHoldingModal()"
                  class="bg-surface-container-low px-4 py-2 rounded-xl text-xs font-bold text-primary-container hover:bg-surface-container transition-colors flex items-center gap-2">
            <span class="material-symbols-outlined text-[16px]">add</span> Add Holding
          </button>
        </div>
        <div class="bg-surface-container-lowest rounded-xl shadow-card overflow-hidden">
          <div id="holdingsTable">
            <div class="p-12 text-center text-on-surface/40">
              <span class="material-symbols-outlined text-4xl block mb-3">account_balance</span>
              <p class="font-semibold">No holdings yet. Add your first mutual fund.</p>
              <button onclick="openAddHoldingModal()" class="mt-4 px-6 py-2 bg-primary-container text-white rounded-xl text-sm font-bold">
                Add First Holding
              </button>
            </div>
          </div>
        </div>
      </section>

      <!-- NAV Chart (shown when a holding is selected) -->
      <section id="navChartSection" class="hidden bg-surface-container-lowest rounded-xl p-6 shadow-card">
        <h3 id="navChartTitle" class="text-lg font-headline font-bold text-primary-container mb-4">NAV Chart</h3>
        <div style="position:relative;height:220px;"><canvas id="navChart"></canvas></div>
      </section>
    </div>

    <!-- ════════════════════════
         JOURNAL VIEW
    ════════════════════════════ -->
    <div id="view-journal" class="view px-8 py-8 max-w-7xl mx-auto space-y-8">
      <div class="flex justify-between items-center">
        <div>
          <h2 class="text-3xl font-headline font-black text-primary-container tracking-tight">Trade Journal</h2>
          <p class="text-sm text-on-surface/60 mt-1">Behavioral tracking & exit decision matrix</p>
        </div>
        <div class="flex gap-3">
          <button onclick="runJournalAI()"
                  class="bg-secondary-container text-on-secondary-container px-4 py-2 rounded-xl text-xs font-black uppercase tracking-wider flex items-center gap-2 sparkle-pulse">
            <span class="material-symbols-outlined fi text-[16px]">colors_spark</span> AI Pattern Analysis
          </button>
          <button onclick="exportJournalCSV()"
                  class="bg-primary-container text-white px-4 py-2 rounded-xl text-xs font-bold flex items-center gap-2">
            <span class="material-symbols-outlined text-[16px]">download</span> Export
          </button>
        </div>
      </div>

      <!-- AI Journal Analysis Result -->
      <div id="journalAIResult" class="hidden bg-surface-container-lowest rounded-xl p-6 shadow-card">
        <div class="flex items-center gap-3 mb-4">
          <span class="bg-secondary-container text-on-secondary-container text-[10px] font-black px-3 py-1 rounded-full flex items-center gap-1">
            <span class="material-symbols-outlined fi text-[11px]">colors_spark</span> AI Behavioral Analysis
          </span>
        </div>
        <div id="journalAIContent" class="space-y-4"></div>
      </div>

      <!-- Add Journal Entry -->
      <div class="bg-surface-container-low rounded-xl p-6">
        <h3 class="text-sm font-black uppercase tracking-widest text-on-surface-variant mb-4">Log New Entry</h3>
        <div class="grid grid-cols-2 md:grid-cols-4 gap-4 mb-4">
          <div>
            <label class="text-[10px] font-black uppercase tracking-widest text-on-surface/50 block mb-2">Fund Name</label>
            <input id="jFundName" type="text" placeholder="e.g. Axis Small Cap"
                   class="w-full bg-white border-none rounded-xl px-4 py-3 text-sm focus:ring-2 focus:ring-primary-container/20"/>
          </div>
          <div>
            <label class="text-[10px] font-black uppercase tracking-widest text-on-surface/50 block mb-2">Amount (₹)</label>
            <input id="jAmount" type="number" placeholder="50000"
                   class="w-full bg-white border-none rounded-xl px-4 py-3 text-sm focus:ring-2 focus:ring-primary-container/20"/>
          </div>
          <div>
            <label class="text-[10px] font-black uppercase tracking-widest text-on-surface/50 block mb-2">Action Type</label>
            <select id="jType" class="w-full bg-white border-none rounded-xl px-4 py-3 text-sm focus:ring-2 focus:ring-primary-container/20">
              <option value="Buy">Buy</option>
              <option value="Sell">Sell</option>
              <option value="Review">Review</option>
              <option value="Note">Note</option>
            </select>
          </div>
          <div>
            <label class="text-[10px] font-black uppercase tracking-widest text-on-surface/50 block mb-2">Sentiment</label>
            <select id="jSentiment" class="w-full bg-white border-none rounded-xl px-4 py-3 text-sm focus:ring-2 focus:ring-primary-container/20">
              <option value="Confident">Confident</option>
              <option value="Optimistic">Optimistic</option>
              <option value="Nervous">Nervous</option>
              <option value="Neutral">Neutral</option>
            </select>
          </div>
        </div>
        <div class="mb-4">
          <label class="text-[10px] font-black uppercase tracking-widest text-on-surface/50 block mb-2">Notes / Rationale</label>
          <textarea id="jNotes" rows="2" placeholder="Why are you making this decision? Be honest…"
                    class="w-full bg-white border-none rounded-xl px-4 py-3 text-sm focus:ring-2 focus:ring-primary-container/20 resize-none"></textarea>
        </div>
        <button onclick="addJournalEntry()"
                class="bg-primary-container text-white px-6 py-2.5 rounded-xl text-xs font-black uppercase tracking-wider hover:opacity-90">
          Log Entry
        </button>
      </div>

      <!-- Journal Entries -->
      <div>
        <h3 class="text-sm font-black uppercase tracking-widest text-on-surface-variant mb-4">Journal Entries</h3>
        <div id="journalEntries" class="space-y-3">
          <div class="p-8 text-center text-on-surface/40 bg-surface-container-lowest rounded-xl shadow-card">
            <span class="material-symbols-outlined text-3xl block mb-2">auto_stories</span>
            <p class="font-semibold text-sm">No journal entries yet. Start logging your decisions.</p>
          </div>
        </div>
      </div>
    </div>

    <!-- ════════════════════════
         AI DISCOVERY VIEW
    ════════════════════════════ -->
    <div id="view-discovery" class="view px-8 py-8 max-w-7xl mx-auto space-y-8">
      <div class="flex justify-between items-start">
        <div>
          <p class="text-[10px] font-black uppercase tracking-[.2em] text-on-surface/40 mb-1">Real-time AI Recommendations</p>
          <h2 class="text-3xl font-headline font-black text-primary-container tracking-tight">AI Discovery</h2>
          <p class="text-sm text-on-surface/60 mt-1">Daily scan of AMFI-registered funds via MFapi.in · Powered by Claude</p>
        </div>
        <div class="flex gap-3 items-start">
          <select id="riskFilter" class="bg-surface-container-low border-none rounded-xl px-4 py-2.5 text-xs font-bold focus:ring-2 focus:ring-primary-container/20">
            <option value="all">All Risk Profiles</option>
            <option value="Aggressive">Aggressive</option>
            <option value="Moderate">Moderate</option>
            <option value="Conservative">Conservative</option>
          </select>
          <button onclick="runScan()"
                  class="bg-secondary-container text-on-secondary-container px-5 py-2.5 rounded-xl text-xs font-black uppercase tracking-wider flex items-center gap-2 sparkle-pulse hover:brightness-95">
            <span class="material-symbols-outlined fi text-[16px]">colors_spark</span> Run AI Scan
          </button>
        </div>
      </div>

      <!-- Scan Status -->
      <div id="scanStatus" class="hidden bg-surface-container-low rounded-xl p-4 text-sm text-on-surface-variant flex items-center gap-3">
        <svg class="spinner w-4 h-4 text-secondary shrink-0" viewBox="0 0 24 24" fill="none">
          <circle cx="12" cy="12" r="10" stroke="currentColor" stroke-width="2" opacity=".2"/>
          <path d="M12 2a10 10 0 0 1 10 10" stroke="currentColor" stroke-width="2" stroke-linecap="round"/>
        </svg>
        <span id="scanStatusText">Fetching NAV data for 20 funds from MFapi.in…</span>
      </div>

      <!-- Market Context -->
      <div id="marketContext" class="hidden bg-primary-container text-white rounded-xl p-5 relative overflow-hidden">
        <div class="absolute -right-6 -bottom-6 w-40 h-40 bg-secondary-container/8 rounded-full blur-3xl"></div>
        <div class="relative z-10 flex justify-between items-start">
          <div>
            <p class="text-[10px] font-black uppercase tracking-widest text-white/50 mb-1">AI Market Context</p>
            <p id="marketContextText" class="text-sm text-white/90 max-w-lg"></p>
          </div>
          <div class="shrink-0 ml-6 text-right">
            <p class="text-[10px] font-black uppercase tracking-widest text-white/50">Top AI Pick</p>
            <p id="topPickName" class="font-headline font-bold text-secondary-container text-sm mt-0.5"></p>
            <p id="topPickReason" class="text-[10px] text-white/60 mt-0.5 max-w-[180px]"></p>
          </div>
        </div>
      </div>

      <!-- Recommendation Tiers -->
      <div class="grid grid-cols-1 lg:grid-cols-3 gap-6">
        <div>
          <div class="flex items-center gap-2 mb-4">
            <span class="w-2.5 h-2.5 rounded-full bg-error"></span>
            <h3 class="text-[10px] font-black uppercase tracking-[.15em] text-on-surface/70">Aggressive Picks</h3>
            <span class="text-[10px] text-on-surface/40">Small/Mid Cap</span>
          </div>
          <div id="aggressiveFunds" class="space-y-3">
            <div class="p-5 bg-surface-container-low rounded-xl text-center text-sm text-on-surface/40">Run AI Scan to load picks</div>
          </div>
        </div>
        <div>
          <div class="flex items-center gap-2 mb-4">
            <span class="w-2.5 h-2.5 rounded-full bg-secondary"></span>
            <h3 class="text-[10px] font-black uppercase tracking-[.15em] text-on-surface/70">Moderate Picks</h3>
            <span class="text-[10px] text-on-surface/40">Large/Flexi Cap</span>
          </div>
          <div id="moderateFunds" class="space-y-3">
            <div class="p-5 bg-surface-container-low rounded-xl text-center text-sm text-on-surface/40">Run AI Scan to load picks</div>
          </div>
        </div>
        <div>
          <div class="flex items-center gap-2 mb-4">
            <span class="w-2.5 h-2.5 rounded-full bg-primary-container/40"></span>
            <h3 class="text-[10px] font-black uppercase tracking-[.15em] text-on-surface/70">Conservative Picks</h3>
            <span class="text-[10px] text-on-surface/40">Debt/Hybrid</span>
          </div>
          <div id="conservativeFunds" class="space-y-3">
            <div class="p-5 bg-surface-container-low rounded-xl text-center text-sm text-on-surface/40">Run AI Scan to load picks</div>
          </div>
        </div>
      </div>

      <!-- Exit Check Tool -->
      <div class="bg-surface-container-lowest rounded-xl p-6 shadow-card">
        <h3 class="text-lg font-headline font-bold text-primary-container mb-5">Exit Decision Matrix</h3>
        <p class="text-sm text-on-surface/60 mb-5">Select a holding and enter your reason to get an AI-powered exit analysis.</p>
        <div class="grid grid-cols-1 md:grid-cols-3 gap-4 mb-4">
          <div class="md:col-span-2">
            <label class="text-[10px] font-black uppercase tracking-widest text-on-surface/50 block mb-2">Select Holding</label>
            <select id="exitHoldingSelect" class="w-full bg-surface-container-low border-none rounded-xl px-4 py-3 text-sm focus:ring-2 focus:ring-primary-container/20">
              <option value="">— Choose a fund from your portfolio —</option>
            </select>
          </div>
          <div>
            <label class="text-[10px] font-black uppercase tracking-widest text-on-surface/50 block mb-2">Exit Reason</label>
            <input id="exitReason" type="text" placeholder="e.g. NAV dropped, fund manager changed"
                   class="w-full bg-surface-container-low border-none rounded-xl px-4 py-3 text-sm focus:ring-2 focus:ring-primary-container/20"/>
          </div>
        </div>
        <button onclick="runExitAnalysis()"
                class="bg-primary-container text-white px-6 py-2.5 rounded-xl text-xs font-black uppercase tracking-wider flex items-center gap-2 hover:opacity-90">
          <span class="material-symbols-outlined fi text-[16px]">colors_spark</span> Analyze Exit
        </button>
        <div id="exitMatrixResult" class="hidden mt-6 space-y-4"></div>
      </div>
    </div>

    <!-- ════════════════════════
         PROFILE VIEW
    ════════════════════════════ -->
    <div id="view-profile" class="view px-8 py-8 max-w-5xl mx-auto space-y-8">
      <div>
        <h2 class="text-3xl font-headline font-black text-primary-container tracking-tight">Profile & Sovereignty</h2>
        <p class="text-sm text-on-surface/60 mt-1">Settings, notifications, and data control</p>
      </div>
      <div class="grid grid-cols-12 gap-8">
        <!-- Settings form -->
        <div class="col-span-12 lg:col-span-7">
          <div class="bg-surface-container-lowest rounded-xl p-8 shadow-card space-y-6">
            <h3 class="text-lg font-headline font-bold text-primary-container">Account Settings</h3>
            <div class="grid grid-cols-2 gap-5">
              <div>
                <label class="text-[10px] font-black uppercase tracking-widest text-on-surface/50 block mb-2">Full Name</label>
                <input id="settingName" type="text" class="w-full bg-surface-container-low border-none rounded-xl px-4 py-3.5 text-sm focus:ring-2 focus:ring-primary-container/20"/>
              </div>
              <div>
                <label class="text-[10px] font-black uppercase tracking-widest text-on-surface/50 block mb-2">Risk Profile</label>
                <select id="settingRisk" class="w-full bg-surface-container-low border-none rounded-xl px-4 py-3.5 text-sm focus:ring-2 focus:ring-primary-container/20">
                  <option value="Conservative">Conservative</option>
                  <option value="Moderate">Moderate</option>
                  <option value="Aggressive">Aggressive</option>
                </select>
              </div>
            </div>
            <div>
              <label class="text-[10px] font-black uppercase tracking-widest text-on-surface/50 block mb-2">Email (for alerts)</label>
              <input id="settingEmail" type="email" placeholder="you@example.com"
                     class="w-full bg-surface-container-low border-none rounded-xl px-4 py-3.5 text-sm focus:ring-2 focus:ring-primary-container/20"/>
            </div>
            <div>
              <label class="text-[10px] font-black uppercase tracking-widest text-on-surface/50 block mb-2">Mobile (WhatsApp)</label>
              <input id="settingMobile" type="tel" placeholder="+91 98200 00000"
                     class="w-full bg-surface-container-low border-none rounded-xl px-4 py-3.5 text-sm focus:ring-2 focus:ring-primary-container/20"/>
            </div>
            <div class="pt-2">
              <h4 class="text-xs font-black uppercase tracking-widest text-on-surface-variant mb-4">Notification Triggers</h4>
              <div class="space-y-3">
                <label class="flex items-center justify-between p-3 bg-surface-container-low rounded-xl cursor-pointer">
                  <span class="text-sm font-medium">Daily Morning Digest (Email)</span>
                  <input id="notifDigest" type="checkbox" checked class="rounded" style="accent-color:#001b44;width:16px;height:16px;"/>
                </label>
                <label class="flex items-center justify-between p-3 bg-surface-container-low rounded-xl cursor-pointer">
                  <span class="text-sm font-medium">NAV Drop &gt;5% Warning</span>
                  <input id="notifWarning" type="checkbox" checked class="rounded" style="accent-color:#001b44;width:16px;height:16px;"/>
                </label>
                <label class="flex items-center justify-between p-3 bg-surface-container-low rounded-xl cursor-pointer">
                  <span class="text-sm font-medium">Goal Proximity Alert</span>
                  <input id="notifGoal" type="checkbox" checked class="rounded" style="accent-color:#001b44;width:16px;height:16px;"/>
                </label>
                <label class="flex items-center justify-between p-3 bg-surface-container-low rounded-xl cursor-pointer">
                  <span class="text-sm font-medium">1-Year LTCG Tax Harvest Alert</span>
                  <input id="notifTax" type="checkbox" checked class="rounded" style="accent-color:#001b44;width:16px;height:16px;"/>
                </label>
              </div>
            </div>
            <button onclick="saveSettings()"
                    class="w-full py-3.5 rounded-xl font-black text-sm text-white tracking-wide"
                    style="background:linear-gradient(135deg,#001b44,#00020a);">
              Save Settings
            </button>
          </div>
        </div>

        <!-- Sovereignty -->
        <div class="col-span-12 lg:col-span-5 space-y-5">
          <div class="rounded-xl p-8 text-white relative overflow-hidden"
               style="background:radial-gradient(ellipse at top right,rgba(0,250,133,.08),transparent 60%),linear-gradient(135deg,#001b44,#00020a);">
            <div class="flex items-center gap-2 mb-4">
              <span class="material-symbols-outlined fi text-secondary-fixed text-xl">shield_person</span>
              <h3 class="text-lg font-headline font-bold">Data Sovereignty</h3>
            </div>
            <p class="text-white/60 text-sm leading-relaxed mb-6">
              You maintain complete ownership. Export your complete trade intelligence at any time.
            </p>
            <div class="space-y-3">
              <button onclick="exportPortfolioCSV()"
                      class="flex items-center justify-between w-full bg-white/5 p-4 rounded-xl hover:bg-white/10 transition-all group"
                      style="border:1px solid rgba(255,255,255,.1);">
                <div>
                  <p class="font-bold text-sm">Portfolio Export</p>
                  <p class="text-[10px] text-white/50 uppercase tracking-widest">CSV · Full Ledger</p>
                </div>
                <span class="material-symbols-outlined text-secondary-fixed group-hover:translate-x-1 transition-transform">download</span>
              </button>
              <button onclick="exportJournalCSV()"
                      class="flex items-center justify-between w-full bg-white/5 p-4 rounded-xl hover:bg-white/10 transition-all group"
                      style="border:1px solid rgba(255,255,255,.1);">
                <div>
                  <p class="font-bold text-sm">Journal Export</p>
                  <p class="text-[10px] text-white/50 uppercase tracking-widest">CSV · Behavioral Log</p>
                </div>
                <span class="material-symbols-outlined text-secondary-fixed group-hover:translate-x-1 transition-transform">download</span>
              </button>
              <button onclick="sendDailyBrief()"
                      class="flex items-center justify-between w-full bg-white/5 p-4 rounded-xl hover:bg-white/10 transition-all group"
                      style="border:1px solid rgba(255,255,255,.1);">
                <div>
                  <p class="font-bold text-sm">Send Test Email</p>
                  <p class="text-[10px] text-white/50 uppercase tracking-widest">Daily Brief via Resend</p>
                </div>
                <span class="material-symbols-outlined text-secondary-fixed group-hover:translate-x-1 transition-transform">send</span>
              </button>
            </div>
          </div>

          <!-- Security status -->
          <div class="bg-surface-container-lowest rounded-xl p-6 shadow-card">
            <h4 class="text-xs font-black uppercase tracking-widest text-on-surface-variant mb-4">Security Status</h4>
            <div class="space-y-3 text-sm">
              <div class="flex items-center justify-between"><div class="flex items-center gap-2"><span class="w-2 h-2 rounded-full bg-secondary"></span>JWT Session Auth</div><span class="text-secondary text-xs font-bold">Active</span></div>
              <div class="flex items-center justify-between"><div class="flex items-center gap-2"><span class="w-2 h-2 rounded-full bg-secondary"></span>HTTPS / TLS 1.3</div><span class="text-secondary text-xs font-bold">Active</span></div>
              <div class="flex items-center justify-between"><div class="flex items-center gap-2"><span class="w-2 h-2 rounded-full bg-secondary"></span>Cloudflare DDoS</div><span class="text-secondary text-xs font-bold">Active</span></div>
              <div class="flex items-center justify-between"><div class="flex items-center gap-2"><span class="w-2 h-2 rounded-full bg-secondary-container"></span>KV Data Encryption</div><span class="text-secondary text-xs font-bold">Active</span></div>
            </div>
          </div>
        </div>
      </div>
    </div>

  </main>
</div>

<!-- ═══════════════════════════
     ADD HOLDING MODAL
════════════════════════════ -->
<div id="addHoldingModal" class="hidden fixed inset-0 bg-primary-container/50 backdrop-blur-sm z-50 flex items-center justify-center p-4">
  <div class="bg-white rounded-2xl p-8 w-full max-w-lg shadow-hero">
    <div class="flex justify-between items-center mb-6">
      <h3 class="text-xl font-headline font-bold text-primary-container">Add Holding</h3>
      <button onclick="closeAddHoldingModal()" class="text-on-surface/40 hover:text-on-surface">
        <span class="material-symbols-outlined">close</span>
      </button>
    </div>
    <div class="space-y-4">
      <div>
        <label class="text-[10px] font-black uppercase tracking-widest text-on-surface/50 block mb-2">Search Fund</label>
        <input id="modalFundSearch" type="text" placeholder="Type fund name…"
               class="w-full bg-surface-container-low border-none rounded-xl px-4 py-3 text-sm focus:ring-2 focus:ring-primary-container/20"
               oninput="onModalFundSearch(this.value)"/>
        <div id="modalFundResults" class="hidden mt-2 bg-white border border-surface-container-high rounded-xl overflow-hidden max-h-48 overflow-y-auto shadow-card"></div>
        <div id="modalSelectedFund" class="hidden mt-2 p-3 bg-secondary-container/20 rounded-xl text-sm font-semibold text-primary-container"></div>
      </div>
      <input type="hidden" id="modalSchemeCode"/>
      <div class="grid grid-cols-2 gap-4">
        <div>
          <label class="text-[10px] font-black uppercase tracking-widest text-on-surface/50 block mb-2">Amount Invested (₹)</label>
          <input id="modalAmount" type="number" placeholder="50000"
                 class="w-full bg-surface-container-low border-none rounded-xl px-4 py-3 text-sm focus:ring-2 focus:ring-primary-container/20"/>
        </div>
        <div>
          <label class="text-[10px] font-black uppercase tracking-widest text-on-surface/50 block mb-2">Units Purchased</label>
          <input id="modalUnits" type="number" placeholder="100.123" step="0.001"
                 class="w-full bg-surface-container-low border-none rounded-xl px-4 py-3 text-sm focus:ring-2 focus:ring-primary-container/20"/>
        </div>
        <div>
          <label class="text-[10px] font-black uppercase tracking-widest text-on-surface/50 block mb-2">Buy Date</label>
          <input id="modalBuyDate" type="date"
                 class="w-full bg-surface-container-low border-none rounded-xl px-4 py-3 text-sm focus:ring-2 focus:ring-primary-container/20"/>
        </div>
        <div>
          <label class="text-[10px] font-black uppercase tracking-widest text-on-surface/50 block mb-2">Buy NAV (₹)</label>
          <input id="modalBuyNAV" type="number" placeholder="523.45" step="0.01"
                 class="w-full bg-surface-container-low border-none rounded-xl px-4 py-3 text-sm focus:ring-2 focus:ring-primary-container/20"/>
        </div>
      </div>
      <div>
        <label class="text-[10px] font-black uppercase tracking-widest text-on-surface/50 block mb-2">Category</label>
        <select id="modalCategory" class="w-full bg-surface-container-low border-none rounded-xl px-4 py-3 text-sm focus:ring-2 focus:ring-primary-container/20">
          <option>Equity - Large Cap</option><option>Equity - Mid Cap</option>
          <option>Equity - Small Cap</option><option>Flexi Cap</option>
          <option>Index Fund</option><option>ELSS</option>
          <option>Hybrid</option><option>Debt</option>
        </select>
      </div>
      <button onclick="submitAddHolding()"
              class="w-full py-3.5 rounded-xl font-black text-sm text-white"
              style="background:linear-gradient(135deg,#001b44,#00020a);">
        Add to Portfolio
      </button>
    </div>
  </div>
</div>

<script>
// ═══════════════════════════════════════════════════════
// STATE & HELPERS
// ═══════════════════════════════════════════════════════
let token = localStorage.getItem('adhyarvansh_token') || '';
let portfolioCache = [];
let navChartInstance = null;
let searchTimeout = null;

const api = async (path, opts = {}) => {
  const res = await fetch(path, {
    ...opts,
    headers: { 'Content-Type': 'application/json', 'Authorization': 'Bearer ' + token, ...(opts.headers || {}) }
  });
  if (res.status === 401) { doLogout(); return null; }
  return res.json();
};

const showLoading = (msg = 'Processing…') => {
  document.getElementById('loadingMsg').textContent = msg;
  document.getElementById('loadingOverlay').classList.add('active');
};
const hideLoading = () => document.getElementById('loadingOverlay').classList.remove('active');

const toast = (msg, ms = 3000) => {
  const t = document.getElementById('toast');
  t.textContent = msg; t.classList.add('show');
  setTimeout(() => t.classList.remove('show'), ms);
};

const fmtCurrency = (n) => '₹' + Math.abs(n).toLocaleString('en-IN', { maximumFractionDigits: 0 });
const fmtPct = (n) => (n >= 0 ? '+' : '') + parseFloat(n).toFixed(2) + '%';

// ═══════════════════════════════════════════════════════
// AUTH
// ═══════════════════════════════════════════════════════
async function doLogin() {
  const pw = document.getElementById('loginPassword').value;
  const res = await fetch('/api/auth/login', {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ password: pw })
  });
  if (res.ok) {
    const data = await res.json();
    token = data.token;
    localStorage.setItem('adhyarvansh_token', token);
    document.getElementById('loginScreen').classList.add('hidden');
    document.getElementById('mainApp').classList.remove('hidden');
    document.getElementById('mainApp').style.display = 'flex';
    await initApp();
  } else {
    document.getElementById('loginError').classList.remove('hidden');
    setTimeout(() => document.getElementById('loginError').classList.add('hidden'), 3000);
  }
}

function doLogout() {
  localStorage.removeItem('adhyarvansh_token');
  token = '';
  location.reload();
}

// ═══════════════════════════════════════════════════════
// INIT
// ═══════════════════════════════════════════════════════
async function initApp() {
  document.getElementById('dashboardDate').textContent = new Date().toLocaleDateString('en-IN', { weekday:'long', year:'numeric', month:'long', day:'numeric' });
  await loadPortfolio();
  await loadJournal();
  await loadSettings();
}

// Auto-login if token exists
window.addEventListener('DOMContentLoaded', () => {
  if (token) {
    // Validate token by making an API call
    api('/api/portfolio').then(data => {
      if (data !== null) {
        document.getElementById('loginScreen').classList.add('hidden');
        document.getElementById('mainApp').classList.remove('hidden');
        document.getElementById('mainApp').style.display = 'flex';
        initApp();
      }
    });
  }
});

// ═══════════════════════════════════════════════════════
// NAVIGATION
// ═══════════════════════════════════════════════════════
function navigate(viewId, linkEl) {
  document.querySelectorAll('.view').forEach(v => v.classList.remove('active'));
  document.querySelectorAll('.nav-link').forEach(l => { l.classList.remove('active'); l.classList.add('opacity-70'); });
  document.getElementById('view-' + viewId).classList.add('active');
  linkEl.classList.add('active'); linkEl.classList.remove('opacity-70');
  window.scrollTo({ top: 0, behavior: 'smooth' });
  if (viewId === 'discovery') populateExitSelect();
}

// ═══════════════════════════════════════════════════════
// PORTFOLIO
// ═══════════════════════════════════════════════════════
async function loadPortfolio() {
  showLoading('Loading portfolio…');
  const data = await api('/api/portfolio');
  hideLoading();
  if (!data) return;
  portfolioCache = data;
  renderKPIs(data);
  renderHoldings(data);
  populateExitSelect();
}

function refreshPortfolio() { loadPortfolio(); }

function renderKPIs(holdings) {
  const totalInvested = holdings.reduce((s, h) => s + h.amountInvested, 0);
  const totalValue    = holdings.reduce((s, h) => s + (h.currentValue || h.amountInvested), 0);
  const totalPnl      = totalValue - totalInvested;
  const pnlPct        = totalInvested > 0 ? ((totalPnl / totalInvested) * 100) : 0;

  document.getElementById('kpiInvested').textContent = fmtCurrency(totalInvested);
  document.getElementById('kpiInvestedNote').textContent = holdings.length + ' active holding' + (holdings.length !== 1 ? 's' : '');
  document.getElementById('kpiValue').textContent = fmtCurrency(totalValue);
  document.getElementById('kpiPnl').textContent = (totalPnl >= 0 ? '+' : '') + fmtCurrency(totalPnl) + ' P&L';
  document.getElementById('kpiReturn').textContent = fmtPct(pnlPct);
  document.getElementById('kpiReturnNote').textContent = totalPnl >= 0 ? 'Profitable portfolio' : 'Portfolio in loss — review recommended';
  document.getElementById('kpiReturn').style.color = pnlPct >= 0 ? '#006d37' : '#ba1a1a';
}

function renderHoldings(holdings) {
  const el = document.getElementById('holdingsTable');
  if (!holdings.length) {
    el.innerHTML = '<div class="p-12 text-center text-on-surface/40"><span class="material-symbols-outlined text-4xl block mb-3">account_balance</span><p class="font-semibold">No holdings yet.</p><button onclick="openAddHoldingModal()" class="mt-4 px-6 py-2 bg-primary-container text-white rounded-xl text-sm font-bold">Add Holding</button></div>';
    return;
  }
  el.innerHTML = '<div class="overflow-x-auto"><table class="w-full text-left border-collapse">' +
    '<thead><tr class="bg-surface-container-low/60">' +
    '<th class="px-5 py-4 text-[10px] font-black uppercase tracking-widest text-on-surface/50">Fund</th>' +
    '<th class="px-5 py-4 text-[10px] font-black uppercase tracking-widest text-on-surface/50">Invested</th>' +
    '<th class="px-5 py-4 text-[10px] font-black uppercase tracking-widest text-on-surface/50">Current Value</th>' +
    '<th class="px-5 py-4 text-[10px] font-black uppercase tracking-widest text-on-surface/50">P&L</th>' +
    '<th class="px-5 py-4 text-[10px] font-black uppercase tracking-widest text-on-surface/50">Tax Type</th>' +
    '<th class="px-5 py-4 text-[10px] font-black uppercase tracking-widest text-on-surface/50">NAV</th>' +
    '<th class="px-5 py-4 text-[10px] font-black uppercase tracking-widest text-on-surface/50 text-center">Actions</th>' +
    '</tr></thead><tbody>' +
    holdings.map(h => {
      const pnlColor = parseFloat(h.pnlPct) >= 0 ? '#006d37' : '#ba1a1a';
      return '<tr style="border-bottom:1px solid rgba(0,27,68,.03);" class="hover:bg-surface-container-low/40 transition-colors">' +
        '<td class="px-5 py-5"><div><p class="font-bold text-sm text-primary-container">' + h.schemeName + '</p>' +
        '<p class="text-[10px] text-on-surface/40">' + (h.category || '') + ' · ' + h.daysSinceBuy + 'd held</p></div></td>' +
        '<td class="px-5 py-5 text-sm font-semibold">' + fmtCurrency(h.amountInvested) + '</td>' +
        '<td class="px-5 py-5 text-sm font-bold text-primary-container">' + fmtCurrency(h.currentValue || h.amountInvested) + '</td>' +
        '<td class="px-5 py-5"><span style="color:' + pnlColor + '" class="font-bold text-sm">' + fmtPct(h.pnlPct || 0) + '</span></td>' +
        '<td class="px-5 py-5"><span class="text-[10px] font-black px-2 py-1 rounded-full ' + (h.taxType === 'LTCG' ? 'bg-secondary/10 text-secondary' : 'chip-watch') + '">' + (h.taxType || 'STCG') + '</span></td>' +
        '<td class="px-5 py-5 text-sm">₹' + (h.currentNAV || '—') + '</td>' +
        '<td class="px-5 py-5 text-center"><div class="flex items-center justify-center gap-2">' +
        '<button onclick="showNAVChart(\'' + h.schemeCode + '\',\'' + h.schemeName.replace(/'/g,"'") + '\')" title="View NAV Chart" class="p-1.5 rounded-lg hover:bg-surface-container-low text-primary-container transition-colors"><span class="material-symbols-outlined text-[18px]">show_chart</span></button>' +
        '<button onclick="removeHolding(\'' + h.id + '\',\'' + h.schemeName.replace(/'/g,"'") + '\')" title="Remove" class="p-1.5 rounded-lg hover:bg-error-container text-error transition-colors"><span class="material-symbols-outlined text-[18px]">delete</span></button>' +
        '</div></td></tr>';
    }).join('') +
    '</tbody></table></div>';
}

async function removeHolding(id, name) {
  if (!confirm('Remove "' + name + '" from portfolio?')) return;
  showLoading('Removing holding…');
  await api('/api/portfolio/' + id, { method: 'DELETE' });
  hideLoading();
  toast('Holding removed.');
  await loadPortfolio();
}

function populateExitSelect() {
  const sel = document.getElementById('exitHoldingSelect');
  sel.innerHTML = '<option value="">— Choose a fund from your portfolio —</option>';
  portfolioCache.forEach(h => {
    const opt = document.createElement('option');
    opt.value = h.id;
    opt.textContent = h.schemeName;
    sel.appendChild(opt);
  });
}

// ═══════════════════════════════════════════════════════
// NAV CHART
// ═══════════════════════════════════════════════════════
async function showNAVChart(code, name) {
  showLoading('Fetching NAV history…');
  const data = await api('/api/funds/' + code + '/nav');
  hideLoading();
  if (!data || !data.history) { toast('Could not fetch NAV data.'); return; }

  const section = document.getElementById('navChartSection');
  section.classList.remove('hidden');
  document.getElementById('navChartTitle').textContent = name + ' — 1Y NAV';
  section.scrollIntoView({ behavior:'smooth', block:'center' });

  const labels = data.history.slice(0, 252).reverse().map(d => d.date);
  const navs   = data.history.slice(0, 252).reverse().map(d => d.nav);

  if (navChartInstance) navChartInstance.destroy();
  navChartInstance = new Chart(document.getElementById('navChart'), {
    type: 'line',
    data: {
      labels,
      datasets: [{
        label: 'NAV (₹)', data: navs,
        borderColor: '#001b44', backgroundColor: 'rgba(0,27,68,.06)',
        borderWidth: 2, pointRadius: 0, tension: 0.3, fill: true
      }]
    },
    options: {
      responsive: true, maintainAspectRatio: false,
      plugins: { legend: { display: false } },
      scales: {
        x: { ticks: { maxTicksLimit: 6, font: { family:'Inter', size:10 }, color:'rgba(13,29,42,.4)' }, grid: { display: false } },
        y: { ticks: { font: { family:'Inter', size:10 }, color:'rgba(13,29,42,.4)', callback: v => '₹'+v }, grid: { color:'rgba(0,27,68,.04)' } }
      }
    }
  });
}

// ═══════════════════════════════════════════════════════
// ADD HOLDING MODAL
// ═══════════════════════════════════════════════════════
function openAddHoldingModal() {
  document.getElementById('addHoldingModal').classList.remove('hidden');
  document.getElementById('modalBuyDate').valueAsDate = new Date();
}
function closeAddHoldingModal() {
  document.getElementById('addHoldingModal').classList.add('hidden');
  document.getElementById('modalSchemeCode').value = '';
  document.getElementById('modalSelectedFund').classList.add('hidden');
  document.getElementById('modalFundResults').classList.add('hidden');
}

let modalSearchTimeout = null;
function onModalFundSearch(q) {
  clearTimeout(modalSearchTimeout);
  if (q.length < 2) { document.getElementById('modalFundResults').classList.add('hidden'); return; }
  modalSearchTimeout = setTimeout(async () => {
    const data = await api('/api/funds/search?q=' + encodeURIComponent(q));
    const el = document.getElementById('modalFundResults');
    if (!data || !data.length) { el.classList.add('hidden'); return; }
    el.innerHTML = data.map(f =>
      '<div class="px-4 py-3 hover:bg-surface-container-low cursor-pointer border-b border-surface-container-low last:border-0 text-sm" onclick="selectModalFund(\'' + f.schemeCode + '\',\'' + f.schemeName.replace(/'/g,"'") + '\')">' +
      '<p class="font-semibold text-primary-container">' + f.schemeName + '</p>' +
      '<p class="text-[10px] text-on-surface/40">' + f.schemeCode + ' · ' + (f.fundHouse || '') + '</p>' +
      '</div>'
    ).join('');
    el.classList.remove('hidden');
  }, 300);
}

function selectModalFund(code, name) {
  document.getElementById('modalSchemeCode').value = code;
  document.getElementById('modalFundSearch').value = name;
  document.getElementById('modalFundResults').classList.add('hidden');
  const sel = document.getElementById('modalSelectedFund');
  sel.textContent = '✓ ' + name + ' (Code: ' + code + ')';
  sel.classList.remove('hidden');
}

async function submitAddHolding() {
  const schemeCode = document.getElementById('modalSchemeCode').value;
  const schemeName = document.getElementById('modalFundSearch').value;
  const amount     = document.getElementById('modalAmount').value;
  const units      = document.getElementById('modalUnits').value;
  const buyDate    = document.getElementById('modalBuyDate').value;
  const buyNAV     = document.getElementById('modalBuyNAV').value;
  const category   = document.getElementById('modalCategory').value;

  if (!schemeCode || !schemeName || !amount || !units || !buyDate) {
    toast('Please fill in all required fields.'); return;
  }
  showLoading('Adding holding…');
  const data = await api('/api/portfolio', {
    method: 'POST',
    body: JSON.stringify({ schemeCode, schemeName, amountInvested: amount, units, buyDate, buyNAV, category })
  });
  hideLoading();
  if (data?.id) {
    toast('Holding added successfully!');
    closeAddHoldingModal();
    await loadPortfolio();
  } else {
    toast('Error adding holding.');
  }
}

// ═══════════════════════════════════════════════════════
// FUND SEARCH (topbar)
// ═══════════════════════════════════════════════════════
function onFundSearch(q) {
  clearTimeout(searchTimeout);
  const el = document.getElementById('fundSearchResults');
  if (q.length < 2) { el.classList.add('hidden'); return; }
  searchTimeout = setTimeout(async () => {
    const data = await api('/api/funds/search?q=' + encodeURIComponent(q));
    if (!data || !data.length) { el.classList.add('hidden'); return; }
    el.innerHTML = data.map(f =>
      '<div class="px-4 py-3 hover:bg-surface-container-low cursor-pointer border-b border-surface-container-low last:border-0 text-sm" onclick="document.getElementById(\'fundSearchInput\').value=\'\';document.getElementById(\'fundSearchResults\').classList.add(\'hidden\');showNAVChart(\'' + f.schemeCode + '\',\'' + f.schemeName.replace(/'/g,"'") + '\')">' +
      '<p class="font-semibold text-primary-container text-sm">' + f.schemeName + '</p>' +
      '<p class="text-[10px] text-on-surface/40">' + f.schemeCode + '</p>' +
      '</div>'
    ).join('');
    el.classList.remove('hidden');
  }, 350);
}
document.addEventListener('click', e => {
  if (!e.target.closest('#fundSearchInput') && !e.target.closest('#fundSearchResults'))
    document.getElementById('fundSearchResults')?.classList.add('hidden');
});

// ═══════════════════════════════════════════════════════
// AI PORTFOLIO ANALYSIS
// ═══════════════════════════════════════════════════════
async function runPortfolioAnalysis() {
  if (!portfolioCache.length) { toast('Add holdings first.'); return; }
  showLoading('Running AI portfolio audit…');
  const data = await api('/api/ai/analyze', {
    method: 'POST', body: JSON.stringify({ holdings: portfolioCache })
  });
  hideLoading();
  if (!data || data.error) { toast('AI audit failed. Try again.'); return; }

  const el = document.getElementById('aiAuditResult');
  el.classList.remove('hidden');
  document.getElementById('auditScore').textContent = (data.healthScore || '—') + '/100';
  document.getElementById('auditScore').style.color = (data.healthScore || 50) >= 70 ? '#006d37' : '#ba1a1a';
  document.getElementById('auditVerdict').textContent = data.verdict || '';

  const det = document.getElementById('auditDetails');
  det.innerHTML = [
    renderAuditCard('Concentration Risk', data.concentration?.risk, data.concentration?.detail),
    renderAuditCard('Rebalance', data.rebalance?.needed ? 'Needed' : 'On Track', data.rebalance?.suggestion),
  ].join('');

  const sug = document.getElementById('auditSuggestions');
  const exitItems = (data.exitReview || []).map(e =>
    '<div class="flex items-center justify-between p-3 ' + (e.signal === 'SELL' ? 'bg-error-container/30' : 'bg-surface-container-low') + ' rounded-xl">' +
    '<div><p class="font-bold text-sm">' + e.fund + '</p><p class="text-xs text-on-surface/60">' + e.reason + '</p></div>' +
    '<span class="' + (e.signal === 'SELL' ? 'chip-sell' : 'chip-watch') + ' px-3 py-1 rounded-lg text-[10px] font-black">' + e.signal + '</span></div>'
  ).join('');
  sug.innerHTML = (exitItems ? '<p class="text-xs font-black uppercase tracking-widest text-on-surface-variant mb-2">Exit Review</p>' + exitItems : '') +
    (data.suggestions ? '<p class="text-xs font-black uppercase tracking-widest text-on-surface-variant mt-4 mb-2">AI Suggestions</p>' + data.suggestions.map(s => '<p class="text-sm text-on-surface/80 pl-3 border-l-2 border-secondary-container">'+s+'</p>').join('') : '');
  el.scrollIntoView({ behavior:'smooth', block:'start' });
}

function renderAuditCard(title, status, detail) {
  const color = (status === 'High' || status === 'Needed' || status === 'Poor') ? '#ba1a1a' : '#006d37';
  return '<div class="p-4 bg-surface-container-low rounded-xl"><p class="text-[10px] font-black uppercase tracking-widest text-on-surface-variant mb-1">' + title + '</p>' +
    '<p class="font-bold text-sm" style="color:' + color + '">' + (status || '—') + '</p>' +
    '<p class="text-xs text-on-surface/60 mt-1">' + (detail || '') + '</p></div>';
}

// ═══════════════════════════════════════════════════════
// JOURNAL
// ═══════════════════════════════════════════════════════
async function loadJournal() {
  const data = await api('/api/journal');
  if (data) renderJournal(data);
}

function renderJournal(entries) {
  const el = document.getElementById('journalEntries');
  if (!entries.length) return;
  const sentimentColors = { Confident:'#006d37', Optimistic:'#006d37', Nervous:'#ba1a1a', Neutral:'#44474f' };
  const typeColors = { Buy:'bg-secondary/10 text-secondary', Sell:'chip-sell', Review:'chip-watch', Note:'bg-primary-container/10 text-primary-container' };
  el.innerHTML = entries.slice(0, 30).map(e =>
    '<div class="bg-surface-container-lowest rounded-xl p-5 shadow-card">' +
    '<div class="flex justify-between items-start mb-3">' +
    '<div class="flex items-center gap-3">' +
    '<span class="' + (typeColors[e.entryType] || 'chip-watch') + ' px-3 py-1 rounded-full text-[10px] font-black">' + (e.entryType || 'Note') + '</span>' +
    '<span class="font-bold text-sm text-primary-container">' + (e.fundName || 'General Note') + '</span>' +
    '</div>' +
    '<span class="text-[10px] text-on-surface/40">' + new Date(e.date).toLocaleDateString('en-IN') + '</span>' +
    '</div>' +
    (e.amount ? '<p class="text-xs text-on-surface/60 mb-2">Amount: ' + fmtCurrency(e.amount) + '</p>' : '') +
    '<div class="flex items-center gap-3">' +
    '<span class="text-[10px] font-bold px-2 py-1 rounded-full bg-surface-container-low" style="color:' + (sentimentColors[e.sentiment] || '#44474f') + '">● ' + (e.sentiment || 'Neutral') + '</span>' +
    (e.notes ? '<p class="text-sm text-on-surface/70 italic">"' + e.notes + '"</p>' : '') +
    '</div></div>'
  ).join('');
}

async function addJournalEntry() {
  const entry = {
    fundName: document.getElementById('jFundName').value,
    amount: document.getElementById('jAmount').value,
    entryType: document.getElementById('jType').value,
    sentiment: document.getElementById('jSentiment').value,
    notes: document.getElementById('jNotes').value
  };
  if (!entry.fundName && !entry.notes) { toast('Enter a fund name or notes.'); return; }
  showLoading('Logging entry…');
  const data = await api('/api/journal', { method: 'POST', body: JSON.stringify(entry) });
  hideLoading();
  if (data?.id) {
    toast('Journal entry logged!');
    document.getElementById('jFundName').value = '';
    document.getElementById('jAmount').value = '';
    document.getElementById('jNotes').value = '';
    await loadJournal();
  }
}

async function runJournalAI() {
  showLoading('Analyzing behavioral patterns…');
  const data = await api('/api/ai/journal', { method: 'POST' });
  hideLoading();
  if (!data || data.message) { toast(data?.message || 'Error in analysis'); return; }
  const el = document.getElementById('journalAIResult');
  el.classList.remove('hidden');
  const content = document.getElementById('journalAIContent');
  content.innerHTML =
    '<div class="p-4 bg-surface-container-low rounded-xl"><p class="text-[10px] font-black uppercase tracking-widest text-on-surface-variant mb-1">Key Insight</p><p class="font-bold text-on-surface">' + (data.keyInsight || '') + '</p></div>' +
    '<div class="p-4 bg-surface-container-low rounded-xl"><p class="text-[10px] font-black uppercase tracking-widest text-on-surface-variant mb-1">Overall Pattern</p><p class="text-sm text-on-surface/80">' + (data.overallPattern || '') + '</p></div>' +
    (data.biases?.length ? '<div><p class="text-[10px] font-black uppercase tracking-widest text-on-surface-variant mb-2">Identified Biases</p>' +
      data.biases.map(b => '<div class="p-3 bg-error-container/20 rounded-xl mb-2"><p class="font-bold text-sm text-error">' + b.bias + '</p><p class="text-xs text-on-surface/70 mt-1">' + b.evidence + '</p><p class="text-xs text-secondary font-semibold mt-1">Fix: ' + b.correction + '</p></div>').join('') + '</div>' : '') +
    (data.actionableAdvice?.length ? '<div><p class="text-[10px] font-black uppercase tracking-widest text-on-surface-variant mb-2">Actionable Advice</p>' + data.actionableAdvice.map(a => '<p class="text-sm p-3 bg-secondary/5 rounded-xl border-l-2 border-secondary">' + a + '</p>').join('') + '</div>' : '');
  el.scrollIntoView({ behavior:'smooth' });
}

// ═══════════════════════════════════════════════════════
// AI DISCOVERY — SCAN
// ═══════════════════════════════════════════════════════
async function runScan() {
  const risk = document.getElementById('riskFilter').value;
  document.getElementById('scanStatus').classList.remove('hidden');
  document.getElementById('scanStatusText').textContent = 'Fetching NAV data from MFapi.in (20 funds)…';
  ['aggressiveFunds','moderateFunds','conservativeFunds','marketContext'].forEach(id =>
    document.getElementById(id).classList.add('hidden'));

  const data = await api('/api/ai/scan', { method:'POST', body: JSON.stringify({ riskFilter: risk }) });
  document.getElementById('scanStatus').classList.add('hidden');

  if (!data || data.error) { toast('Scan failed. Check your API keys.'); return; }

  // Market context
  const mc = document.getElementById('marketContext');
  mc.classList.remove('hidden');
  document.getElementById('marketContextText').textContent = data.marketContext || '';
  document.getElementById('topPickName').textContent = data.topPick?.name || '';
  document.getElementById('topPickReason').textContent = data.topPick?.reason || '';

  // Render tiers
  renderFundTier('aggressiveFunds', data.aggressive || [], 'aggressive');
  renderFundTier('moderateFunds',   data.moderate   || [], 'moderate');
  renderFundTier('conservativeFunds', data.conservative || [], 'conservative');

  if (data.fromCache) toast('Showing cached results (refreshes every 4h)');
  else toast('AI Scan complete — ' + (data.fundCount || 0) + ' funds analyzed');
}

function renderFundTier(containerId, funds, tier) {
  const el = document.getElementById(containerId);
  el.classList.remove('hidden');
  if (!funds.length) { el.innerHTML = '<div class="p-4 bg-surface-container-low rounded-xl text-sm text-on-surface/40 text-center">No recommendations for this tier.</div>'; return; }
  const tierColors = { aggressive:'bg-error/10 text-error', moderate:'bg-secondary/10 text-secondary', conservative:'bg-primary-container/10 text-primary-container' };
  el.innerHTML = funds.map((f, i) => {
    const conv = Math.round(f.conviction || 0);
    return '<div class="bg-surface-container-lowest rounded-xl p-5 shadow-card">' +
      '<div class="flex justify-between items-start mb-3">' +
      '<div><p class="font-headline font-bold text-primary-container text-sm">' + f.name + '</p>' +
      '<p class="text-[10px] text-on-surface/40 mt-0.5">' + f.category + ' · ' + f.idealDuration + '</p></div>' +
      '<span class="font-black text-sm ' + (parseFloat(f.r1y || 0) >= 0 ? 'text-secondary' : 'text-error') + '">' + fmtPct(f.r1y || 0) + '</span>' +
      '</div>' +
      '<div class="bg-surface-container-low rounded-xl p-3 mb-3">' +
      '<div class="flex items-start gap-2"><span class="material-symbols-outlined fi text-secondary text-[14px] shrink-0 mt-0.5">colors_spark</span>' +
      '<p class="text-xs text-on-surface/80 leading-relaxed">' + (f.why || '') + '</p></div></div>' +
      '<div class="flex gap-2 flex-wrap">' +
      '<span class="text-[10px] font-bold px-2 py-1 rounded-full ' + tierColors[tier] + '">Exit: ' + (f.exitSignal || '—') + '</span>' +
      '<span class="text-[10px] font-bold px-2 py-1 rounded-full bg-surface-container-low text-on-surface/60">Conviction: ' + conv + '/10</span>' +
      (f.caution ? '<span class="text-[10px] font-bold px-2 py-1 rounded-full chip-watch">⚠ ' + f.caution + '</span>' : '') +
      '</div>' +
      (f.schemeCode ? '<button onclick="openAddHoldingModal()" class="mt-3 w-full py-2 bg-primary-container text-white text-[10px] font-black uppercase tracking-widest rounded-xl hover:opacity-90">+ Add to Portfolio</button>' : '') +
      '</div>';
  }).join('');
}

// ═══════════════════════════════════════════════════════
// EXIT ANALYSIS
// ═══════════════════════════════════════════════════════
async function runExitAnalysis() {
  const holdingId = document.getElementById('exitHoldingSelect').value;
  const reason    = document.getElementById('exitReason').value;
  if (!holdingId) { toast('Select a holding first.'); return; }
  const holding = portfolioCache.find(h => h.id === holdingId);
  if (!holding) { toast('Holding not found.'); return; }
  showLoading('Running Exit Decision Matrix…');
  const data = await api('/api/ai/exit', { method:'POST', body: JSON.stringify({ holding, reason }) });
  hideLoading();
  if (!data || data.error) { toast('Exit analysis failed.'); return; }

  const el = document.getElementById('exitMatrixResult');
  el.classList.remove('hidden');
  const decisionColor = data.decision === 'SELL' ? '#ba1a1a' : data.decision === 'WATCH' ? '#44474f' : '#006d37';
  const f = data.factors || {};
  el.innerHTML =
    '<div class="flex items-center gap-4 p-4 rounded-xl bg-surface-container-low">' +
    '<div><p class="text-[10px] font-black uppercase tracking-widest text-on-surface-variant">AI Decision</p>' +
    '<p class="text-3xl font-headline font-black mt-1" style="color:' + decisionColor + '">' + data.decision + '</p>' +
    '<p class="text-xs text-on-surface/60">' + data.confidence + '% confidence</p></div>' +
    '<div class="flex-1"><p class="text-sm text-on-surface/80 leading-relaxed">' + (data.recommendation || '') + '</p>' +
    (data.alternativeAction ? '<p class="text-xs text-secondary font-semibold mt-2">Alternative: ' + data.alternativeAction + '</p>' : '') +
    '</div></div>' +
    '<div class="grid grid-cols-2 gap-3">' +
    renderFactorCard('Performance', f.performance) +
    renderFactorCard('Cost (Expense Ratio)', f.cost) +
    renderFactorCard('Tax Impact', f.taxImpact) +
    renderFactorCard('Exit Load', f.exitLoad) +
    '</div>' +
    (data.reasonValidation ? '<div class="p-4 bg-surface-container-low rounded-xl"><p class="text-[10px] font-black uppercase tracking-widest text-on-surface-variant mb-1">Reason Validation: ' + data.reasonValidation.type + '</p><p class="text-sm text-on-surface/80">' + data.reasonValidation.detail + '</p></div>' : '');
  el.scrollIntoView({ behavior:'smooth', block:'nearest' });
}

function renderFactorCard(title, factor) {
  if (!factor) return '';
  const statusColor = (factor.status === 'Good') ? '#006d37' : (factor.status === 'Poor') ? '#ba1a1a' : '#44474f';
  return '<div class="p-4 bg-surface-container-low rounded-xl"><p class="text-[10px] font-black uppercase tracking-widest text-on-surface-variant mb-1">' + title + '</p>' +
    '<p class="font-bold text-sm mb-1" style="color:' + statusColor + '">' + (factor.status || '—') + '</p>' +
    '<p class="text-xs text-on-surface/70">' + (factor.detail || '') + '</p>' +
    (factor.estimatedTax ? '<p class="text-xs font-bold text-error mt-1">Est. Tax: ₹' + factor.estimatedTax.toLocaleString('en-IN') + '</p>' : '') +
    '</div>';
}

// ═══════════════════════════════════════════════════════
// SETTINGS
// ═══════════════════════════════════════════════════════
async function loadSettings() {
  const data = await api('/api/settings');
  if (!data) return;
  document.getElementById('settingName').value    = data.name || '';
  document.getElementById('settingEmail').value   = data.email || '';
  document.getElementById('settingMobile').value  = data.mobile || '';
  document.getElementById('settingRisk').value    = data.riskProfile || 'Moderate';
  if (data.notifications) {
    document.getElementById('notifDigest').checked  = !!data.notifications.dailyDigest;
    document.getElementById('notifWarning').checked = !!data.notifications.warnings;
    document.getElementById('notifGoal').checked    = !!data.notifications.goalProximity;
    document.getElementById('notifTax').checked     = !!data.notifications.taxHarvest;
  }
}

async function saveSettings() {
  const body = {
    name: document.getElementById('settingName').value,
    email: document.getElementById('settingEmail').value,
    mobile: document.getElementById('settingMobile').value,
    riskProfile: document.getElementById('settingRisk').value,
    notifications: {
      dailyDigest:   document.getElementById('notifDigest').checked,
      warnings:      document.getElementById('notifWarning').checked,
      goalProximity: document.getElementById('notifGoal').checked,
      taxHarvest:    document.getElementById('notifTax').checked,
    }
  };
  showLoading('Saving settings…');
  await api('/api/settings', { method:'POST', body: JSON.stringify(body) });
  hideLoading();
  toast('Settings saved!');
}

async function sendDailyBrief() {
  const settings = { email: document.getElementById('settingEmail')?.value };
  if (!settings.email) { toast('Configure your email in Settings first.'); navigate('profile', document.querySelectorAll('.nav-link')[3]); return; }
  showLoading('Sending email brief…');
  await api('/api/notify/email', { method:'POST', body: JSON.stringify({ subject:'Adhyarvansh Daily Brief', message:'Your daily portfolio brief from Adhyarvansh.' }) });
  hideLoading();
  toast('Daily brief sent to ' + settings.email);
}

// ═══════════════════════════════════════════════════════
// EXPORTS
// ═══════════════════════════════════════════════════════
function exportPortfolioCSV() {
  if (!portfolioCache.length) { toast('No holdings to export.'); return; }
  const header = 'Fund Name,Scheme Code,Amount Invested,Units,Buy Date,Buy NAV,Current NAV,Current Value,P&L %,Tax Type,Category';
  const rows = portfolioCache.map(h => [
    '"'+h.schemeName+'"', h.schemeCode, h.amountInvested, h.units, h.buyDate,
    h.buyNAV, h.currentNAV||'', h.currentValue||'', h.pnlPct||'', h.taxType||'', h.category||''
  ].join(','));
  downloadCSV('adhyarvansh_portfolio_' + new Date().toISOString().slice(0,10) + '.csv', [header,...rows].join('\\n'));
}

function exportJournalCSV() {
  api('/api/journal').then(entries => {
    if (!entries?.length) { toast('No journal entries to export.'); return; }
    const header = 'Date,Fund Name,Amount,Entry Type,Sentiment,Notes';
    const rows = entries.map(e => [new Date(e.date).toLocaleDateString('en-IN'), '"'+(e.fundName||'')+'"', e.amount||0, e.entryType||'', e.sentiment||'', '"'+(e.notes||'')+'"'].join(','));
    downloadCSV('adhyarvansh_journal_' + new Date().toISOString().slice(0,10) + '.csv', [header,...rows].join('\\n'));
  });
}

function downloadCSV(filename, content) {
  const blob = new Blob([content], { type: 'text/csv' });
  const a = document.createElement('a');
  a.href = URL.createObjectURL(blob); a.download = filename; a.click();
  toast('Exported: ' + filename);
}
</script>
</body>
</html>`;
}
