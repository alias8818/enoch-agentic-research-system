from __future__ import annotations

import asyncio
from collections import Counter
from collections import deque
from datetime import datetime, timezone
import heapq
import html
import json
import os
import subprocess
from pathlib import Path
import time
from typing import Any

from fastapi import FastAPI, Header, HTTPException, Query, Response
from fastapi.responses import HTMLResponse

from .callbacks import CallbackSender
from .control_plane.router import create_control_plane_router
from .config import GateConfig
from .enoch_core.router import create_enoch_core_router
from .gate import WakeGate
from .models import (
    DispatchRequest,
    GateCallback,
    GateState,
    OmxEvent,
    PaperArtifactReadRequest,
    PaperArtifactRequest,
    PrepareProjectRequest,
    ProcessInfo,
    ProjectDecision,
    ProjectStatusResponse,
    RunRecord,
    SessionHistoryEntry,
    utc_now,
)
from .process_tracker import ProcessTracker
from .state_store import StateStore
from .telemetry import TelemetryCollector


def load_config(path: Path | None = None) -> GateConfig:
    env_path = os.environ.get("OMX_WAKE_GATE_CONFIG")
    config_path = path or (
        Path(env_path).expanduser()
        if env_path
        else (Path(__file__).resolve().parents[1] / "config.example.json")
    )
    data = json.loads(config_path.read_text())
    return GateConfig.model_validate(data)


config = load_config()
store = StateStore(config.expanded_state_dir)
telemetry = TelemetryCollector()
gate = WakeGate(config, ProcessTracker(config.expanded_project_root), telemetry)
sender = CallbackSender(config)
app = FastAPI(title="omx_wake_gate", version="0.1.0")
evaluation_tasks: dict[str, asyncio.Task] = {}
reconcile_task: asyncio.Task | None = None


DASHBOARD_HTML = """
<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>OMX Operations Console</title>
  <style>
    :root {
      color-scheme: dark;
      --bg: #05070b;
      --bg2: #0b1320;
      --panel: rgba(12, 20, 33, .86);
      --panel2: rgba(20, 31, 48, .76);
      --panel3: rgba(31, 45, 67, .72);
      --text: #eef6ff;
      --muted: #9fb0c3;
      --soft: #c9d8ea;
      --line: rgba(148, 163, 184, .20);
      --line2: rgba(148, 163, 184, .32);
      --good: #4ade80;
      --warn: #fbbf24;
      --bad: #fb7185;
      --info: #60a5fa;
      --purple: #c084fc;
      --cyan: #22d3ee;
      --shadow: 0 24px 70px rgba(0, 0, 0, .42);
      font-family: Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
    }
    * { box-sizing: border-box; }
    body {
      margin: 0;
      min-height: 100vh;
      color: var(--text);
      background:
        radial-gradient(circle at 10% -10%, rgba(34, 211, 238, .18), transparent 36%),
        radial-gradient(circle at 85% 0%, rgba(192, 132, 252, .17), transparent 32%),
        radial-gradient(circle at 50% 110%, rgba(74, 222, 128, .08), transparent 40%),
        linear-gradient(145deg, var(--bg) 0%, var(--bg2) 100%);
    }
    header {
      position: sticky;
      top: 0;
      z-index: 20;
      border-bottom: 1px solid var(--line);
      background: rgba(5, 7, 11, .78);
      backdrop-filter: blur(18px);
    }
    .wrap { width: min(1620px, calc(100vw - 36px)); margin: 0 auto; }
    .topbar { display:flex; align-items:center; justify-content:space-between; gap:18px; padding:18px 0; }
    .brand { display:flex; align-items:center; gap:14px; }
    .logo { width:44px; height:44px; border-radius:14px; display:grid; place-items:center; background: linear-gradient(135deg, rgba(96,165,250,.95), rgba(34,211,238,.7)); box-shadow: 0 14px 36px rgba(96,165,250,.24); font-weight:900; letter-spacing:-.08em; }
    h1 { margin:0; font-size: clamp(1.35rem, 2.1vw, 2.35rem); letter-spacing:-.045em; }
    .subtitle { margin-top:3px; color:var(--muted); font-size:.94rem; }
    .actions { display:flex; gap:10px; flex-wrap:wrap; justify-content:flex-end; }
    button, input, select {
      border:1px solid var(--line);
      background: rgba(15, 23, 42, .76);
      color:var(--text);
      border-radius:12px;
      padding:10px 12px;
      font:inherit;
      outline:none;
    }
    button { cursor:pointer; transition: .15s ease; }
    button:hover { border-color: rgba(96,165,250,.75); transform: translateY(-1px); }
    button.primary { background: linear-gradient(135deg, rgba(37,99,235,.92), rgba(8,145,178,.78)); border-color: rgba(147,197,253,.45); }
    main { padding: 22px 0 44px; }
    .grid { display:grid; gap:16px; }
    .cards { grid-template-columns: repeat(6, minmax(140px, 1fr)); }
    .layout { grid-template-columns: minmax(0, 1.2fr) minmax(390px, .8fr); align-items:start; margin-top:16px; }
    .panel, .metric, .hero {
      background: var(--panel);
      border: 1px solid var(--line);
      border-radius: 22px;
      box-shadow: var(--shadow);
      overflow:hidden;
    }
    .hero { padding:18px; margin-bottom:16px; display:grid; grid-template-columns: minmax(0, 1fr) auto; gap:18px; align-items:center; background: linear-gradient(135deg, rgba(15,23,42,.92), rgba(20,83,115,.35)); }
    .hero-title { font-size:1.15rem; font-weight:800; letter-spacing:-.02em; margin-bottom:6px; }
    .hero-copy { color:var(--muted); line-height:1.45; }
    .metric { min-height:118px; padding:16px; background: linear-gradient(145deg, rgba(255,255,255,.07), rgba(255,255,255,.025)); }
    .metric .label { color:var(--muted); font-size:.76rem; letter-spacing:.09em; text-transform:uppercase; }
    .metric .value { margin-top:7px; font-size:2rem; font-weight:850; letter-spacing:-.055em; }
    .metric .hint { margin-top:7px; color:var(--muted); font-size:.88rem; line-height:1.35; }
    .panel-head { display:flex; justify-content:space-between; align-items:center; gap:12px; padding:15px 18px; border-bottom:1px solid var(--line); background: rgba(255,255,255,.025); }
    .panel-title { display:flex; align-items:center; gap:10px; }
    .panel h2 { margin:0; font-size:1rem; letter-spacing:-.02em; }
    .panel-body { padding:16px 18px; }
    .toolbar { display:flex; gap:10px; margin: 0 0 14px; flex-wrap:wrap; }
    .toolbar input { flex: 1 1 360px; }
    .status-dot { width:10px; height:10px; border-radius:50%; display:inline-block; background:var(--muted); box-shadow:0 0 18px currentColor; }
    .status-dot.good { background:var(--good); color:var(--good); }
    .status-dot.warn { background:var(--warn); color:var(--warn); }
    .status-dot.bad { background:var(--bad); color:var(--bad); }
    .status-dot.info { background:var(--info); color:var(--info); }
    .status-dot.purple { background:var(--purple); color:var(--purple); }
    .pill { display:inline-flex; align-items:center; gap:6px; padding:5px 10px; border-radius:999px; border:1px solid var(--line2); background: rgba(255,255,255,.055); font-size:.8rem; font-weight:750; white-space:nowrap; }
    .pill.good { color:var(--good); border-color:rgba(74,222,128,.42); background:rgba(74,222,128,.08); }
    .pill.warn { color:var(--warn); border-color:rgba(251,191,36,.42); background:rgba(251,191,36,.08); }
    .pill.bad { color:var(--bad); border-color:rgba(251,113,133,.42); background:rgba(251,113,133,.08); }
    .pill.info { color:var(--info); border-color:rgba(96,165,250,.42); background:rgba(96,165,250,.08); }
    .pill.purple { color:var(--purple); border-color:rgba(192,132,252,.42); background:rgba(192,132,252,.08); }
    table { width:100%; border-collapse: collapse; }
    th, td { padding:13px 12px; border-bottom:1px solid var(--line); vertical-align:middle; }
    th { color:var(--muted); text-align:left; font-size:.74rem; text-transform:uppercase; letter-spacing:.09em; }
    tbody tr { cursor:pointer; transition:.12s ease; }
    tbody tr:hover td { background:rgba(255,255,255,.035); }
    tbody tr.selected td { background: rgba(96,165,250,.075); }
    .project-name { font-weight:800; letter-spacing:-.015em; margin-bottom:4px; }
    .small { font-size:.86rem; color:var(--muted); }
    .mono { font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace; font-size:.84em; }
    .truncate { overflow:hidden; text-overflow:ellipsis; white-space:nowrap; max-width: 520px; }
    .stack { display:grid; gap:10px; }
    .kv { display:grid; grid-template-columns: 130px minmax(0, 1fr); gap:10px; padding:9px 0; border-bottom:1px solid rgba(148,163,184,.12); }
    .kv:last-child { border-bottom:0; }
    .kv .k { color:var(--muted); font-size:.82rem; }
    .kv .v { color:var(--soft); overflow-wrap:anywhere; }
    .section-title { color:var(--muted); text-transform:uppercase; letter-spacing:.1em; font-size:.72rem; margin:18px 0 8px; }
    .process { padding:10px; border:1px solid var(--line); border-radius:12px; background:rgba(0,0,0,.13); }
    .event { padding:12px 0; border-bottom:1px solid var(--line); }
    .event:last-child { border-bottom:0; }
    .event-top { display:flex; align-items:center; justify-content:space-between; gap:8px; margin-bottom:6px; }
    .event-name { font-weight:800; }
    .event-detail { color:var(--muted); line-height:1.4; overflow-wrap:anywhere; }
    .notes { display:grid; gap:8px; }
    .note { padding:10px 12px; border-left:3px solid rgba(96,165,250,.7); background:rgba(96,165,250,.065); border-radius:10px; color:#dcecff; line-height:1.42; }
    .files { display:flex; gap:8px; flex-wrap:wrap; }
    .file { max-width:100%; padding:6px 9px; border-radius:999px; background:rgba(148,163,184,.09); border:1px solid var(--line); color:#dbeafe; }
    .paper-review { min-height: 220px; }
    .review-actions { display:flex; gap:8px; flex-wrap:wrap; margin:10px 0; }
    .review-actions button, .review-actions a { text-decoration:none; color:var(--text); border:1px solid var(--line); background:rgba(15,23,42,.76); border-radius:12px; padding:9px 11px; font:inherit; display:inline-flex; align-items:center; gap:6px; }
    .review-actions a:hover { border-color:rgba(96,165,250,.75); }
    .paper-preview pre { max-height: 620px; }
    details.raw { margin-top:12px; border:1px solid var(--line); border-radius:12px; background:rgba(2,6,23,.5); }
    details.raw summary { cursor:pointer; padding:10px 12px; color:var(--muted); font-weight:700; }
    pre { margin:0; max-height:360px; overflow:auto; white-space:pre-wrap; overflow-wrap:anywhere; padding:12px; color:#dbeafe; border-top:1px solid var(--line); }
    .empty { padding:28px; text-align:center; color:var(--muted); }
    .tabs { display:flex; gap:8px; flex-wrap:wrap; margin-bottom:12px; }
    .tab { padding:7px 10px; font-size:.86rem; border-radius:999px; color:var(--muted); border:1px solid var(--line); background:rgba(255,255,255,.035); }
    .tab.active { color:var(--text); border-color:rgba(96,165,250,.55); background:rgba(96,165,250,.12); }
    .page-nav { display:flex; gap:10px; flex-wrap:wrap; margin: 0 0 16px; padding:8px; border:1px solid var(--line); border-radius:18px; background:rgba(255,255,255,.035); box-shadow: var(--shadow); }
    .nav-btn { border-radius:14px; color:var(--muted); background:transparent; }
    .nav-btn.active { color:var(--text); border-color:rgba(34,211,238,.56); background:linear-gradient(135deg, rgba(37,99,235,.34), rgba(8,145,178,.22)); }
    .page { display:none; }
    .page.active { display:block; }
    .compact-cards { grid-template-columns: repeat(4, minmax(150px, 1fr)); }
    .count-grid { display:grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap:10px; }
    .count-row { display:flex; align-items:center; justify-content:space-between; gap:12px; padding:11px 12px; border:1px solid var(--line); border-radius:14px; background:rgba(255,255,255,.04); }
    .count-label { color:var(--soft); font-weight:760; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }
    .count-value { font-size:1.25rem; font-weight:850; letter-spacing:-.04em; }
    .progress { height:9px; border-radius:999px; overflow:hidden; background:rgba(148,163,184,.18); margin-top:12px; }
    .progress > span { display:block; height:100%; width:0%; background:linear-gradient(90deg, var(--cyan), var(--good)); }
    .summary-copy { color:var(--muted); line-height:1.5; margin-bottom:12px; }
    @media (max-width: 1280px) { .cards { grid-template-columns: repeat(3, minmax(160px, 1fr)); } .layout { grid-template-columns:1fr; } }
    @media (max-width: 780px) { .cards, .compact-cards, .count-grid { grid-template-columns:1fr 1fr; } .topbar { flex-direction:column; align-items:flex-start; } th:nth-child(4), td:nth-child(4) { display:none; } .wrap { width:min(100vw - 20px, 1620px); } }
    @media (max-width: 560px) { .cards, .compact-cards, .count-grid { grid-template-columns:1fr; } }
  </style>
</head>
<body>
  <header>
    <div class="wrap topbar">
      <div class="brand">
        <div class="logo">Ω</div>
        <div>
          <h1>OMX Operations Console</h1>
          <div class="subtitle" id="subtitle">Wake-gate runs, quiet windows, callbacks, and active Codex work.</div>
        </div>
      </div>
      <div class="actions">
        <button id="tokenBtn">Token</button>
        <button class="primary" id="refreshBtn">Refresh</button>
        <button id="autoBtn">Auto: on</button>
      </div>
    </div>
  </header>
  <main class="wrap">
    <section class="hero">
      <div>
        <div class="hero-title" id="heroTitle">Loading operations state…</div>
        <div class="hero-copy" id="heroCopy">The console summarizes the signal path instead of dumping raw run JSON. Raw payloads are available only under explicit developer toggles.</div>
      </div>
      <span class="pill info" id="lastLoad">not loaded</span>
    </section>
    <nav class="page-nav" aria-label="Dashboard pages">
      <button class="nav-btn active" data-page="overview">Overview</button>
      <button class="nav-btn" data-page="projects">Project Queue</button>
      <button class="nav-btn" data-page="papers">Paper Queue</button>
      <button class="nav-btn" data-page="runs">Wake Gate</button>
    </nav>
    <section class="page active" id="page-overview">
      <section class="grid cards" id="cards"></section>
      <section class="grid layout">
        <div class="panel">
          <div class="panel-head"><div class="panel-title"><span class="status-dot good"></span><h2>Project Queue Status</h2></div><span class="small" id="overviewProjectHint"></span></div>
          <div class="panel-body" id="overviewProjects"></div>
        </div>
        <aside class="grid">
          <div class="panel">
            <div class="panel-head"><div class="panel-title"><span class="status-dot purple"></span><h2>Outcome Mix</h2></div><span class="small">decision states</span></div>
            <div class="panel-body" id="overviewOutcomes"></div>
          </div>
          <div class="panel">
            <div class="panel-head"><div class="panel-title"><span class="status-dot info"></span><h2>Paper Queue Status</h2></div><span class="small" id="overviewPaperHint"></span></div>
            <div class="panel-body" id="overviewPapers"></div>
          </div>
        </aside>
      </section>
    </section>
    <section class="page" id="page-projects">
      <section class="grid cards compact-cards" id="projectCards"></section>
      <section class="grid layout">
        <div class="panel">
          <div class="panel-head"><div class="panel-title"><span class="status-dot info"></span><h2>Project Status Counts</h2></div><span class="small" id="projectStatusHint"></span></div>
          <div class="panel-body" id="projectStatusBreakdown"></div>
        </div>
        <aside class="panel">
          <div class="panel-head"><div class="panel-title"><span class="status-dot purple"></span><h2>Project Outcome Counts</h2></div><span class="small">last run states</span></div>
          <div class="panel-body" id="projectOutcomeBreakdown"></div>
        </aside>
      </section>
      <section class="panel" id="queuePanel" style="margin-top:16px; display:none">
        <div class="panel-head">
          <div class="panel-title"><span class="status-dot bad"></span><h2>Queue Attention</h2></div>
          <span class="small" id="queueHint"></span>
        </div>
        <div class="panel-body" id="queueAttention"></div>
      </section>
      <section class="panel" style="margin-top:16px">
        <div class="panel-head"><div class="panel-title"><span class="status-dot good"></span><h2>Project Queue Rows</h2></div><span class="small" id="projectRowsHint"></span></div>
        <div class="panel-body" id="projectRows"></div>
      </section>
    </section>
    <section class="page" id="page-papers">
      <section class="grid cards compact-cards" id="paperCards"></section>
      <section class="grid layout">
        <div class="panel">
          <div class="panel-head"><div class="panel-title"><span class="status-dot info"></span><h2>Paper Status Counts</h2></div><span class="small" id="paperStatusHint"></span></div>
          <div class="panel-body" id="paperStatusBreakdown"></div>
        </div>
        <aside class="panel">
          <div class="panel-head"><div class="panel-title"><span class="status-dot purple"></span><h2>Paper Type Counts</h2></div><span class="small">artifact types</span></div>
          <div class="panel-body" id="paperTypeBreakdown"></div>
        </aside>
      </section>
      <section class="grid layout" id="paperPanel" style="margin-top:16px; display:none">
        <div class="panel">
          <div class="panel-head">
            <div class="panel-title"><span class="status-dot purple"></span><h2>Paper Review Queue</h2></div>
            <span class="small" id="paperHint"></span>
          </div>
          <div class="panel-body">
            <div class="toolbar">
              <input id="paperSearch" placeholder="Search paper, project, status, model, notes…" />
              <select id="paperStatusFilter"><option value="">All paper statuses</option></select>
            </div>
            <table>
              <thead><tr><th>Status</th><th>Paper</th><th>Evidence</th><th>Updated</th></tr></thead>
              <tbody id="papers"></tbody>
            </table>
            <div class="empty" id="paperEmpty" style="display:none">No papers match the current filters.</div>
          </div>
        </div>
        <aside class="panel paper-review">
          <div class="panel-head"><h2>Paper Reader</h2><span class="small" id="paperSelectedHint">click a paper</span></div>
          <div class="panel-body" id="paperReader"><div class="empty">Select a paper to review Markdown, LaTeX, claim audit, or evidence artifacts from the dashboard.</div></div>
        </aside>
      </section>
    </section>
    <section class="page" id="page-runs">
      <section class="panel" style="margin-top:16px">
        <div class="panel-head">
          <div class="panel-title"><span class="status-dot" id="loadDot"></span><h2>Run Board</h2></div>
          <span class="small" id="runCount"></span>
        </div>
        <div class="panel-body">
          <div class="toolbar">
            <input id="search" placeholder="Search project, run, session, state, decision…" />
            <select id="stateFilter"><option value="">All states</option></select>
            <select id="signalFilter"><option value="">All signals</option><option value="active">Active</option><option value="attention">Needs attention</option><option value="pending">Callback pending</option><option value="delivered">Delivered history</option><option value="settling">Settling</option><option value="historical">Historical</option></select>
          </div>
          <table>
            <thead><tr><th>Signal</th><th>Project</th><th>State</th><th>Last evidence</th><th>Decision</th></tr></thead>
            <tbody id="runs"></tbody>
          </table>
          <div class="empty" id="empty" style="display:none">No runs match the current filters.</div>
        </div>
      </section>
      <section class="grid layout">
        <div class="panel">
          <div class="panel-head"><h2>Selected Run</h2><span class="small" id="selectedHint">click a row</span></div>
          <div class="panel-body" id="selected"><div class="empty">Select a run to inspect the operator summary.</div></div>
        </div>
        <aside class="grid">
          <div class="panel">
            <div class="panel-head"><h2>Telemetry & State Mix</h2><span class="small" id="serviceInfo"></span></div>
            <div class="panel-body" id="telemetry"></div>
          </div>
          <div class="panel">
            <div class="panel-head"><h2>Recent Wake Events</h2><span class="small" id="eventCount"></span></div>
            <div class="panel-body" id="events"></div>
          </div>
        </aside>
      </section>
    </section>
  </main>
  <script>
    let snapshot = null;
    let selectedRunId = null;
    let selectedPaperId = null;
    let selectedPaperPath = null;
    let currentPage = "overview";
    let auto = true;
    let timer = null;
    const tokenKey = "omx-dashboard-token";
    const cls = {good:"good", warn:"warn", bad:"bad", info:"info", purple:"purple"};

    const token = () => localStorage.getItem(tokenKey) || "";
    const esc = (value) => String(value ?? "").replace(/[&<>"']/g, ch => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[ch]));
    const plural = (n, word) => `${n} ${word}${n === 1 ? "" : "s"}`;
    function fmtDate(value) { if (!value) return "—"; const d = new Date(value); return Number.isNaN(d.getTime()) ? value : d.toLocaleString(); }
    function age(value) { if (!value) return "unknown"; const ms = Date.now() - new Date(value).getTime(); if (!Number.isFinite(ms)) return "unknown"; const s=Math.max(0, Math.round(ms/1000)); if (s<90) return `${s}s ago`; const m=Math.round(s/60); if (m<90) return `${m}m ago`; const h=Math.round(m/60); if (h<48) return `${h}h ago`; return `${Math.round(h/24)}d ago`; }
    function compact(text, max=120) { text = String(text ?? "").replace(/\\s+/g, " ").trim(); return text.length > max ? text.slice(0, max-1).trimEnd() + "…" : text; }
    const count = (obj, key) => Number(obj?.[key] || 0);
    const sumCounts = (obj, keys) => keys.reduce((total, key) => total + count(obj, key), 0);
    function stateTone(state) { state=String(state||""); if (["running","active"].includes(state)) return cls.good; if (["callback_pending","settling","waiting_for_quiet_window","waiting_for_process_exit","pending_idle_gate","finished_pending_gate"].includes(state)) return cls.warn; if (["attention","stale_callback_ready","question_pending","error","gate_timeout"].includes(state)) return cls.bad; if (["callback_delivered","finished_delivered"].includes(state)) return cls.purple; return cls.info; }
    function signal(run) {
      const label = run.operator_status || run.lifecycle_state || run.gate_state || "unknown";
      const tone = stateTone(run.lifecycle_state || run.gate_state);
      return {label, tone, copy: run.operator_status_detail || run.current_activity || "Tracked run"};
    }
    function pill(label, tone="info") { return `<span class="pill ${tone}">${esc(label)}</span>`; }
    function metric(label, value, hint) { return `<div class="metric"><div class="label">${esc(label)}</div><div class="value">${esc(value)}</div><div class="hint">${esc(hint || "")}</div></div>`; }
    function setToken() { const next = prompt("Wake-gate dashboard token", token()); if (next !== null) { localStorage.setItem(tokenKey, next.trim()); load(); } }
    function bootstrapTokenFromUrl() { const params = new URLSearchParams(location.search); const t = params.get("token"); if (t) { localStorage.setItem(tokenKey, t.trim()); params.delete("token"); history.replaceState(null, "", `${location.pathname}${params.toString() ? "?"+params.toString() : ""}`); } }
    function setPage(page, updateHash=true) {
      currentPage = ["overview", "projects", "papers", "runs"].includes(page) ? page : "overview";
      document.querySelectorAll(".page").forEach(el => el.classList.toggle("active", el.id === `page-${currentPage}`));
      document.querySelectorAll("[data-page]").forEach(btn => btn.classList.toggle("active", btn.dataset.page === currentPage));
      if (updateHash) history.replaceState(null, "", `${location.pathname}${location.search}${currentPage === "overview" ? "" : "#" + currentPage}`);
    }
    function initPageFromHash() { setPage((location.hash || "").replace("#", "") || "overview", false); }

    async function load() {
      document.getElementById("loadDot").className = "status-dot warn";
      try {
        const headers = token() ? {Authorization:`Bearer ${token()}`} : {};
        const res = await fetch("/dashboard/api?limit=40&event_limit=30", {headers});
        if (res.status === 401) { document.getElementById("loadDot").className="status-dot bad"; document.getElementById("lastLoad").textContent="token required"; if (!token()) setToken(); return; }
        if (!res.ok) throw new Error(`${res.status}: ${await res.text()}`);
        snapshot = await res.json();
        if (!selectedRunId && snapshot.runs?.length) selectedRunId = snapshot.runs[0].run_id;
        if (!selectedPaperId && snapshot.papers?.latest_rows?.length) selectedPaperId = snapshot.papers.latest_rows[0].paper_id;
        render();
        document.getElementById("loadDot").className = "status-dot good";
        document.getElementById("lastLoad").textContent = `updated ${new Date().toLocaleTimeString()}`;
      } catch (err) {
        document.getElementById("loadDot").className = "status-dot bad";
        document.getElementById("lastLoad").textContent = err.message;
      }
    }

    function queueStats() {
      const queue = snapshot?.queue || {};
      const status = queue.status_counts || {};
      const states = queue.run_state_counts || {};
      const active = Number(queue.active_count ?? sumCounts(status, ["dispatching", "awaiting_wake", "running"]));
      const blocked = Number(queue.blocked_count ?? count(status, "blocked"));
      const queued = Number(queue.queued_count ?? count(status, "queued"));
      const completed = Number(queue.completed_count ?? count(status, "completed"));
      const positive = Number(queue.positive_count ?? count(states, "finalize_positive"));
      const negative = Number(queue.negative_count ?? count(states, "finalize_negative"));
      const branch = Number(queue.branch_count ?? (count(states, "branch_new_project") + count(states, "branch_queued")));
      const total = Number(queue.total || queue.valid_projects || Object.values(status).reduce((a, b) => a + Number(b || 0), 0));
      const terminal = completed + count(status, "canceled") + count(status, "failed");
      return {queue, status, states, total, active, blocked, queued, completed, positive, negative, branch, terminal, yet: queued + active};
    }
    function paperStats() {
      const papers = snapshot?.papers || {};
      const status = papers.status_counts || {};
      const types = papers.type_counts || {};
      return {
        papers,
        status,
        types,
        total: Number(papers.total || Object.values(status).reduce((a, b) => a + Number(b || 0), 0)),
        reviewable: Number(papers.reviewable_count || 0),
        publication: Number(papers.publication_count || count(status, "publication_draft")),
        draftReview: count(status, "draft_review") + count(status, "ready_for_review"),
      };
    }
    function toneForLabel(label) {
      const value = String(label || "").toLowerCase();
      if (["completed", "finalize_positive", "publication_draft", "ready_for_review"].includes(value)) return cls.good;
      if (["queued", "awaiting_wake", "running", "dispatching", "continue", "draft_review"].includes(value)) return cls.warn;
      if (["blocked", "needs_review", "finalize_negative", "failed", "error"].includes(value)) return cls.bad;
      if (value.includes("branch") || value.includes("callback")) return cls.purple;
      return cls.info;
    }
    function countRows(counts, preferred=[]) {
      const entries = [];
      const used = new Set();
      preferred.forEach(key => {
        if (counts?.[key] !== undefined) { entries.push([key, counts[key]]); used.add(key); }
      });
      Object.keys(counts || {}).sort().forEach(key => { if (!used.has(key)) entries.push([key, counts[key]]); });
      return entries.length ? `<div class="count-grid">${entries.map(([key, value]) => `<div class="count-row"><div>${pill(key, toneForLabel(key))}</div><div class="count-value">${esc(value)}</div></div>`).join("")}</div>` : `<div class="empty">No count data posted yet.</div>`;
    }
    function progress(value, total) {
      const pct = total > 0 ? Math.max(0, Math.min(100, Math.round((value / total) * 100))) : 0;
      return `<div class="progress" title="${pct}%"><span style="width:${pct}%"></span></div>`;
    }

    function renderCards() {
      const runs = snapshot.runs || [];
      const totals = snapshot.totals || {};
      const t = snapshot.telemetry || {};
      const live = Number(totals.live || 0);
      const attention = Number(totals.needs_attention || 0);
      const q = queueStats();
      const callbackPending = Number(totals.callback_pending || 0);
      const staleCallbacks = Number(totals.stale_callbacks || 0);
      const p = paperStats();
      document.getElementById("cards").innerHTML = [
        metric("Projects Total", q.total, `${q.completed} done · ${q.yet} yet to do`),
        metric("Projects Active", q.active, `${q.queued} queued · snapshot ${age(q.queue.updated_at)}`),
        metric("Outcomes", `${q.positive}/${q.negative}`, "positive / negative final decisions"),
        metric("Papers", p.total, `${p.reviewable} reviewable · ${p.publication} publication drafts`),
        metric("Queue Blocked", q.blocked, "blocked rows from intake/queue mirror"),
        metric("Wake Attention", attention, `${staleCallbacks} stale callbacks · ${callbackPending} pending`),
        metric("GPU / UMA", `${Number(t.gpu_pct||0).toFixed(1)}%`, `${t.memory_source === "nvml_dedicated" ? (t.vram_used_mib||0) + " MiB VRAM" : (t.uma_allocatable_mib||0) + " MiB allocatable"}`),
      ].join("");
      const primary = runs.find(r => r.is_live || r.needs_attention) || runs[0];
      const sig = primary ? signal(primary) : null;
      document.getElementById("heroTitle").textContent = q.blocked ? `Queue attention: ${q.blocked} blocked rows` : primary ? `${live ? "Live lane" : attention ? "Attention" : "Inactive"}: ${primary.project_name || primary.project_id}` : "No wake-gate runs found";
      document.getElementById("heroCopy").textContent = q.blocked ? `Queue mirror reports blocked work. Wake-gate process lane is ${live ? "active" : "inactive"}.` : primary ? `${sig.label}: ${sig.copy}. Raw gate state: ${primary.gate_state || "unknown"}.` : "The API is reachable but returned no runs for the current state directory.";
      document.getElementById("subtitle").textContent = `${snapshot.service?.project_root || "project root"} · ${snapshot.service?.state_dir || "state dir"}`;
      document.getElementById("serviceInfo").textContent = `sample ${snapshot.service?.sample_interval_sec || "?"}s`;
    }
    function renderOverview() {
      const q = queueStats();
      const p = paperStats();
      const donePct = q.total ? Math.round((q.completed / q.total) * 100) : 0;
      document.getElementById("overviewProjectHint").textContent = `snapshot ${age(q.queue.updated_at)}`;
      document.getElementById("overviewProjects").innerHTML = `
        <div class="summary-copy">Project queue completion is ${donePct}%: ${q.completed} done, ${q.yet} still queued or active, and ${q.blocked} blocked.</div>
        <div class="count-grid">
          <div class="count-row"><div class="count-label">Total Projects</div><div class="count-value">${esc(q.total)}</div></div>
          <div class="count-row"><div class="count-label">Done</div><div class="count-value">${esc(q.completed)}</div></div>
          <div class="count-row"><div class="count-label">Yet To Do</div><div class="count-value">${esc(q.yet)}</div></div>
          <div class="count-row"><div class="count-label">Active Now</div><div class="count-value">${esc(q.active)}</div></div>
          <div class="count-row"><div class="count-label">Queued</div><div class="count-value">${esc(q.queued)}</div></div>
          <div class="count-row"><div class="count-label">Blocked / Review</div><div class="count-value">${esc(q.blocked)}</div></div>
        </div>
        ${progress(q.completed, q.total)}`;
      document.getElementById("overviewOutcomes").innerHTML = `
        <div class="summary-copy">Outcome counts come from the queue row's last run state, not from wake-gate historical files.</div>
        <div class="count-grid">
          <div class="count-row"><div>${pill("finalize_positive", cls.good)}</div><div class="count-value">${esc(q.positive)}</div></div>
          <div class="count-row"><div>${pill("finalize_negative", cls.bad)}</div><div class="count-value">${esc(q.negative)}</div></div>
          <div class="count-row"><div>${pill("branch", cls.purple)}</div><div class="count-value">${esc(q.branch)}</div></div>
          <div class="count-row"><div>${pill("blocked", cls.bad)}</div><div class="count-value">${esc(q.blocked)}</div></div>
        </div>`;
      document.getElementById("overviewPaperHint").textContent = `snapshot ${age(p.papers.updated_at)}`;
      document.getElementById("overviewPapers").innerHTML = `
        <div class="summary-copy">${p.reviewable} papers have reviewable artifacts. ${p.publication} are publication drafts.</div>
        <div class="count-grid">
          <div class="count-row"><div class="count-label">Total Papers</div><div class="count-value">${esc(p.total)}</div></div>
          <div class="count-row"><div class="count-label">Reviewable</div><div class="count-value">${esc(p.reviewable)}</div></div>
          <div class="count-row"><div class="count-label">Publication Drafts</div><div class="count-value">${esc(p.publication)}</div></div>
          <div class="count-row"><div class="count-label">Draft Review</div><div class="count-value">${esc(p.draftReview)}</div></div>
        </div>`;
    }
    function renderProjectQueuePage() {
      const q = queueStats();
      document.getElementById("projectCards").innerHTML = [
        metric("Total", q.total, `${q.completed} completed`),
        metric("Yet To Do", q.yet, `${q.queued} queued · ${q.active} active`),
        metric("Positive / Negative", `${q.positive}/${q.negative}`, "finalized outcomes"),
        metric("Blocked", q.blocked, "needs operator or queue repair"),
      ].join("");
      document.getElementById("projectStatusHint").textContent = `${Object.keys(q.status).length} statuses · snapshot ${age(q.queue.updated_at)}`;
      document.getElementById("projectStatusBreakdown").innerHTML = countRows(q.status, ["queued", "dispatching", "awaiting_wake", "running", "completed", "blocked", "failed", "canceled"]);
      document.getElementById("projectOutcomeBreakdown").innerHTML = countRows(q.states, ["continue", "finalize_positive", "finalize_negative", "branch_new_project", "needs_review", "blocked"]);
      const rows = q.queue.rows || [];
      document.getElementById("projectRowsHint").textContent = rows.length ? `${plural(rows.length, "row")} in snapshot` : "counts only";
      if (!rows.length) {
        document.getElementById("projectRows").innerHTML = `<div class="empty">The queue snapshot has aggregate counts but no row-level list yet. Active and blocked rows still appear in Queue Attention when the intake mirror posts them.</div>`;
        return;
      }
      document.getElementById("projectRows").innerHTML = `
        <table>
          <thead><tr><th>Status</th><th>Project</th><th>Run State</th><th>Updated</th></tr></thead>
          <tbody>${rows.map(row => `<tr>
            <td>${pill(row.queue_status || "unknown", toneForLabel(row.queue_status))}</td>
            <td><div class="project-name">${esc(row.project_name || row.project_id || "unknown")}</div><div class="small mono truncate">${esc(row.project_id || "")}</div></td>
            <td>${pill(row.last_run_state || "unknown", toneForLabel(row.last_run_state))}<div class="small">${esc(compact(row.next_action_hint || row.last_result_summary || row.blocked_reason || "", 140))}</div></td>
            <td><div>${fmtDate(row.updated_at || row.created_at)}</div><div class="small">${age(row.updated_at || row.created_at)}</div></td>
          </tr>`).join("")}</tbody>
        </table>`;
    }
    function renderPaperQueuePage() {
      const p = paperStats();
      const q = queueStats();
      document.getElementById("paperCards").innerHTML = [
        metric("Total Papers", p.total, `${p.reviewable} reviewable artifacts`),
        metric("Publication Drafts", p.publication, "ready for final review lane"),
        metric("Draft Candidates", Number(q.queue.draft_candidate_count || 0), "eligible positive projects"),
        metric("Polish Candidates", Number(q.queue.polish_candidate_count || 0), "eligible existing drafts"),
      ].join("");
      document.getElementById("paperStatusHint").textContent = `${Object.keys(p.status).length} statuses · snapshot ${age(p.papers.updated_at)}`;
      document.getElementById("paperStatusBreakdown").innerHTML = countRows(p.status, ["queued", "generating", "draft_review", "ready_for_review", "publication_draft", "failed", "error"]);
      document.getElementById("paperTypeBreakdown").innerHTML = countRows(p.types, ["research_note", "publication", "evaluation_report"]);
    }
    function renderFilters() {
      const select = document.getElementById("stateFilter");
      const current = select.value;
      const states = [...new Set((snapshot.runs||[]).map(r => r.lifecycle_state || r.gate_state || "unknown"))].sort();
      select.innerHTML = `<option value="">All states</option>` + states.map(s => `<option value="${esc(s)}">${esc(s)}</option>`).join("");
      select.value = states.includes(current) ? current : "";
    }
    function signalFilterMatches(run, filter) {
      if (!filter) return true;
      const lifecycle = String(run.lifecycle_state || "").toLowerCase();
      const label = signal(run).label.toLowerCase();
      if (filter === "active") return Boolean(run.is_live) || ["active", "settling", "question_pending", "callback_pending"].includes(lifecycle);
      if (filter === "attention") return Boolean(run.needs_attention) || ["attention", "stale_callback_ready", "question_pending", "error"].includes(lifecycle);
      if (filter === "pending") return ["callback_pending", "stale_callback_ready"].includes(lifecycle);
      if (filter === "delivered") return ["callback_delivered", "finished_delivered"].includes(lifecycle);
      if (filter === "settling") return lifecycle === "settling" || ["waiting_for_quiet_window", "waiting_for_process_exit", "pending_idle_gate", "finished_pending_gate"].includes(String(run.gate_state || "").toLowerCase());
      if (filter === "historical") return Boolean(run.is_historical) || lifecycle === "superseded";
      return label.includes(filter);
    }
    function rowMatches(run) {
      const q = document.getElementById("search").value.toLowerCase();
      const state = document.getElementById("stateFilter").value;
      const sf = document.getElementById("signalFilter").value;
      const hay = [run.project_id, run.project_name, run.run_id, run.session_id, run.gate_state, run.lifecycle_state, run.operator_status, run.current_activity, run.project_decision?.project_decision, run.project_decision?.recommended_next_action].join(" ").toLowerCase();
      return (!q || hay.includes(q)) && (!state || (run.lifecycle_state || run.gate_state) === state) && signalFilterMatches(run, sf);
    }
    function renderQueueAttention() {
      const queue = snapshot.queue || {};
      const counts = queue.status_counts || {};
      const blocked = queue.blocked_rows || [];
      const activeRows = queue.active_rows || [];
      const blockedCount = Number(counts.blocked || blocked.length || 0);
      const activeCount = Number(counts.dispatching || 0) + Number(counts.awaiting_wake || 0) + Number(counts.running || 0) || activeRows.length;
      const panel = document.getElementById("queuePanel");
      panel.style.display = (blockedCount || activeCount) ? "block" : "none";
      document.getElementById("queueHint").textContent = `${blockedCount} blocked · ${activeCount} active · snapshot ${age(queue.updated_at)}`;
      if (!blockedCount && !activeCount) {
        document.getElementById("queueAttention").innerHTML = `<div class="empty">No queue-level blocked or active rows.</div>`;
        return;
      }
      const rowCard = (row, tone, fallback) => `
        <div class="event">
          <div class="event-top">
            <span class="event-name">${esc(row.project_name || row.project_id || "unknown project")}</span>
            ${pill(row.queue_status || row.next_action_hint || fallback, tone)}
          </div>
          <div class="event-detail">${esc(compact(row.next_action_hint || row.blocked_reason || row.last_result_summary || "No notes yet.", 260))}</div>
          <div class="small mono">${esc(row.project_id || "")}${row.current_run_id ? " · " + esc(row.current_run_id) : ""}</div>
        </div>`;
      const activeHtml = activeRows.length
        ? activeRows.map(row => rowCard(row, cls.good, "active")).join("")
        : activeCount ? `<div class="empty">Queue reports ${activeCount} active rows; snapshot did not include row details.</div>` : "";
      const blockedHtml = blocked.length ? blocked.map(row => rowCard(row, cls.bad, "blocked")).join("") : `<div class="empty">No blocked row details.</div>`;
      document.getElementById("queueAttention").innerHTML = `
        <div class="note">This is the intake/queue mirror, not wake-gate runfile history. These rows should match the operator-facing queue state.</div>
        ${activeCount ? `<div class="section-title">Queue active</div>${activeHtml}` : ""}
        <div class="section-title">Blocked queue rows</div>
        ${blockedHtml}`;
    }
    function paperTone(status) {
      status = String(status || "").toLowerCase();
      if (["publication_draft", "ready_for_review", "draft_review"].includes(status)) return cls.good;
      if (["error", "failed"].includes(status)) return cls.bad;
      if (["queued", "polishing", "generating"].includes(status)) return cls.warn;
      return cls.info;
    }
    function paperPaths(row) {
      return [
        ["Markdown", row.draft_markdown_path],
        ["LaTeX", row.draft_latex_path],
        ["Claim audit", row.claim_ledger_path],
        ["Evidence", row.evidence_bundle_path],
        ["Manifest", row.manifest_path],
      ].filter(([, path]) => path);
    }
    function paperMatches(row) {
      const q = document.getElementById("paperSearch")?.value.toLowerCase() || "";
      const status = document.getElementById("paperStatusFilter")?.value || "";
      const hay = [row.paper_id, row.project_id, row.project_name, row.paper_status, row.paper_type, row.model_used, row.evidence_strength, row.hypothesis_status, row.project_decision, row.review_notes, row.last_error].join(" ").toLowerCase();
      return (!q || hay.includes(q)) && (!status || row.paper_status === status);
    }
    function renderPaperFilters() {
      const select = document.getElementById("paperStatusFilter");
      if (!select) return;
      const current = select.value;
      const rows = snapshot.papers?.latest_rows || [];
      const statuses = [...new Set(rows.map(r => r.paper_status || "unknown"))].sort();
      select.innerHTML = `<option value="">All paper statuses</option>` + statuses.map(s => `<option value="${esc(s)}">${esc(s)}</option>`).join("");
      select.value = statuses.includes(current) ? current : "";
    }
    function renderPapers() {
      const panel = document.getElementById("paperPanel");
      if (!panel) return;
      const rowsAll = snapshot.papers?.latest_rows || [];
      panel.style.display = rowsAll.length ? "grid" : "none";
      if (!rowsAll.length) return;
      renderPaperFilters();
      const rows = rowsAll.filter(paperMatches);
      document.getElementById("paperHint").textContent = `${plural(rows.length, "paper")} visible · snapshot ${age(snapshot.papers?.updated_at)}`;
      document.getElementById("paperEmpty").style.display = rows.length ? "none" : "block";
      document.getElementById("papers").innerHTML = rows.map(row => {
        const reviewPaths = paperPaths(row);
        const note = compact(row.review_notes || row.last_error || "No review notes", 160);
        return `<tr class="${row.paper_id === selectedPaperId ? "selected" : ""}" data-paper="${esc(row.paper_id)}">
          <td>${pill(row.paper_status || "unknown", paperTone(row.paper_status))}<div class="small">${esc(row.paper_type || "paper")} · ${esc(row.model_used || "unknown model")}</div></td>
          <td><div class="project-name">${esc(row.project_name || row.project_id || "unknown")}</div><div class="small mono truncate">${esc(row.paper_id || "")}</div></td>
          <td>${pill(row.evidence_strength || "unknown", row.evidence_strength === "strong" ? cls.good : cls.warn)}<div class="small">${esc(row.hypothesis_status || "")} · ${plural(reviewPaths.length, "artifact")}</div><div class="small">${esc(note)}</div></td>
          <td><div>${fmtDate(row.updated_at || row.generated_at)}</div><div class="small">${age(row.updated_at || row.generated_at)}</div></td>
        </tr>`;
      }).join("");
      document.querySelectorAll("#papers tr").forEach(tr => tr.addEventListener("click", () => {
        selectedPaperId = tr.dataset.paper;
        selectedPaperPath = null;
        renderPapers();
        renderPaperReader();
      }));
      renderPaperReader();
    }
    async function loadPaperArtifact(projectId, path) {
      const reader = document.getElementById("paperReader");
      reader.innerHTML = `<div class="empty">Loading ${esc(path)}…</div>`;
      try {
        const headers = token() ? {Authorization:`Bearer ${token()}`} : {};
        const url = `/dashboard/api/paper-artifact/${encodeURIComponent(projectId)}?path=${encodeURIComponent(path)}`;
        const res = await fetch(url, {headers});
        if (!res.ok) throw new Error(`${res.status}: ${await res.text()}`);
        const data = await res.json();
        const openUrl = `/dashboard/paper-artifact/${encodeURIComponent(projectId)}?path=${encodeURIComponent(path)}${token() ? `&token=${encodeURIComponent(token())}` : ""}`;
        reader.innerHTML = `
          ${kv("Artifact", `<span class="mono">${esc(data.path)}</span>`)}
          ${kv("Bytes", esc(data.bytes))}
          <div class="review-actions"><button id="backToPaper">Back to paper</button><a target="_blank" rel="noopener" href="${esc(openUrl)}">Open full review</a></div>
          <details class="raw paper-preview" open><summary>Artifact content</summary><pre>${esc(data.content)}</pre></details>`;
        document.getElementById("backToPaper").onclick = () => { selectedPaperPath = null; renderPaperReader(); };
      } catch (err) {
        reader.innerHTML = `<div class="note">Could not load artifact: ${esc(err.message)}</div><div class="review-actions"><button id="backToPaper">Back to paper</button></div>`;
        document.getElementById("backToPaper").onclick = () => { selectedPaperPath = null; renderPaperReader(); };
      }
    }
    function renderPaperReader() {
      const row = (snapshot.papers?.latest_rows || []).find(r => r.paper_id === selectedPaperId) || (snapshot.papers?.latest_rows || [])[0];
      const reader = document.getElementById("paperReader");
      if (!reader) return;
      if (!row) { reader.innerHTML = `<div class="empty">No paper selected.</div>`; return; }
      selectedPaperId = row.paper_id;
      document.getElementById("paperSelectedHint").textContent = row.project_name || row.project_id || "selected";
      if (selectedPaperPath) { loadPaperArtifact(row.project_id, selectedPaperPath); return; }
      const paths = paperPaths(row);
      const buttons = paths.map(([label, path]) => `<button data-paper-path="${esc(path)}">Review ${esc(label)}</button>`).join("");
      const notion = row.notion_page_url ? `<a target="_blank" rel="noopener" href="${esc(row.notion_page_url)}">Open Notion</a>` : "";
      reader.innerHTML = `
        ${kv("Paper", `<strong>${esc(row.project_name || row.project_id || "unknown")}</strong><div class="small mono">${esc(row.paper_id || "")}</div>`)}
        ${kv("Status", `${pill(row.paper_status || "unknown", paperTone(row.paper_status))} ${pill(row.paper_type || "paper", cls.info)}`)}
        ${kv("Generated", `${fmtDate(row.generated_at)} · updated ${age(row.updated_at || row.generated_at)}`)}
        ${kv("Decision", `${esc(row.project_decision || "—")} · ${esc(row.hypothesis_status || "unknown")} · ${esc(row.evidence_strength || "unknown")} evidence`)}
        ${kv("Model", esc(row.model_used || "—"))}
        ${kv("Review notes", esc(row.review_notes || row.last_error || "—"))}
        <div class="section-title">Review artifacts</div>
        <div class="review-actions">${buttons || `<span class="small">No artifact paths in snapshot.</span>`}${notion}</div>
        <div class="section-title">Paths</div>
        <div class="files">${paths.map(([label, path]) => `<span class="file mono">${esc(label)}: ${esc(path)}</span>`).join("")}</div>
        <details class="raw"><summary>Developer JSON</summary><pre>${esc(JSON.stringify(row, null, 2))}</pre></details>`;
      document.querySelectorAll("[data-paper-path]").forEach(btn => btn.addEventListener("click", () => { selectedPaperPath = btn.dataset.paperPath; renderPaperReader(); }));
    }

    function renderRuns() {
      const rows = (snapshot.runs || []).filter(rowMatches);
      document.getElementById("runCount").textContent = `${plural(rows.length, "run")} visible`;
      document.getElementById("empty").style.display = rows.length ? "none" : "block";
      document.getElementById("runs").innerHTML = rows.map(run => {
        const s = signal(run); const decision = run.project_decision?.project_decision || "—";
        const note = compact((run.run_notes_tail || []).slice(-1)[0] || run.project_decision?.recommended_next_action || run.current_activity || "", 170);
        return `<tr class="${run.run_id === selectedRunId ? "selected" : ""}" data-run="${esc(run.run_id)}">
          <td>${pill(s.label, s.tone)}<div class="small">${esc(s.copy)}</div></td>
          <td><div class="project-name">${esc(run.project_name || run.project_id || "unknown")}</div><div class="small mono truncate">${esc(run.run_id || "")}</div></td>
          <td>${pill(run.lifecycle_state || run.gate_state || "unknown", stateTone(run.lifecycle_state || run.gate_state))}<div class="small">raw ${esc(run.gate_state || "unknown")} · updated ${age(run.updated_at)}</div></td>
          <td><div>${esc(note || "No notes yet")}</div><div class="small">${plural(run.active_process_count || 0, "process")} · ${plural((run.result_files||[]).length, "artifact")}</div></td>
          <td>${pill(decision, decision === "blocked" ? cls.bad : decision.includes("finalize") ? cls.purple : cls.info)}<div class="small">${esc(run.project_decision?.hypothesis_status || "")}</div></td>
        </tr>`;
      }).join("");
      document.querySelectorAll("#runs tr").forEach(tr => tr.addEventListener("click", () => { selectedRunId = tr.dataset.run; renderRuns(); renderSelected(); }));
    }
    function kv(k, v) { return `<div class="kv"><div class="k">${esc(k)}</div><div class="v">${v}</div></div>`; }
    function renderSelected() {
      const run = (snapshot.runs || []).find(r => r.run_id === selectedRunId) || (snapshot.runs || [])[0];
      if (!run) { document.getElementById("selected").innerHTML = `<div class="empty">No run selected.</div>`; return; }
      const s = signal(run);
      document.getElementById("selectedHint").textContent = run.project_id || run.run_id || "selected";
      const processes = (run.active_processes || []).length ? (run.active_processes || []).map(p => `<div class="process"><strong class="mono">${esc(p.pid)}</strong> <span class="small">${esc(p.elapsed_sec ?? "?")}s</span><div class="mono small">${esc(compact(p.cmdline, 220))}</div></div>`).join("") : `<div class="empty">No active processes for this run.</div>`;
      const notes = (run.run_notes_tail || []).length ? `<div class="notes">${(run.run_notes_tail || []).slice(-8).map(n => `<div class="note">${esc(n)}</div>`).join("")}</div>` : `<div class="empty">No run notes captured.</div>`;
      const files = (run.result_files || []).length ? `<div class="files">${(run.result_files || []).map(f => `<span class="file mono">${esc(f)}</span>`).join("")}</div>` : `<div class="empty">No result artifacts listed.</div>`;
      const recent = (run.recent_files || []).length ? `<div class="files">${(run.recent_files || []).map(f => `<span class="file mono">${esc(f)}</span>`).join("")}</div>` : `<div class="empty">No recent files listed.</div>`;
      const d = run.project_decision;
      const decision = d ? [kv("Decision", pill(d.project_decision, d.project_decision === "blocked" ? cls.bad : cls.info)), kv("Hypothesis", esc(d.hypothesis_status)), kv("Evidence", `${esc(d.evidence_strength)} / ${esc(d.confidence)} confidence`), kv("Next action", esc(d.recommended_next_action || "—")), kv("Stop reason", esc(d.stop_reason || "—"))].join("") : `<div class="empty">No project decision artifact found.</div>`;
      document.getElementById("selected").innerHTML = `
        <div class="tabs"><span class="tab active">Operator View</span>${pill(s.label, s.tone)}${pill(run.gate_state || "unknown", stateTone(run.gate_state))}</div>
        ${kv("Project", `<strong>${esc(run.project_name || run.project_id || "unknown")}</strong><div class="small mono">${esc(run.project_id || "")}</div>`)}
        ${kv("Operator status", `${pill(s.label, s.tone)}<div class="small">${esc(s.copy)}</div>`)}
        ${kv("Raw gate state", `<span class="mono">${esc(run.gate_state || "—")}</span>`)}
        ${kv("Activity", esc(run.current_activity || "—"))}
        ${kv("Session", `<span class="mono">${esc(run.session_id || "—")}</span>`)}
        ${kv("Wake evidence", `idle ${fmtDate(run.idle_seen_at)} · last event ${esc(run.last_event || "—")} ${age(run.last_event_at)}`)}
        ${kv("Quiet samples", `${plural((run.quiet_samples || []).length, "sample")} · CPU/GPU currently shown in telemetry card`)}
        <div class="section-title">Decision</div>${decision}
        <div class="section-title">Active processes</div>${processes}
        <div class="section-title">Run notes</div>${notes}
        <div class="section-title">Result artifacts</div>${files}
        <div class="section-title">Recent files</div>${recent}
        <details class="raw"><summary>Developer JSON (full compact row)</summary><pre>${esc(JSON.stringify(run, null, 2))}</pre></details>`;
    }
    function renderTelemetry() {
      const t = snapshot.telemetry || {}; const by = snapshot.totals?.by_lifecycle || {}; const q = snapshot.queue || {};
      document.getElementById("telemetry").innerHTML = `
        <div class="grid" style="grid-template-columns:1fr 1fr">
          ${pill(`CPU ${Number(t.cpu_pct||0).toFixed(1)}%`, cls.info)}
          ${pill(`GPU ${Number(t.gpu_pct||0).toFixed(1)}%`, cls.info)}
          ${pill(t.memory_source === "nvml_dedicated" ? `VRAM ${t.vram_used_mib||0} MiB` : `UMA free+swap ${t.uma_allocatable_mib||0} MiB`, cls.purple)}
          ${pill(`${plural((t.gpu_compute_pids||[]).length, "GPU PID")}`, cls.good)}
          ${pill(`Memory ${esc(t.memory_source || "unknown")}`, cls.info)}
        </div>
        <div class="section-title">Truthful lifecycle mix</div>
        ${Object.keys(by).sort().map(k => kv(k, `<strong>${esc(by[k])}</strong>`)).join("") || `<div class="empty">No state data.</div>`}
        <div class="section-title">Queue mirror</div>
        ${q.status_counts ? Object.keys(q.status_counts).sort().map(k => kv(k, `<strong>${esc(q.status_counts[k])}</strong>`)).join("") : `<div class="empty">No queue snapshot posted yet.</div>`}`;
    }
    function renderEvents() {
      const events = snapshot.events || [];
      document.getElementById("eventCount").textContent = plural(events.length, "event");
      document.getElementById("events").innerHTML = events.length ? events.map(e => {
        const okTone = e.ok === true ? cls.good : e.ok === false ? cls.bad : cls.warn;
        const title = e.kind || e.event || e.event_type || "event";
        const detail = e.detail || e.reason || e.message || e.raw_preview || "";
        return `<div class="event"><div class="event-top"><span class="event-name">${esc(title)}</span>${pill(e.event_type || (e.ok === true ? "ok" : e.ok === false ? "failed" : "event"), okTone)}</div><div class="event-detail">${esc(compact(detail, 190))}</div><div class="small mono">${esc(e.run_id || "")} · ${fmtDate(e.timestamp)}</div></div>`;
      }).join("") : `<div class="empty">No recent events.</div>`;
    }
    function render() { renderCards(); renderOverview(); renderProjectQueuePage(); renderPaperQueuePage(); renderQueueAttention(); renderPapers(); renderFilters(); renderRuns(); renderSelected(); renderTelemetry(); renderEvents(); setPage(currentPage, false); }
    document.getElementById("tokenBtn").onclick = setToken;
    document.getElementById("refreshBtn").onclick = load;
    document.getElementById("autoBtn").onclick = () => { auto=!auto; document.getElementById("autoBtn").textContent=`Auto: ${auto ? "on" : "off"}`; if (timer) clearInterval(timer); timer = auto ? setInterval(load, 10000) : null; };
    document.querySelectorAll("[data-page]").forEach(btn => btn.addEventListener("click", () => setPage(btn.dataset.page)));
    window.addEventListener("hashchange", initPageFromHash);
    document.getElementById("search").oninput = renderRuns;
    document.getElementById("stateFilter").onchange = renderRuns;
    document.getElementById("signalFilter").onchange = renderRuns;
    document.getElementById("paperSearch").oninput = () => { renderPapers(); renderPaperReader(); };
    document.getElementById("paperStatusFilter").onchange = () => { renderPapers(); renderPaperReader(); };
    bootstrapTokenFromUrl(); initPageFromHash(); timer=setInterval(load, 10000); load();
  </script>
</body>
</html>
"""


@app.get("/healthz")
def healthz() -> dict:
    return {"ok": True, "service": "omx_wake_gate", "timestamp": utc_now()}


def _require_local_bearer(authorization: str | None) -> None:
    expected = f"Bearer {config.omx_inbound_bearer_token}"
    if authorization != expected:
        raise HTTPException(status_code=401, detail="invalid bearer token")


def _require_dashboard_bearer(authorization: str | None, token: str | None = None) -> None:
    if authorization is None and token:
        authorization = f"Bearer {token}"
    _require_local_bearer(authorization)


app.include_router(create_enoch_core_router(config, _require_local_bearer))
app.include_router(create_control_plane_router(config, _require_local_bearer))


def _resolve_under_root(path_str: str, root: Path) -> Path:
    raw = Path(path_str).expanduser()
    candidate = raw if raw.is_absolute() else root / raw
    resolved = candidate.resolve()
    root_resolved = root.expanduser().resolve()
    try:
        resolved.relative_to(root_resolved)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=f"path escapes configured project root: {path_str}") from exc
    return resolved


def _write_text(path: Path, text: str, overwrite: bool) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists() and not overwrite:
        raise HTTPException(status_code=409, detail=f"refusing to overwrite existing file: {path}")
    path.write_text(text, encoding="utf-8")


def _normalize_prepare_metadata(metadata: dict[str, Any]) -> dict[str, Any]:
    normalized = dict(metadata or {})
    try:
        workload_class, _ = config.resolve_workload_profile(normalized.get("workload_class"))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    normalized["workload_class"] = workload_class
    return normalized


def _load_project_metadata(project_dir: Path) -> dict[str, Any]:
    path = project_dir / ".omx" / "project.json"
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=500, detail=f"invalid project metadata JSON: {path}") from exc
    if not isinstance(payload, dict):
        raise HTTPException(status_code=500, detail=f"project metadata must be a JSON object: {path}")
    return payload


def _resolve_workload_profile_for_project_dir(project_dir: Path) -> tuple[str, Any]:
    payload = _load_project_metadata(project_dir)
    metadata = payload.get("metadata")
    if metadata is not None and not isinstance(metadata, dict):
        raise HTTPException(
            status_code=500,
            detail=f"project metadata 'metadata' field must be an object: {project_dir / '.omx' / 'project.json'}",
        )
    try:
        return config.resolve_workload_profile((metadata or {}).get("workload_class"))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


def _assign_record_workload_profile(record: RunRecord) -> RunRecord:
    if record.workload_class and record.workload_profile is not None:
        return record

    project_dir: Path | None = None
    if record.project_dir:
        try:
            project_dir = _resolve_under_root(record.project_dir, config.expanded_project_root)
        except HTTPException:
            project_dir = None
    elif record.project_id:
        try:
            project_dir = _resolve_under_root(record.project_id, config.expanded_project_root)
        except HTTPException:
            project_dir = None

    if project_dir is not None:
        workload_class, workload_profile = _resolve_workload_profile_for_project_dir(project_dir)
        record.project_dir = str(project_dir)
    else:
        workload_class, workload_profile = config.resolve_workload_profile(record.workload_class)
    record.workload_class = workload_class
    record.workload_profile = workload_profile
    return record


def _wake_decision_profile_evidence(record: RunRecord) -> dict[str, Any]:
    workload_class = record.workload_class or config.normalize_workload_class(None)
    workload_profile = record.workload_profile
    if workload_profile is None:
        workload_class, workload_profile = config.resolve_workload_profile(workload_class)
    return {
        "workload_class": workload_class,
        "workload_profile_name": workload_class,
        "workload_thresholds": workload_profile.model_dump(),
    }


def _resolve_project_relative_path(project_dir: Path, relative_path: str) -> Path:
    raw = Path(relative_path)
    if raw.is_absolute():
        raise HTTPException(status_code=400, detail=f"paper artifact path must be relative: {relative_path}")
    if not relative_path.strip():
        raise HTTPException(status_code=400, detail="paper artifact path cannot be empty")
    if any(part in {"", ".", ".."} for part in raw.parts):
        raise HTTPException(status_code=400, detail=f"paper artifact path contains unsafe segment: {relative_path}")

    resolved = (project_dir / raw).resolve()
    try:
        resolved.relative_to(project_dir.resolve())
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=f"paper artifact path escapes project directory: {relative_path}") from exc
    return resolved


def _find_run_record(project_id: str, run_id: str | None = None) -> RunRecord | None:
    if run_id:
        record = store.load_run(run_id)
        if record is not None:
            return record

    candidates = [record for record in store.list_runs() if record.project_id == project_id]
    if not candidates:
        return None
    candidates.sort(key=lambda record: (record.updated_at or "", record.last_event_at or "", record.created_at or ""), reverse=True)
    return candidates[0]


def _resolve_project_dir(project_id: str, project_dir: str | None) -> Path:
    if project_dir:
        return _resolve_under_root(project_dir, config.expanded_project_root)
    return _resolve_under_root(project_id, config.expanded_project_root)


def _safe_read_json(path: Path) -> dict[str, Any]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ValueError(f"decision file not found: {path}") from exc
    except json.JSONDecodeError as exc:
        raise ValueError(f"invalid JSON in decision file: {path}") from exc


def _coerce_project_decision(raw: dict[str, Any], source: str, source_path: Path | None = None) -> ProjectDecision:
    action = str(raw.get("project_decision") or raw.get("decision") or "").strip()
    if action not in {"continue", "finalize_negative", "finalize_positive", "branch_new_project", "blocked", "needs_review"}:
        raise ValueError(f"unsupported project decision: {action or '<missing>'}")

    hypothesis_status = str(raw.get("hypothesis_status") or "inconclusive").strip() or "inconclusive"
    if hypothesis_status not in {"supported", "unsupported", "mixed", "inconclusive"}:
        hypothesis_status = "inconclusive"

    confidence = str(raw.get("confidence") or "medium").strip() or "medium"
    if confidence not in {"low", "medium", "high"}:
        confidence = "medium"

    evidence_strength = str(raw.get("evidence_strength") or "moderate").strip() or "moderate"
    if evidence_strength not in {"weak", "moderate", "strong"}:
        evidence_strength = "moderate"

    return ProjectDecision(
        project_decision=action,
        hypothesis_status=hypothesis_status,
        confidence=confidence,
        evidence_strength=evidence_strength,
        novelty_progress=bool(raw.get("novelty_progress", False)),
        results_changed=bool(raw.get("results_changed", False)),
        recommended_next_action=str(raw.get("recommended_next_action") or "").strip(),
        stop_reason=str(raw.get("stop_reason") or "").strip(),
        branch_project_name=str(raw.get("branch_project_name") or "").strip() or None,
        branch_reason=str(raw.get("branch_reason") or "").strip() or None,
        decision_source=source,
        source_path=source_path.as_posix() if source_path else None,
        updated_at=str(raw.get("updated_at") or raw.get("generated_at") or raw.get("prepared_at") or utc_now()),
    )


def _project_decision_from_summary(summary: dict[str, Any], source_path: Path) -> ProjectDecision:
    native = summary.get("native_phase") if isinstance(summary.get("native_phase"), dict) else {}
    alternative = summary.get("alternative_deployment_branch") if isinstance(summary.get("alternative_deployment_branch"), dict) else {}
    recommendation = str(summary.get("recommendation") or "").strip()
    native_kill = str(native.get("kill_condition_status") or "").strip()
    alternative_status = str(alternative.get("status") or "").strip()

    action = "continue"
    hypothesis_status = "inconclusive"
    confidence = "medium"
    evidence_strength = "moderate"
    stop_reason = ""
    branch_project_name = None
    branch_reason = None

    if native_kill == "supported" or "falsified" in recommendation.lower():
        action = "finalize_negative"
        hypothesis_status = "unsupported"
        confidence = "high"
        evidence_strength = "strong"
        stop_reason = "Static selective up-precision thesis is falsified on the current native evidence."
        if alternative_status.startswith("supported"):
            branch_project_name = "Bonsai-Up Profile Variation Branch"
            branch_reason = "Profile variation appears promising but should be treated as a separate project from the falsified static-mask thesis."
    elif alternative_status.startswith("supported"):
        action = "branch_new_project"
        hypothesis_status = "mixed"
        confidence = "medium"
        evidence_strength = "moderate"
        stop_reason = "A different profile-variation mechanism looks promising enough to split into its own project."
        branch_project_name = "Bonsai-Up Profile Variation Branch"
        branch_reason = "Alternative deployment branch cleared cost-normalized support while the original thesis remained mixed."

    return ProjectDecision(
        project_decision=action,
        hypothesis_status=hypothesis_status,
        confidence=confidence,
        evidence_strength=evidence_strength,
        novelty_progress=False,
        results_changed=True,
        recommended_next_action=recommendation,
        stop_reason=stop_reason or recommendation,
        branch_project_name=branch_project_name,
        branch_reason=branch_reason,
        decision_source="summary_fallback",
        source_path=source_path.as_posix(),
        updated_at=utc_now(),
    )


def _load_project_decision(
    project_dir: Path,
    *,
    include_summary_fallback: bool = True,
) -> tuple[ProjectDecision | None, str | None]:
    explicit_path = project_dir / ".omx" / "project_decision.json"
    if explicit_path.exists():
        try:
            return _coerce_project_decision(_safe_read_json(explicit_path), "codex_turn", explicit_path), None
        except ValueError as exc:
            return None, str(exc)

    if not include_summary_fallback:
        return None, None

    summary_candidates = sorted(project_dir.glob("results/**/project_decision_summary/summary.json"))
    for candidate in summary_candidates:
        try:
            return _project_decision_from_summary(_safe_read_json(candidate), candidate), None
        except ValueError as exc:
            return None, str(exc)

    return None, None


def _tail_lines(path: Path, limit: int = 30) -> list[str]:
    if not path.exists() or not path.is_file():
        return []
    try:
        with path.open("r", encoding="utf-8", errors="ignore") as handle:
            lines = [line.rstrip() for line in deque(handle, maxlen=limit)]
    except OSError:
        return []
    return [line for line in lines if line.strip()]


def _recent_files(
    project_dir: Path,
    limit: int = 12,
    *,
    max_entries: int = 2_500,
    max_seconds: float = 0.35,
) -> list[str]:
    ignore_dirs = {
        ".venv",
        ".git",
        "__pycache__",
        ".mypy_cache",
        ".pytest_cache",
        ".ruff_cache",
        "node_modules",
        "dist",
        "build",
        ".tox",
    }
    ignored_roots = {
        ("results",),
        ("artifacts",),
        (".omx", "state"),
        (".omx", "logs"),
    }
    collected: list[tuple[float, str]] = []
    scanned = 0
    deadline = time.monotonic() + max_seconds
    for root, dirs, files in os.walk(project_dir):
        if scanned >= max_entries or time.monotonic() > deadline:
            break
        root_path = Path(root)
        rel_root = root_path.relative_to(project_dir)
        if any(part in ignore_dirs for part in rel_root.parts) or any(
            rel_root.parts[: len(parts)] == parts for parts in ignored_roots
        ):
            dirs[:] = []
            continue
        dirs[:] = [directory for directory in dirs if directory not in ignore_dirs]
        for filename in files:
            scanned += 1
            if scanned > max_entries or time.monotonic() > deadline:
                break
            path = root_path / filename
            rel = path.relative_to(project_dir)
            try:
                stat = path.stat()
            except OSError:
                continue
            entry = (stat.st_mtime, f"{Path(path).relative_to(project_dir)}")
            if len(collected) < limit:
                heapq.heappush(collected, entry)
            else:
                heapq.heappushpop(collected, entry)
    return [
        f"{Path(path).as_posix()}"
        for _, path in sorted(collected, key=lambda item: item[0], reverse=True)
    ]


def _result_files(
    project_dir: Path,
    limit: int = 20,
    *,
    max_entries: int = 2_500,
    max_seconds: float = 0.35,
) -> list[str]:
    collected: list[tuple[float, str]] = []
    scanned = 0
    deadline = time.monotonic() + max_seconds
    for folder_name in ("results", "artifacts"):
        root = project_dir / folder_name
        if not root.exists():
            continue
        for current_root, dirs, files in os.walk(root):
            if scanned >= max_entries or time.monotonic() > deadline:
                break
            dirs[:] = [
                directory
                for directory in dirs
                if directory not in {".git", "__pycache__", ".mypy_cache", ".pytest_cache"}
            ]
            for filename in files:
                scanned += 1
                if scanned > max_entries or time.monotonic() > deadline:
                    break
                path = Path(current_root) / filename
                if not path.is_file():
                    continue
                try:
                    stat = path.stat()
                except OSError:
                    continue
                entry = (stat.st_mtime, path.relative_to(project_dir).as_posix())
                if len(collected) < limit:
                    heapq.heappush(collected, entry)
                else:
                    heapq.heappushpop(collected, entry)
        if scanned >= max_entries or time.monotonic() > deadline:
            break
    return [path for _, path in sorted(collected, key=lambda item: item[0], reverse=True)]


def _tail_jsonl(path: Path, limit: int = 80) -> list[str]:
    if not path.exists():
        return []
    try:
        with path.open("r", encoding="utf-8", errors="ignore") as handle:
            return [line.rstrip("\n") for line in deque(handle, maxlen=limit)]
    except OSError:
        return []


def _latest_session(project_dir: Path) -> SessionHistoryEntry | None:
    history_path = project_dir / ".omx" / "logs" / "session-history.jsonl"
    if not history_path.exists():
        return None
    latest: dict[str, Any] | None = None
    try:
        for line in history_path.read_text(encoding="utf-8", errors="ignore").splitlines():
            line = line.strip()
            if not line:
                continue
            latest = json.loads(line)
    except (OSError, json.JSONDecodeError):
        return None
    if latest is None:
        return None
    return SessionHistoryEntry.model_validate(latest)


def _activity_from_processes(processes: list[ProcessInfo], gate_state: str | None) -> str:
    if not processes:
        return gate_state or "idle"

    preferred: ProcessInfo | None = None
    for process in processes:
        cmd = process.cmdline
        if any(marker in cmd for marker in ("notify-fallback", "notify-hook", "/bin/omx exec", "/usr/bin/codex exec")):
            continue
        if cmd.strip() in {"-bash", "bash", "-sh", "sh", "-zsh", "zsh", "fish", "-fish", "jq"} or cmd.startswith("tail -f "):
            continue
        preferred = process
        break
    preferred = preferred or processes[0]
    cmd = preferred.cmdline.strip()
    if len(cmd) > 160:
        cmd = cmd[:157] + "..."
    return f"running {cmd}" if cmd else (gate_state or "running")


def _read_recent_events(limit: int = 80) -> list[dict[str, Any]]:
    if not store.events_log.exists():
        return []

    events: list[dict[str, Any]] = []
    for line in reversed(_tail_jsonl(store.events_log, max(limit * 8, limit, 80))):
        line = line.strip()
        if not line:
            continue
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            event = {"kind": "unparseable_event", "raw": line}
        events.append(event)
        if len(events) >= limit:
            break
    return events


def _truncate(value: str | None, max_chars: int) -> str:
    text = value or ""
    if len(text) <= max_chars:
        return text
    return text[: max(0, max_chars - 20)].rstrip() + "\n[truncated]"


def _trim_event(event: dict[str, Any], max_chars: int = 1600) -> dict[str, Any]:
    encoded = json.dumps(event, sort_keys=True)
    if len(encoded) <= max_chars:
        return event
    trimmed = {
        key: event.get(key)
        for key in ("kind", "event", "event_type", "run_id", "session_id", "project_id", "ok", "timestamp")
        if key in event
    }
    trimmed["truncated"] = True
    trimmed["raw_preview"] = _truncate(encoded, max_chars)
    return trimmed


def _parse_timestamp(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def _record_age_seconds(record: RunRecord) -> float | None:
    parsed = _parse_timestamp(record.updated_at or record.last_event_at or record.created_at)
    if parsed is None:
        return None
    return (datetime.now(timezone.utc) - parsed).total_seconds()


def _callback_delivered(record: RunRecord) -> bool:
    if record.gate_state not in {GateState.WAKE_READY, GateState.FINISHED_READY}:
        return False
    if not record.last_idempotency_key:
        return False
    delivered_events = {"wake_ready", "session_finished_ready"}
    parts = record.last_idempotency_key.split(":")
    return len(parts) >= 3 and parts[0] == record.run_id and parts[1] in delivered_events


def _dashboard_truth(
    record: RunRecord,
    active_processes: list[ProcessInfo],
    *,
    superseded: bool = False,
) -> dict[str, Any]:
    state = record.gate_state
    delivered = _callback_delivered(record)
    age_seconds = _record_age_seconds(record)
    stale_seconds = max(config.idle_sustain_sec * 2, config.sample_interval_sec * 12, 300)
    stale_callback = (
        state in {GateState.WAKE_READY, GateState.FINISHED_READY}
        and not delivered
        and age_seconds is not None
        and age_seconds > stale_seconds
    )

    if active_processes:
        lifecycle = "active"
        status = "Active"
        detail = "Codex or project-owned processes are still running."
        is_live = True
        needs_attention = False
    elif superseded:
        lifecycle = "superseded"
        status = "Superseded"
        detail = "A newer run exists for this project; this older record is historical evidence, not current attention."
        is_live = False
        needs_attention = False
    elif state == GateState.RUNNING:
        lifecycle = "active"
        status = "Active"
        detail = "Codex or project-owned processes are still running."
        is_live = True
        needs_attention = False
    elif state == GateState.QUESTION_PENDING:
        lifecycle = "question_pending"
        status = "Question pending"
        detail = "Codex asked for input; this is a real operator hold."
        is_live = True
        needs_attention = True
    elif state == GateState.ERROR:
        lifecycle = "attention"
        status = "Attention"
        detail = "Wake-gate recorded an error for this run."
        is_live = False
        needs_attention = True
    elif stale_callback:
        lifecycle = "stale_callback_ready"
        status = "Stale callback"
        detail = "Wake-gate reached callback-ready but has no delivered idempotency key; review or reconcile."
        is_live = False
        needs_attention = True
    elif state in {GateState.WAKE_READY, GateState.FINISHED_READY} and not delivered:
        lifecycle = "callback_pending"
        status = "Callback pending"
        detail = "Wake-gate is ready and waiting for callback delivery confirmation."
        is_live = True
        needs_attention = False
    elif delivered:
        lifecycle = "callback_delivered" if state == GateState.WAKE_READY else "finished_delivered"
        status = "Delivered"
        detail = "The configured completion callback accepted the wake/finish event; this is historical evidence, not live work."
        is_live = False
        needs_attention = False
    elif state in {
        GateState.PENDING_IDLE_GATE,
        GateState.WAITING_FOR_PROCESS_EXIT,
        GateState.WAITING_FOR_QUIET_WINDOW,
        GateState.FINISHED_PENDING_GATE,
    }:
        lifecycle = "settling"
        status = "Settling"
        detail = "Wake-gate is waiting for process-exit or quiet-window evidence."
        is_live = True
        needs_attention = False
    else:
        lifecycle = "historical"
        status = "Historical"
        detail = "Inactive historical run record."
        is_live = False
        needs_attention = False

    return {
        "lifecycle_state": lifecycle,
        "operator_status": status,
        "operator_status_detail": detail,
        "callback_delivered": delivered,
        "is_live": is_live,
        "needs_attention": needs_attention,
        "is_historical": not is_live and not needs_attention,
        "age_seconds": age_seconds,
    }


def _latest_runs_by_project(records: list[RunRecord]) -> dict[str, RunRecord]:
    latest_by_project: dict[str, RunRecord] = {}
    for record in records:
        if not record.project_id:
            continue
        latest = latest_by_project.get(record.project_id)
        if latest is None or (
            record.updated_at or "",
            record.last_event_at or "",
            record.created_at or "",
        ) > (
            latest.updated_at or "",
            latest.last_event_at or "",
            latest.created_at or "",
        ):
            latest_by_project[record.project_id] = record
    return latest_by_project


def _is_superseded_record(record: RunRecord, latest_by_project: dict[str, RunRecord]) -> bool:
    if not record.project_id:
        return False
    latest = latest_by_project.get(record.project_id)
    return latest is not None and latest.run_id != record.run_id


def _run_dashboard_item(
    record: RunRecord,
    *,
    detail: bool = False,
    superseded: bool = False,
) -> dict[str, Any]:
    process_states = {
        GateState.RUNNING,
        GateState.PENDING_IDLE_GATE,
        GateState.WAITING_FOR_PROCESS_EXIT,
        GateState.WAITING_FOR_QUIET_WINDOW,
        GateState.FINISHED_PENDING_GATE,
    }
    active_processes = (
        gate.process_tracker.describe_processes(record)
        if detail or record.gate_state in process_states
        else []
    )
    project_dir: Path | None = None
    if record.project_dir:
        try:
            project_dir = _resolve_under_root(record.project_dir, config.expanded_project_root)
        except HTTPException:
            project_dir = Path(record.project_dir).expanduser()

    latest_session = _latest_session(project_dir) if detail and project_dir is not None else None
    project_decision: ProjectDecision | None = None
    decision_error: str | None = None
    run_notes_tail: list[str] = []
    recent_files: list[str] = []
    result_files: list[str] = []
    if project_dir is not None and project_dir.exists():
        run_notes_tail = _tail_lines(project_dir / "run_notes.md", limit=30 if detail else 8)
        if detail:
            recent_files = _recent_files(project_dir, limit=30, max_entries=6_000, max_seconds=0.9)
            result_files = _result_files(project_dir, limit=50, max_entries=6_000, max_seconds=0.9)
        project_decision, decision_error = _load_project_decision(
            project_dir,
            include_summary_fallback=detail,
        )

    truth = _dashboard_truth(record, active_processes, superseded=superseded)
    current_activity = _activity_from_processes(active_processes, record.gate_state.value)
    if not active_processes:
        current_activity = truth["operator_status_detail"]

    return {
        "run_id": record.run_id,
        "session_id": record.session_id,
        "project_id": record.project_id,
        "project_name": record.project_name,
        "project_dir": record.project_dir,
        "gate_state": record.gate_state.value,
        **truth,
        "current_activity": current_activity,
        "root_pid": record.root_pid,
        "process_group_id": record.process_group_id,
        "active_process_count": len(active_processes),
        "active_processes": [
            process.model_dump()
            for process in (active_processes if detail else active_processes[:8])
        ],
        "active_processes_truncated": (not detail and len(active_processes) > 8),
        "baseline_vram_mib": record.baseline_vram_mib,
        "idle_seen_at": record.idle_seen_at,
        "last_event": record.last_event.value if record.last_event else None,
        "last_event_at": record.last_event_at,
        "last_idempotency_key": record.last_idempotency_key,
        "quiet_samples": [
            sample.model_dump()
            for sample in record.quiet_samples[-(24 if detail else 6):]
        ],
        "created_at": record.created_at,
        "updated_at": record.updated_at,
        "latest_session": latest_session.model_dump() if latest_session else None,
        "project_decision": project_decision.model_dump() if project_decision else None,
        "decision_error": decision_error,
        "run_notes_tail": [_truncate(line, 900 if detail else 360) for line in run_notes_tail],
        "recent_files": recent_files,
        "result_files": result_files,
    }


@app.get("/dashboard", response_class=HTMLResponse)
def dashboard() -> HTMLResponse:
    return HTMLResponse(DASHBOARD_HTML)


@app.get("/favicon.ico", include_in_schema=False)
def favicon() -> Response:
    return Response(status_code=204)


def _queue_snapshot_path() -> Path:
    return config.expanded_state_dir / "queue_snapshot.json"


def _read_queue_snapshot() -> dict[str, Any]:
    path = _queue_snapshot_path()
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def _snapshot_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _queue_row_summary(row: dict[str, Any]) -> dict[str, Any]:
    keys = (
        "project_id",
        "project_name",
        "notion_page_url",
        "project_dir",
        "current_run_id",
        "run_id",
        "status",
        "queue_status",
        "last_run_state",
        "run_state",
        "next_action_hint",
        "blocked_reason",
        "manual_review_required",
        "last_result_summary",
        "created_at",
        "updated_at",
    )
    summarized = {key: _truncate(str(row.get(key) or ""), 2000) for key in keys}
    summarized["queue_status"] = summarized.get("queue_status") or summarized.get("status") or "unknown"
    summarized["last_run_state"] = (
        summarized.get("last_run_state")
        or summarized.get("run_state")
        or summarized.get("next_action_hint")
        or "unknown"
    )
    return summarized


def _count_queue_field(rows: list[dict[str, Any]], field: str) -> dict[str, int]:
    counts: Counter[str] = Counter()
    for row in rows:
        key = str(row.get(field) or "unknown").strip() or "unknown"
        counts[key] += 1
    return dict(sorted(counts.items()))


def _build_queue_snapshot(payload: dict[str, Any]) -> dict[str, Any]:
    raw_rows = payload.get("rows") if isinstance(payload.get("rows"), list) else payload.get("queue_rows")
    rows = [_queue_row_summary(row) for row in raw_rows[:250] if isinstance(row, dict)] if isinstance(raw_rows, list) else []
    rows.sort(key=lambda row: row.get("updated_at") or row.get("created_at") or "", reverse=True)

    status_counts = (
        payload.get("status_counts")
        if isinstance(payload.get("status_counts"), dict)
        else _count_queue_field(rows, "queue_status")
    )
    run_state_counts = (
        payload.get("run_state_counts")
        if isinstance(payload.get("run_state_counts"), dict)
        else _count_queue_field(rows, "last_run_state")
    )

    active_statuses = {"dispatching", "awaiting_wake", "running"}
    active_rows = payload.get("active_rows") if isinstance(payload.get("active_rows"), list) else [
        row for row in rows if row.get("queue_status") in active_statuses
    ]
    blocked_rows = payload.get("blocked_rows") if isinstance(payload.get("blocked_rows"), list) else [
        row
        for row in rows
        if row.get("queue_status") == "blocked" or row.get("last_run_state") in {"blocked", "needs_review"}
    ]
    total = _snapshot_int(payload.get("total"), len(rows))
    valid_projects = _snapshot_int(payload.get("valid_projects"), total)

    return {
        "updated_at": utc_now(),
        "source": str(payload.get("source") or "unknown"),
        "total": total,
        "valid_projects": valid_projects,
        "status_counts": status_counts,
        "run_state_counts": run_state_counts,
        "blocked_rows": blocked_rows,
        "active_rows": active_rows,
        "active_count": sum(_snapshot_int(status_counts.get(status)) for status in active_statuses) or len(active_rows),
        "blocked_count": _snapshot_int(status_counts.get("blocked"), len(blocked_rows)),
        "queued_count": _snapshot_int(status_counts.get("queued")),
        "completed_count": _snapshot_int(status_counts.get("completed")),
        "positive_count": _snapshot_int(run_state_counts.get("finalize_positive")),
        "negative_count": _snapshot_int(run_state_counts.get("finalize_negative")),
        "branch_count": _snapshot_int(run_state_counts.get("branch_new_project"))
        + _snapshot_int(run_state_counts.get("branch_queued")),
        "draft_candidate_count": _snapshot_int(payload.get("draft_candidate_count")),
        "polish_candidate_count": _snapshot_int(payload.get("polish_candidate_count")),
        "warnings": payload.get("warnings") if isinstance(payload.get("warnings"), list) else [],
        "rows": rows,
    }


@app.post("/dashboard/queue-snapshot")
def dashboard_queue_snapshot(
    payload: dict[str, Any],
    authorization: str | None = Header(default=None),
) -> dict[str, Any]:
    _require_local_bearer(authorization)
    snapshot = _build_queue_snapshot(payload)
    path = _queue_snapshot_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(snapshot, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return {"ok": True, "queue_snapshot": snapshot}



def _paper_snapshot_path() -> Path:
    return config.expanded_state_dir / "paper_snapshot.json"


def _read_paper_snapshot() -> dict[str, Any]:
    path = _paper_snapshot_path()
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def _clean_snapshot_text(value: Any, max_chars: int = 2000) -> str:
    text = str(value or "").strip()
    if len(text) <= max_chars:
        return text
    return text[: max(0, max_chars - 15)].rstrip() + "\n[truncated]"


def _paper_row_summary(row: dict[str, Any]) -> dict[str, Any]:
    keys = (
        "paper_id",
        "project_id",
        "project_name",
        "run_id",
        "session_id",
        "notion_page_url",
        "project_dir",
        "paper_status",
        "paper_type",
        "draft_markdown_path",
        "draft_latex_path",
        "evidence_bundle_path",
        "claim_ledger_path",
        "manifest_path",
        "generated_at",
        "updated_at",
        "model_used",
        "evidence_strength",
        "hypothesis_status",
        "project_decision",
        "review_notes",
        "last_error",
    )
    summarized = {key: _clean_snapshot_text(row.get(key), 2000) for key in keys}
    summarized["reviewable"] = bool(
        summarized.get("project_id")
        and (summarized.get("draft_markdown_path") or summarized.get("draft_latex_path"))
    )
    return summarized


def _count_by(rows: list[dict[str, Any]], field: str) -> dict[str, int]:
    counts: Counter[str] = Counter()
    for row in rows:
        key = str(row.get(field) or "unknown").strip() or "unknown"
        counts[key] += 1
    return dict(sorted(counts.items()))


def _build_paper_snapshot(payload: dict[str, Any]) -> dict[str, Any]:
    raw_rows = payload.get("latest_rows") if isinstance(payload.get("latest_rows"), list) else payload.get("rows")
    rows = [_paper_row_summary(row) for row in raw_rows[:120]] if isinstance(raw_rows, list) else []
    rows.sort(key=lambda row: row.get("updated_at") or row.get("generated_at") or "", reverse=True)
    status_counts = payload.get("status_counts") if isinstance(payload.get("status_counts"), dict) else _count_by(rows, "paper_status")
    type_counts = payload.get("type_counts") if isinstance(payload.get("type_counts"), dict) else _count_by(rows, "paper_type")
    reviewable_count = sum(1 for row in rows if row.get("reviewable"))
    publication_count = sum(1 for row in rows if row.get("paper_status") == "publication_draft")
    return {
        "updated_at": utc_now(),
        "source": str(payload.get("source") or "unknown"),
        "total": int(payload.get("total") or len(rows)),
        "reviewable_count": int(payload.get("reviewable_count") or reviewable_count),
        "publication_count": int(payload.get("publication_count") or publication_count),
        "status_counts": status_counts,
        "type_counts": type_counts,
        "latest_rows": rows,
    }


@app.post("/dashboard/paper-snapshot")
def dashboard_paper_snapshot(
    payload: dict[str, Any],
    authorization: str | None = Header(default=None),
) -> dict[str, Any]:
    _require_local_bearer(authorization)
    snapshot = _build_paper_snapshot(payload)
    path = _paper_snapshot_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(snapshot, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return {"ok": True, "paper_snapshot": snapshot}


@app.get("/dashboard/api/paper-artifact/{project_id}")
def dashboard_api_paper_artifact(
    project_id: str,
    path: str = Query(..., min_length=1),
    authorization: str | None = Header(default=None),
    token: str | None = Query(default=None),
    max_bytes: int = Query(default=350_000, ge=1, le=2_000_000),
) -> dict[str, Any]:
    _require_dashboard_bearer(authorization, token)
    project_dir = _resolve_project_dir(project_id, None)
    if not project_dir.exists() or not project_dir.is_dir():
        raise HTTPException(status_code=404, detail=f"project directory not found: {project_id}")
    artifact_path = _resolve_project_relative_path(project_dir, path)
    if not artifact_path.exists() or not artifact_path.is_file():
        raise HTTPException(status_code=404, detail=f"paper artifact not found: {path}")
    size = artifact_path.stat().st_size
    if size > max_bytes:
        raise HTTPException(status_code=413, detail=f"paper artifact too large for dashboard preview: {path}")
    try:
        content = artifact_path.read_text(encoding="utf-8")
    except UnicodeDecodeError as exc:
        raise HTTPException(status_code=415, detail=f"paper artifact is not UTF-8 text: {path}") from exc
    return {
        "ok": True,
        "project_id": project_id,
        "project_dir": project_dir.as_posix(),
        "path": artifact_path.relative_to(project_dir).as_posix(),
        "bytes": size,
        "content": content,
        "timestamp": utc_now(),
    }


@app.get("/dashboard/paper-artifact/{project_id}", response_class=HTMLResponse)
def dashboard_paper_artifact(
    project_id: str,
    path: str = Query(..., min_length=1),
    authorization: str | None = Header(default=None),
    token: str | None = Query(default=None),
) -> HTMLResponse:
    data = dashboard_api_paper_artifact(project_id, path, authorization=authorization, token=token, max_bytes=2_000_000)
    title = html.escape(f"{project_id} · {data['path']}")
    content = html.escape(data["content"])
    return HTMLResponse(
        f"""
<!doctype html>
<html lang=\"en\"><head><meta charset=\"utf-8\"><title>{title}</title>
<style>body{{margin:0;background:#05070b;color:#eef6ff;font-family:ui-sans-serif,system-ui}}header{{position:sticky;top:0;background:#0b1320;border-bottom:1px solid rgba(148,163,184,.3);padding:14px 18px}}pre{{white-space:pre-wrap;overflow-wrap:anywhere;margin:0;padding:18px;font-family:ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;line-height:1.45}}.small{{color:#9fb0c3;font-size:.9rem}}</style>
</head><body><header><strong>{title}</strong><div class=\"small\">{data['bytes']} bytes · {html.escape(data['timestamp'])}</div></header><pre>{content}</pre></body></html>
"""
    )


@app.get("/dashboard/api")
def dashboard_api(
    authorization: str | None = Header(default=None),
    token: str | None = Query(default=None),
    limit: int = Query(default=40, ge=1, le=250),
    event_limit: int = Query(default=30, ge=0, le=200),
    detail: bool = Query(default=False),
) -> dict[str, Any]:
    _require_dashboard_bearer(authorization, token)

    records = store.list_runs()
    latest_by_project = _latest_runs_by_project(records)

    truth_by_run = {
        record.run_id: _dashboard_truth(
            record,
            [],
            superseded=_is_superseded_record(record, latest_by_project),
        )
        for record in records
    }
    records.sort(key=lambda record: (record.updated_at or "", record.last_event_at or "", record.created_at or ""), reverse=True)
    records.sort(
        key=lambda record: (
            0
            if truth_by_run[record.run_id]["is_live"]
            else 1
            if truth_by_run[record.run_id]["needs_attention"]
            else 2
        )
    )
    visible_records = records[:limit]
    state_counts = Counter(record.gate_state.value for record in records)
    run_items = [
        _run_dashboard_item(
            record,
            detail=detail,
            superseded=_is_superseded_record(record, latest_by_project),
        )
        for record in visible_records
    ]
    lifecycle_counts = Counter(item["lifecycle_state"] for item in truth_by_run.values())
    live_count = sum(1 for item in truth_by_run.values() if item["is_live"])
    attention_count = sum(1 for item in truth_by_run.values() if item["needs_attention"])
    callback_pending_count = lifecycle_counts.get("callback_pending", 0)
    stale_callback_count = lifecycle_counts.get("stale_callback_ready", 0)
    callback_delivered_count = lifecycle_counts.get("callback_delivered", 0) + lifecycle_counts.get("finished_delivered", 0)
    telemetry_sample = telemetry.sample()

    return {
        "timestamp": utc_now(),
        "service": {
            "name": "omx_wake_gate",
            "listen_host": config.listen_host,
            "listen_port": config.listen_port,
            "state_dir": config.expanded_state_dir.as_posix(),
            "project_root": config.expanded_project_root.as_posix(),
            "completion_callback_url": config.completion_callback_url,
            "idle_sustain_sec": config.idle_sustain_sec,
            "sample_interval_sec": config.sample_interval_sec,
        },
        "totals": {
            "runs": len(records),
            "shown": len(visible_records),
            "active_or_waiting": live_count,
            "live": live_count,
            "needs_attention": attention_count,
            "callback_pending": callback_pending_count,
            "stale_callbacks": stale_callback_count,
            "callback_delivered": callback_delivered_count,
            "by_state": dict(sorted(state_counts.items())),
            "by_lifecycle": dict(sorted(lifecycle_counts.items())),
        },
        "telemetry": telemetry_sample.model_dump(),
        "queue": _read_queue_snapshot(),
        "papers": _read_paper_snapshot(),
        "runs": run_items,
        "events": [_trim_event(event) for event in _read_recent_events(event_limit)],
    }


@app.get("/dashboard/api/run/{run_id}")
def dashboard_api_run(
    run_id: str,
    authorization: str | None = Header(default=None),
    token: str | None = Query(default=None),
) -> dict[str, Any]:
    _require_dashboard_bearer(authorization, token)
    record = store.load_run(run_id)
    if record is None:
        raise HTTPException(status_code=404, detail="run not found")
    latest_by_project = _latest_runs_by_project(store.list_runs())
    return {
        "timestamp": utc_now(),
        "run": _run_dashboard_item(
            record,
            detail=True,
            superseded=_is_superseded_record(record, latest_by_project),
        ),
        "events": [
            _trim_event(event, max_chars=3000)
            for event in _read_recent_events(200)
            if event.get("run_id") == run_id
        ],
    }


@app.get("/project-status/{project_id}")
async def project_status(
    project_id: str,
    authorization: str | None = Header(default=None),
    run_id: str | None = Query(default=None),
    project_dir: str | None = Query(default=None),
) -> dict[str, Any]:
    _require_local_bearer(authorization)

    try:
        resolved_project_dir = _resolve_project_dir(project_id, project_dir)
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    record = _find_run_record(project_id, run_id)
    latest_session = _latest_session(resolved_project_dir)
    run_notes_tail = _tail_lines(resolved_project_dir / "run_notes.md")
    recent_files = _recent_files(resolved_project_dir)
    result_files = _result_files(resolved_project_dir)
    project_decision, decision_error = _load_project_decision(resolved_project_dir)

    active_processes: list[ProcessInfo] = []
    gate_state = record.gate_state.value if record is not None else None
    if record is not None:
        active_processes = gate.process_tracker.describe_processes(record)

    response = ProjectStatusResponse(
        project_id=project_id,
        project_dir=resolved_project_dir.as_posix(),
        available=resolved_project_dir.exists(),
        run_id=record.run_id if record is not None else run_id,
        session_id=record.session_id if record is not None else None,
        project_name=(record.project_name if record is not None else None) or project_id,
        gate_state=gate_state,
        current_activity=_activity_from_processes(active_processes, gate_state),
        run_notes_tail=run_notes_tail,
        recent_files=recent_files,
        result_files=result_files,
        active_processes=active_processes,
        latest_session=latest_session,
        project_decision=project_decision,
        decision_error=decision_error,
    )
    return response.model_dump(exclude_none=False)


@app.post("/prepare-project")
async def prepare_project(
    request: PrepareProjectRequest,
    authorization: str | None = Header(default=None),
) -> dict[str, Any]:
    _require_local_bearer(authorization)
    metadata = _normalize_prepare_metadata(request.metadata)

    project_root = config.expanded_project_root
    project_root.mkdir(parents=True, exist_ok=True)

    project_dir = _resolve_under_root(request.project_dir, project_root)
    prompt_file = _resolve_under_root(request.prompt_file, project_root)
    resume_prompt_file = (
        _resolve_under_root(request.resume_prompt_file, project_root)
        if request.resume_prompt_file
        else None
    )

    project_dir.mkdir(parents=True, exist_ok=True)
    (project_dir / ".omx").mkdir(parents=True, exist_ok=True)

    _write_text(prompt_file, request.prompt_text, request.overwrite)
    if resume_prompt_file and request.resume_prompt_text is not None:
        _write_text(resume_prompt_file, request.resume_prompt_text, request.overwrite)

    metadata_path = project_dir / ".omx" / "project.json"
    metadata_payload = {
        "run_id": request.run_id,
        "project_id": request.project_id,
        "project_name": request.project_name,
        "notion_page_url": request.notion_page_url,
        "project_dir": str(project_dir),
        "prompt_file": str(prompt_file),
        "resume_prompt_file": str(resume_prompt_file) if resume_prompt_file else "",
        "prompt_length": len(request.prompt_text),
        "resume_prompt_length": len(request.resume_prompt_text or ""),
        "prepared_at": utc_now(),
        "metadata": metadata,
    }
    metadata_path.write_text(json.dumps(metadata_payload, indent=2, sort_keys=True), encoding="utf-8")

    return {
        "accepted": True,
        "prepared": {
            "project_dir": str(project_dir),
            "prompt_file": str(prompt_file),
            "resume_prompt_file": str(resume_prompt_file) if resume_prompt_file else "",
            "metadata_file": str(metadata_path),
        },
        "timestamp": utc_now(),
    }


@app.post("/project-paper/{project_id}/read")
async def read_project_paper(
    project_id: str,
    request: PaperArtifactReadRequest,
    authorization: str | None = Header(default=None),
) -> dict[str, Any]:
    _require_local_bearer(authorization)
    if len(request.paths) > 20:
        raise HTTPException(status_code=400, detail="too many paper artifact paths; max 20")
    if request.max_bytes_per_file < 1 or request.max_bytes_per_file > 2_000_000:
        raise HTTPException(status_code=400, detail="max_bytes_per_file must be between 1 and 2000000")

    project_dir = _resolve_project_dir(project_id, None)
    if not project_dir.exists() or not project_dir.is_dir():
        raise HTTPException(status_code=404, detail=f"project directory not found: {project_id}")

    files: list[dict[str, Any]] = []
    for relative in request.paths:
        path = _resolve_project_relative_path(project_dir, relative)
        if not path.exists() or not path.is_file():
            raise HTTPException(status_code=404, detail=f"paper artifact not found: {relative}")
        size = path.stat().st_size
        if size > request.max_bytes_per_file:
            raise HTTPException(status_code=413, detail=f"paper artifact too large to read: {relative}")
        try:
            content = path.read_text(encoding="utf-8")
        except UnicodeDecodeError as exc:
            raise HTTPException(status_code=415, detail=f"paper artifact is not UTF-8 text: {relative}") from exc
        files.append({"path": path.relative_to(project_dir).as_posix(), "bytes": size, "content": content})

    return {"ok": True, "project_id": project_id, "project_dir": project_dir.as_posix(), "files": files, "timestamp": utc_now()}


@app.post("/project-paper/{project_id}")
async def write_project_paper(
    project_id: str,
    request: PaperArtifactRequest,
    authorization: str | None = Header(default=None),
) -> dict[str, Any]:
    _require_local_bearer(authorization)
    if len(request.files) > 20:
        raise HTTPException(status_code=400, detail="too many paper artifact files; max 20")

    project_dir = _resolve_project_dir(project_id, None)
    if not project_dir.exists() or not project_dir.is_dir():
        raise HTTPException(status_code=404, detail=f"project directory not found: {project_id}")

    written: list[dict[str, Any]] = []
    for artifact in request.files:
        if len(artifact.content.encode("utf-8")) > 2_000_000:
            raise HTTPException(status_code=413, detail=f"paper artifact too large: {artifact.path}")
        path = _resolve_project_relative_path(project_dir, artifact.path)
        _write_text(path, artifact.content, request.overwrite)
        written.append(
            {
                "path": path.relative_to(project_dir).as_posix(),
                "bytes": len(artifact.content.encode("utf-8")),
            }
        )

    manifest_path = project_dir / "papers" / request.run_id / "paper_manifest.json"
    manifest = {
        "project_id": project_id,
        "run_id": request.run_id,
        "paper_id": request.paper_id,
        "written": written,
        "updated_at": utc_now(),
    }
    _write_text(manifest_path, json.dumps(manifest, indent=2, sort_keys=True) + "\n", True)
    return {
        "ok": True,
        "project_id": project_id,
        "run_id": request.run_id,
        "paper_id": request.paper_id,
        "project_dir": project_dir.as_posix(),
        "written": written,
        "manifest_path": manifest_path.relative_to(project_dir).as_posix(),
        "timestamp": utc_now(),
    }


@app.post("/dispatch")
async def dispatch_run(
    request: DispatchRequest,
    authorization: str | None = Header(default=None),
) -> dict:
    _require_local_bearer(authorization)
    project_dir = _resolve_under_root(request.project_dir, config.expanded_project_root)
    prompt_file = _resolve_under_root(request.prompt_file, config.expanded_project_root)
    workload_class, workload_profile = _resolve_workload_profile_for_project_dir(project_dir)

    script_path = Path(config.dispatch_script_path).expanduser()
    if not script_path.exists():
        raise HTTPException(status_code=500, detail=f"dispatch script not found: {script_path}")

    cmd = [
        str(script_path),
        "--run-id",
        request.run_id,
        "--project-dir",
        str(project_dir),
        "--prompt-file",
        str(prompt_file),
        "--mode",
        request.mode,
        "--sandbox",
        request.sandbox,
    ]
    if request.project_id:
        cmd.extend(["--project-id", request.project_id])
    if request.session_id:
        cmd.extend(["--session-id", request.session_id])
    if request.last:
        cmd.append("--last")
    if request.model:
        cmd.extend(["--model", request.model])
    if request.reasoning_effort:
        cmd.extend(["--reasoning-effort", request.reasoning_effort])
    if request.log_dir:
        cmd.extend(["--log-dir", request.log_dir])

    try:
        result = await asyncio.to_thread(
            subprocess.run,
            cmd,
            capture_output=True,
            text=True,
            check=False,
            timeout=config.dispatch_timeout_sec,
        )
    except subprocess.TimeoutExpired as exc:
        raise HTTPException(status_code=504, detail=f"dispatch timed out after {config.dispatch_timeout_sec}s") from exc

    if result.returncode != 0:
        raise HTTPException(
            status_code=502,
            detail={
                "message": "dispatch failed",
                "returncode": result.returncode,
                "stderr": result.stderr.strip(),
            },
        )

    try:
        payload = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise HTTPException(
            status_code=502,
            detail={
                "message": "dispatch returned non-json output",
                "stdout": result.stdout.strip(),
                "stderr": result.stderr.strip(),
            },
        ) from exc

    record = store.load_run(request.run_id) or RunRecord(
        run_id=request.run_id,
        session_id=request.session_id or "",
        project_id=request.project_id,
        project_name=request.project_id,
    )
    record.session_id = request.session_id or record.session_id
    record.project_id = request.project_id or record.project_id
    record.project_name = request.project_id or record.project_name
    record.project_dir = str(project_dir)
    record.workload_class = workload_class
    record.workload_profile = workload_profile
    record.root_pid = payload.get("pid") or record.root_pid
    record.process_group_id = payload.get("pgid") or record.process_group_id
    record.gate_state = GateState.RUNNING
    record.idle_seen_at = None
    record.last_event = None
    record.last_event_at = None
    record.last_idempotency_key = None
    record.quiet_samples = []
    record.updated_at = utc_now()
    baseline_sample = telemetry.sample()
    if record.baseline_vram_mib is None or (baseline_sample.memory_source == "uma_meminfo" and record.baseline_vram_mib == 0):
        record.baseline_vram_mib = baseline_sample.vram_used_mib
    store.save_run(record)

    return {
        "accepted": True,
        "dispatch": payload,
        "timestamp": utc_now(),
    }


async def _deliver_callback(callback: GateCallback) -> tuple[bool, str]:
    loop = asyncio.get_running_loop()
    try:
        status, text = await loop.run_in_executor(None, sender.send, callback)
        return True, f"{status}:{text}"
    except Exception as exc:  # pragma: no cover - network/deploy time failure
        return False, f"{type(exc).__name__}: {exc}"


async def _reap_and_log_stale_project_processes(record: RunRecord) -> None:
    reaped_processes = await asyncio.to_thread(gate.reap_stale_project_processes, record)
    if not reaped_processes:
        return
    store.append_event(
        {
            "kind": "stale_project_process_reaped",
            "run_id": record.run_id,
            "session_id": record.session_id,
            "project_id": record.project_id,
            "timestamp": utc_now(),
            "reason": "root session exited/idle; project-owned stale smoke process exceeded grace window",
            "stale_after_sec": config.stale_project_process_grace_sec,
            "processes": reaped_processes,
        }
    )


async def _evaluate_until_ready(run_id: str) -> None:
    try:
        while True:
            record = store.load_run(run_id)
            if record is None:
                return
            record = _assign_record_workload_profile(record)

            await _reap_and_log_stale_project_processes(record)

            if gate.is_timed_out(record):
                timeout_idempotency_key = f"{record.run_id}:gate_timeout:{record.idle_seen_at or record.last_event_at}"
                if record.last_idempotency_key == timeout_idempotency_key:
                    return
                profile_evidence = _wake_decision_profile_evidence(record)
                timeout_callback = GateCallback(
                    event_type="gate_timeout",
                    run_id=record.run_id,
                    session_id=record.session_id,
                    project_id=record.project_id,
                    project_name=record.project_name,
                    source_event=(record.last_event.value if record.last_event else "unknown"),
                    gate_state=record.gate_state.value,
                    idle_seen_at=record.idle_seen_at,
                    process_tracking=gate.process_tracker.snapshot(record, []),
                    telemetry={
                        "workload_class": profile_evidence["workload_class"],
                        "workload_profile_name": profile_evidence["workload_profile_name"],
                        "thresholds": profile_evidence["workload_thresholds"],
                    },
                    reason="idle_gate_timeout",
                    idempotency_key=timeout_idempotency_key,
                )
                record.gate_state = GateState.ERROR
                record.last_idempotency_key = timeout_callback.idempotency_key
                store.save_run(record)
                ok, detail = await _deliver_callback(timeout_callback)
                store.append_event(
                    {
                        "kind": "callback_attempt",
                        "run_id": record.run_id,
                        "event_type": timeout_callback.event_type,
                        "ok": ok,
                        "detail": detail,
                        "timestamp": utc_now(),
                        **profile_evidence,
                    }
                )
                if ok:
                    store.save_run(record)
                    return
                store.save_run(record)
                return

            record, callback = gate.evaluate(record)
            store.save_run(record)
            if callback is not None:
                ok, detail = await _deliver_callback(callback)
                profile_evidence = _wake_decision_profile_evidence(record)
                store.append_event(
                    {
                        "kind": "callback_attempt",
                        "run_id": record.run_id,
                        "event_type": callback.event_type,
                        "ok": ok,
                        "detail": detail,
                        "timestamp": utc_now(),
                        **profile_evidence,
                    }
                )
                if ok:
                    record.last_idempotency_key = callback.idempotency_key
                    store.save_run(record)
                    return

            await asyncio.sleep(config.sample_interval_sec)
    finally:
        evaluation_tasks.pop(run_id, None)


def _ensure_evaluator(run_id: str) -> None:
    current = evaluation_tasks.get(run_id)
    if current is not None and not current.done():
        return
    evaluation_tasks[run_id] = asyncio.create_task(_evaluate_until_ready(run_id))


async def _reconcile_missing_idle_loop() -> None:
    try:
        while True:
            for record in store.list_runs():
                record = _assign_record_workload_profile(record)
                if record.gate_state == GateState.RUNNING:
                    await _reap_and_log_stale_project_processes(record)
                    record, changed = gate.reconcile(record)
                    if changed:
                        store.append_event(
                            {
                                "kind": "reconciled_missing_idle",
                                "run_id": record.run_id,
                                "session_id": record.session_id,
                                "timestamp": utc_now(),
                            }
                        )
                        store.save_run(record)
                if record.gate_state in {
                    GateState.PENDING_IDLE_GATE,
                    GateState.WAITING_FOR_PROCESS_EXIT,
                    GateState.WAITING_FOR_QUIET_WINDOW,
                    GateState.FINISHED_PENDING_GATE,
                }:
                    _ensure_evaluator(record.run_id)
            await asyncio.sleep(config.sample_interval_sec)
    except asyncio.CancelledError:
        raise


@app.on_event("startup")
async def _startup_tasks() -> None:
    global reconcile_task
    if reconcile_task is None or reconcile_task.done():
        reconcile_task = asyncio.create_task(_reconcile_missing_idle_loop())


@app.on_event("shutdown")
async def _shutdown_tasks() -> None:
    global reconcile_task
    if reconcile_task is not None:
        reconcile_task.cancel()
        try:
            await reconcile_task
        except asyncio.CancelledError:
            pass
        reconcile_task = None


@app.post("/omx/event")
async def omx_event(event: OmxEvent, authorization: str | None = Header(default=None)) -> dict:
    _require_local_bearer(authorization)
    store.append_event(event.model_dump())
    record = store.load_run(event.run_id) or RunRecord(
        run_id=event.run_id,
        session_id=event.session_id,
        project_id=event.project_id,
        project_name=event.project_name,
    )
    record.project_dir = record.project_dir or (str((config.expanded_project_root / event.project_id).resolve()) if event.project_id else record.project_dir)
    record = _assign_record_workload_profile(record)
    record = gate.apply_event(record, event)
    baseline_sample = telemetry.sample()
    if record.baseline_vram_mib is None or (baseline_sample.memory_source == "uma_meminfo" and record.baseline_vram_mib == 0):
        record.baseline_vram_mib = baseline_sample.vram_used_mib

    store.save_run(record)
    callback = None
    if event.event.value in {"session-idle", "session-end"}:
        _ensure_evaluator(event.run_id)
    elif event.event.value == "ask-user-question":
        callback = GateCallback(
            event_type="question_pending",
            run_id=record.run_id,
            session_id=record.session_id,
            project_id=record.project_id,
            project_name=record.project_name,
            source_event=event.event.value,
            gate_state=record.gate_state.value,
            idle_seen_at=record.idle_seen_at,
            process_tracking=gate.process_tracker.snapshot(record, []),
            telemetry={},
            reason="operator_input_required",
            idempotency_key=f"{record.run_id}:question_pending:{event.timestamp}",
        )
        ok, detail = await _deliver_callback(callback)
        store.append_event(
            {
                "kind": "callback_attempt",
                "run_id": record.run_id,
                "event_type": callback.event_type,
                "ok": ok,
                "detail": detail,
                "timestamp": utc_now(),
            }
        )
        if ok:
            record.last_idempotency_key = callback.idempotency_key
            store.save_run(record)

    return {
        "accepted": True,
        "run_id": record.run_id,
        "gate_state": record.gate_state.value,
        "callback_ready": callback is not None,
        "callback_preview": None if callback is None else callback.model_dump(),
        "evaluator_active": event.run_id in evaluation_tasks,
    }
