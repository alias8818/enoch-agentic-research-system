from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
import os
import re
import shlex
import subprocess
import time
from typing import Any, Callable
from urllib.parse import urlparse

from fastapi import APIRouter, Body, Header, HTTPException, Query
from fastapi.encoders import jsonable_encoder
from fastapi.responses import HTMLResponse

from ..config import GateConfig
from ..enoch_core.logic import draft_candidate_payload, eligible_paper_draft_candidates, paper_draft_decision_gate
from ..enoch_core.store import IdempotencyConflict
from ..models import GateCallback, utc_now
from ..observability import current_rss_mib, peak_rss_mib
from .paper_writer import write_paper_artifacts
from .models import (
    ControlStateResponse,
    DashboardConfigStatus,
    DashboardFinding,
    DashboardFreshness,
    DashboardObservationRecord,
    DashboardStatusResponse,
    DashboardRunDetailResponse,
    DashboardQueueResponse,
    DashboardProjectDetailResponse,
    DashboardPapersResponse,
    DashboardPaperDetailResponse,
    DashboardPaperReviewsResponse,
    DashboardPaperReviewDetailResponse,
    DashboardPageMeta,
    DashboardIntakeResponse,
    DashboardEventsResponse,
    DispatchNextRequest,
    DispatchNextResponse,
    DispatchOneRequest,
    DraftNextRequest,
    DraftNextResponse,
    ImportSnapshotRequest,
    ImportSnapshotResponse,
    IdeaIntakeRequest,
    IdeaIntakeResponse,
    MarkQueueItemPausedRequest,
    NotionIntakeRequest,
    NotionIntakeResponse,
    ExportSnapshotResponse,
    FollowupLaunchRequest,
    FollowupLaunchResponse,
    PaperRecord,
    PaperStatus,
    PaperReviewApproveFinalizationRequest,
    PaperReviewBackfillRequest,
    PaperReviewBackfillResponse,
    PaperReviewChecklistUpdateRequest,
    PaperReviewClaimRequest,
    PaperReviewFinalizationPackageResponse,
    PaperReviewMutationResponse,
    PaperReviewPrepareFinalizationRequest,
    PaperReviewBulkRewriteRequest,
    PaperReviewBulkRewriteResponse,
    PaperReviewRewriteDraftRequest,
    PaperReviewRewriteDraftResponse,
    PaperReviewStatusUpdateRequest,
    ProjectionResponse,
    WorkerPreflightRequest,
    WorkerPreflightResponse,
    PauseRequest,
    ResumeRequest,
)
from .alerts import evaluate_and_notify_queue_alerts
from .graphs import build_dispatch_graph
from .longhaul_readiness import evaluate_longhaul_readiness
from . import read_models
from .store import ControlPlaneStore
from .supabase_store import SupabaseControlPlaneStore, SupabaseReadOnlyControlPlaneStore, resolve_supabase_database_url
from .worker_adapter import post_worker_json, run_worker_preflight

RequireBearer = Callable[[str | None], None]


CONTROL_DASHBOARD_HTML = """
<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>Enoch Control Status Dashboard</title>
  <style>
    :root {
      color-scheme: light dark;
      --bg:#f8fafc; --surface:#ffffff; --surface-muted:#f1f5f9; --sidebar:#ffffff; --text:#0f172a; --muted:#64748b; --line:#e2e8f0;
      --good:#16a34a; --good-bg:#dcfce7; --warn:#d97706; --warn-bg:#fef3c7; --bad:#dc2626; --bad-bg:#fee2e2; --info:#2563eb; --info-bg:#dbeafe;
      --shadow:0 1px 2px rgba(15,23,42,.06),0 8px 24px rgba(15,23,42,.06); --radius:18px;
      font-family: Inter, ui-sans-serif, system-ui, -apple-system, Segoe UI, sans-serif;
    }
    @media (prefers-color-scheme: dark) {
      :root { --bg:#09090b; --surface:#111113; --surface-muted:#18181b; --sidebar:#111113; --text:#f4f4f5; --muted:#a1a1aa; --line:#27272a; --good:#22c55e; --good-bg:#052e16; --warn:#f59e0b; --warn-bg:#451a03; --bad:#fb7185; --bad-bg:#4c0519; --info:#60a5fa; --info-bg:#172554; --shadow:0 1px 1px rgba(0,0,0,.35),0 16px 48px rgba(0,0,0,.35); }
    }
    * { box-sizing:border-box; }
    body { margin:0; background:var(--bg); color:var(--text); line-height:1.45; }
    a { color:inherit; text-decoration:none; } a:hover { color:var(--info); }
    h1,h2,h3 { letter-spacing:-.035em; } h1 { margin:0; font-size:clamp(1.7rem,2.6vw,2.7rem); } h2 { margin:0 0 10px; font-size:1.05rem; } h3 { margin:14px 0 8px; font-size:.98rem; }
    input,select,button { background:var(--surface); color:var(--text); border:1px solid var(--line); border-radius:12px; padding:9px 11px; box-shadow:none; }
    button { cursor:pointer; font-weight:650; } button:hover, nav a:hover { border-color:color-mix(in srgb, var(--info) 55%, var(--line)); background:var(--surface-muted); }
    .app-shell { min-height:100vh; display:grid; grid-template-columns:280px minmax(0,1fr); }
    .sidebar { position:sticky; top:0; height:100vh; padding:18px 16px; border-right:1px solid var(--line); background:var(--sidebar); display:flex; flex-direction:column; gap:18px; }
    .brand { display:flex; align-items:center; gap:11px; padding:5px 4px 14px; border-bottom:1px solid var(--line); }
    .brand-mark { width:34px; height:34px; border-radius:12px; display:grid; place-items:center; background:#0f172a; color:white; font-weight:900; box-shadow:var(--shadow); }
    .brand-title { font-weight:850; letter-spacing:-.04em; } .brand-subtitle,.sub,.muted { color:var(--muted); } .brand-subtitle { font-size:.8rem; margin-top:2px; }
    nav { display:grid; gap:5px; }
    nav a { display:flex; align-items:center; justify-content:space-between; color:var(--muted); border:1px solid transparent; border-radius:12px; padding:9px 10px; font-weight:650; }
    nav a.active { color:var(--text); background:var(--surface-muted); border-color:var(--line); box-shadow:inset 3px 0 0 var(--info); }
    .sidebar-footer { margin-top:auto; color:var(--muted); font-size:.82rem; border-top:1px solid var(--line); padding-top:12px; }
    .dashboard-main { min-width:0; padding:18px 26px 44px; }
    .topbar { height:54px; display:flex; align-items:center; justify-content:space-between; gap:14px; margin-bottom:28px; }
    .search-box { flex:1; max-width:560px; position:relative; }
    .search-box input { width:100%; padding-left:36px; background:var(--surface); } .search-box:before { content:'⌕'; position:absolute; left:13px; top:7px; color:var(--muted); font-size:1.2rem; }
    .token-row { display:flex; gap:8px; align-items:center; }
    .page-heading { display:flex; align-items:flex-end; justify-content:space-between; gap:16px; margin-bottom:14px; }
    .wrap { width:100%; margin:0; } main { padding:0; }
    section { margin-top:16px; }
    .hero { display:grid; grid-template-columns:minmax(0,2fr) minmax(280px,1fr); gap:16px; align-items:stretch; }
    .grid { display:grid; grid-template-columns:repeat(4,minmax(0,1fr)); gap:16px; } .grid.two { grid-template-columns:repeat(2,minmax(0,1fr)); } .grid.three { grid-template-columns:repeat(3,minmax(0,1fr)); }
    .card,.banner { background:var(--surface); border:1px solid var(--line); border-radius:var(--radius); padding:18px; box-shadow:var(--shadow); overflow:auto; }
    .card.tight { padding:13px; } .card:hover { border-color:color-mix(in srgb, var(--line) 55%, var(--muted)); }
    .label { color:var(--muted); font-size:.78rem; text-transform:uppercase; letter-spacing:.08em; font-weight:750; }
    .value { font-size:2rem; font-weight:850; margin-top:6px; letter-spacing:-.05em; }
    .pill { display:inline-flex; gap:7px; align-items:center; border:1px solid var(--line); border-radius:999px; padding:5px 9px; font-size:.82rem; margin:2px; background:var(--surface); color:var(--muted); font-weight:650; }
    .good { color:var(--good); } .warn { color:var(--warn); } .bad,.critical { color:var(--bad); } .info { color:var(--info); }
    .banner.good { border-color:color-mix(in srgb, var(--good) 45%, var(--line)); background:linear-gradient(135deg,var(--good-bg),var(--surface)); }
    .banner.warn { border-color:color-mix(in srgb, var(--warn) 45%, var(--line)); background:linear-gradient(135deg,var(--warn-bg),var(--surface)); }
    .banner.critical { border-color:color-mix(in srgb, var(--bad) 45%, var(--line)); background:linear-gradient(135deg,var(--bad-bg),var(--surface)); }
    table { width:100%; border-collapse:separate; border-spacing:0; font-size:.9rem; }
    th,td { text-align:left; border-bottom:1px solid var(--line); padding:11px 10px; vertical-align:top; } th { color:var(--muted); font-weight:750; font-size:.78rem; text-transform:uppercase; letter-spacing:.05em; }
    tbody tr:hover { background:var(--surface-muted); }
    .truncate { max-width:420px; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; display:inline-block; vertical-align:bottom; }
    .mono { font-family:ui-monospace,SFMono-Regular,Menlo,Monaco,Consolas,monospace; }
    .row { display:flex; flex-wrap:wrap; gap:8px; align-items:center; } .toolbar { display:flex; gap:8px; flex-wrap:wrap; align-items:center; margin:12px 0; } .toolbar-note { color:var(--muted); margin-top:12px; } .activity-list { display:grid; gap:10px; } .card.tight strong { font-size:1rem; }
    details { border:1px solid var(--line); border-radius:14px; padding:10px 12px; background:var(--surface-muted); margin-top:10px; } summary { cursor:pointer; color:var(--text); font-weight:700; } pre { white-space:pre-wrap; color:var(--muted); margin:10px 0 0; max-height:480px; overflow:auto; }
    .kpi-strip { display:grid; grid-template-columns:repeat(5,minmax(0,1fr)); gap:16px; }
    @media (max-width:1100px) { .app-shell { grid-template-columns:1fr; } .sidebar { position:relative; height:auto; } nav { grid-template-columns:repeat(2,minmax(0,1fr)); } .dashboard-main { padding:18px; } .hero,.grid,.grid.two,.grid.three,.kpi-strip { grid-template-columns:repeat(2,minmax(0,1fr)); } .topbar { height:auto; align-items:stretch; flex-direction:column; } .search-box { max-width:none; } }
    @media (max-width:640px) { nav,.hero,.grid,.grid.two,.grid.three,.kpi-strip { grid-template-columns:1fr; } .page-heading,.token-row { align-items:stretch; flex-direction:column; } }
  </style>
</head>
<body>
<div class="app-shell">
  <aside class="sidebar">
    <div class="brand"><div class="brand-mark">E</div><div><div class="brand-title">Enoch Control</div><div class="brand-subtitle">Professional operator console</div></div></div>
    <nav id="nav" aria-label="Dashboard navigation"></nav>
    <div class="sidebar-footer">Bounded Supabase read models · raw states stay in drill-down views</div>
  </aside>
  <main class="dashboard-main">
    <div class="topbar">
      <div class="search-box"><input id="globalSearch" placeholder="Search projects, runs, papers, or events…" onkeydown="if(event.key==='Enter')globalSearch()" /></div>
      <div class="token-row"><input id="token" placeholder="Bearer token" type="password" /><button onclick="saveToken()">Save token</button><button onclick="route()">Refresh</button></div>
    </div>
    <div class="page-heading"><div><h1>Dashboard</h1><div class="sub">Operator-first state, paper pipeline, and release readiness.</div></div><div id="status" class="pill warn">Loading…</div></div>
    <div id="app" class="banner warn">Loading dashboard cards…</div>
  </main>
</div>
<script>
let currentRouteController=null, currentRouteSignal=null;
function beginRoute(){if(currentRouteController)currentRouteController.abort(); currentRouteController=new AbortController(); currentRouteSignal=currentRouteController.signal;}
const pages=[['overview','Overview'],['projects','Projects'],['queue:active','Active'],['queue:queued','Queued'],['queue:blocked','Blocked'],['runs','Runs'],['papers','Papers'],['corpus','Corpus Import'],['events','Events'],['automation','Publication Automation'],['intake','Ideas'],['research','Research Facility'],['observability','Observability']];
const $=id=>document.getElementById(id); const AI_ACTOR='ai-publication-pipeline'; const AI_NOTE='AI-generated publication pipeline; operator claims no personal authorship credit.';
const esc=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
function token(){return localStorage.getItem('enochControlToken')||'';} function saveToken(){localStorage.setItem('enochControlToken',$('token').value.trim());route();} function globalSearch(){const q=($('globalSearch')?.value||'').trim(); if(q) location.hash='projects?search='+encodeURIComponent(q); }
async function api(path,opts={}){const headers={Authorization:'Bearer '+token(),...(opts.headers||{})}; const requestOpts={cache:'no-store',...opts,headers}; if(!('signal' in requestOpts)&&currentRouteSignal)requestOpts.signal=currentRouteSignal; const r=await fetch(path,requestOpts); if(!r.ok) throw new Error(path+' -> '+r.status+' '+await r.text()); return r.json();}
async function postJson(path,payload){return api(path,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(payload),signal:null});}
function renderNav(active){$('nav').innerHTML=pages.map(([k,l])=>`<a class="${active===k||active.startsWith(k+':')?'active':''}" href="#${k}">${l}</a>`).join('');}
function card(label,value,cls='',note=''){return `<div class="card"><div class="label">${esc(label)}</div><div class="value ${cls}">${esc(value)}</div>${note?`<div class="muted">${esc(note)}</div>`:''}</div>`;}
function debugBlock(label,obj){return `<details><summary>${esc(label)}</summary><pre>${esc(JSON.stringify(obj,null,2))}</pre></details>`;}
function linkProject(id){return id?`<a href="#project:${encodeURIComponent(id)}">${shortId(id)}</a>`:'';} function linkRun(id){return id?`<a href="#run:${encodeURIComponent(id)}">${shortId(id)}</a>`:'';} function linkPaper(id){return id?`<a href="#paper:${encodeURIComponent(id)}">${shortId(id)}</a>`:'';}
function statusClass(value){const s=String(value||'').toLowerCase(); if(['blocked','dispatch_error','failed','error','critical','rejected','negative','not positive','no paper'].some(x=>s.includes(x)))return 'bad'; if(['queued','awaiting','review','paused','warn','pending'].some(x=>s.includes(x)))return 'warn'; if(['complete','finalized','ok','ready','approved','success'].some(x=>s.includes(x)))return 'good'; return 'info';}
function titleCase(s){return String(s||'').replace(/[._-]+/g,' ').replace(/\\b\\w/g,c=>c.toUpperCase());}
function paperStatusLabel(s){const v=String(s||''); const map={draft_review:'First draft',publication_draft:'Publication draft',draft_generating:'Writing draft',publication_generating:'Finalizing draft',human_review_required:'Needs policy decision',finalized:'Ready to publish',approved_for_corpus:'Published'}; return map[v]||titleCase(v);}
function automationStatusLabel(s){const v=String(s||''); const map={unreviewed:'Waiting for automation',triage_ready:'Ready for automation',in_review:'Automation running',changes_requested:'Automation blocked',blocked:'Automation blocked',approved_for_finalization:'Ready to package',finalized:'Finalized',rejected:'Not publishing',queued:'Queued for automation',claimed:'Automation running',deferred:'Deferred'}; return map[v]||titleCase(v);}
function queueStatusLabel(s){const v=String(s||''); const map={queued:'Ready queue',dispatching:'Dispatching',running:'Running',awaiting_wake:'Waiting for worker callback',wake_received:'Reconciling callback',reconciling:'Reconciling',completed:'Completed',paused:'Paused',canceled:'Canceled',dispatch_error:'Dispatch error',blocked:'Needs attention',needs_review:'Needs attention'}; return map[v]||titleCase(v);}
function runStateLabel(s){const v=String(s||''); const map={prepared:'Preparing dispatch',dispatching:'Dispatching',running:'Running',awaiting_wake:'Waiting for callback',question_pending:'Worker question pending',wake_ready:'Worker delivered',session_finished_ready:'Worker delivered',gate_timeout:'Gate timeout',gate_error:'Gate error',reconciled:'Reconciled',dispatch_error:'Dispatch error',dispatch_accepted:'Dispatch accepted',needs_review:'Needs attention',waiting_external_evidence:'Waiting for evidence',unknown:'Historical unknown',cancelled:'Canceled',canceled:'Canceled'}; return map[v]||titleCase(v);}
function shortId(value){const s=String(value||''); if(!s)return ''; if(s.length<=26)return esc(s); return `<span title="${esc(s)}">${esc(s.slice(0,10)+'…'+s.slice(-8))}</span>`;}
function formatBytes(bytes){const n=Number(bytes||0); if(!n)return 'no payload'; if(n>1024*1024)return (n/1024/1024).toFixed(1)+' MB'; if(n>1024)return (n/1024).toFixed(1)+' KB'; return n+' B';}
function formatTime(value){if(!value)return ''; const d=new Date(value); if(Number.isNaN(d.getTime()))return esc(value); return d.toLocaleString([], {month:'short', day:'numeric', hour:'2-digit', minute:'2-digit'});}
function eventLabel(type){const map={'notion.intake':'Legacy Notion import captured','ideas.intake':'Supabase ideas imported','paper_review.finalization_package_prepared':'Finalization package prepared','paper_review.draft_rewritten':'Draft rewritten','paper.drafted':'Paper draft created','paper_review.backfill':'Publication automation backfilled','worker.callback':'Worker callback received','control.pause':'Queue paused','control.resume':'Queue resumed'}; return map[type]||titleCase(type);}
function eventTone(type){const t=String(type||''); if(t.includes('error')||t.includes('failed'))return 'bad'; if(t.includes('blocked')||t.includes('pause'))return 'warn'; if(t.includes('draft')||t.includes('finalization')||t.includes('notion')||t.includes('ideas'))return 'info'; return 'good';}
function payloadDigest(summary){const bytes=summary?.bytes||0; const keys=(summary?.keys||[]).filter(k=>!['notion_rows','paper','payload'].includes(k)).slice(0,4); return `<span class="pill">${esc(formatBytes(bytes))}</span>${keys.map(k=>`<span class="pill">${esc(titleCase(k))}</span>`).join('')}${bytes>1024*1024?'<span class="pill warn">large payload hidden</span>':''}`;}
function activityCards(rows){return `<div class="activity-list">${(rows||[]).map(e=>`<div class="card tight"><div class="row"><strong class="${eventTone(e.event_type)}">${esc(eventLabel(e.event_type))}</strong><span class="pill">${esc(formatTime(e.created_at))}</span><span class="pill">${esc(titleCase(e.entity_type))}</span></div><div class="muted mono">${shortId(e.entity_id)}</div><div class="row">${payloadDigest(e.payload_summary||{})}</div></div>`).join('')||'<div class="card tight"><strong>No recent activity</strong><div class="muted">No control-plane events were returned for this view.</div></div>'}</div>`;}
function cell(c,v,r){if(c==='candidate_action')return r.candidate_id?`<button onclick="selectResearchCandidate('${esc(r.candidate_id)}')">Select</button>`:''; if(c==='project_id')return `${linkProject(v)}${r.project_name?`<div class="muted">${esc(r.project_name)}</div>`:''}`; if(c==='current_run_id'||c==='run_id')return linkRun(v); if(c==='paper_id')return linkPaper(v); if(c==='automation')return r.paper_id?`<a href="#automation:${encodeURIComponent(r.paper_id)}">Open ${esc(r.project_name||r.paper_id)}</a>`:''; if(c==='review')return r.paper_id?`<a href="#automation:${encodeURIComponent(r.paper_id)}">Open ${esc(r.project_name||r.paper_id)}</a>`:''; if(c==='paper_title')return `<strong>${esc(r.project_name||r.paper_id||'Untitled')}</strong><div class="muted mono">${shortId(r.paper_id||'')}</div>`; if(c==='notion_page_url'&&v)return `<a href="${esc(v)}">Source</a>`; if(c==='artifact_paths_present')return Object.entries(v||{}).map(([k,ok])=>`<span class="pill ${ok?'good':'warn'}">${esc(k.replace('_path','').replaceAll('_',' '))}: ${ok?'yes':'no'}</span>`).join(''); if(c==='payload_summary')return payloadDigest(v||{}); if(c==='paper_status'||c==='related_paper_status')return `<span class="truncate ${statusClass(v)}">${esc(paperStatusLabel(v))}</span>`; if(c==='review_status'||c==='related_review_status'||c==='automation_status')return `<span class="truncate ${statusClass(v)}">${esc(automationStatusLabel(v))}</span>`; if(c==='status'||c==='queue_status')return `<span class="truncate ${statusClass(v)}">${esc(queueStatusLabel(v))}</span>`; if(c==='state'||c==='last_run_state'||c==='gate_state')return `<span class="truncate ${statusClass(v)}">${esc(runStateLabel(v))}</span>`; if(c==='entity_id')return shortId(v); if(c==='created_at'||c==='updated_at'||c==='generated_at')return formatTime(v); if(typeof v==='boolean')return `<span class="pill ${v?'good':'warn'}">${v?'yes':'no'}</span>`; if(Array.isArray(v))return `<span class="truncate">${esc(v.join('; '))}</span>`; if(v&&typeof v==='object')return '<span class="muted">details hidden</span>'; return `<span class="truncate ${statusClass(v)}">${esc(v)}</span>`;}
function tableRows(rows,cols,empty='No rows match this view'){return `<table><thead><tr>${cols.map(c=>`<th>${esc(c.replaceAll('_',' '))}</th>`).join('')}</tr></thead><tbody>${(rows||[]).map(r=>`<tr>${cols.map(c=>`<td>${cell(c,r[c],r)}</td>`).join('')}</tr>`).join('')||`<tr><td colspan="${cols.length}">${esc(empty)}</td></tr>`}</tbody></table>`;}
function pageMeta(page,label='Showing'){return `<div class="muted">${esc(label)} ${esc(page?.returned??0)} items · ${page?.has_more?'more available':'end of list'}</div>`;}
function operatorQuestionCards(counts={},operators={},pipeline={},investigation={}){const attention=Number(operators.needs_attention ?? counts.blocked ?? 0), running=Number(counts.active||operators.running||0), write=Number(pipeline.write_needed||0), follow=Number(investigation.followup_needed||operators.followup_investigation||0), publish=Number(pipeline.publish_ready||operators.ready_to_publish||0), done=Number(operators.complete_no_paper||0); return `<section class="card"><h2>What do I need to know?</h2><div class="muted">Primary dashboard cards answer operator questions first. Raw states stay in drill-down/debug views.</div><section class="grid">${card('What needs me?',attention,attention?'warn':'good',attention?'Open Needs attention and resolve blockers/questions.':'Nothing needs operator action.')}${card('What is running?',running,running?'info':'good',running?'Work is executing or waiting on callback.':'No active worker lane.')}${card('What can be written?',write,write?'warn':'good',write?'Only positive, decision-gated runs count here.':'No actionable paper-positive runs need drafts.')}${card('Needs another investigation?',follow,follow?'info':'good',follow?'No-paper rows with specific adjacent follow-up evidence.':'No bounded follow-up candidates.')}${card('What can be published?',publish,publish?'warn':'good',publish?'Finalized drafts are missing corpus import.':'No finalized drafts are missing corpus import.')}${card('What is done / no paper?',done,'muted','Completed non-positive or non-writable rows; no paper action.')}</section></section>`;}
function investigationPipelineCards(investigation={}){const follow=Number(investigation.followup_needed||0), next=investigation.next_followup_candidate||null; const nextText=next?`Next: ${esc(next.followup_title||next.project_name||next.project_id||'untitled')}`:'No bounded follow-up candidate'; const button=follow?'<div class="toolbar"><button onclick="launchNextFollowup()">Launch follow-up</button></div>':''; return `<section class="card"><h2>Investigation follow-ups</h2><div class="muted">Follow-ups are investigation work only. They do not become papers unless the new run independently becomes paper-positive.</div><section class="grid">${card('Needs another investigation',follow,follow?'info':'good',nextText)}${card('Max follow-up depth',investigation.max_followup_depth??2,'muted','Safety cap prevents infinite chaining.')}</section>${button}${debugBlock('Follow-up definitions',investigation.definitions||{})}</section>`;}
function automationReadinessCard(readiness={}){const ok=!!readiness.ok, label=readiness.label||'Long-haul mode: UNKNOWN', blockers=readiness.blockers||[], summary=readiness.summary||{}, checks=readiness.checks||[]; const tone=ok?'good':'warn'; const ageText=(seconds,maxSeconds)=>seconds===null||seconds===undefined?'last tick unknown':`${Math.round(Number(seconds)/60)}m ago · max ${Math.round(Number(maxSeconds||0)/60)}m`; const blockerHtml=blockers.length?`<ul>${blockers.slice(0,6).map(b=>`<li>${esc(b)}</li>`).join('')}</ul>`:'<div class="muted">All long-haul readiness checks passed.</div>'; const checkHtml=checks.slice(0,8).map(c=>`<span class="pill ${c.ok?'good':'warn'}">${esc(c.name)}: ${c.ok?'ok':'blocked'}</span>`).join(''); return `<section class="card" id="automationReadiness"><h2>Automation readiness</h2><div class="row"><span class="pill ${tone}">${esc(label)}</span></div><div class="muted">Single source for overnight/24x7 readiness. This must be READY before claiming unattended long-haul operation.</div>${blockerHtml}<div class="row">${checkHtml}</div><section class="grid">${card('Queue',`queued ${summary.queued||0} · active ${summary.active||0}`,tone,`paused=${summary.queue_paused?'true':'false'} · maintenance=${summary.maintenance_mode?'true':'false'}`)}${card('Research autopilot',summary.research_timer_active?'timer active':'timer inactive',summary.research_timer_active?'good':'warn',`last tick ${ageText(summary.research_tick_age_seconds,summary.research_tick_max_age_seconds)} · result ${summary.research_last_result||'unknown'}`)}${card('Corpus autopilot',summary.corpus_timer_active?'timer active':'timer inactive',summary.corpus_timer_active?'good':'warn',`last tick ${ageText(summary.corpus_tick_age_seconds,summary.corpus_tick_max_age_seconds)} · result ${summary.corpus_last_result||'unknown'}`)}${card('Paper lane',`write ${summary.write_needed||0} · publish ${summary.publish_ready||0}`,tone,`${summary.published_imported||0} imported`)}</section></section>`;}
function paperPipelineCards(pipeline={},papers={}){const write=Number(pipeline.write_needed||0), finalize=Number(pipeline.finalize_needed||0), publish=Number(pipeline.publish_ready||0), imported=Number(pipeline.published_imported||0), totalReady=Number(pipeline.publication_ready_total||0), raw=Number(pipeline.raw_completed_no_paper_candidates||0), blocked=Number(pipeline.not_writable_by_decision_gate||0), next=pipeline.next_write_candidate||null, nextPublish=pipeline.next_publish_candidate||null, lastImport=pipeline.last_import_result||null, ledgerOk=imported===totalReady&&publish===0; const nextText=next?`Next: ${esc(next.project_name||next.project_id||'untitled')}`:'No live write candidate'; const nextPublishText=nextPublish?`Next: ${esc(nextPublish.project_name||nextPublish.paper_id||'untitled')}`:'No corpus-import candidate'; const lastImportText=lastImport?`${esc(lastImport.project_name||lastImport.paper_id||'untitled')} · ${esc(formatTime(lastImport.corpus_imported_at||lastImport.updated_at))}`:'No import ledger row yet'; return `<section class="card"><h2>Paper pipeline</h2><div class="muted">Back-to-basics paper state: write only paper-positive runs, finalize the draft, then publish/import it. These are separate steps.</div><section class="grid">${card('1. Write papers',write,write?'warn':'good',`Actionable paper-positive runs with no live paper row. ${nextText}`)}${card('2. Finalize drafts',finalize,finalize?'warn':'good','Publication drafts missing automated finalization package')}${card('3. Publish/import',publish,publish?'warn':'good',`Finalized drafts missing a corpus-import ledger row. ${nextPublishText}`)}${card('Last import result',lastImport?'synced':'none',lastImport?'good':'muted',lastImportText)}${card('Import validation',ledgerOk?'clean':'pending',ledgerOk?'good':'warn',ledgerOk?'Corpus ledger is reconciled.':'Run capped import, rebuild manifest, and validate counts before publishing.')}${card('Corpus ledger',`${imported}/${totalReady}`,ledgerOk?'good':'warn',ledgerOk?'Reconciled public import ledger':'Imported count does not match finalized/public corpus view')}</section><details><summary>Debug paper counts</summary><div class="muted">Raw completed/no-paper rows are informational, not write work. Historical finalized rows already in the corpus are not import work.</div><section class="grid">${card('Live paper rows',papers.all||0,'info',`${papers.publication_draft||0} publication draft rows · ${papers.archived||0} archived/no-paper rows`)}${card('Publication-ready total',totalReady,'info',`${imported} already imported · ${publish} missing corpus import`)}${card('Raw completed/no-paper candidates',raw,'muted','Before the decision gate; not actionable by itself.')}${card('Rejected by decision gate',blocked,blocked?'good':'muted','Negative, missing, malformed, unknown, or otherwise non-positive decisions.')}</section></details></section>`;}
function workState(counts,operators={},pipeline={},investigation={}){const attention=operators.needs_attention ?? counts.blocked ?? 0, write=Number(pipeline.write_needed||0), follow=Number(investigation.followup_needed||operators.followup_investigation||0), finalize=Number(pipeline.finalize_needed||0), publish=Number(pipeline.publish_ready||operators.ready_to_publish||0), active=counts.active||operators.running||0, queued=counts.queued||operators.ready_queue||0; if(attention)return {label:'Needs attention', tone:'warn', detail:`${attention} item${attention===1?'':'s'} need operator action`}; if(write)return {label:'Papers to write', tone:'warn', detail:`${write} paper-positive run${write===1?'':'s'} still need first paper drafts`}; if(follow)return {label:'Needs another investigation', tone:'info', detail:`${follow} no-paper result${follow===1?'':'s'} have bounded follow-up evidence`}; if(finalize)return {label:'Drafts to finalize', tone:'warn', detail:`${finalize} publication draft${finalize===1?'':'s'} need automated finalization`}; if(publish)return {label:'Ready to publish', tone:'warn', detail:`${publish} finalized publication draft${publish===1?'':'s'} missing corpus import`}; if(active)return {label:'Work running', tone:'info', detail:`${active} active item${active===1?'':'s'} in progress`}; if(queued)return {label:'Ready to dispatch', tone:'info', detail:`${queued} queued item${queued===1?'':'s'} waiting`}; return {label:'Work is idle', tone:'good', detail:'No active, queued, follow-up, or paper-pipeline work needs action right now'};}

function commandResultBlock(result){return `<details open><summary>Last command result</summary><pre>${esc(JSON.stringify(result,null,2))}</pre></details>`;}
function dispatchOneControls(queued,active){return `<div class="toolbar"><input id="dispatchOneProjectId" placeholder="queued project id"/><button onclick="dispatchSelectedProject()" ${queued&&!active?'':'disabled'}>Dispatch selected queued project</button></div><div class="muted">Single-project dispatch works even while the broad queue is paused. It dry-runs the selected project first and never starts a batch drain.</div>`;}
function operatorCommandPanel(counts={}){const queued=Number(counts.queued||0), active=Number(counts.active||0); return `<section class="card" id="commandPanel"><h2>Commands</h2><div class="muted">Authenticated operator controls. Pause/resume are immediate; Start next does a dry-run first and asks before live dispatch.</div><div class="toolbar"><button onclick="pauseQueue()">Pause queue</button><button onclick="resumeQueue()">Resume queue</button><button onclick="dryRunDispatchNext()">Check next dispatch</button><button onclick="startNextDispatch()" ${queued&&!active?'':'disabled'}>Start next queued item</button></div><h3>Controlled one-off dispatch</h3>${dispatchOneControls(queued,active)}<div id="commandStatus" class="muted">Queued ${esc(queued)} · active ${esc(active)}. Loading pause state…</div></section>`;}
function setCommandBusy(label){const el=$('commandStatus'); if(el){el.className='banner warn'; el.textContent=label;}}
function setCommandResult(result,tone='info'){const el=$('commandStatus'); if(el){el.className='banner '+tone; el.innerHTML=commandResultBlock(result);}}
async function refreshCommandPanel(){const el=$('commandPanel'); if(!el)return; try{const existingProjectId=$('dispatchOneProjectId')?.value||''; const state=await api('/control/state'); const flags=state.flags||{}, counts=state.counts||{}, next=state.next_candidate||null; const queued=Number(counts.queued||0), active=Number(counts.active||0), paused=Boolean(flags.queue_paused), maintenance=Boolean(flags.maintenance_mode); el.innerHTML=`<h2>Commands</h2><div class="muted">Authenticated operator controls. Pause/resume are immediate; Start next does a dry-run first and asks before live dispatch.</div><div class="toolbar"><button onclick="pauseQueue()" ${paused?'disabled':''}>Pause queue</button><button onclick="resumeQueue()" ${!paused&&!maintenance?'disabled':''}>Resume queue</button><button onclick="dryRunDispatchNext()">Check next dispatch</button><button onclick="startNextDispatch()" ${queued&&!active&&!paused&&!maintenance?'':'disabled'}>Start next queued item</button></div><h3>Controlled one-off dispatch</h3>${dispatchOneControls(queued,active)}<div id="commandStatus" class="banner ${paused||maintenance?'warn':'good'}"><strong>${paused||maintenance?'Queue paused':'Queue open'}</strong><div>Queued ${esc(queued)} · active ${esc(active)} · maintenance ${maintenance?'on':'off'}</div><div class="muted">${next?`Next: ${esc(next.project_name||next.project_id)}`:'No next candidate'}</div></div>`; const input=$('dispatchOneProjectId'); if(input&&existingProjectId)input.value=existingProjectId;}catch(e){const status=$('commandStatus'); if(status){status.className='banner critical'; status.textContent='Command state unavailable: '+e.message;}}}
async function pauseQueue(){setCommandBusy('Pausing queue…'); const result=await postJson('/control/pause',{reason:'dashboard operator pause',paused_by:'dashboard',maintenance_mode:true}); setCommandResult(result,'good'); return route();}
async function resumeQueue(){setCommandBusy('Resuming queue…'); const result=await postJson('/control/resume',{resumed_by:'dashboard',maintenance_mode:false}); setCommandResult(result,'good'); return route();}
async function dryRunDispatchNext(){setCommandBusy('Checking next dispatch candidate…'); const result=await postJson('/control/dispatch-next',{dry_run:true,requested_by:'dashboard',force_preflight:true}); setCommandResult(result,result.action==='dry_run_dispatch'?'good':'warn'); return refreshCommandPanel();}
async function startNextDispatch(){setCommandBusy('Dry-running dispatch before live start…'); const dry=await postJson('/control/dispatch-next',{dry_run:true,requested_by:'dashboard',force_preflight:true}); if(dry.action!=='dry_run_dispatch'){setCommandResult(dry,'warn'); await refreshCommandPanel(); return;} const candidate=dry.candidate||{}; const name=candidate.project_name||candidate.project_id||'next queued item'; if(!confirm(`Start live dispatch for ${name}? This may launch GB10 work.`)){setCommandResult({ok:true,action:'cancelled',reason:'operator cancelled live dispatch',candidate},'warn'); return;} setCommandBusy('Refreshing worker state, then starting live dispatch…'); const result=await postJson('/control/dispatch-next',{dry_run:false,requested_by:'dashboard',force_preflight:true}); setCommandResult(result,result.action==='live_dispatch'?'good':'warn'); return route();}
async function dispatchSelectedProject(){const projectId=($('dispatchOneProjectId')?.value||'').trim(); if(!projectId){setCommandResult({ok:false,action:'dispatch_blocked',reason:'Enter a queued project id before dispatching.'},'warn'); return;} setCommandBusy('Dry-running selected project dispatch…'); const dry=await postJson('/control/dispatch-one',{project_id:projectId,dry_run:true,requested_by:'dashboard',force_preflight:true}); if(dry.action!=='dry_run_dispatch_one'){setCommandResult(dry,'warn'); await refreshCommandPanel(); const input=$('dispatchOneProjectId'); if(input)input.value=projectId; return;} const candidate=dry.candidate||{}; const name=candidate.project_name||candidate.project_id||projectId; if(!confirm(`Dispatch exactly this queued project while preserving the broad queue pause?\n\n${name}`)){setCommandResult({ok:true,action:'cancelled',reason:'operator cancelled selected-project dispatch',candidate},'warn'); return;} setCommandBusy('Starting exactly one selected queued project…'); const result=await postJson('/control/dispatch-one',{project_id:projectId,dry_run:false,requested_by:'dashboard',force_preflight:true}); setCommandResult(result,result.action==='live_dispatch_one'?'good':'warn'); return route();}
async function launchNextFollowup(){setCommandBusy('Checking bounded follow-up candidate…'); const dry=await postJson('/control/api/v1/followups/launch-next',{dry_run:true,requested_by:'dashboard',max_followup_depth:2}); if(dry.action!=='dry_run_followup'){setCommandResult(dry,'warn'); return refreshCommandPanel();} const f=dry.followup||{}; if(!confirm(`Queue follow-up investigation: ${f.title||f.idea_id||'untitled'}? This only queues investigation work; it does not write a paper.`)){setCommandResult({ok:true,action:'cancelled',reason:'operator cancelled follow-up launch',candidate:dry.candidate,followup:f},'warn'); return;} const result=await postJson('/control/api/v1/followups/launch-next',{dry_run:false,requested_by:'dashboard',max_followup_depth:2}); setCommandResult(result,result.action==='followup_queued'?'good':'warn'); return route();}
async function overviewPage(){const routeKey=(location.hash||'#overview').slice(1).split('?')[0]||'overview'; renderNav('overview'); const app=$('app'), hasOverview=app?.dataset?.page==='overview'; const previousCommandPanel=hasOverview?$('commandPanel')?.outerHTML||'':''; $('status').className='pill warn'; $('status').textContent=hasOverview?'Refreshing overview…':'Loading overview…'; if(!hasOverview){app.className=''; app.innerHTML='<section class="card"><h2>Loading overview…</h2><div class="muted">Fetching the bounded operator summary first. Secondary health checks load after the primary cards render.</div></section>';} const overview=await api('/control/api/v1/overview?active_limit=8&event_limit=6'); if((location.hash||'#overview').slice(1).split('?')[0]!==routeKey)return; const counts=overview.counts||{}, papers=overview.paper_counts||{}, ops=overview.operator_counts||{}, pipeline=overview.paper_pipeline||{}, investigation=overview.investigation_pipeline||{}, state=workState(counts,ops,pipeline,investigation); $('status').className='pill '+state.tone; $('status').textContent=`Overview · ${state.label}`; $('app').dataset.page='overview'; $('app').className=''; $('app').innerHTML=`<section class="banner ${state.tone}"><h2>${esc(state.label)}</h2><div>${esc(state.detail)}</div><div class="muted">Last refreshed ${esc(formatTime(overview.generated_at))}. Showing bounded, operator-safe summaries.</div></section>${previousCommandPanel||operatorCommandPanel(counts)}${operatorQuestionCards(counts,ops,pipeline,investigation)}${investigationPipelineCards(investigation)}${paperPipelineCards(pipeline,papers)}<section class="card" id="automationReadiness"><h2>Automation readiness</h2><div class="row"><span class="pill warn">Loading readiness…</span></div><div class="muted">Checking queue flags, timers, recent ticks, provider budget, and paper gate status.</div></section><section class="grid two"><div class="card"><h2>Active work</h2><div class="muted">Only work currently running or awaiting callback appears here.</div>${tableRows(overview.active_items||[],['operator_stage_label','project_id','current_run_id','operator_next_step','updated_at'],'No active work right now')}</div><div class="card" id="overviewHealth"><h2>System health</h2><div class="row"><span class="pill warn">Loading health…</span></div><div class="muted">Secondary health checks load after the primary operator cards so they do not block the overview.</div></div></section><section class="card"><h2>Recent activity</h2><div class="muted">Formatted control-plane events. Large payloads stay hidden.</div>${activityCards(overview.recent_events||[])}</section>`; api('/control/api/v1/automation-readiness').then(readiness=>{if((location.hash||'#overview').slice(1).split('?')[0]!==routeKey)return; const el=$('automationReadiness'); if(el)el.outerHTML=automationReadinessCard(readiness);}).catch(e=>{if((location.hash||'#overview').slice(1).split('?')[0]!==routeKey)return; const el=$('automationReadiness'); if(el)el.innerHTML=`<h2>Automation readiness</h2><span class="pill warn">Readiness unavailable</span><div class="muted">${esc(e.message)}</div>`;}); Promise.all([api('/control/api/v1/observability/memory'),api('/control/api/v1/observability/health')]).then(([memory,health])=>{if((location.hash||'#overview').slice(1).split('?')[0]!==routeKey)return; const el=$('overviewHealth'); if(!el)return; el.innerHTML=`<h2>System health</h2><div class="row"><span class="pill ${memory.memory_warn?'warn':'good'}">Controller memory ${esc(Number(memory.rss_mib||0).toFixed(0))} MiB</span><span class="pill">Peak ${esc(Number(memory.peak_rss_mib||0).toFixed(0))} MiB</span><span class="pill ${health.route_observability_enabled?'good':'warn'}">Route observations ${health.route_observability_enabled?'on':'off'}</span></div><div class="muted">Memory is shown as a secondary health signal, not the primary work status.</div>`;}).catch(e=>{if((location.hash||'#overview').slice(1).split('?')[0]!==routeKey)return; const el=$('overviewHealth'); if(el)el.innerHTML=`<h2>System health</h2><span class="pill warn">Health unavailable</span><div class="muted">${esc(e.message)}</div>`;}); refreshCommandPanel();}
function projectControls(view,params){const size=params.get('page_size')||'50', sort=params.get('sort')||'recent', status=params.get('status')||'', term=params.get('search')||''; return `<div class="toolbar-note">Find projects by name, status, run, or action. Sort by Recently added or Recently updated, and choose 200 per page when you need a wider read.</div><div class="toolbar"><input id="search" value="${esc(term)}" placeholder="Find projects, status, run, action" onkeydown="if(event.key==='Enter') applyProjectFilters('${view}')"/><select id="statusFilter"><option value="">all statuses</option>${['queued','awaiting_wake','running','needs_review','blocked','dispatch_error','paused','completed','canceled'].map(v=>`<option value="${v}" ${status===v?'selected':''}>${queueStatusLabel(v)}</option>`).join('')}</select><select id="sortFilter"><option value="recent" ${sort==='recent'?'selected':''}>Recently updated</option><option value="created" ${sort==='created'?'selected':''}>Recently added</option><option value="priority" ${sort==='priority'?'selected':''}>Dispatch priority</option><option value="name" ${sort==='name'?'selected':''}>Project name</option><option value="status" ${sort==='status'?'selected':''}>Status</option></select><select id="pageSize">${['25','50','100','200'].map(v=>`<option value="${v}" ${size===v?'selected':''}>${v} per page</option>`).join('')}</select><button onclick="applyProjectFilters('${view}')">Apply</button><button onclick="location.hash='${view}'">Reset</button></div>`;}
function applyProjectFilters(view){const params=new URLSearchParams(); const term=$('search')?.value||''; const status=$('statusFilter')?.value||''; const sort=$('sortFilter')?.value||'recent'; const pageSize=$('pageSize')?.value||'50'; if(term)params.set('search',term); if(status)params.set('status',status); if(sort)params.set('sort',sort); if(pageSize)params.set('page_size',pageSize); location.hash=view+(params.toString()?('?'+params.toString()):'');}
async function projectListPage(view='projects',queue='all'){renderNav(view); const params=new URLSearchParams(location.hash.split('?')[1]||''); const term=params.get('search')||'', cursor=params.get('cursor')||'', pageSize=params.get('page_size')||'50', sort=params.get('sort')||(view==='projects'?'recent':'priority'), status=params.get('status')||''; const qs=new URLSearchParams({queue,page_size:pageSize,search:term,cursor,sort,status}); const data=await api('/control/api/v1/queue?'+qs.toString()); const counts=data.counts||{}; const title=view==='projects'?'All projects':({active:'Active work',queued:'Ready queue',blocked:'Needs attention',paused:'Paused work',completed:'Completed work'}[queue]||titleCase(queue)+' queue'); $('status').className='pill '+(queue==='blocked'?'warn':'info'); $('status').textContent=`${title} · showing ${data.page.returned} · ${counts.blocked||0} need attention`; const nextParams=new URLSearchParams(params); if(data.page.next_cursor)nextParams.set('cursor',data.page.next_cursor); $('app').className=''; $('app').innerHTML=`<section class="card"><h2>${esc(title)}</h2><div class="muted">Search, filter, sort, and page through the complete project list. Use “Recently added” or “Recently updated” to find the last projects added or pushed.</div><section class="grid"><div class="card tight"><div class="label">Showing now</div><div class="value">${esc(data.page.returned)}</div></div><div class="card tight"><div class="label">Running</div><div class="value ${counts.active?'info':'good'}">${esc(counts.active||0)}</div></div><div class="card tight"><div class="label">Queued</div><div class="value info">${esc(counts.queued||0)}</div></div><div class="card tight"><div class="label">Needs attention</div><div class="value ${counts.blocked?'warn':'good'}">${esc(counts.blocked||0)}</div></div></section>${projectControls(view,params)}${tableRows(data.rows,['operator_stage_label','project_decision_summary','project_id','dispatch_priority','selection_rank','current_run_id','operator_next_step','updated_at'],`No ${title.toLowerCase()} items match these filters`)}<div class="toolbar">${cursor?`<button onclick="history.back()">Previous view</button>`:''}${data.page.has_more?`<button onclick="location.hash='${view}?${nextParams.toString()}'">Next page</button>`:''}</div></section>`;}
async function queuePage(q){return projectListPage('queue:'+q,q);}
function runControls(params){const size=params.get('page_size')||'50', state=params.get('state')||'', sort=params.get('sort')||'recent', term=params.get('search')||'', project=params.get('project_id')||''; return `<div class="toolbar-note">Find runs by project, run id, state, or worker activity. Filter by run state, sort by recent/start/end/project, and choose 200 per page.</div><div class="toolbar"><input id="runSearch" value="${esc(term)}" placeholder="Find runs, projects, sessions" onkeydown="if(event.key==='Enter') applyRunFilters()"/><input id="runProject" value="${esc(project)}" placeholder="project id filter"/><select id="runState"><option value="">all run states</option>${['wake_ready','session_finished_ready','awaiting_wake','running','failed','dispatch_error'].map(v=>`<option value="${v}" ${state===v?'selected':''}>${runStateLabel(v)}</option>`).join('')}</select><select id="runSort"><option value="recent" ${sort==='recent'?'selected':''}>Recently updated</option><option value="started" ${sort==='started'?'selected':''}>Recently started</option><option value="ended" ${sort==='ended'?'selected':''}>Recently ended</option><option value="state" ${sort==='state'?'selected':''}>State</option><option value="project" ${sort==='project'?'selected':''}>Project</option><option value="oldest" ${sort==='oldest'?'selected':''}>Oldest updated</option></select><select id="runPageSize">${['25','50','100','200'].map(v=>`<option value="${v}" ${size===v?'selected':''}>${v} per page</option>`).join('')}</select><button onclick="applyRunFilters()">Apply</button><button onclick="location.hash='runs'">Reset</button></div>`;}
function applyRunFilters(){const params=new URLSearchParams(); const term=$('runSearch')?.value||'', project=$('runProject')?.value||'', state=$('runState')?.value||'', sort=$('runSort')?.value||'recent', pageSize=$('runPageSize')?.value||'50'; if(term)params.set('search',term); if(project)params.set('project_id',project); if(state)params.set('state',state); if(sort)params.set('sort',sort); if(pageSize)params.set('page_size',pageSize); location.hash='runs'+(params.toString()?('?'+params.toString()):'');}
async function runsPage(){renderNav('runs'); const params=new URLSearchParams(location.hash.split('?')[1]||''); const cursor=params.get('cursor')||'', pageSize=params.get('page_size')||'50', state=params.get('state')||'', project=params.get('project_id')||'', term=params.get('search')||'', sort=params.get('sort')||'recent'; const qs=new URLSearchParams({page_size:pageSize,cursor,state,project_id:project,search:term,sort}); const data=await api('/control/api/v1/runs?'+qs.toString()); const nextParams=new URLSearchParams(params); if(data.page.next_cursor)nextParams.set('cursor',data.page.next_cursor); $('status').className='pill info'; $('status').textContent=`Runs · showing ${data.page.returned}`; $('app').className=''; $('app').innerHTML=`<section class="card"><h2>Runs</h2><div class="muted">Browse worker runs with the same management affordances as projects and papers.</div>${runControls(params)}${pageMeta(data.page)}${tableRows(data.rows,['operator_stage_label','project_id','run_id','related_paper_id','operator_next_step','updated_at'])}<div class="toolbar">${cursor?`<button onclick="history.back()">Previous view</button>`:''}${data.page.has_more?`<button onclick="location.hash='runs?${nextParams.toString()}'">Next page</button>`:''}</div></section>`;}
function paperControls(params){const size=params.get('page_size')||'50', status=params.get('status')||'', sort=params.get('sort')||'recent', term=params.get('search')||''; return `<div class="toolbar-note">Find papers by title, project, run, or status. Filter publication drafts and choose 200 per page when you need a wider read.</div><div class="toolbar"><input id="paperSearch" value="${esc(term)}" placeholder="Find papers, projects, runs" onkeydown="if(event.key==='Enter') applyPaperFilters()"/><select id="paperStatus"><option value="">all paper statuses</option>${['publication_draft','archived'].map(v=>`<option value="${v}" ${status===v?'selected':''}>${paperStatusLabel(v)}</option>`).join('')}</select><select id="paperSort"><option value="recent" ${sort==='recent'?'selected':''}>Recently updated</option><option value="created" ${sort==='created'?'selected':''}>Recently added</option><option value="status" ${sort==='status'?'selected':''}>Status</option><option value="title" ${sort==='title'?'selected':''}>Paper title</option></select><select id="paperPageSize">${['25','50','100','200'].map(v=>`<option value="${v}" ${size===v?'selected':''}>${v} per page</option>`).join('')}</select><button onclick="applyPaperFilters()">Apply</button><button onclick="location.hash='papers'">Reset</button></div>`;}
function applyPaperFilters(){const params=new URLSearchParams(); const term=$('paperSearch')?.value||'', status=$('paperStatus')?.value||'', sort=$('paperSort')?.value||'recent', pageSize=$('paperPageSize')?.value||'50'; if(term)params.set('search',term); if(status)params.set('status',status); if(sort)params.set('sort',sort); if(pageSize)params.set('page_size',pageSize); location.hash='papers'+(params.toString()?('?'+params.toString()):'');}
async function papersPage(){renderNav('papers'); const params=new URLSearchParams(location.hash.split('?')[1]||''); const pageSize=params.get('page_size')||'50', status=params.get('status')||'', term=params.get('search')||'', cursor=params.get('cursor')||'', sort=params.get('sort')||'recent'; const qs=new URLSearchParams({page_size:pageSize,status,search:term,cursor,sort}); const data=await api('/control/api/v1/papers?'+qs.toString()); const counts=data.counts||{}; const nextParams=new URLSearchParams(params); if(data.page.next_cursor)nextParams.set('cursor',data.page.next_cursor); $('status').className='pill info'; $('status').textContent=`Papers · showing ${data.page.returned} · ${counts.publication_draft||0} drafts`; $('app').className=''; $('app').innerHTML=`<section class="card"><h2>Papers</h2><div class="muted">Browse paper artifacts with the same management affordances as projects: search, filter, sort, page size, and next-page navigation.</div><section class="grid"><div class="card tight"><div class="label">Showing now</div><div class="value">${esc(data.page.returned)}</div></div><div class="card tight"><div class="label">Publication drafts</div><div class="value info">${esc(counts.publication_draft||0)}</div></div><div class="card tight"><div class="label">First drafts</div><div class="value warn">${esc(counts.draft_review||0)}</div></div><div class="card tight"><div class="label">All papers</div><div class="value">${esc(counts.all||0)}</div></div></section>${paperControls(params)}${tableRows(data.rows,['operator_stage_label','paper_title','project_id','run_id','artifact_paths_present','updated_at'],`No papers match these filters`)}<div class="toolbar">${cursor?`<button onclick="history.back()">Previous view</button>`:''}${data.page.has_more?`<button onclick="location.hash='papers?${nextParams.toString()}'">Next page</button>`:''}</div></section>`;}
async function corpusPage(){renderNav('corpus'); const overview=await api('/control/api/v1/overview?active_limit=1&event_limit=1'); const data=await api('/control/api/v1/papers?page_size=50&status=publication_draft&sort=recent'); const pipeline=overview.paper_pipeline||{}; const rows=data.rows||[]; $('status').className='pill '+(Number(pipeline.publish_ready||0)?'warn':'good'); $('status').textContent=`Corpus import · ${pipeline.publish_ready||0} missing`; $('app').className=''; $('app').innerHTML=`<section class="card"><h2>Corpus Import</h2><div class="muted">Ledger-backed publication view. Publish/import work means finalized publication drafts missing a corpus-import ledger row; already imported drafts are informational.</div><section class="grid">${card('Missing corpus import',pipeline.publish_ready||0,Number(pipeline.publish_ready||0)?'warn':'good','Actionable import work only')}${card('Already imported',pipeline.published_imported||0,'good','Recorded in corpus_imports ledger')}${card('Publication-ready total',pipeline.publication_ready_total||0,'info','Finalized drafts whether imported or missing')}${card('Public corpus gap',pipeline.missing_from_corpus||0,Number(pipeline.missing_from_corpus||0)?'warn':'good','Same as missing corpus import')}</section><h3>Recent publication drafts</h3>${tableRows(rows,['operator_stage_label','paper_title','corpus_imported','corpus_import_id','project_id','run_id','updated_at'],'No publication drafts returned')}</section>`;}

function eventControls(params){const size=params.get('page_size')||'50', sort=params.get('sort')||'recent', term=params.get('search')||'', type=params.get('entity_type')||'', id=params.get('entity_id')||'', event=params.get('event_type')||''; return `<div class="toolbar-note">Find events by type, entity id, or payload text. Filter by entity/event type and sort the activity stream.</div><div class="toolbar"><input id="eventSearch" value="${esc(term)}" placeholder="Find events or payload text" onkeydown="if(event.key==='Enter') applyEventFilters()"/><input id="eventType" value="${esc(event)}" placeholder="event type"/><input id="entityType" value="${esc(type)}" placeholder="entity type"/><input id="entityId" value="${esc(id)}" placeholder="entity id"/><select id="eventSort"><option value="recent" ${sort==='recent'?'selected':''}>Newest first</option><option value="type" ${sort==='type'?'selected':''}>Event type</option><option value="entity" ${sort==='entity'?'selected':''}>Entity</option></select><select id="eventPageSize">${['25','50','100','200'].map(v=>`<option value="${v}" ${size===v?'selected':''}>${v} per page</option>`).join('')}</select><button onclick="applyEventFilters()">Apply</button><button onclick="location.hash='events'">Reset</button></div>`;}
function applyEventFilters(){const params=new URLSearchParams(); const term=$('eventSearch')?.value||'', eventType=$('eventType')?.value||'', entityType=$('entityType')?.value||'', entityId=$('entityId')?.value||'', sort=$('eventSort')?.value||'recent', pageSize=$('eventPageSize')?.value||'50'; if(term)params.set('search',term); if(eventType)params.set('event_type',eventType); if(entityType)params.set('entity_type',entityType); if(entityId)params.set('entity_id',entityId); if(sort)params.set('sort',sort); if(pageSize)params.set('page_size',pageSize); location.hash='events'+(params.toString()?('?'+params.toString()):'');}
async function eventsPage(){renderNav('events'); const params=new URLSearchParams(location.hash.split('?')[1]||''); const cursor=params.get('cursor')||'', pageSize=params.get('page_size')||'50', term=params.get('search')||'', entityType=params.get('entity_type')||'', entityId=params.get('entity_id')||'', eventType=params.get('event_type')||'', sort=params.get('sort')||'recent'; const qs=new URLSearchParams({page_size:pageSize,cursor,search:term,entity_type:entityType,entity_id:entityId,event_type:eventType,sort}); const data=await api('/control/api/v1/events?'+qs.toString()); const nextParams=new URLSearchParams(params); if(data.page.next_cursor)nextParams.set('cursor',data.page.next_cursor); $('status').className='pill info'; $('status').textContent=`Activity log · ${data.page.returned} shown`; $('app').className=''; $('app').innerHTML=`<section class="card"><h2>Activity log</h2><div class="muted">Human-readable event stream. Payload fields are summarized as chips; large payloads are not printed into the table.</div>${eventControls(params)}${pageMeta(data.page,'Showing latest')}${activityCards(data.rows||[])}<div class="toolbar">${cursor?`<button onclick="history.back()">Previous view</button>`:''}${data.page.has_more?`<button onclick="location.hash='events?${nextParams.toString()}'">Next page</button>`:''}</div></section>`;}
async function observabilityPage(){renderNav('observability'); const [memory,health]=await Promise.all([api('/control/api/v1/observability/memory'),api('/control/api/v1/observability/health')]); $('status').className='pill '+(memory.memory_warn?'warn':'good'); $('status').textContent=`Observability · controller memory ${Number(memory.rss_mib||0).toFixed(0)} MiB`; $('app').className=''; $('app').innerHTML=`<section class="grid three">${card('Controller memory',Number(memory.rss_mib||0).toFixed(0),memory.memory_warn?'warn':'good','MiB RSS now')}${card('Peak memory',Number(memory.peak_rss_mib||0).toFixed(0),'info','MiB since process start')}${card('Route observations',health.route_observability_enabled?'On':'Off',health.route_observability_enabled?'good':'warn','Request timing and size sampling')}</section><section class="card"><h2>Diagnostics</h2><div class="muted">Technical route-observation evidence is collapsed here for debugging only.</div>${health.latest_route_observation?`<details><summary>Latest route observation JSONL</summary><pre>${esc(health.latest_route_observation)}</pre></details>`:'<span class="pill warn">No observation logged</span>'}${debugBlock('Memory details',memory)}${debugBlock('Health details',health)}</section>`;}
async function intakePage(){renderNav('intake'); const data=await api('/control/api/intake/ideas'); $('status').className='pill info'; $('status').textContent='Supabase ideas'; $('app').className=''; $('app').innerHTML=`<section class="grid two"><div class="card"><h2>Supabase idea workbench</h2><div class="muted">Native idea rows are the editable intake ledger. Legacy Notion fields, when present, are provenance only.</div>${tableRows([data.latest_sync||{}],['source','status','observed_at','authority'])}${debugBlock('Latest intake JSON',data.latest_sync||{})}</div><div class="card"><h2>Skipped reasons</h2>${tableRows(Object.entries(data.skipped_reasons||{}).map(([reason,count])=>({reason,count})),['reason','count'])}</div></section><section class="card"><h2>Idea workbench</h2>${tableRows(data.queued_projection||[],['idea_id','title','idea_status','queue_status','next_action_hint','paper_status','source_kind','updated_at'])}</section>`;}
async function checkProviderBudget(){const el=$('providerBudgetStatus'); if(el){el.className='banner warn'; el.textContent='Checking provider budget…';} try{const result=await api('/control/api/research/provider-budget?estimated_requests=1&reserve_requests=2'); const tone=result.ok?'good':'warn'; if(el){el.className='banner '+tone; el.innerHTML=`<strong>Provider budget ${result.ok?'ok':'not ready'}</strong><div>Remaining credits ${esc(result.remaining_credits??'unknown')} · rolling remaining ${esc(result.rolling_remaining??'unknown')}</div><div class="muted">${(result.failures||[]).length?esc((result.failures||[]).join('; ')):'No budget failures reported.'}</div>${debugBlock('Provider budget details',result)}`;} }catch(e){if(el){el.className='banner critical'; el.textContent='Provider budget check failed: '+e.message;}}}
async function generateProviderCandidateBatch(){const el=$('researchProviderGenerateStatus'); if(el){el.className='banner warn'; el.textContent='Checking provider quota before generation…';} const topic=($('researchProviderTopic')?.value||'').trim(); const model=($('researchProviderModel')?.value||'').trim(); const dry=await postJson('/control/api/research/generate-provider-batch',{dry_run:true,max_candidates:2,topic,model,temperature:0.6,generation_max_tokens:8000,generation_attempts:2,requested_by:'dashboard'}); if(el){el.className=dry.ok?'banner good':'banner warn'; el.innerHTML=`<strong>Provider generation preflight ${dry.ok?'passed':'blocked'}.</strong><div>${esc((dry.budget||{}).remaining_credits??'unknown')} credits · rolling ${esc((dry.budget||{}).rolling_remaining??'unknown')} · no provider request spent.</div>${debugBlock('Provider dry-run details',dry)}`;} if(!dry.ok)return; if(!confirm(`Spend one provider request to generate up to ${dry.max_candidates||2} candidates?\n\nThis writes Research Facility ledgers only. It will not queue or dispatch work.`))return; if(el){el.className='banner warn'; el.textContent='Calling provider and writing candidate/admission ledgers only…';} const live=await postJson('/control/api/research/generate-provider-batch',{dry_run:false,max_candidates:2,topic,model,temperature:0.6,generation_max_tokens:8000,generation_attempts:2,requested_by:'dashboard'}); if(el){el.className=live.ok?'banner good':'banner warn'; el.innerHTML=`<strong>Provider generation ${live.ok?'complete':'blocked'}.</strong><div>${esc(live.candidate_count||0)} candidates · admitted ${esc(live.admitted_count||0)} · review ${esc(live.needs_review_count||0)} · queued ${esc(live.queued_count||0)}.</div>${debugBlock('Provider live details',live)}`;} return researchPage();}
async function generateResearchSmokeBatch(){const el=$('researchGenerateStatus'); if(el){el.className='banner warn'; el.textContent='Dry-running candidate generation…';} const dry=await postJson('/control/api/research/generate-batch',{dry_run:true,max_candidates:3,requested_by:'dashboard'}); if(el){el.className=dry.ok?'banner good':'banner warn'; el.innerHTML=`<strong>Dry-run generated ${esc(dry.candidate_count||0)} candidates.</strong><div>${esc(dry.admitted_count||0)} admitted · ${esc(dry.needs_review_count||0)} need review · ${esc(dry.rejected_count||0)} rejected. No ledger rows written.</div>${debugBlock('Dry-run generation details',dry)}`;} if(!dry.ok||!Number(dry.candidate_count||0))return; if(!confirm(`Write ${dry.candidate_count} generated candidates to Research Facility ledgers only? This will not queue or dispatch work.`))return; if(el){el.className='banner warn'; el.textContent='Writing candidate/admission ledgers…';} const live=await postJson('/control/api/research/generate-batch',{dry_run:false,max_candidates:3,requested_by:'dashboard'}); if(el){el.className=live.ok?'banner good':'banner warn'; el.innerHTML=`<strong>Research ledger write ${live.ok?'complete':'not complete'}.</strong><div>${esc(live.candidate_count||0)} candidates · ${esc(live.ledger_result?.admissions_inserted??0)} new admission rows · queued ${esc(live.queued_count||0)}.</div>${debugBlock('Live generation details',live)}`;} return researchPage();}
async function runResearchCycle(dryRun){const el=$('researchAutopilotStatus'); const dispatch=Boolean($('researchCycleDispatch')?.checked), wait=Boolean($('researchCycleWait')?.checked), papers=Boolean($('researchCyclePapers')?.checked); if(el){el.className='banner warn'; el.textContent=dryRun?'Dry-running bounded research cycle…':'Running one bounded research cycle…';} if(!dryRun&&!confirm(`Run one bounded Research Facility cycle?\n\nThis may spend one provider request and promote one admitted candidate.${dispatch?' It may also dispatch exactly one queued candidate while preserving the global queue pause.':' It will not dispatch work.'}${papers?' If a completed run is paper-positive, it may draft and finalize exactly one paper.':' It will not write papers.'}`))return; const payload={enabled:!dryRun,dry_run:dryRun,max_provider_requests_per_run:1,max_promotions_per_run:1,max_dispatches_per_run:dispatch?1:0,wait_for_completion:wait,max_wait_seconds:wait?900:0,max_paper_drafts_per_run:papers?1:0,max_publication_rewrites_per_run:papers?1:0,model:($('researchProviderModel')?.value||'').trim(),topic:($('researchProviderTopic')?.value||'').trim(),generation_max_tokens:8000,generation_attempts:2,temperature:0.6,requested_by:'dashboard'}; const result=await postJson('/control/api/research/run-cycle',payload); if(el){el.className=result.ok?'banner good':'banner warn'; el.innerHTML=`<strong>Bounded research cycle ${result.ok?'complete':'stopped'}.</strong><div>${esc(result.generated_count||0)} generated · ${esc(result.promoted_count||0)} promoted · ${esc(result.dispatched_count||0)} dispatched · ${esc(result.paper_drafted_count||0)} drafted · ${esc(result.publication_finalized_count||0)} finalized · queued ${esc(result.queued_count||0)}.</div><div class="muted">${esc(result.reason||'Policy-gated cycle finished.')}</div>${debugBlock('Research autopilot details',result)}`;} return researchPage();}
function selectResearchCandidate(candidateId){const input=$('researchCandidateId'); if(input)input.value=candidateId; const el=$('researchPromoteStatus'); if(el){el.className='banner info'; el.innerHTML=`Selected admitted candidate <span class="mono">${esc(candidateId)}</span>. Next step: dry-run promotion.`;} }
async function promoteResearchCandidate(){const el=$('researchPromoteStatus'), candidateId=($('researchCandidateId')?.value||'').trim(); if(!candidateId){if(el){el.className='banner warn'; el.textContent='Enter an admitted candidate id before promotion.';} return;} if(el){el.className='banner warn'; el.textContent='Dry-running candidate promotion…';} const dry=await postJson('/control/api/research/promote-candidate',{candidate_id:candidateId,dry_run:true,requested_by:'dashboard'}); if(dry.action!=='dry_run_promote_candidate'){if(el){el.className='banner warn'; el.innerHTML=`<strong>Promotion blocked.</strong><div>${esc(dry.reason||'Candidate is not promotable.')}</div>${debugBlock('Dry-run promotion details',dry)}`;} return;} if(el){el.className='banner good'; el.innerHTML=`<strong>Dry-run promotion passed.</strong><div>${esc(dry.title||candidateId)} can be promoted to queued idea/project rows. No dispatch will run.</div>${debugBlock('Dry-run promotion details',dry)}`;} if(!confirm(`Promote this admitted Research Facility candidate into the idea/project queue?\n\n${candidateId}\n\nThis will not dispatch work.`))return; if(el){el.className='banner warn'; el.textContent='Writing promotion ledgers and queued idea/project rows…';} const live=await postJson('/control/api/research/promote-candidate',{candidate_id:candidateId,dry_run:false,requested_by:'dashboard'}); if(el){el.className=live.ok?'banner good':'banner warn'; el.innerHTML=`<strong>Promotion ${live.ok?'complete':'blocked'}.</strong><div>${esc(live.reason||live.action||'')}</div>${debugBlock('Live promotion details',live)}`;} return researchPage();}
async function researchPage(){renderNav('research'); const data=await api('/control/api/research/facility?page_size=100'); const rows=data.rows||[], counts=data.counts||{}; const admittedCandidates=rows.filter(r=>r.admission_decision==='admitted'&&!r.admitted_idea_id); const admitted=rows.filter(r=>r.admission_decision==='admitted').length, queued=rows.filter(r=>r.admitted_idea_id).length; $('status').className='pill info'; $('status').textContent=`Research Facility · ${rows.length} candidates`; $('app').className=''; $('app').innerHTML=`<section class="card"><h2>Research Facility</h2><div class="muted">Idea-generation smoke surface. It shows candidate/admission ledgers and provider budget. It does not queue, dispatch, or write papers automatically.</div><section class="grid">${card('Generated candidates',rows.length,'info','Rows in the Research Facility workbench')}${card('Admitted ideas',admitted,admitted?'good':'muted','Candidates admitted by the scoring gate')}${card('Queued ideas',queued,queued?'info':'muted','Admitted candidates promoted to idea/project queue rows')}${card('Provider budget','Manual check','info','Checks Synthetic quota through the proxy-safe provider path')}</section><div class="toolbar"><button onclick="checkProviderBudget()">Check provider budget</button><button onclick="generateResearchSmokeBatch()">Generate smoke batch</button></div><div id="providerBudgetStatus" class="banner info">Provider budget has not been checked in this browser session.</div><div id="researchGenerateStatus" class="banner info">Candidate generation has not been run in this browser session. Dry-run happens first; live write only records Research Facility ledgers.</div><h3>Provider-backed generation</h3><div class="muted">Provider generation checks quota first, spends only after confirmation, writes Research Facility ledgers only, and never queues or dispatches work.</div><div class="toolbar"><input id="researchProviderTopic" placeholder="optional topic focus"/><input id="researchProviderModel" placeholder="optional provider model"/><button onclick="generateProviderCandidateBatch()">Generate provider batch</button></div><div id="researchProviderGenerateStatus" class="banner info">Provider-backed generation has not been run in this browser session.</div><h3>Research Autopilot</h3><div class="muted">Runs one bounded cycle only: quota check, optional provider generation, ledger admission, promote up to one admitted candidate, optional one-item dispatch, and optional positive-gated paper draft/finalization. It never unpauses the broad queue.</div><div class="toolbar"><label class="pill"><input id="researchCycleDispatch" type="checkbox"/> allow one explicit dispatch</label><label class="pill"><input id="researchCycleWait" type="checkbox"/> wait for completion</label><label class="pill"><input id="researchCyclePapers" type="checkbox"/> draft/finalize if positive</label><button onclick="runResearchCycle(true)">Dry-run bounded cycle</button><button onclick="runResearchCycle(false)">Run one bounded cycle</button></div><div id="researchAutopilotStatus" class="banner info">Research Autopilot is disabled until you explicitly run a dry-run or one bounded cycle.</div><h3>Admitted candidates → Dry-run promote → Promote selected candidate</h3><div class="muted">This is the explicit boundary between generation and queue work. Select an admitted candidate, dry-run promotion, then confirm the live promotion. Promotion creates queued idea/project rows only; it does not dispatch work.</div>${tableRows(admittedCandidates.map(r=>({...r,candidate_action:r.candidate_id})),['candidate_action','candidate_id','title','total_score','provider_model','updated_at'],'No unpromoted admitted candidates') }<div class="toolbar"><input id="researchCandidateId" placeholder="admitted candidate id"/><button onclick="promoteResearchCandidate()">Dry-run promote selected</button></div><div id="researchPromoteStatus" class="banner info">No candidate promotion has been attempted in this browser session.</div><h3>Ledger authority</h3>${tableRows([{authority:data.authority||'Research Facility ledgers: sources, candidates, admissions, lineage'}],['authority'])}<h3>Candidate/admission counts</h3>${tableRows(Object.entries(counts).map(([status,count])=>({status,count})),['status','count'],'No candidate counts yet')}<h3>Recent candidate rows</h3>${tableRows(rows,['candidate_id','title','status','admission_decision','total_score','admitted_idea_id','updated_at'],'No Research Facility candidates yet')}${debugBlock('Research Facility JSON',data)}</section>`;}
async function reviewsPage(){renderNav('automation'); const search=new URLSearchParams(location.hash.split('?')[1]||''); const term=search.get('search')||'', reviewStatus=search.get('review_status')||'', paperStatus=search.get('paper_status')||'', page=search.get('page')||'1', sort=search.get('sort')||'-rank_score', pageSize=search.get('page_size')||'100'; const qs=new URLSearchParams({page,page_size:pageSize,search:term,review_status:reviewStatus,paper_status:paperStatus,sort,include_rank_reasons:'true'}); const data=await api('/control/api/publication-automation?'+qs.toString()); const rows=(data.rows||[]).map(r=>({...r,automation:'Open',automation_state:automationStatusLabel(r.review_status),progress:`${(r.checklist_progress||{}).passed||0}/${(r.checklist_progress||{}).total||0}`,reasons:(r.rank_reasons||[]).slice(0,2).join('; ')})); $('status').className='pill info'; $('status').textContent=`automation queue · ${data.page.total} filtered · ${data.counts.all||0} total`; $('app').className=''; $('app').innerHTML=`<section class="card"><h2>Publication Automation Queue</h2><div class="muted">Automated rewrite/finalization lane · canonical /control/api/publication-automation · page ${esc(data.page.page)} · returned ${esc(data.page.returned)} of ${esc(data.page.total)}</div><div class="row">${Object.entries(data.counts||{}).map(([k,v])=>`<span class="pill">${esc(k)} ${esc(v)}</span>`).join('')}</div><div id="batchStatus" class="banner info">GLM-5.1 batch idle. Click rewrite once; a 10-paper batch usually takes several minutes.</div><div class="toolbar"><button onclick="openNextReview()">Open next publication-ready</button><button id="rewriteBatchButton" onclick="rewriteBatchVisible()">Rewrite next 10 with GLM-5.1</button><input id="search" value="${esc(term)}" placeholder="search papers/projects"/><select id="review_status"><option value="">all automation states</option>${['queued','claimed','blocked','finalized','deferred','rejected'].map(v=>`<option value="${v}" ${reviewStatus===v?'selected':''}>${automationStatusLabel(v)}</option>`).join('')}</select><select id="paper_status"><option value="">all paper states</option>${['publication_draft','archived'].map(v=>`<option value="${v}" ${paperStatus===v?'selected':''}>${paperStatusLabel(v)}</option>`).join('')}</select><select id="reviewSort"><option value="-rank_score" ${sort==='-rank_score'?'selected':''}>Highest rank</option><option value="updated_at" ${sort==='updated_at'?'selected':''}>Recently updated</option><option value="review_status" ${sort==='review_status'?'selected':''}>Automation state</option><option value="paper_status" ${sort==='paper_status'?'selected':''}>Paper status</option></select><select id="reviewPageSize">${['25','50','100','200'].map(v=>`<option value="${v}" ${pageSize===v?'selected':''}>${v} per page</option>`).join('')}</select><button onclick="location.hash='automation?search='+encodeURIComponent($('search').value)+'&review_status='+encodeURIComponent($('review_status').value)+'&paper_status='+encodeURIComponent($('paper_status').value)+'&sort='+encodeURIComponent($('reviewSort').value)+'&page_size='+encodeURIComponent($('reviewPageSize').value)">Apply</button></div>${tableRows(rows,['automation','paper_title','rank_score','rank_bucket','automation_state','progress','paper_status','project_id','blocker','reasons','updated_at'])}${debugBlock('Automation queue JSON',data)}</section>`;}
async function openNextReview(){const data=await api('/control/api/publication-automation/next?paper_status=publication_draft'); location.hash='automation:'+encodeURIComponent((data.item||{}).paper_id||data.paper_id);}
function artifactButtons(id){return ['draft_markdown_path','draft_latex_path','evidence_bundle_path','claim_ledger_path','manifest_path'].map(k=>`<button onclick="previewArtifact('${esc(id)}','${k}')">Preview ${k.replace('_path','').replaceAll('_',' ')}</button>`).join(' ');}
async function previewArtifact(id,field){const paperId=decodeURIComponent(id); const data=await api(`/control/api/papers/${encodeURIComponent(paperId)}/artifact/${field}`); $('artifactPreview').innerHTML=`<h2>${esc(data.project_name||'Paper')} · ${esc(field)}</h2><div class="muted">Raw artifact preview is an explicit debug action.</div><details open><summary>Artifact content</summary><pre>${esc(data.content||'')}</pre></details>`; $('artifactPreview').scrollIntoView({behavior:'smooth'});}
function checklistRows(items){return `<table><thead><tr><th>Item</th><th>Required</th><th>Status</th><th>Note</th><th>Actions</th></tr></thead><tbody>${(items||[]).map(i=>`<tr><td>${esc(i.label||i.id)}</td><td>${i.required?'yes':'no'}</td><td>${esc(i.status)}</td><td>${esc(i.note||'')}</td><td><button onclick="setChecklist('${esc(i.id)}','pass')">Pass</button><button onclick="setChecklist('${esc(i.id)}','fail')">Fail</button><button onclick="setChecklist('${esc(i.id)}','accepted_risk')">Risk</button></td></tr>`).join('')}</tbody></table>`;}
async function reviewDetail(id){renderNav('automation'); const data=await api(`/control/api/publication-automation/${id}`); const item=data.item||{}, checklist=data.checklist||{}; window.currentReviewId=id; $('status').className='pill info'; $('status').textContent=`automation · ${item.project_name||id} · ${automationStatusLabel(item.review_status)} · score ${item.rank_score??''}`; $('app').className=''; $('app').innerHTML=`<section class="grid two"><div class="card"><h2>${esc(item.project_name||'Untitled Paper')}</h2><div class="muted mono">Automation item ${esc(id)}</div><div class="row"><span class="pill">automation ${esc(automationStatusLabel(item.review_status))}</span><span class="pill">paper ${esc(paperStatusLabel(item.paper_status))}</span><span class="pill">rank ${esc(item.rank_score)}</span><span class="pill">checklist ${(item.checklist_progress||{}).passed||0}/${(item.checklist_progress||{}).total||0}</span></div><div class="toolbar"><button onclick="rewriteReviewDraft()">Rewrite/finalize now</button><button onclick="prepareFinalizationPackage(false)">prepare finalization package</button><button onclick="setReviewStatus('rejected')">Reject</button></div>${debugBlock('Automation item JSON',item)}</div><div class="card"><h2>Artifacts and rank reasons</h2><div class="toolbar">${artifactButtons(id)}</div><h3>Artifact path fields</h3>${tableRows(['draft_markdown_path','draft_latex_path','evidence_bundle_path','claim_ledger_path','manifest_path'].map(k=>({field:k,present:Boolean(item[k])})),['field','present'])}${debugBlock('Rank reasons',item.rank_reasons||[])}${debugBlock('Missing signals',item.missing_signals||[])}</div></section><section id="artifactPreview" class="card"><h2>Artifact preview</h2><div class="muted">Use the artifact preview buttons above for deliberate raw content access.</div></section><section class="card"><h2>automation checklist</h2>${checklistRows(checklist.items||[])}</section>`;}
async function setChecklist(itemId,status){await postJson(`/control/api/publication-automation/${window.currentReviewId}/checklist/${itemId}`,{idempotency_key:'dashboard-check:'+window.currentReviewId+':'+itemId+':'+Date.now(),requested_by:AI_ACTOR,status,note:AI_NOTE}); return reviewDetail(window.currentReviewId);}
async function setReviewStatus(review_status){await postJson(`/control/api/publication-automation/${window.currentReviewId}/status`,{idempotency_key:'dashboard-status:'+window.currentReviewId+':'+review_status+':'+Date.now(),requested_by:AI_ACTOR,review_status}); return reviewDetail(window.currentReviewId);}
async function claimReview(){await postJson(`/control/api/publication-automation/${window.currentReviewId}/claim`,{idempotency_key:'dashboard-claim:'+window.currentReviewId+':'+Date.now(),requested_by:AI_ACTOR,reviewer:AI_ACTOR,note:AI_NOTE,clear_blocker:true}); return reviewDetail(window.currentReviewId);}
async function prepareFinalizationPackage(dry_run){const result=await postJson(`/control/api/publication-automation/${window.currentReviewId}/prepare-finalization-package`,{idempotency_key:'dashboard-package:'+window.currentReviewId+':'+Date.now(),requested_by:AI_ACTOR,target_label:'ai-publication',dry_run}); alert((dry_run?'Dry-run':'Prepared')+' package: '+(result.package_path||'manifest preview')); return reviewDetail(window.currentReviewId);}
async function rewriteReviewDraft(){const result=await postJson(`/control/api/publication-automation/${window.currentReviewId}/rewrite-draft`,{idempotency_key:'dashboard-rewrite:'+window.currentReviewId+':'+Date.now(),requested_by:AI_ACTOR,force:true}); alert('Rewrite complete: '+(result.writer||{}).provider+' / '+((result.writer||{}).model||'')); return reviewDetail(window.currentReviewId);}
async function rewriteBatchVisible(){const search=new URLSearchParams(location.hash.split('?')[1]||''); const button=$('rewriteBatchButton'), status=$('batchStatus'); if(button){button.disabled=true; button.textContent='GLM-5.1 batch running…';} if(status){status.className='banner warn'; status.textContent='GLM-5.1 rewrite running. Do not click again.';} const payload={idempotency_key:'dashboard-bulk-rewrite:'+Date.now(),requested_by:AI_ACTOR,paper_status:search.get('paper_status')||'publication_draft',review_status:search.get('review_status')||'',search:search.get('search')||'',limit:10,force:true,dry_run:false,skip_rewritten:true}; try{const result=await postJson('/control/api/publication-automation/rewrite-batch',payload); if(status){status.className=result.failed?'banner warn':'banner good'; status.innerHTML=`<strong>Batch rewrite complete.</strong><div>${esc(result.rewritten)} rewritten · ${esc(result.failed)} failed · ${esc(result.matched)} matched.</div>${debugBlock('Batch rows',result.rows||[])}`;} return reviewsPage();}catch(e){if(status){status.className='banner critical'; status.textContent='Batch rewrite failed: '+e.message;} throw e;}finally{if(button){button.disabled=false; button.textContent='Rewrite next 10 with GLM-5.1';}}}
async function detail(kind,id){renderNav(kind==='project'?'queue:active':kind==='paper'?'papers':'runs'); const path=kind==='project'?`/control/api/v1/projects/${id}`:kind==='run'?`/control/api/v1/runs/${id}`:`/control/api/v1/papers/${id}`; const data=await api(path); $('status').className='pill info'; $('status').textContent=`${kind} detail`; const primary=data[kind]||data.project||data.paper||data.run||{}; $('app').className=''; $('app').innerHTML=`<section class="grid two"><div class="card"><h2>${esc(kind)} ${esc(id)}</h2>${tableRows([primary],Object.keys(primary).filter(k=>!['links'].includes(k)).slice(0,10))}</div><div class="card"><h2>Related records</h2>${data.runs?`<h3>Runs</h3>${tableRows(data.runs,['state','run_id','current_activity','updated_at'])}`:''}${data.papers?`<h3>Papers</h3>${tableRows(data.papers,['operator_stage_label','paper_id','run_id','artifact_paths_present','updated_at'])}`:''}${data.queue_item?`<h3>Queue</h3>${tableRows([data.queue_item],['operator_stage_label','project_decision_summary','project_id','current_run_id','operator_next_step','operator_explanation','updated_at'])}`:''}</div></section><section class="card"><h2>Related activity</h2>${activityCards(data.events||[])}</section>`;}
async function route(){try{beginRoute(); if(token())$('token').value=token(); renderNav((location.hash||'#overview').slice(1).split('?')[0]); if(!token()){$('status').className='pill warn';$('status').textContent='Token required';$('app').className='banner warn';$('app').innerHTML='<strong>Enter the control-plane bearer token to load bounded operator read models.</strong><div class="muted">The dashboard does not call authenticated APIs until a token is saved locally in this browser.</div>';return;} const h=(location.hash||'#overview').slice(1); const routeKey=h.split('?')[0]||'overview'; if(routeKey!=='overview')delete $('app').dataset.page; if(h==='projects'||h.startsWith('projects?')) return projectListPage('projects','all'); if(h.startsWith('queue:')) return queuePage((h.split(':')[1]||'active').split('?')[0]); if(h==='runs'||h.startsWith('runs?')) return runsPage(); if(h==='papers'||h.startsWith('papers?')) return papersPage(); if(h==='corpus') return corpusPage(); if(h==='events'||h.startsWith('events?')) return eventsPage(); if(h==='automation'||h.startsWith('automation?')||h==='reviews'||h.startsWith('reviews?')) return reviewsPage(); if(h==='intake') return intakePage(); if(h==='research') return researchPage(); if(h==='observability') return observabilityPage(); if(h.startsWith('project:')) return detail('project',encodeURIComponent(decodeURIComponent(h.split(':')[1]||''))); if(h.startsWith('run:')) return detail('run',encodeURIComponent(decodeURIComponent(h.split(':')[1]||''))); if(h.startsWith('paper:')) return detail('paper',encodeURIComponent(decodeURIComponent(h.split(':')[1]||''))); if(h.startsWith('automation:')) return reviewDetail(encodeURIComponent(decodeURIComponent(h.split(':')[1]||''))); if(h.startsWith('review:')) return reviewDetail(encodeURIComponent(decodeURIComponent(h.split(':')[1]||''))); return overviewPage();}catch(e){if(e.name==='AbortError')return; $('status').className='pill bad';$('status').textContent='Error';$('app').className='banner critical';$('app').textContent=e.message;}}
function autoRefreshCurrentPage(){const h=(location.hash||'#overview').slice(1).split('?')[0]; if(h==='overview'||h==='observability') route();}
window.addEventListener('hashchange',route); route(); setInterval(autoRefreshCurrentPage,15000);
</script>
</body>
</html>
"""




def _local_high_signal_evidence_present(project_dir: Path) -> bool:
    return (project_dir / "run_notes.md").is_file() and any((project_dir / rel).is_file() for rel in (".enoch/project_decision.json", ".omx/project_decision.json"))


def _local_paper_evidence_present(project_dir: Path) -> bool:
    if _local_high_signal_evidence_present(project_dir):
        return True
    papers_dir = project_dir / "papers"
    if papers_dir.exists():
        for name in ("evidence_bundle.json", "claim_ledger.json"):
            if any(papers_dir.rglob(name)):
                return True
    results_dir = project_dir / "results"
    return results_dir.exists() and any(results_dir.rglob("*.json"))


def _sync_worker_http_evidence(config: GateConfig, *, project_id: str, artifact_root: Path, source_run_id: str = "") -> dict[str, Any]:
    if not config.worker_wake_gate_bearer_token:
        return {"ok": False, "reason": "worker_token_missing"}
    base_run = source_run_id.removesuffix("-publication") if source_run_id else ""
    paths = [
        "run_notes.md",
        ".enoch/project_decision.json",
        ".enoch/metrics.json",
        ".omx/project_decision.json",
        ".omx/metrics.json",
        "results/hot_cold_sim_results.json",
        "results/smoke.json",
        "results/llamacpp_probe/hotcold_probe.json",
        "results/llamacpp_hotcold_residency/qwen32b_hotcold_residency.json",
        "results/llamacpp_hotcold_residency/qwen32b_hotcold_fixed_budget_pager_sweep.json",
        "results/llamacpp_hotcold_residency/qwen32b_hotcold_fixed_budget_pager_sweep_summary.csv",
        "results/llamacpp_hotcold_residency/qwen32b_hotcold_reuse_pager_sweep.json",
        "results/llamacpp_hotcold_residency/qwen32b_hotcold_reuse_pager_sweep_summary.csv",
    ]
    if base_run:
        paths.extend([
            f"papers/{base_run}/README.md",
            f"papers/{base_run}/paper.md",
            f"papers/{base_run}/paper_manifest.json",
            f"papers/{base_run}/evidence_bundle.json",
            f"papers/{base_run}/claim_ledger.json",
        ])
    written = []
    skipped = []
    # Read each evidence path independently. The GB10 worker read endpoint is
    # intentionally strict and returns a non-2xx response when any requested
    # path is missing. Most projects only have a subset of the optional
    # artifacts below, so a single bulk read can fail an otherwise valid rewrite
    # before useful evidence is copied. Treat missing optional paths as skipped
    # and let the later local evidence gate decide whether enough material was
    # synced to ground a paper.
    for path in paths:
        result = post_worker_json(
            config.worker_wake_gate_url,
            f"/project-paper/{project_id}/read",
            config.worker_wake_gate_bearer_token,
            {"paths": [path], "max_bytes_per_file": 2_000_000},
        )
        if not result.ok or not result.body:
            skipped.append({"path": path, "status": result.status, "error": result.error[:300]})
            continue
        for file in result.body.get("files", []):
            rel = str(file.get("path") or "")
            content = str(file.get("content") or "")
            target = (artifact_root / rel).resolve()
            try:
                target.relative_to(artifact_root)
            except ValueError:
                skipped.append({"path": rel, "status": "unsafe_path", "error": "worker returned path outside artifact root"})
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content, encoding="utf-8")
            written.append(rel)
    if not written:
        return {"ok": False, "reason": "worker_read_failed", "files": 0, "paths": [], "skipped": skipped[:30]}
    return {"ok": True, "reason": "worker_http_synced", "files": len(written), "paths": written[:30], "skipped": skipped[:30]}


def _sync_remote_project_evidence(config: GateConfig, *, project_id: str, artifact_root: Path, source_project_dir: str = "", source_run_id: str = "") -> dict[str, Any]:
    if not config.paper_evidence_sync_enabled:
        return {"enabled": False, "synced": False, "reason": "disabled"}
    if _local_high_signal_evidence_present(artifact_root):
        return {"enabled": True, "synced": False, "reason": "local_high_signal_evidence_present"}
    http_sync = _sync_worker_http_evidence(config, project_id=project_id, artifact_root=artifact_root, source_run_id=source_run_id)
    if _local_high_signal_evidence_present(artifact_root):
        return {"enabled": True, "synced": True, "reason": http_sync.get("reason", "worker_http_synced"), "method": "worker_http", "http_sync": http_sync}
    if _local_paper_evidence_present(artifact_root):
        return {"enabled": True, "synced": True, "reason": http_sync.get("reason", "worker_http_synced"), "method": "worker_http", "http_sync": http_sync}
    remote_dir = source_project_dir.strip() or f"{config.paper_evidence_sync_remote_root.rstrip('/')}/{project_id}"
    # The VM talks to the GB10 over SSH and streams a bounded evidence tarball.
    # This intentionally excludes external source trees and large trace/log files,
    # while preserving the artifacts the paper writer needs for claim grounding.
    include_paths = [
        "run_notes.md",
        ".enoch/project_decision.json",
        ".enoch/metrics.json",
        ".omx/project_decision.json",
        ".omx/metrics.json",
        "papers",
        "results/hot_cold_sim_results.json",
        "results/smoke.json",
        "results/llamacpp_probe/hotcold_probe.json",
        "results/llamacpp_hotcold_residency/qwen32b_hotcold_residency.json",
        "results/llamacpp_hotcold_residency/qwen32b_hotcold_fixed_budget_pager_sweep.json",
        "results/llamacpp_hotcold_residency/qwen32b_hotcold_fixed_budget_pager_sweep_summary.csv",
        "results/llamacpp_hotcold_residency/qwen32b_hotcold_reuse_pager_sweep.json",
        "results/llamacpp_hotcold_residency/qwen32b_hotcold_reuse_pager_sweep_summary.csv",
    ]
    remote_cmd = "cd " + shlex.quote(remote_dir) + " && tar -czf - --ignore-failed-read " + " ".join(shlex.quote(path) for path in include_paths)
    ssh_cmd = ["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=8", "-o", "StrictHostKeyChecking=accept-new", config.paper_evidence_sync_ssh_host, remote_cmd]
    tar_cmd = ["tar", "-xzf", "-", "-C", str(artifact_root)]
    artifact_root.mkdir(parents=True, exist_ok=True)
    try:
        ssh_proc = subprocess.Popen(ssh_cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        tar_proc = subprocess.Popen(tar_cmd, stdin=ssh_proc.stdout, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        if ssh_proc.stdout is not None:
            ssh_proc.stdout.close()
        tar_out, tar_err = tar_proc.communicate(timeout=config.paper_evidence_sync_timeout_sec)
        ssh_err = ssh_proc.stderr.read() if ssh_proc.stderr is not None else b""
        ssh_code = ssh_proc.wait(timeout=5)
    except subprocess.TimeoutExpired as exc:
        for proc_name in ("ssh_proc", "tar_proc"):
            proc = locals().get(proc_name)
            if proc is not None:
                proc.kill()
        return {"enabled": True, "synced": False, "reason": "timeout", "remote_dir": remote_dir, "error": str(exc), "http_sync": http_sync}
    except OSError as exc:
        return {"enabled": True, "synced": False, "reason": "spawn_failed", "remote_dir": remote_dir, "error": str(exc), "http_sync": http_sync}
    if ssh_code != 0 or tar_proc.returncode != 0:
        return {
            "enabled": True,
            "synced": False,
            "reason": "command_failed",
            "remote_dir": remote_dir,
            "ssh_returncode": ssh_code,
            "tar_returncode": tar_proc.returncode,
            "stderr": ((ssh_err or b"") + (tar_err or b"")).decode("utf-8", errors="replace")[-2000:],
            "stdout": (tar_out or b"").decode("utf-8", errors="replace")[-1000:],
            "http_sync": http_sync,
        }
    return {"enabled": True, "synced": True, "reason": "synced", "remote_dir": remote_dir, "local_evidence_present": _local_paper_evidence_present(artifact_root)}


def _safe_slug(value: str, fallback: str) -> str:
    slug = re.sub(r"[^a-zA-Z0-9._-]+", "-", value.strip()).strip("-._").lower()
    return (slug or fallback)[:96]


def _live_run_id(project_id: str) -> str:
    stamp = utc_now().replace("-", "").replace(":", "").replace(".", "").replace("+00:00", "Z")
    return f"{project_id}-{stamp}"


def _parse_ts(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def _fresh_until(observed_at: str | None, ttl_seconds: int | None) -> str | None:
    observed = _parse_ts(observed_at)
    if observed is None or ttl_seconds is None:
        return None
    return (observed + timedelta(seconds=ttl_seconds)).isoformat()


def _is_stale(observed_at: str | None, ttl_seconds: int | None) -> bool:
    observed = _parse_ts(observed_at)
    if observed is None or ttl_seconds is None:
        return True
    return datetime.now(timezone.utc) > observed + timedelta(seconds=ttl_seconds)


def _preflight_check(preflight: DashboardObservationRecord | None, name: str) -> dict | None:
    checks = ((preflight.payload if preflight else {}).get("checks") or [])
    for check in checks:
        if isinstance(check, dict) and check.get("name") == name:
            return check
    return None


def _truncate_text(value: Any, limit: int = 500) -> Any:
    if not isinstance(value, str) or len(value) <= limit:
        return value
    return f"{value[:limit]}…"


def _compact_list(values: Any, *, limit: int = 5) -> dict[str, Any]:
    if not isinstance(values, list):
        return {"count": 0, "items": []}
    return {"count": len(values), "items": values[:limit], "truncated": len(values) > limit}


def _compact_project_decision(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        return {}
    keys = (
        "project_decision",
        "hypothesis_status",
        "evidence_strength",
        "recommended_next_action",
        "stop_reason",
        "followup_recommended",
        "followup_count",
        "parent_project_id",
    )
    compact = {key: _truncate_text(value.get(key), 300) for key in keys if key in value}
    for key in ("key_findings", "next_steps", "followup_ideas"):
        if isinstance(value.get(key), list):
            compact[key] = _compact_list([_truncate_text(item, 240) for item in value[key]], limit=3)
    return compact


def _compact_worker_run_item(run_item: Any) -> dict[str, Any]:
    """Keep worker runtime evidence useful without caching multi-100KB detail blobs.

    The GB10 dashboard can include long tails such as quiet_samples,
    run_notes_tail, project_decision narratives, and file listings.  Status and
    detail views need the identity/lifecycle/safety facts, not the full worker
    transcript.  Full worker evidence remains available from the worker host.
    """

    if not isinstance(run_item, dict):
        return {}
    scalar_keys = (
        "run_id",
        "project_id",
        "session_id",
        "gate_state",
        "is_live",
        "is_historical",
        "lifecycle_state",
        "needs_attention",
        "operator_status",
        "operator_status_detail",
        "current_activity",
        "created_at",
        "updated_at",
        "last_event_at",
        "callback_delivered",
        "active_process_count",
        "project_dir",
    )
    compact = {key: _truncate_text(run_item.get(key), 300) for key in scalar_keys if key in run_item}
    if "project_decision" in run_item:
        compact["project_decision"] = _compact_project_decision(run_item.get("project_decision"))
    if "decision_error" in run_item:
        compact["decision_error"] = _truncate_text(run_item.get("decision_error"), 500)
    for key in ("result_files", "recent_files", "active_processes"):
        if key in run_item:
            compact[key] = _compact_list(run_item.get(key), limit=5)
    for key in ("quiet_samples", "run_notes_tail", "stdout_tail", "stderr_tail"):
        if key in run_item:
            value = run_item.get(key)
            compact[f"{key}_omitted"] = True
            compact[f"{key}_count"] = len(value) if isinstance(value, list) else (1 if value else 0)
    return compact


def _compact_worker_dashboard_body(body: Any) -> dict[str, Any]:
    if not isinstance(body, dict):
        return {}
    compact: dict[str, Any] = {}
    for key in ("ok", "timestamp", "totals", "telemetry"):
        if key in body:
            compact[key] = body.get(key)
    queue = body.get("queue")
    if isinstance(queue, dict):
        compact["queue"] = {
            key: queue.get(key)
            for key in (
                "total",
                "source",
                "updated_at",
                "active_count",
                "queued_count",
                "blocked_count",
                "branch_count",
                "negative_count",
                "positive_count",
                "completed_count",
                "draft_candidate_count",
                "polish_candidate_count",
                "status_counts",
                "run_state_counts",
            )
            if key in queue
        }
        if isinstance(queue.get("rows"), list):
            compact["queue"]["rows_omitted"] = True
            compact["queue"]["rows_count"] = len(queue["rows"])
    runs = body.get("runs")
    if isinstance(runs, list):
        compact["runs"] = [_compact_worker_run_item(run_item) for run_item in runs[:10]]
        compact["runs_count"] = len(runs)
        compact["runs_truncated"] = len(runs) > 10
    return compact


def _compact_worker_dashboard_check_payload(payload: dict[str, Any]) -> dict[str, Any]:
    compact = dict(payload)
    data = dict(compact.get("data") or {})
    if "body" in data:
        data["body"] = _compact_worker_dashboard_body(data.get("body") or {})
        data["body_compacted"] = True
    compact["data"] = data
    return compact


def _compact_worker_preflight_payload(payload: dict[str, Any]) -> dict[str, Any]:
    compact = dict(payload)
    checks: list[Any] = []
    for check in payload.get("checks") or []:
        if isinstance(check, dict) and check.get("name") == "wake_gate_dashboard_api":
            checks.append(_compact_worker_dashboard_check_payload(check))
        else:
            checks.append(check)
    compact["checks"] = checks
    return compact


def _project_prompt(candidate: dict) -> str:
    title = str(candidate.get("project_name") or candidate.get("project_id") or "Untitled Project")
    return f"""# Enoch Research Action: {title}

You are running under the Enoch LangGraph hard-cutover controller.

Project ID: {candidate.get('project_id') or ''}
Source/provenance URL: {candidate.get('notion_page_url') or ''}
Origin status: {candidate.get('origin_idea_status') or ''}
Controller source kind: {candidate.get('idea_source_kind') or ''}
Controller follow-up depth: {candidate.get('source_followup_depth') if candidate.get('source_followup_depth') is not None else candidate.get('followup_depth', 0)}

## Mission
Turn this idea into a concrete, evidence-backed research result. Work autonomously inside the project directory. Prefer install/build/run/verify over blocking on missing ordinary dependencies. If the idea is not viable, produce a clear negative result with evidence.

## Operating constraints
- Do not require human input for installable, downloadable, compilable, or locally runnable dependencies.
- For GB10 work, start with a small smoke test, then calibrate throughput/utilization before any long run.
- Swap is intentionally disabled on GB10; use MemAvailable/UMA telemetry and earlyoom posture, not swap availability, for memory judgment.
- Leave durable artifacts: run_notes.md, commands/log paths, metrics, and a final .enoch/project_decision.json.
- If final scientific closure truly needs human/private/external evidence, state that precisely and stop with a needs_review/blocker decision.
- Match the evidence to the claim. If this idea asks for a large/overnight/full-scale validation, a short proxy run must not be presented as full validation.

## Required final decision artifact
Write `.enoch/project_decision.json` with these exact enum values. Do not invent
near-synonyms such as `partial_viable`, `promising_synthetic_positive`, or
`negative_result`.

Required JSON shape:
```json
{{
  "project_decision": "finalize_positive | finalize_negative | needs_review | blocked | continue | branch_new_project",
  "hypothesis_status": "supported | unsupported | mixed | inconclusive",
  "confidence": "low | medium | high",
  "evidence_strength": "weak | moderate | strong",
  "novelty_progress": true,
  "results_changed": true,
  "recommended_next_action": "one concrete next action or stop rationale",
  "stop_reason": "",
  "followup_recommended": false,
  "followup_type": "",
  "followup_title": "",
  "followup_hypothesis": "",
  "followup_required_evidence": [],
  "followup_success_threshold": "",
  "followup_stop_condition": "",
  "followup_depth": 0
}}
```

Decision rules:
- Use `finalize_positive` only when the evidence supports writing a paper now.
- Use `finalize_negative` when the result is negative, non-viable, or not worth a paper.
- Use `needs_review` only for a real ambiguity or required external/private evidence.
- Use `blocked` only for an execution blocker that prevented a valid test.
- Use `continue` only when more autonomous work should run before paper/no-paper closure.
- Use `branch_new_project` only when this run found a distinct follow-up idea.

Evidence-depth rules:
- Do not add new decision fields or enum values. Use the existing fields precisely.
- A short smoke/proxy/synthetic test may close `finalize_negative` only when it is an explicit early falsification of the hypothesis or success threshold.
- For early falsification, `run_notes.md` must say what was directly tested, what was only proxied, and what direct/full evidence would be required to overturn the result.
- For early falsification, keep `evidence_strength` at `weak` or `moderate` unless direct/full-scale evidence was actually produced.
- For early falsification, make `recommended_next_action` and `stop_reason` state that the result is a proxy/early falsification rather than a full validation.
- Do not use `finalize_positive` for a proxy-only result unless the original claim was explicitly scoped to that proxy.

Follow-up rules:
- Follow-up fields are optional adjacent-investigation metadata; they never make this run paper-positive.
- Set `followup_recommended: true` only when this run is no-paper but produced specific evidence for a bounded adjacent test.
- Leave `followup_recommended` false for hard negatives, weak speculation, missing evidence, or ordinary incremental tweaks.
- When recommending follow-up, set `followup_type` to `deepen`, `branch`, or `retry`, and provide a concrete title, hypothesis, required evidence, success threshold, and stop condition.
- If the controller prompt/source metadata says this is a follow-up and provides `Controller follow-up depth`, copy that exact integer into `followup_depth`; do not reset it to 1.
- If the current/controller follow-up depth is 2 or greater, set `followup_recommended: false` unless explicit controller instructions say otherwise; explain the cap in `recommended_next_action`.
- Do not chain indefinitely; preserve controller lineage depth, and assume the controller will cap follow-ups at depth 2.
"""

def _paper_record_from_candidate(candidate: dict, *, force: bool = False) -> PaperRecord:
    project_id = str(candidate.get("project_id") or "").strip()
    run_id = str(candidate.get("current_run_id") or candidate.get("run_id") or "").strip()
    paper_type = "arxiv_draft"
    paper_id = f"{project_id}:{run_id}:{paper_type}"
    paper_dir = f"papers/{run_id}"
    now = utc_now()
    return PaperRecord(
        paper_id=paper_id,
        project_id=project_id,
        run_id=run_id,
        paper_type=paper_type,
        draft_markdown_path=f"{paper_dir}/paper.md",
        draft_latex_path=f"{paper_dir}/paper.tex",
        evidence_bundle_path=f"{paper_dir}/evidence_bundle.json",
        claim_ledger_path=f"{paper_dir}/claim_ledger.json",
        manifest_path=f"{paper_dir}/paper_manifest.json",
        generated_at=now,
        updated_at=now,
    )


def _write_deterministic_paper(config: GateConfig, candidate: dict, paper: PaperRecord, *, force: bool) -> None:
    project_dir_text = str(candidate.get("project_dir") or "").strip()
    if not project_dir_text:
        raise HTTPException(status_code=400, detail="candidate lacks project_dir")
    root = config.expanded_project_root.resolve()
    project_dir = Path(project_dir_text).expanduser()
    if not project_dir.is_absolute():
        project_dir = root / project_dir
    project_dir = project_dir.resolve()
    try:
        project_dir.relative_to(root)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="project_dir escapes configured project root") from exc
    title = str(candidate.get("project_name") or paper.project_id).strip()
    files = {
        paper.draft_markdown_path: f"# {title}: Evidence-Grounded Technical Report\n\nStatus: first draft.\n\nGenerated by LangGraph hard-cutover MVP at {paper.generated_at}.\n\n## Automation Status\n\nThis deterministic MVP draft proves the new control plane can create paper artifacts. It is intended for automated rewrite/finalization, not operator approval.\n",
        paper.draft_latex_path: "\\documentclass{article}\n\\title{" + title.replace("_", "\\_") + "}\n\\author{Enoch LangGraph MVP}\n\\begin{document}\n\\maketitle\nMVP draft for automated rewrite and finalization.\n\\end{document}\n",
        paper.evidence_bundle_path: '{\n  "source": "langgraph_control_plane_mvp",\n  "project_id": "' + paper.project_id + '",\n  "run_id": "' + paper.run_id + '"\n}\n',
        paper.claim_ledger_path: '{\n  "claims": [],\n  "limitations": ["MVP deterministic draft; automated rewrite/finalization required."]\n}\n',
        paper.manifest_path: '{\n  "paper_id": "' + paper.paper_id + '",\n  "generated_at": "' + paper.generated_at + '"\n}\n',
    }
    for rel_path, content in files.items():
        target = (project_dir / rel_path).resolve()
        try:
            target.relative_to(project_dir)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=f"paper path escapes project dir: {rel_path}") from exc
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.exists() and not force:
            continue
        target.write_text(content, encoding="utf-8")


def create_control_plane_router(config: GateConfig, require_bearer: RequireBearer) -> APIRouter:
    router = APIRouter(prefix="/control", tags=["control-plane"])
    if config.control_plane_store_backend == "supabase_readonly":
        store = SupabaseReadOnlyControlPlaneStore(resolve_supabase_database_url(config.supabase_database_url))
    elif config.control_plane_store_backend == "supabase":
        store = SupabaseControlPlaneStore(resolve_supabase_database_url(config.supabase_database_url))
    else:
        store = ControlPlaneStore(config.expanded_state_dir / "control_plane.sqlite3")

    def authorize(authorization: str | None) -> None:
        require_bearer(authorization)


    def _live_dispatch(candidate: dict, requested_by: str, force_preflight: bool, *, allow_paused: bool = False) -> tuple[dict, int | None, dict]:
        if not config.live_dispatch_enabled:
            raise HTTPException(status_code=501, detail="live dispatch is disabled by config.live_dispatch_enabled")
        flags = store.flags()
        if flags.maintenance_mode:
            raise HTTPException(status_code=409, detail="control plane must be out of maintenance mode before live dispatch")
        if flags.queue_paused and not allow_paused:
            raise HTTPException(status_code=409, detail="control plane must be resumed before live dispatch")
        if not config.worker_wake_gate_bearer_token:
            raise HTTPException(status_code=500, detail="worker wake-gate bearer token is not configured")
        project_id = str(candidate.get("project_id") or "").strip()
        if not project_id:
            raise HTTPException(status_code=400, detail="candidate lacks project_id")
        project_dir = _safe_slug(str(candidate.get("project_dir") or project_id), project_id)
        run_id = _live_run_id(project_id)
        claim = store.claim_dispatch_candidate(project_id=project_id, run_id=run_id, requested_by=requested_by)
        if not claim:
            raise HTTPException(status_code=409, detail="dispatch candidate was already claimed or is no longer queued")
        candidate = claim
        # Live dispatch is never allowed to bypass fresh worker evidence.  The
        # request field remains for API compatibility, but the control plane
        # always performs the non-mutating worker preflight before prepare/dispatch.
        preflight = run_worker_preflight(
            WorkerPreflightRequest(
                wake_gate_url=config.worker_wake_gate_url,
                bearer_token=config.worker_wake_gate_bearer_token,
                require_paused=False,
                strict=False,
            ),
            store.flags(),
        )
        _record_preflight_observations(preflight)
        if not preflight.ok:
            store.release_dispatch_claim(project_id=project_id, run_id=run_id, reason="worker preflight failed")
            raise HTTPException(status_code=409, detail={"message": "worker preflight failed", "preflight": preflight.model_dump(mode="json"), "force_preflight_ignored": not force_preflight})
        prompt_file = f"{project_dir}/prompts/initial.md"
        resume_prompt_file = f"{project_dir}/prompts/resume.md"
        prepare_payload = {
            "run_id": run_id,
            "project_id": project_id,
            "project_name": str(candidate.get("project_name") or project_id),
            "notion_page_url": str(candidate.get("notion_page_url") or ""),
            "project_dir": project_dir,
            "prompt_file": prompt_file,
            "prompt_text": _project_prompt(candidate),
            "resume_prompt_file": resume_prompt_file,
            "resume_prompt_text": _project_prompt(candidate) + "\n\nResume from the existing project artifacts and continue to a verified decision.\n",
            "metadata": {"workload_class": "inference_eval", "source": "langgraph_control_plane", "requested_by": requested_by},
            "overwrite": True,
        }
        prepare = post_worker_json(config.worker_wake_gate_url, "/prepare-project", config.worker_wake_gate_bearer_token, prepare_payload)
        if not prepare.ok:
            store.release_dispatch_claim(project_id=project_id, run_id=run_id, reason="worker prepare-project failed")
            raise HTTPException(status_code=502, detail={"message": "worker prepare-project failed", "status": prepare.status, "error": prepare.error, "body": prepare.body})
        dispatch_payload = {
            "run_id": run_id,
            "project_id": project_id,
            "project_dir": project_dir,
            "prompt_file": prompt_file,
            "mode": "exec",
            "model": str(candidate.get("model") or "gpt-5.5"),
            "reasoning_effort": "medium",
            "sandbox": str(candidate.get("sandbox") or "danger-full-access"),
        }
        dispatch = post_worker_json(config.worker_wake_gate_url, "/dispatch", config.worker_wake_gate_bearer_token, dispatch_payload)
        if not dispatch.ok:
            store.release_dispatch_claim(project_id=project_id, run_id=run_id, reason="worker dispatch failed")
            raise HTTPException(status_code=502, detail={"message": "worker dispatch failed", "status": dispatch.status, "error": dispatch.error, "body": dispatch.body})
        body = dispatch.body or {}
        session_id = str(((body.get("dispatch") or {}) if isinstance(body.get("dispatch"), dict) else {}).get("session_id") or "")
        # Persist the exact worker directory slug used for prepare/dispatch.
        # Research-facility IDs can exceed the safe worker path length and are
        # intentionally shortened by _safe_slug.  If the DB keeps the full
        # project_id as project_dir, later callback and evidence-sync paths look
        # in a non-existent directory and mark a completed run as missing its
        # decision artifact.
        store.update_project_dir(project_id, project_dir)
        event_id, updated_candidate = store.mark_dispatch_started(project_id=project_id, run_id=run_id, session_id=session_id, dispatch_payload=body, requested_by=requested_by)
        return {
            "run_id": run_id,
            "project_id": project_id,
            "project_dir": project_dir,
            "prompt_file": prompt_file,
            "prepare": prepare.body or {},
            "dispatch": body,
            "preflight": preflight.model_dump(mode="json") if preflight else None,
        }, event_id, updated_candidate

    def state_response() -> ControlStateResponse:
        # Legacy /control/state must stay bounded and operator-safe. Paper-writing
        # eligibility is exposed by /control/api/v1/overview.paper_pipeline, not
        # mixed into the dispatch candidate slot here. This keeps the state
        # endpoint focused on pause flags, queue counts, active work, and the
        # next dispatchable queue row.
        counts = store.queue_counts_sql() if hasattr(store, "queue_counts_sql") else store.status_counts()
        paper_counts = store.paper_counts_sql() if hasattr(store, "paper_counts_sql") else {}
        queue_total = counts.get("all", 0)
        return ControlStateResponse(
            flags=store.flags(),
            counts={**counts, "papers": int(paper_counts.get("all", 0)), "queue_total": int(queue_total)},
            active_items=store.active_items(),
            next_candidate=store.next_dispatch_candidate(),
            recent_events=store.recent_events(10),
        )

    def _config_status() -> DashboardConfigStatus:
        return DashboardConfigStatus(
            live_dispatch_enabled=config.live_dispatch_enabled,
            worker_wake_gate_url=config.worker_wake_gate_url,
            worker_token_configured=bool(config.worker_wake_gate_bearer_token),
            dispatch_timeout_sec=config.dispatch_timeout_sec,
            project_root=str(config.expanded_project_root),
            state_dir=str(config.expanded_state_dir),
            pushover_alerts_enabled=config.pushover_alerts_enabled,
            pushover_configured=bool(config.pushover_app_token and config.pushover_user_key),
            queue_alert_cooldown_sec=config.queue_alert_cooldown_sec,
            queue_alert_hang_after_sec=config.queue_alert_hang_after_sec,
        )

    def _systemctl_show(unit: str, properties: list[str]) -> dict[str, Any]:
        cmd = ["systemctl", "show", unit, "--no-pager"]
        for prop in properties:
            cmd.extend(["-p", prop])
        try:
            result = subprocess.run(cmd, check=False, capture_output=True, text=True, timeout=8)
        except (OSError, subprocess.TimeoutExpired) as exc:
            return {"Unit": unit, "ok": False, "error": str(exc)}
        parsed: dict[str, Any] = {"Unit": unit, "ok": result.returncode == 0}
        for line in result.stdout.splitlines():
            if "=" in line:
                key, value = line.split("=", 1)
                parsed[key] = value
        if result.returncode != 0:
            parsed["error"] = (result.stderr or result.stdout)[-500:]
        return parsed

    def _automation_timer_snapshot() -> tuple[dict[str, dict[str, Any]], dict[str, dict[str, Any]]]:
        timers = {
            unit: _systemctl_show(unit, ["ActiveState", "LastTriggerUSec", "NextElapseUSecRealtime"])
            for unit in ("enoch-research-autopilot.timer", "enoch-corpus-import-autopilot.timer")
        }
        services = {
            unit: _systemctl_show(unit, ["ActiveState", "SubState", "Result", "ExecMainStatus", "ActiveEnterTimestamp", "InactiveEnterTimestamp"])
            for unit in ("enoch-research-autopilot.service", "enoch-corpus-import-autopilot.service")
        }
        return timers, services

    def _provider_budget_for_readiness() -> dict[str, Any]:
        from scripts import research_provider_budget

        base_url = os.environ.get("ENOCH_RESEARCH_PROVIDER_BASE_URL", "https://synthetic.int.exe.xyz").rstrip("/")
        estimated_requests = int(os.environ.get("ENOCH_RESEARCH_AUTOPILOT_ESTIMATED_REQUESTS") or 1)
        reserve_requests = max(1, int(os.environ.get("ENOCH_RESEARCH_AUTOPILOT_RESERVE_REQUESTS") or 2))
        min_remaining_credits = float(os.environ.get("ENOCH_RESEARCH_AUTOPILOT_MIN_CREDITS") or 5.0)
        min_rolling_remaining = int(os.environ.get("ENOCH_RESEARCH_AUTOPILOT_MIN_ROLLING") or 10)
        try:
            payload = research_provider_budget.fetch_json(
                f"{base_url}/v2/quotas",
                api_key="",
                timeout=max(1, min(int(os.environ.get("ENOCH_RESEARCH_AUTOPILOT_BUDGET_TIMEOUT") or 20), 60)),
            )
            result = research_provider_budget.synthetic_budget_status(
                payload,
                min_remaining_credits=min_remaining_credits,
                min_rolling_remaining=min_rolling_remaining,
                estimated_requests=estimated_requests,
                reserve_requests=reserve_requests,
            )
        except Exception as exc:  # noqa: BLE001 - readiness must fail closed if the provider cannot be checked
            result = {
                "ok": False,
                "provider": "synthetic",
                "checked_at": utc_now(),
                "estimated_requests": estimated_requests,
                "reserve_requests": reserve_requests,
                "failures": [f"provider budget check failed: {exc}"],
            }
        safe_keys = {
            "ok", "provider", "checked_at", "estimated_requests", "reserve_requests",
            "remaining_credits", "min_remaining_credits", "rolling_remaining", "rolling_max",
            "rolling_limited", "rolling_next_tick_at", "weekly_next_regen_at",
            "weekly_next_regen_credits", "subscription_remaining", "subscription_renews_at", "failures",
        }
        return {key: result.get(key) for key in safe_keys if key in result}

    def _automation_readiness_payload() -> dict[str, Any]:
        state = state_response().model_dump(mode="json")
        overview = read_models.overview(store, active_limit=5, event_limit=5)
        timers, services = _automation_timer_snapshot()
        readiness = evaluate_longhaul_readiness(
            state=state,
            overview=overview,
            timers=timers,
            services=services,
            provider_budget=_provider_budget_for_readiness(),
        )
        return {
            "source": "control_api_v1_automation_readiness",
            "authority": "live control-plane state, systemd timers, provider budget, and bounded dashboard read model",
            "timers": timers,
            "services": services,
            **readiness,
        }

    def _record_preflight_observations(response: WorkerPreflightResponse) -> None:
        preflight_payload = _compact_worker_preflight_payload(response.model_dump(mode="json"))
        store.upsert_dashboard_observation(
            source="worker_preflight",
            status="ok" if response.ok else "warn",
            ttl_seconds=300,
            payload=preflight_payload,
        )
        dashboard_check = next((check for check in response.checks if check.name == "wake_gate_dashboard_api"), None)
        if dashboard_check is not None:
            dashboard_payload = _compact_worker_dashboard_check_payload(dashboard_check.model_dump(mode="json"))
            store.upsert_dashboard_observation(
                source="worker_dashboard_api",
                status="ok" if dashboard_check.ok else "unavailable",
                ttl_seconds=300,
                payload=dashboard_payload,
            )
            body = (dashboard_payload.get("data") or {}).get("body") or {}
            for run_item in body.get("runs") or []:
                if not isinstance(run_item, dict):
                    continue
                run_id = str(run_item.get("run_id") or "").strip()
                project_id = str(run_item.get("project_id") or "").strip()
                scoped_payload = {"source": "worker_dashboard_api", "run": run_item, "dashboard_timestamp": body.get("timestamp"), "totals": body.get("totals") or {}}
                if run_id:
                    store.upsert_dashboard_observation(source="worker_dashboard_api", scope=f"run:{run_id}", status="ok" if dashboard_check.ok else "unavailable", ttl_seconds=120, payload=scoped_payload)
                if project_id:
                    store.upsert_dashboard_observation(source="worker_dashboard_api", scope=f"project:{project_id}", status="ok" if dashboard_check.ok else "unavailable", ttl_seconds=120, payload=scoped_payload)

    def _freshness_for_observation(source: str, authority: str, observation: DashboardObservationRecord | None) -> DashboardFreshness:
        if observation is None:
            return DashboardFreshness(source=source, authority=authority, stale=True, detail="no cached observation")
        stale = _is_stale(observation.observed_at, observation.ttl_seconds)
        return DashboardFreshness(
            source=source,
            authority=authority,
            observed_at=observation.observed_at,
            ttl_seconds=observation.ttl_seconds,
            fresh_until=_fresh_until(observation.observed_at, observation.ttl_seconds),
            stale=stale,
            status=observation.status,
            detail="stale cached observation" if stale else "fresh cached observation",
        )

    def _worker_observations_need_refresh(observations: dict[str, DashboardObservationRecord | None], active: list[dict]) -> bool:
        for source in ("worker_preflight", "worker_dashboard_api"):
            observation = observations.get(source)
            if observation is None or _is_stale(observation.observed_at, observation.ttl_seconds):
                return True
        preflight = observations.get("worker_preflight")
        no_live = _preflight_check(preflight, "worker_no_live_runs")
        if no_live:
            worker_reports_idle = bool(no_live.get("ok"))
            control_reports_active = bool(active)
            if worker_reports_idle == control_reports_active:
                # The cached worker/control active-lane projections disagree.
                # Refresh before presenting a scary conflict; the transition
                # may simply have happened between dashboard polls.
                return True
        return False

    def _refresh_worker_observations_if_needed(observations: dict[str, DashboardObservationRecord | None], active: list[dict]) -> dict[str, DashboardObservationRecord]:
        if not _worker_observations_need_refresh(observations, active):
            return {key: value for key, value in observations.items() if value is not None}
        if not config.live_dispatch_enabled or not config.worker_wake_gate_url or not config.worker_wake_gate_bearer_token:
            return {key: value for key, value in observations.items() if value is not None}
        preflight = run_worker_preflight(
            WorkerPreflightRequest(
                wake_gate_url=config.worker_wake_gate_url,
                bearer_token=config.worker_wake_gate_bearer_token,
                require_paused=False,
                strict=False,
            ),
            store.flags(),
        )
        _record_preflight_observations(preflight)
        return store.latest_dashboard_observations()

    def dashboard_status_response(*, refresh_worker: bool = False) -> DashboardStatusResponse:
        rows = store.queue_rows()
        paper_rows = store.paper_rows()
        flags = store.flags()
        active = store.active_items()
        observations: dict[str, DashboardObservationRecord | None] = {
            # Status uses the bounded preflight payload for dispatch-safety checks.
            "worker_preflight": store.latest_dashboard_observation(source="worker_preflight"),
            # The preflight payload already carries the bounded dashboard check used by status.
            # Keep the standalone dashboard observation to freshness metadata here.
            "worker_dashboard_api": _latest_dashboard_observation_metadata("worker_dashboard_api"),
            # Intake/snapshot observations can contain full batch payloads. Status only needs freshness.
            "idea_intake": _latest_dashboard_observation_metadata("idea_intake"),
            "snapshot_mirror": _latest_dashboard_observation_metadata("snapshot_mirror"),
        }
        if refresh_worker or _worker_observations_need_refresh(observations, active):
            refreshed = _refresh_worker_observations_if_needed(dict(observations), active)
            observations = {
                "worker_preflight": refreshed.get("worker_preflight"),
                "worker_dashboard_api": _latest_dashboard_observation_metadata("worker_dashboard_api"),
                "idea_intake": _latest_dashboard_observation_metadata("idea_intake"),
                "snapshot_mirror": _latest_dashboard_observation_metadata("snapshot_mirror"),
            }
        preflight = observations.get("worker_preflight")
        worker_dashboard = observations.get("worker_dashboard_api")
        recent_events = store.recent_events(10)
        counts = {**store.status_counts(), "papers": len(paper_rows), "queue_total": len(rows)}
        cfg = _config_status()
        source_freshness = {
            "control_plane_db": DashboardFreshness(
                source="control_plane_db",
                authority="canonical execution/control state",
                observed_at=utc_now(),
                stale=False,
                status="ok",
                detail="direct SQLite read",
            ),
            "control_plane_config": DashboardFreshness(
                source="control_plane_config",
                authority="static operational config",
                observed_at=utc_now(),
                stale=False,
                status="ok",
                detail="current process config",
            ),
            "worker_preflight": _freshness_for_observation("worker_preflight", "cached explicit worker preflight evidence", preflight),
            "worker_dashboard_api": _freshness_for_observation("worker_dashboard_api", "cached GB10 runtime evidence", worker_dashboard),
            "idea_intake": _freshness_for_observation("idea_intake", "Supabase-native ideas intake", observations.get("idea_intake")),
            "snapshot_mirror": _freshness_for_observation("snapshot_mirror", "cached worker/intake mirror", observations.get("snapshot_mirror")),
        }
        warnings: list[DashboardFinding] = []
        conflicts: list[DashboardFinding] = []
        blockers: list[str] = []
        if flags.queue_paused:
            blockers.append("queue paused")
            warnings.append(DashboardFinding(severity="warn", source="control_plane_db", authority="dynamic control flag", message=flags.pause_reason or "queue is paused", suggested_action="resume the queue when maintenance is complete"))
        if flags.maintenance_mode:
            blockers.append("maintenance mode")
            warnings.append(DashboardFinding(severity="warn", source="control_plane_db", authority="dynamic control flag", message="maintenance mode is enabled", suggested_action="disable maintenance mode before live dispatch"))
        if not config.live_dispatch_enabled:
            blockers.append("live dispatch disabled")
            warnings.append(DashboardFinding(severity="warn", source="control_plane_config", authority="static operational config", message="live dispatch is disabled by config", suggested_action="enable live_dispatch_enabled only when ready"))
        if active:
            blockers.append("active GB10 lane exists")
        if not active and not flags.queue_paused and not flags.maintenance_mode and config.live_dispatch_enabled and not store.next_dispatch_candidate():
            blockers.append("no queued dispatch candidate")
        no_live = _preflight_check(preflight, "worker_no_live_runs")
        worker_live_matches_active = bool(active and no_live and no_live.get("ok") is False)
        for name, freshness in source_freshness.items():
            if freshness.stale and name in {"worker_preflight", "worker_dashboard_api"}:
                warnings.append(DashboardFinding(severity="warn", source=name, authority=freshness.authority, message=f"{name} is stale or missing", observed_at=freshness.observed_at, suggested_action="run /control/api/preflight or wait for the next refresh observation"))
                if config.live_dispatch_enabled and not flags.queue_paused and not flags.maintenance_mode:
                    blockers.append(f"{name} stale or missing")
            elif name in {"worker_preflight", "worker_dashboard_api"} and freshness.status != "ok":
                if name == "worker_preflight" and worker_live_matches_active:
                    continue
                warnings.append(DashboardFinding(severity="warn", source=name, authority=freshness.authority, message=f"{name} status is {freshness.status}", observed_at=freshness.observed_at, suggested_action="run /control/api/preflight and verify GB10 health before dispatch"))
                if config.live_dispatch_enabled and not flags.queue_paused and not flags.maintenance_mode:
                    blockers.append(f"{name} not ok")
        health = _preflight_check(preflight, "wake_gate_healthz")
        dashboard = _preflight_check(preflight, "wake_gate_dashboard_api")
        if health and not health.get("ok"):
            warnings.append(DashboardFinding(severity="warn", source="worker_preflight", authority="GB10 reachability evidence", message="GB10 wake gate health check failed", observed_at=preflight.observed_at if preflight else None, suggested_action="verify worker service before dispatch", data=health))
            if config.live_dispatch_enabled and not flags.queue_paused and not flags.maintenance_mode:
                blockers.append("worker health check failed")
        if dashboard and dashboard.get("data", {}).get("skipped"):
            warnings.append(DashboardFinding(severity="warn", source="worker_preflight", authority="GB10 runtime evidence", message="authenticated worker dashboard checks were skipped", observed_at=preflight.observed_at if preflight else None, suggested_action="configure worker bearer token before live dispatch", data=dashboard))
            if config.live_dispatch_enabled and not flags.queue_paused and not flags.maintenance_mode:
                blockers.append("worker dashboard telemetry skipped")
        if active and no_live and no_live.get("ok") is True:
            conflicts.append(DashboardFinding(
                severity="warn",
                source="control_plane_db+worker_preflight",
                authority="cross-source active-lane reconciliation",
                message="VM control plane has an active row, but cached GB10 preflight says no live worker run",
                observed_at=preflight.observed_at if preflight else None,
                suggested_action="inspect run detail and reconcile if the worker truly exited",
                data={"active_count": len(active), "worker_check": no_live},
            ))
        if not active and no_live and no_live.get("ok") is False:
            conflicts.append(DashboardFinding(
                severity="critical",
                source="control_plane_db+worker_preflight",
                authority="single active GB10 lane safety",
                message="GB10 reports live/active work but VM control plane has no active row",
                observed_at=preflight.observed_at if preflight else None,
                suggested_action="pause dispatch and reconcile before starting another job",
                data={"worker_check": no_live},
            ))
            blockers.append("GB10/VM active-lane conflict")
        has_critical = any(item.severity == "critical" for item in conflicts)
        dispatch_safe = not blockers and not has_critical
        return DashboardStatusResponse(
            flags=flags,
            config=cfg,
            counts=counts,
            active_items=active,
            next_candidate=store.next_dispatch_candidate(),
            dispatch_safe=dispatch_safe,
            dispatch_blockers=blockers,
            source_freshness=source_freshness,
            observations={source: observations.get(source) for source in ("worker_preflight", "worker_dashboard_api", "idea_intake", "snapshot_mirror")},
            warnings=warnings,
            conflicts=conflicts,
            recent_events=recent_events,
        )


    def _db_freshness(authority: str = "canonical control-plane SQLite") -> dict[str, DashboardFreshness]:
        return {
            "control_plane_db": DashboardFreshness(
                source="control_plane_db",
                authority=authority,
                observed_at=utc_now(),
                stale=False,
                status="ok",
                detail="direct SQLite read",
            )
        }

    def _latest_dashboard_observation_metadata(source: str, scope: str = "global") -> DashboardObservationRecord | None:
        summary_reader = getattr(store, "latest_dashboard_observation_summary", None)
        if callable(summary_reader):
            return summary_reader(source=source, scope=scope)
        return store.latest_dashboard_observation(source=source, scope=scope)

    def _cached_observation_freshness(source: str, authority: str, scope: str = "global") -> dict[str, DashboardFreshness]:
        observation = _latest_dashboard_observation_metadata(source, scope)
        return {source: _freshness_for_observation(source, authority, observation)}

    def _classify_queue(row: dict[str, Any]) -> set[str]:
        status = str(row.get("status") or "")
        groups = {"all", status}
        if status in {"dispatching", "running", "awaiting_wake", "wake_received", "reconciling"}:
            groups.add("active")
        if status == "queued":
            groups.add("queued")
        if status in {"blocked", "needs_review", "dispatch_error"} or row.get("manual_review_required"):
            groups.add("blocked")
        if status == "paused":
            groups.add("paused")
        if status in {"completed", "canceled"}:
            groups.add("completed")
        return groups

    def _row_age_seconds(row: dict[str, Any]) -> int | None:
        ts = _parse_ts(str(row.get("updated_at") or row.get("created_at") or ""))
        if ts is None:
            return None
        return max(0, int((datetime.now(timezone.utc) - ts).total_seconds()))

    def _enrich_queue_row(row: dict[str, Any]) -> dict[str, Any]:
        out = dict(row)
        out["queue_groups"] = sorted(_classify_queue(row))
        out["age_seconds"] = _row_age_seconds(row)
        out["links"] = {
            "project": f"/control/api/projects/{row.get('project_id') or ''}",
            "run": f"/control/api/runs/{row.get('current_run_id') or ''}" if row.get("current_run_id") else "",
            "dashboard_project": f"/control/dashboard#project:{row.get('project_id') or ''}",
            "dashboard_run": f"/control/dashboard#run:{row.get('current_run_id') or ''}" if row.get("current_run_id") else "",
        }
        if row.get("stale_after") and _is_stale(str(row.get("stale_after")), 0):
            out["stale"] = True
        return out

    def _search_rows(rows: list[dict[str, Any]], search: str) -> list[dict[str, Any]]:
        needle = search.strip().lower()
        if not needle:
            return rows
        return [row for row in rows if needle in " ".join(str(v).lower() for v in row.values() if isinstance(v, (str, int, float, bool)))]

    def _sort_rows(rows: list[dict[str, Any]], sort: str) -> list[dict[str, Any]]:
        reverse = sort.startswith("-")
        key = sort[1:] if reverse else sort
        if key in {"updated_at", "project_name", "status", "last_callback_at", "last_dispatch_at", "paper_status", "review_status", "rank_bucket"}:
            return sorted(rows, key=lambda row: str(row.get(key) or ""), reverse=reverse)
        if key in {"dispatch_priority", "selection_rank", "retry_count", "age_seconds", "rank_score"}:
            return sorted(rows, key=lambda row: int(row.get(key) or 0), reverse=reverse)
        return rows

    def _paper_record_from_row(row: dict[str, Any]) -> PaperRecord:
        data = dict(row)
        for key in ("generated_at", "updated_at"):
            value = data.get(key)
            if isinstance(value, datetime):
                data[key] = value.isoformat()
        return PaperRecord.model_validate(data)

    def _paginate(rows: list[dict[str, Any]], *, page: int, page_size: int) -> tuple[list[dict[str, Any]], int, int]:
        safe_page = max(1, page)
        safe_size = max(1, min(page_size, 500))
        start = (safe_page - 1) * safe_size
        return rows[start:start + safe_size], safe_page, safe_size

    def _queue_counts(rows: list[dict[str, Any]]) -> dict[str, int]:
        counts: dict[str, int] = {"all": len(rows)}
        for row in rows:
            for group in _classify_queue(row):
                counts[group] = counts.get(group, 0) + 1
        return counts

    def _paper_counts(rows: list[dict[str, Any]]) -> dict[str, int]:
        counts: dict[str, int] = {"all": len(rows)}
        for row in rows:
            key = str(row.get("paper_status") or "unknown")
            counts[key] = counts.get(key, 0) + 1
        return counts

    def _review_counts(rows: list[dict[str, Any]]) -> dict[str, int]:
        counts: dict[str, int] = {"all": len(rows)}
        for row in rows:
            for key_name in ("review_status", "paper_status", "rank_bucket"):
                key = str(row.get(key_name) or "unknown")
                counts[key] = counts.get(key, 0) + 1
        return counts

    def _project_events(project_id: str) -> list[dict[str, Any]]:
        events = store.event_rows(limit=100, entity_id=project_id)
        queue = store.queue_row(project_id)
        run_id = str((queue or {}).get("current_run_id") or "")
        if run_id:
            events.extend(store.event_rows(limit=50, entity_id=run_id))
        events.sort(key=lambda item: int(item.get("event_id") or 0), reverse=True)
        return events[:100]

    def _intake_freshness() -> dict[str, DashboardFreshness]:
        return {
            **_db_freshness("Supabase-native ideas workbench"),
            **_cached_observation_freshness("idea_intake", "latest Supabase-native ideas intake observation"),
        }

    def _require_legacy_notion_api_enabled() -> None:
        if not config.legacy_notion_api_enabled:
            raise HTTPException(
                status_code=410,
                detail={
                    "message": "Legacy Notion control-plane APIs are disabled; use Supabase-native /control/intake/ideas and /control/api/intake/ideas.",
                    "replacement": "/control/intake/ideas",
                },
            )


    @router.get("/dashboard", response_class=HTMLResponse)
    def dashboard() -> HTMLResponse:
        return HTMLResponse(CONTROL_DASHBOARD_HTML, headers={"Cache-Control": "no-store"})

    @router.get("/health")
    def health(authorization: str | None = Header(default=None)) -> dict:
        authorize(authorization)
        backend = config.control_plane_store_backend
        db_path = str(getattr(store, "path", backend))
        return {"ok": True, "service": "enoch-langgraph-control-plane", "db_path": db_path, "store_backend": backend, "timestamp": utc_now()}

    @router.get("/state", response_model=ControlStateResponse)
    def get_state(authorization: str | None = Header(default=None)) -> ControlStateResponse:
        authorize(authorization)
        return state_response()

    @router.get("/api/status", response_model=DashboardStatusResponse)
    def dashboard_status(refresh_worker: bool = Query(default=False), authorization: str | None = Header(default=None)) -> DashboardStatusResponse:
        authorize(authorization)
        return dashboard_status_response(refresh_worker=refresh_worker)

    @router.post("/api/alerts/queue-check")
    def dashboard_queue_alert_check(payload: dict[str, Any] | None = None, authorization: str | None = Header(default=None)) -> dict[str, Any]:
        authorize(authorization)
        request_payload = payload or {}
        status = dashboard_status_response(refresh_worker=bool(request_payload.get("refresh_worker", False)))
        return evaluate_and_notify_queue_alerts(
            config=config,
            store=store,
            status=status,
            dry_run=bool(request_payload.get("dry_run", True)),
            force_notify=bool(request_payload.get("force_notify", False)),
            requested_by=str(request_payload.get("requested_by") or "operator"),
        )

    @router.get("/api/queue-health")
    def dashboard_queue_health(refresh_worker: bool = Query(default=False), authorization: str | None = Header(default=None)) -> dict[str, Any]:
        authorize(authorization)
        status = dashboard_status_response(refresh_worker=refresh_worker)
        active = status.active_items[0] if status.active_items else None
        run_id = str((active or {}).get("current_run_id") or "")
        project_id = str((active or {}).get("project_id") or "")
        alert = evaluate_and_notify_queue_alerts(
            config=config,
            store=store,
            status=status,
            dry_run=True,
            force_notify=False,
            requested_by="dashboard.queue_health",
        )
        return {
            "ok": True,
            "source": "control_api_queue_health",
            "authority": "aggregated queue health read model",
            "generated_at": utc_now(),
            "status": status.model_dump(mode="json"),
            "active_run_detail": {
                "queue_item": active,
                "run": store.run_row(run_id) if run_id else None,
                "project": store.project_row(project_id) if project_id else None,
                "events": _project_events(project_id) if project_id else [],
            },
            "latest_alert_check": alert,
            "recent_alert_events": store.event_rows(limit=20, entity_type="queue_alert"),
            "recent_worker_callbacks": store.event_rows(limit=20, search="worker_callback."),
        }

    @router.post("/api/worker-callback")
    def worker_callback(callback: GateCallback, authorization: str | None = Header(default=None)) -> dict[str, Any]:
        authorize(authorization)
        try:
            event_id, inserted, row = store.record_worker_callback(callback)
        except IdempotencyConflict as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        decision_sync: dict[str, Any] | None = None
        if callback.event_type in {"wake_ready", "session_finished_ready"} and row:
            project_id = str(row.get("project_id") or callback.project_id or "").strip()
            project_dir_text = str(row.get("project_dir") or project_id).strip()
            root = config.expanded_project_root.resolve()
            artifact_root = (root / project_id).resolve()
            if project_dir_text:
                candidate_root = Path(project_dir_text).expanduser()
                if not candidate_root.is_absolute():
                    artifact_root = (root / candidate_root).resolve()
                else:
                    try:
                        candidate_root.resolve().relative_to(root)
                        artifact_root = candidate_root.resolve()
                    except ValueError:
                        artifact_root = (root / project_id).resolve()
            evidence_sync = _sync_remote_project_evidence(
                config,
                project_id=project_id,
                artifact_root=artifact_root,
                source_project_dir=project_dir_text if project_dir_text.startswith("/") else "",
                source_run_id=str(callback.run_id or ""),
            )
            decision_sync = {"artifact_root": str(artifact_root), "evidence_sync": evidence_sync}
            if hasattr(store, "record_project_decision_gate"):
                decision_record = store.record_project_decision_gate(
                    project_id=project_id,
                    run_id=str(callback.run_id or ""),
                    artifact_root=artifact_root,
                )
                decision_sync["decision_record"] = decision_record
                if decision_record.get("persisted") and project_id:
                    store.update_project_dir(project_id, str(artifact_root))
                    row = store.queue_row(project_id) or row
        return {
            "ok": True,
            "accepted": True,
            "run_id": callback.run_id,
            "session_id": callback.session_id,
            "event_type": callback.event_type,
            "state": callback.event_type,
            "idempotency_key": callback.idempotency_key,
            "event_id": event_id,
            "inserted_event": inserted,
            "queue_item": row,
            "decision_sync": decision_sync,
            "controller_action": "record_worker_callback",
            "next_action_hint": row.get("next_action_hint") if row else "callback_recorded_no_queue_row",
        }

    @router.get("/api/v1/automation-readiness")
    def dashboard_v1_automation_readiness(authorization: str | None = Header(default=None)) -> dict[str, Any]:
        authorize(authorization)
        return _automation_readiness_payload()


    @router.get("/api/v1/overview")
    def dashboard_v1_overview(
        authorization: str | None = Header(default=None),
        active_limit: int = Query(default=5, ge=1, le=25),
        event_limit: int = Query(default=10, ge=0, le=50),
    ) -> dict[str, Any]:
        authorize(authorization)
        data = read_models.overview(store, active_limit=active_limit, event_limit=event_limit)
        return {
            "ok": True,
            "source": "control_api_v1_overview",
            "authority": "bounded dashboard read model",
            "generated_at": utc_now(),
            **data,
            "links": {
                "queue": "/control/api/v1/queue",
                "runs": "/control/api/v1/runs",
                "papers": "/control/api/v1/papers",
                "events": "/control/api/v1/events",
            },
        }


    @router.post("/api/v1/followups/launch-next", response_model=FollowupLaunchResponse)
    def launch_next_followup(payload: FollowupLaunchRequest, authorization: str | None = Header(default=None)) -> FollowupLaunchResponse:
        authorize(authorization)
        launcher = getattr(store, "launch_followup_candidate", None)
        if not callable(launcher):
            return FollowupLaunchResponse(ok=True, action="noop", reason="store does not support follow-up branching")
        result = launcher(
            project_id=payload.project_id,
            dry_run=payload.dry_run,
            requested_by=payload.requested_by,
            max_followup_depth=payload.max_followup_depth,
        )
        return FollowupLaunchResponse(
            ok=bool(result.get("ok", True)),
            action=result.get("action") or "noop",
            reason=result.get("reason") or "",
            candidate=result.get("candidate"),
            followup=result.get("followup"),
            event_id=result.get("event_id"),
        )

    @router.get("/api/v1/lanes")
    def dashboard_v1_lanes(authorization: str | None = Header(default=None)) -> dict[str, Any]:
        authorize(authorization)
        active = [read_models.summarize_queue_row(row) for row in store.active_items_sql(limit=10)]
        next_candidate = store.next_candidate_sql()
        return {
            "ok": True,
            "source": "control_api_v1_lanes",
            "authority": "bounded active-lane read model",
            "generated_at": utc_now(),
            "active_items": active,
            "next_candidate": read_models.summarize_queue_row(next_candidate) if next_candidate else None,
            "counts": store.queue_counts_sql(),
        }

    @router.get("/api/v1/queue")
    def dashboard_v1_queue(
        authorization: str | None = Header(default=None),
        queue: str = Query(default="all"),
        status: str = "",
        search: str = "",
        cursor: str = "",
        page_size: int = Query(default=50, ge=1, le=200),
        sort: str = "priority",
    ) -> dict[str, Any]:
        authorize(authorization)
        safe_size = read_models.page_size(page_size)
        rows, next_cursor, has_more = store.queue_page(queue=queue, status=status, search=search, cursor=cursor, page_size=safe_size, sort=sort)
        out = [read_models.summarize_queue_row(row) for row in rows]
        return {
            "ok": True,
            "source": "control_api_v1_queue",
            "authority": "bounded SQL queue read model",
            "generated_at": utc_now(),
            "counts": store.queue_counts_sql(),
            "page": read_models.page_response(rows=out, next_cursor=next_cursor, has_more=has_more, page_size_value=safe_size, cursor=cursor, filters={"queue": queue, "status": status, "search": search, "sort": sort}),
            "rows": out,
        }

    @router.get("/api/v1/runs")
    def dashboard_v1_runs(
        authorization: str | None = Header(default=None),
        state: str = "",
        project_id: str = "",
        search: str = "",
        cursor: str = "",
        page_size: int = Query(default=50, ge=1, le=200),
        sort: str = "recent",
    ) -> dict[str, Any]:
        authorize(authorization)
        safe_size = read_models.page_size(page_size)
        rows, next_cursor, has_more = store.run_page(state=state, project_id=project_id, search=search, cursor=cursor, page_size=safe_size, sort=sort)
        out = [read_models.summarize_run_row(row) for row in rows]
        return {
            "ok": True,
            "source": "control_api_v1_runs",
            "authority": "bounded SQL run read model",
            "generated_at": utc_now(),
            "page": read_models.page_response(rows=out, next_cursor=next_cursor, has_more=has_more, page_size_value=safe_size, cursor=cursor, filters={"state": state, "project_id": project_id, "search": search, "sort": sort}),
            "rows": out,
        }

    @router.get("/api/v1/runs/{run_id}")
    def dashboard_v1_run_detail(run_id: str, authorization: str | None = Header(default=None), event_limit: int = Query(default=50, ge=0, le=100)) -> dict[str, Any]:
        authorize(authorization)
        run = store.run_row(run_id)
        if run is None:
            raise HTTPException(status_code=404, detail="run not found")
        project_id = str(run.get("project_id") or "")
        events, next_cursor, has_more = store.event_page(entity_id=run_id, page_size=event_limit, include_payload=False)
        papers, paper_cursor, paper_more = store.paper_page(run_id=run_id, page_size=25)
        return {
            "ok": True,
            "source": "control_api_v1_run",
            "authority": "bounded SQL run detail read model",
            "generated_at": utc_now(),
            "run_id": run_id,
            "run": read_models.summarize_run_row(run),
            "project": store.project_row(project_id) if project_id else None,
            "papers": [read_models.summarize_paper_row(row) for row in papers],
            "papers_page": read_models.page_response(rows=papers, next_cursor=paper_cursor, has_more=paper_more, page_size_value=25, cursor="", filters={"run_id": run_id}),
            "events": events,
            "events_page": read_models.page_response(rows=events, next_cursor=next_cursor, has_more=has_more, page_size_value=read_models.page_size(event_limit, cap=100), cursor="", filters={"entity_id": run_id}),
        }

    @router.get("/api/v1/projects/{project_id}")
    def dashboard_v1_project_detail(project_id: str, authorization: str | None = Header(default=None), event_limit: int = Query(default=50, ge=0, le=100)) -> dict[str, Any]:
        authorize(authorization)
        project = store.project_row(project_id)
        if project is None:
            raise HTTPException(status_code=404, detail="project not found")
        runs, run_cursor, run_more = store.run_page(project_id=project_id, page_size=25)
        papers, paper_cursor, paper_more = store.paper_page(project_id=project_id, page_size=25)
        events, event_cursor, event_more = store.event_page(entity_id=project_id, page_size=event_limit, include_payload=False)
        queue_item = store.queue_row(project_id)
        return {
            "ok": True,
            "source": "control_api_v1_project",
            "authority": "bounded SQL project detail read model",
            "generated_at": utc_now(),
            "project_id": project_id,
            "project": project,
            "queue_item": read_models.summarize_queue_row(queue_item) if queue_item else None,
            "runs": [read_models.summarize_run_row(row) for row in runs],
            "runs_page": read_models.page_response(rows=runs, next_cursor=run_cursor, has_more=run_more, page_size_value=25, cursor="", filters={"project_id": project_id}),
            "papers": [read_models.summarize_paper_row(row) for row in papers],
            "papers_page": read_models.page_response(rows=papers, next_cursor=paper_cursor, has_more=paper_more, page_size_value=25, cursor="", filters={"project_id": project_id}),
            "events": events,
            "events_page": read_models.page_response(rows=events, next_cursor=event_cursor, has_more=event_more, page_size_value=read_models.page_size(event_limit, cap=100), cursor="", filters={"entity_id": project_id}),
        }

    @router.get("/api/v1/papers")
    def dashboard_v1_papers(
        authorization: str | None = Header(default=None),
        status: str = "",
        search: str = "",
        cursor: str = "",
        page_size: int = Query(default=50, ge=1, le=200),
        sort: str = "recent",
    ) -> dict[str, Any]:
        authorize(authorization)
        safe_size = read_models.page_size(page_size)
        rows, next_cursor, has_more = store.paper_page(status=status, search=search, cursor=cursor, page_size=safe_size, sort=sort)
        out = [read_models.summarize_paper_row(row) for row in rows]
        return {
            "ok": True,
            "source": "control_api_v1_papers",
            "authority": "bounded SQL paper read model",
            "generated_at": utc_now(),
            "counts": store.paper_counts_sql(),
            "page": read_models.page_response(rows=out, next_cursor=next_cursor, has_more=has_more, page_size_value=safe_size, cursor=cursor, filters={"status": status, "search": search, "sort": sort}),
            "rows": out,
        }

    @router.get("/api/v1/papers/{paper_id}")
    def dashboard_v1_paper_detail(paper_id: str, authorization: str | None = Header(default=None), event_limit: int = Query(default=50, ge=0, le=100)) -> dict[str, Any]:
        authorize(authorization)
        paper = store.paper_row(paper_id)
        if paper is None:
            raise HTTPException(status_code=404, detail="paper not found")
        project_id = str(paper.get("project_id") or "")
        run_id = str(paper.get("run_id") or "")
        events, next_cursor, has_more = store.event_page(entity_id=paper_id, page_size=event_limit, include_payload=False)
        return {
            "ok": True,
            "source": "control_api_v1_paper",
            "authority": "bounded SQL paper detail read model",
            "generated_at": utc_now(),
            "paper_id": paper_id,
            "paper": read_models.summarize_paper_row(paper),
            "project": store.project_row(project_id) if project_id else None,
            "run": store.run_row(run_id) if run_id else None,
            "events": events,
            "events_page": read_models.page_response(rows=events, next_cursor=next_cursor, has_more=has_more, page_size_value=read_models.page_size(event_limit, cap=100), cursor="", filters={"entity_id": paper_id}),
        }

    @router.get("/api/v1/events")
    def dashboard_v1_events(
        authorization: str | None = Header(default=None),
        entity_type: str = "",
        entity_id: str = "",
        event_type: str = "",
        search: str = "",
        cursor: str = "",
        page_size: int = Query(default=50, ge=1, le=200),
        include_payload: bool = False,
        sort: str = "recent",
    ) -> dict[str, Any]:
        authorize(authorization)
        safe_size = read_models.page_size(page_size)
        rows, next_cursor, has_more = store.event_page(entity_type=entity_type, entity_id=entity_id, event_type=event_type, search=search, cursor=cursor, page_size=safe_size, include_payload=include_payload, sort=sort)
        return {
            "ok": True,
            "source": "control_api_v1_events",
            "authority": "bounded SQL event read model",
            "generated_at": utc_now(),
            "page": read_models.page_response(rows=rows, next_cursor=next_cursor, has_more=has_more, page_size_value=safe_size, cursor=cursor, filters={"entity_type": entity_type, "entity_id": entity_id, "event_type": event_type, "search": search, "include_payload": include_payload, "sort": sort}),
            "rows": rows,
        }

    @router.get("/api/v1/observability/health")
    def dashboard_v1_observability_health(authorization: str | None = Header(default=None)) -> dict[str, Any]:
        authorize(authorization)
        latest_route_observation = None
        if config.route_observability_enabled:
            path = Path(config.route_observability_log_path).expanduser() if config.route_observability_log_path else config.expanded_state_dir / "route_observations.jsonl"
            try:
                with path.open("rb") as handle:
                    handle.seek(0, 2)
                    size = handle.tell()
                    handle.seek(max(0, size - 4096))
                    latest = handle.readlines()[-1:] or []
                    latest_route_observation = latest[0].decode("utf-8", errors="replace").strip() if latest else None
            except OSError:
                latest_route_observation = None
        return {
            "ok": True,
            "source": "control_api_v1_observability_health",
            "authority": "bounded route observability read model",
            "generated_at": utc_now(),
            "route_observability_enabled": config.route_observability_enabled,
            "route_observability_log_configured": bool(config.route_observability_log_path),
            "latest_route_observation": latest_route_observation,
        }

    @router.get("/api/v1/observability/memory")
    def dashboard_v1_observability_memory(authorization: str | None = Header(default=None)) -> dict[str, Any]:
        authorize(authorization)
        rss = current_rss_mib()
        peak = peak_rss_mib()
        warn_threshold = config.route_observability_memory_warn_rss_mib
        return {
            "ok": True,
            "source": "control_api_v1_observability_memory",
            "authority": "current controller process memory sample",
            "generated_at": utc_now(),
            "rss_mib": rss,
            "peak_rss_mib": peak,
            "warn_threshold_mib": warn_threshold,
            "memory_warn": bool(warn_threshold and rss is not None and rss >= warn_threshold),
            "route_observability_enabled": config.route_observability_enabled,
        }


    @router.get("/api/queues/{queue}", response_model=DashboardQueueResponse)
    def dashboard_queue(
        queue: str,
        authorization: str | None = Header(default=None),
        page: int = Query(default=1, ge=1),
        page_size: int = Query(default=50, ge=1, le=500),
        search: str = "",
        status: str = "",
        sort: str = "dispatch_priority",
    ) -> DashboardQueueResponse:
        authorize(authorization)
        all_rows = [_enrich_queue_row(row) for row in store.queue_rows()]
        selected = [row for row in all_rows if queue in _classify_queue(row)] if queue != "all" else all_rows
        if status:
            selected = [row for row in selected if str(row.get("status") or "") == status]
        selected = _sort_rows(_search_rows(selected, search), sort)
        page_rows, safe_page, safe_size = _paginate(selected, page=page, page_size=page_size)
        return DashboardQueueResponse(
            queue=queue,
            counts=_queue_counts(all_rows),
            rows=page_rows,
            page=DashboardPageMeta(page=safe_page, page_size=safe_size, total=len(selected), returned=len(page_rows), queue=queue, filters={"search": search, "status": status}, sort=sort),
            source_freshness=_db_freshness("canonical queue/project read model"),
            conflicts=[],
        )



    def _worker_detail_observations(project_id: str = "", run_id: str = "") -> dict[str, DashboardObservationRecord | None]:
        observations: dict[str, DashboardObservationRecord | None] = {
            "worker_preflight": store.latest_dashboard_observation(source="worker_preflight"),
            "worker_dashboard_api": store.latest_dashboard_observation(source="worker_dashboard_api"),
        }
        if project_id:
            observations["worker_dashboard_api_project"] = store.latest_dashboard_observation(source="worker_dashboard_api", scope=f"project:{project_id}")
        if run_id:
            observations["worker_dashboard_api_run"] = store.latest_dashboard_observation(source="worker_dashboard_api", scope=f"run:{run_id}")
        return observations



    def _worker_detail_freshness(source: str, authority: str, scope: str) -> dict[str, DashboardFreshness]:
        scoped = store.latest_dashboard_observation(source=source, scope=scope)
        if scoped is not None:
            return {source: _freshness_for_observation(source, authority, scoped)}
        global_observation = store.latest_dashboard_observation(source=source)
        if global_observation is not None:
            return {source: _freshness_for_observation(source, f"{authority} (global fallback)", global_observation)}
        return {source: _freshness_for_observation(source, authority, None)}

    def _detail_conflicts(*, active: bool = False, worker_observations: dict[str, DashboardObservationRecord | None]) -> list[DashboardFinding]:
        preflight = worker_observations.get("worker_preflight")
        no_live = _preflight_check(preflight, "worker_no_live_runs")
        conflicts: list[DashboardFinding] = []
        if active and no_live and no_live.get("ok") is True:
            conflicts.append(DashboardFinding(
                severity="warn",
                source="control_plane_db+worker_preflight",
                authority="cross-source active-lane reconciliation",
                message="control-plane row is active but latest worker preflight reports no live run",
                observed_at=preflight.observed_at if preflight else None,
                suggested_action="inspect run detail and reconcile the active row if the worker exited",
                data={"worker_check": no_live},
            ))
        if not active and no_live and no_live.get("ok") is False:
            conflicts.append(DashboardFinding(
                severity="critical",
                source="control_plane_db+worker_preflight",
                authority="single active GB10 lane safety",
                message="worker reports live work but this detail view has no active control-plane row",
                observed_at=preflight.observed_at if preflight else None,
                suggested_action="pause dispatch and reconcile before starting another job",
                data={"worker_check": no_live},
            ))
        return conflicts
    @router.get("/api/projects/{project_id}", response_model=DashboardProjectDetailResponse)
    def dashboard_project(project_id: str, authorization: str | None = Header(default=None)) -> DashboardProjectDetailResponse:
        authorize(authorization)
        project = store.project_row(project_id)
        queue_item = store.queue_row(project_id)
        if project is None and queue_item is None:
            raise HTTPException(status_code=404, detail="project not found")
        runs = [row for row in store.run_rows() if row.get("project_id") == project_id]
        papers = [row for row in store.paper_rows() if row.get("project_id") == project_id]
        observations = _worker_detail_observations(project_id=project_id, run_id=str((queue_item or {}).get("current_run_id") or ""))
        warnings = []
        active = bool(queue_item and "active" in _classify_queue(queue_item))
        if queue_item and "active" in _classify_queue(queue_item) and not runs and not (observations.get("worker_dashboard_api_project") or observations.get("worker_dashboard_api")):
            warnings.append(DashboardFinding(severity="warn", source="control_plane_db", authority="project detail aggregate", message="active queue item has no local run row or worker observation", suggested_action="inspect worker and reconcile if process exited"))
        return DashboardProjectDetailResponse(
            project_id=project_id,
            project=project,
            queue_item=_enrich_queue_row(queue_item) if queue_item else None,
            runs=runs,
            papers=papers,
            events=_project_events(project_id),
            worker_observations=observations,
            source_freshness={**_db_freshness("project/queue/run/paper aggregate"), **_worker_detail_freshness("worker_dashboard_api", "project-scoped cached worker detail", f"project:{project_id}")},
            warnings=warnings,
            conflicts=_detail_conflicts(active=active, worker_observations=observations),
        )

    @router.get("/api/runs/{run_id}", response_model=DashboardRunDetailResponse)
    def dashboard_run(run_id: str, authorization: str | None = Header(default=None)) -> DashboardRunDetailResponse:
        authorize(authorization)
        run = store.run_row(run_id)
        queue_item = next((row for row in store.queue_rows() if row.get("current_run_id") == run_id), None)
        project_id = str((run or queue_item or {}).get("project_id") or "")
        if run is None and queue_item is None:
            raise HTTPException(status_code=404, detail="run not found")
        observations = _worker_detail_observations(project_id=project_id, run_id=run_id)
        active = bool(queue_item and "active" in _classify_queue(queue_item))
        return DashboardRunDetailResponse(
            run_id=run_id,
            run=run,
            queue_item=_enrich_queue_row(queue_item) if queue_item else None,
            project=store.project_row(project_id) if project_id else None,
            papers=[row for row in store.paper_rows() if row.get("run_id") == run_id],
            events=store.event_rows(limit=100, entity_id=run_id) + (store.event_rows(limit=50, entity_id=project_id) if project_id else []),
            worker_observations=observations,
            source_freshness={**_db_freshness("run/project/paper aggregate"), **_worker_detail_freshness("worker_dashboard_api", "run-scoped cached worker detail", f"run:{run_id}")},
            warnings=[] if (observations.get("worker_dashboard_api_run") or observations.get("worker_dashboard_api")) else [DashboardFinding(severity="info", source="worker_dashboard_api", authority="run detail worker evidence", message="no worker observation cached yet", suggested_action="run /control/api/preflight or refresh run detail when available")],
            conflicts=_detail_conflicts(active=active, worker_observations=observations),
        )

    @router.post("/api/publication-automation/backfill", response_model=PaperReviewBackfillResponse)
    @router.post("/api/paper-reviews/backfill", response_model=PaperReviewBackfillResponse)
    def dashboard_paper_reviews_backfill(payload: PaperReviewBackfillRequest, authorization: str | None = Header(default=None)) -> PaperReviewBackfillResponse:
        authorize(authorization)
        try:
            inserted, created, updated, skipped, errors = store.backfill_paper_reviews(payload)
        except IdempotencyConflict as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        return PaperReviewBackfillResponse(dry_run=payload.dry_run, inserted_event=inserted, created=created, updated=updated, skipped=skipped, errors=errors)

    def _dashboard_paper_reviews_response(
        *,
        authorization: str | None = Header(default=None),
        page: int = Query(default=1, ge=1),
        page_size: int = Query(default=50, ge=1, le=500),
        review_status: str = "",
        paper_status: str = "",
        search: str = "",
        sort: str = "-rank_score",
        include_rank_reasons: bool = True,
        queue_label: str = "publication_automation",
    ) -> DashboardPaperReviewsResponse:
        authorize(authorization)
        rows = store.paper_review_rows(include_rank_reasons=include_rank_reasons)
        all_counts = _review_counts(rows)
        if review_status:
            rows = [row for row in rows if str(row.get("review_status") or "") == review_status]
        if paper_status:
            rows = [row for row in rows if str(row.get("paper_status") or "") == paper_status]
        rows = _sort_rows(_search_rows(rows, search), sort)
        page_rows, safe_page, safe_size = _paginate(rows, page=page, page_size=page_size)
        return DashboardPaperReviewsResponse(
            page=DashboardPageMeta(page=safe_page, page_size=safe_size, total=len(rows), returned=len(page_rows), queue=queue_label, filters={"search": search, "review_status": review_status, "paper_status": paper_status, "include_rank_reasons": include_rank_reasons}, sort=sort),
            counts=all_counts,
            rows=page_rows,
            source_freshness=_db_freshness("canonical publication automation queue read model"),
            conflicts=[],
        )

    @router.get("/api/publication-automation", response_model=DashboardPaperReviewsResponse)
    def dashboard_publication_automation(
        authorization: str | None = Header(default=None),
        page: int = Query(default=1, ge=1),
        page_size: int = Query(default=50, ge=1, le=500),
        review_status: str = "",
        paper_status: str = "",
        search: str = "",
        sort: str = "-rank_score",
        include_rank_reasons: bool = True,
    ) -> DashboardPaperReviewsResponse:
        return _dashboard_paper_reviews_response(
            authorization=authorization,
            page=page,
            page_size=page_size,
            review_status=review_status,
            paper_status=paper_status,
            search=search,
            sort=sort,
            include_rank_reasons=include_rank_reasons,
            queue_label="publication_automation",
        )

    @router.get("/api/paper-reviews", response_model=DashboardPaperReviewsResponse)
    def dashboard_paper_reviews(
        authorization: str | None = Header(default=None),
        page: int = Query(default=1, ge=1),
        page_size: int = Query(default=50, ge=1, le=500),
        review_status: str = "",
        paper_status: str = "",
        search: str = "",
        sort: str = "-rank_score",
        include_rank_reasons: bool = True,
    ) -> DashboardPaperReviewsResponse:
        return _dashboard_paper_reviews_response(
            authorization=authorization,
            page=page,
            page_size=page_size,
            review_status=review_status,
            paper_status=paper_status,
            search=search,
            sort=sort,
            include_rank_reasons=include_rank_reasons,
            queue_label="paper_reviews",
        )

    def _paper_review_detail_response(paper_id: str) -> DashboardPaperReviewDetailResponse:
        item = store.paper_review_row(paper_id, include_rank_reasons=True)
        paper = store.paper_row(paper_id)
        if item is None or paper is None:
            raise HTTPException(status_code=404, detail="publication automation item not found")
        project_id = str(paper.get("project_id") or "")
        return DashboardPaperReviewDetailResponse(
            paper_id=paper_id,
            item=item,
            checklist=store.paper_review_checklist(paper_id),
            paper=paper,
            project=store.project_row(project_id) if project_id else None,
            events=store.event_rows(limit=100, entity_id=paper_id) + (store.event_rows(limit=50, entity_id=project_id) if project_id else []),
            source_freshness=_db_freshness("publication automation/paper/project aggregate"),
            warnings=[],
            conflicts=[],
        )

    def _dashboard_next_paper_review_response(
        *,
        authorization: str | None = Header(default=None),
        review_status: str = "",
        paper_status: str = "publication_draft",
        search: str = "",
    ) -> DashboardPaperReviewDetailResponse:
        authorize(authorization)
        rows = store.paper_review_rows(include_rank_reasons=True)
        if review_status:
            rows = [row for row in rows if str(row.get("review_status") or "") == review_status]
        else:
            rows = [row for row in rows if str(row.get("review_status") or "") not in {"finalized", "rejected"}]
        if paper_status:
            rows = [row for row in rows if str(row.get("paper_status") or "") == paper_status]
        rows = _sort_rows(_search_rows(rows, search), "-rank_score")
        if not rows:
            raise HTTPException(status_code=404, detail="no matching publication automation item")
        return _paper_review_detail_response(str(rows[0].get("paper_id") or ""))

    @router.get("/api/publication-automation/next", response_model=DashboardPaperReviewDetailResponse)
    def dashboard_next_publication_automation(
        authorization: str | None = Header(default=None),
        review_status: str = "",
        paper_status: str = "publication_draft",
        search: str = "",
    ) -> DashboardPaperReviewDetailResponse:
        return _dashboard_next_paper_review_response(authorization=authorization, review_status=review_status, paper_status=paper_status, search=search)

    @router.get("/api/paper-reviews/next", response_model=DashboardPaperReviewDetailResponse)
    def dashboard_next_paper_review(
        authorization: str | None = Header(default=None),
        review_status: str = "",
        paper_status: str = "publication_draft",
        search: str = "",
    ) -> DashboardPaperReviewDetailResponse:
        return _dashboard_next_paper_review_response(authorization=authorization, review_status=review_status, paper_status=paper_status, search=search)

    @router.get("/api/publication-automation/{paper_id}", response_model=DashboardPaperReviewDetailResponse)
    def dashboard_publication_automation_item(paper_id: str, authorization: str | None = Header(default=None)) -> DashboardPaperReviewDetailResponse:
        authorize(authorization)
        return _paper_review_detail_response(paper_id)

    @router.get("/api/paper-reviews/{paper_id}", response_model=DashboardPaperReviewDetailResponse)
    def dashboard_paper_review(paper_id: str, authorization: str | None = Header(default=None)) -> DashboardPaperReviewDetailResponse:
        authorize(authorization)
        return _paper_review_detail_response(paper_id)

    @router.post("/api/publication-automation/{paper_id}/claim", response_model=PaperReviewMutationResponse)
    @router.post("/api/paper-reviews/{paper_id}/claim", response_model=PaperReviewMutationResponse)
    def dashboard_paper_review_claim(paper_id: str, payload: PaperReviewClaimRequest, authorization: str | None = Header(default=None)) -> PaperReviewMutationResponse:
        authorize(authorization)
        try:
            event_id, inserted, item = store.claim_paper_review(paper_id, payload)
        except IdempotencyConflict as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return PaperReviewMutationResponse(inserted_event=inserted, event_id=event_id, item=item)

    @router.post("/api/publication-automation/{paper_id}/checklist/{item_id}", response_model=PaperReviewMutationResponse)
    @router.post("/api/paper-reviews/{paper_id}/checklist/{item_id}", response_model=PaperReviewMutationResponse)
    def dashboard_paper_review_checklist(paper_id: str, item_id: str, payload: PaperReviewChecklistUpdateRequest, authorization: str | None = Header(default=None)) -> PaperReviewMutationResponse:
        authorize(authorization)
        try:
            event_id, inserted, item = store.update_paper_review_checklist(paper_id, item_id, payload)
        except IdempotencyConflict as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return PaperReviewMutationResponse(inserted_event=inserted, event_id=event_id, item=item)

    @router.post("/api/publication-automation/{paper_id}/status", response_model=PaperReviewMutationResponse)
    @router.post("/api/paper-reviews/{paper_id}/status", response_model=PaperReviewMutationResponse)
    def dashboard_paper_review_status(paper_id: str, payload: PaperReviewStatusUpdateRequest, authorization: str | None = Header(default=None)) -> PaperReviewMutationResponse:
        authorize(authorization)
        try:
            event_id, inserted, item = store.update_paper_review_status(paper_id, payload)
        except IdempotencyConflict as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return PaperReviewMutationResponse(inserted_event=inserted, event_id=event_id, item=item)

    @router.post("/api/publication-automation/{paper_id}/approve-finalization", response_model=PaperReviewMutationResponse)
    @router.post("/api/paper-reviews/{paper_id}/approve-finalization", response_model=PaperReviewMutationResponse)
    def dashboard_paper_review_approve_finalization(paper_id: str, payload: PaperReviewApproveFinalizationRequest, authorization: str | None = Header(default=None)) -> PaperReviewMutationResponse:
        authorize(authorization)
        try:
            event_id, inserted, item = store.approve_paper_review_finalization(paper_id, payload)
        except IdempotencyConflict as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return PaperReviewMutationResponse(inserted_event=inserted, event_id=event_id, item=item)

    def _rewrite_paper_review_draft(paper_id: str, payload: PaperReviewRewriteDraftRequest) -> PaperReviewRewriteDraftResponse:
        paper = store.paper_row(paper_id)
        item = store.paper_review_row(paper_id, include_rank_reasons=True)
        if paper is None or item is None:
            raise HTTPException(status_code=404, detail="publication automation item not found")
        if str(item.get("review_status") or "") == "rejected":
            raise HTTPException(status_code=400, detail="rejected publication automation items cannot be rewritten or auto-published")
        project_id = str(paper.get("project_id") or "")
        project = store.project_row(project_id) if project_id else None
        configured_root = config.expanded_project_root.resolve()
        current_project_dir = Path(str((project or {}).get("project_dir") or "")).expanduser() if project else Path()
        use_current_dir = False
        if str(current_project_dir):
            try:
                resolved_current = current_project_dir.resolve()
                resolved_current.relative_to(configured_root)
                use_current_dir = resolved_current.exists()
            except (OSError, ValueError):
                use_current_dir = False
        artifact_root = (current_project_dir.resolve() if use_current_dir else (configured_root / project_id).resolve())
        artifact_root.mkdir(parents=True, exist_ok=True)
        source_project_dir = str((project or {}).get("project_dir") or "")
        evidence_sync = _sync_remote_project_evidence(config, project_id=project_id, artifact_root=artifact_root, source_project_dir=source_project_dir if source_project_dir and source_project_dir.startswith("/") and not use_current_dir else "", source_run_id=str(paper.get("run_id") or ""))
        if config.paper_evidence_sync_enabled and not _local_paper_evidence_present(artifact_root):
            raise HTTPException(status_code=424, detail={"message": "paper rewrite requires synced project evidence", "evidence_sync": evidence_sync})
        record = _paper_record_from_row(paper).model_copy(update={"paper_status": PaperStatus.PUBLICATION_DRAFT, "updated_at": utc_now()})
        candidate = {
            "project_id": project_id,
            "project_name": str((project or paper or item).get("project_name") or project_id),
            "project_dir": str(artifact_root),
            "run_id": record.run_id,
            "current_run_id": record.run_id,
            "notion_page_url": str((project or paper).get("notion_page_url") or ""),
            "paper_review_item": item,
            "paper": paper,
            "publication_policy": {
                "ai_generated": True,
                "operator_credit_claim": "none",
                "disclaimer": "AI-generated and AI-written from automated research artifacts; released with no personal authorship credit claimed by the operator.",
            },
        }
        try:
            writer = write_paper_artifacts(config, candidate, record, force=payload.force)
            if not use_current_dir:
                store.update_project_dir(project_id, str(artifact_root))
            store.upsert_paper(record)
            event_payload = {
                "action": "rewrite_draft",
                "requested_by": payload.requested_by,
                "force": payload.force,
                "artifact_root": str(artifact_root),
                "writer": writer,
                "evidence_sync": evidence_sync,
                "publication_policy": candidate["publication_policy"],
                "paper_paths": {
                    "draft_markdown_path": record.draft_markdown_path,
                    "draft_latex_path": record.draft_latex_path,
                    "evidence_bundle_path": record.evidence_bundle_path,
                    "claim_ledger_path": record.claim_ledger_path,
                    "manifest_path": record.manifest_path,
                },
            }
            event_id, inserted = store.append_event(idempotency_key=payload.idempotency_key, event_type="paper_review.draft_rewritten", entity_type="paper_review", entity_id=paper_id, payload=event_payload)
            finalization_event_id, finalization_inserted, finalized_item, package_path, _manifest = store.prepare_paper_review_finalization_package(
                paper_id,
                PaperReviewPrepareFinalizationRequest(
                    idempotency_key=f"{payload.idempotency_key}:automated-finalization",
                    requested_by=payload.requested_by,
                    target_label="automated-publication",
                    dry_run=False,
                ),
                require_approval=False,
            )
        except IdempotencyConflict as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        refreshed = store.paper_review_row(paper_id, include_rank_reasons=True) or finalized_item or item
        writer_with_sync = {
            **writer,
            "evidence_sync": evidence_sync,
            "automated_finalization": {
                "inserted_event": finalization_inserted,
                "event_id": finalization_event_id,
                "package_path": package_path,
                "review_status": str((refreshed or {}).get("review_status") or ""),
            },
        }
        return PaperReviewRewriteDraftResponse(inserted_event=inserted, event_id=event_id, item=refreshed, paper=store.paper_row(paper_id), writer=writer_with_sync, artifact_root=str(artifact_root))

    @router.post("/api/publication-automation/rewrite-batch", response_model=PaperReviewBulkRewriteResponse)
    @router.post("/api/paper-reviews/rewrite-batch", response_model=PaperReviewBulkRewriteResponse)
    def dashboard_paper_reviews_rewrite_batch(payload: PaperReviewBulkRewriteRequest, authorization: str | None = Header(default=None)) -> PaperReviewBulkRewriteResponse:
        authorize(authorization)
        rows = store.paper_review_rows(include_rank_reasons=True)
        if payload.review_status:
            rows = [row for row in rows if str(row.get("review_status") or "") == payload.review_status]
        else:
            rows = [row for row in rows if str(row.get("review_status") or "") not in {"finalized", "rejected"}]
        if payload.paper_status:
            rows = [row for row in rows if str(row.get("paper_status") or "") == payload.paper_status]
        if payload.skip_rewritten:
            rows = [row for row in rows if not store.event_rows(limit=1, entity_id=str(row.get("paper_id") or ""), event_type="paper_review.draft_rewritten")]
        rows = _sort_rows(_search_rows(rows, payload.search), "-rank_score")
        matched = len(rows)
        selected = rows[: payload.limit]
        out_rows: list[dict[str, Any]] = []
        if payload.dry_run:
            for row in selected:
                out_rows.append({"paper_id": row.get("paper_id"), "project_name": row.get("project_name"), "action": "would_rewrite"})
            return PaperReviewBulkRewriteResponse(dry_run=True, matched=matched, processed=len(selected), rewritten=0, failed=0, rows=out_rows)
        rewritten = 0
        failed = 0
        for index, row in enumerate(selected, start=1):
            pid = str(row.get("paper_id") or "")
            try:
                result = _rewrite_paper_review_draft(pid, PaperReviewRewriteDraftRequest(idempotency_key=f"{payload.idempotency_key}:{index}:{pid}", requested_by=payload.requested_by, force=payload.force))
                rewritten += 1
                out_rows.append({"paper_id": pid, "project_name": row.get("project_name"), "ok": True, "provider": result.writer.get("provider"), "model": result.writer.get("model"), "evidence_sync": result.writer.get("evidence_sync"), "artifact_root": result.artifact_root})
            except HTTPException as exc:
                failed += 1
                out_rows.append({"paper_id": pid, "project_name": row.get("project_name"), "ok": False, "error": exc.detail})
            except Exception as exc:  # pragma: no cover - defensive for live batch operations
                failed += 1
                out_rows.append({"paper_id": pid, "project_name": row.get("project_name"), "ok": False, "error": f"{type(exc).__name__}: {exc}"})
        return PaperReviewBulkRewriteResponse(dry_run=False, matched=matched, processed=len(selected), rewritten=rewritten, failed=failed, rows=out_rows)

    @router.post("/api/publication-automation/{paper_id}/rewrite-draft", response_model=PaperReviewRewriteDraftResponse)
    @router.post("/api/paper-reviews/{paper_id}/rewrite-draft", response_model=PaperReviewRewriteDraftResponse)
    def dashboard_paper_review_rewrite_draft(paper_id: str, payload: PaperReviewRewriteDraftRequest, authorization: str | None = Header(default=None)) -> PaperReviewRewriteDraftResponse:
        authorize(authorization)
        return _rewrite_paper_review_draft(paper_id, payload)

    @router.post("/api/publication-automation/{paper_id}/prepare-finalization-package", response_model=PaperReviewFinalizationPackageResponse)
    @router.post("/api/paper-reviews/{paper_id}/prepare-finalization-package", response_model=PaperReviewFinalizationPackageResponse)
    def dashboard_paper_review_prepare_finalization_package(paper_id: str, payload: PaperReviewPrepareFinalizationRequest, authorization: str | None = Header(default=None)) -> PaperReviewFinalizationPackageResponse:
        authorize(authorization)
        try:
            event_id, inserted, item, package_path, manifest = store.prepare_paper_review_finalization_package(paper_id, payload, require_approval=False)
        except IdempotencyConflict as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return PaperReviewFinalizationPackageResponse(dry_run=payload.dry_run, inserted_event=inserted, event_id=event_id, item=item, package_path=package_path, manifest=manifest)

    @router.get("/api/papers", response_model=DashboardPapersResponse)
    def dashboard_papers(
        authorization: str | None = Header(default=None),
        page: int = Query(default=1, ge=1),
        page_size: int = Query(default=50, ge=1, le=500),
        search: str = "",
        status: str = "",
        sort: str = "-updated_at",
    ) -> DashboardPapersResponse:
        authorize(authorization)
        rows = store.paper_rows()
        all_counts = _paper_counts(rows)
        if status:
            rows = [row for row in rows if str(row.get("paper_status") or "") == status]
        rows = _sort_rows(_search_rows(rows, search), sort)
        page_rows, safe_page, safe_size = _paginate(rows, page=page, page_size=page_size)
        for row in page_rows:
            row["links"] = {
                "paper": f"/control/api/papers/{row.get('paper_id') or ''}",
                "project": f"/control/api/projects/{row.get('project_id') or ''}",
                "run": f"/control/api/runs/{row.get('run_id') or ''}" if row.get("run_id") else "",
            }
        return DashboardPapersResponse(
            page=DashboardPageMeta(page=safe_page, page_size=safe_size, total=len(rows), returned=len(page_rows), queue="papers", filters={"search": search, "status": status}, sort=sort),
            counts=all_counts,
            rows=page_rows,
            source_freshness=_db_freshness("canonical paper queue read model"),
            conflicts=[],
        )

    def _resolve_paper_artifact(paper: dict[str, Any], field: str) -> Path:
        allowed = {"draft_markdown_path", "draft_latex_path", "evidence_bundle_path", "claim_ledger_path", "manifest_path"}
        if field not in allowed:
            raise HTTPException(status_code=404, detail="unknown paper artifact field")
        raw_path = str(paper.get(field) or "").strip()
        if not raw_path:
            raise HTTPException(status_code=404, detail=f"paper artifact path is empty: {field}")
        project_dir = Path(str(paper.get("project_dir") or "")).expanduser() if str(paper.get("project_dir") or "").strip() else None
        if project_dir is not None and not project_dir.is_absolute():
            project_dir = config.expanded_project_root / project_dir
        path = Path(raw_path).expanduser()
        resolved = path if path.is_absolute() else ((project_dir / path) if project_dir else path)
        resolved = resolved.resolve()
        if project_dir is not None:
            try:
                resolved.relative_to(project_dir.resolve())
            except ValueError as exc:
                raise HTTPException(status_code=400, detail="paper artifact path escapes project directory") from exc
        if not resolved.exists() or not resolved.is_file():
            raise HTTPException(status_code=404, detail=f"paper artifact is not readable: {field}")
        return resolved

    @router.get("/api/papers/{paper_id}/artifact/{field}")
    def dashboard_paper_artifact(paper_id: str, field: str, authorization: str | None = Header(default=None)) -> dict[str, Any]:
        authorize(authorization)
        paper = store.paper_row(paper_id)
        if paper is None:
            raise HTTPException(status_code=404, detail="paper not found")
        path = _resolve_paper_artifact(paper, field)
        max_bytes = 1_000_000
        data = path.read_bytes()
        truncated = len(data) > max_bytes
        if truncated:
            data = data[:max_bytes]
        return {
            "ok": True,
            "paper_id": paper_id,
            "project_id": str(paper.get("project_id") or ""),
            "project_name": str(paper.get("project_name") or ""),
            "field": field,
            "path": str(paper.get(field) or ""),
            "absolute_path": str(path),
            "size_bytes": path.stat().st_size,
            "truncated": truncated,
            "content": data.decode("utf-8", errors="replace"),
        }

    @router.get("/api/papers/{paper_id}", response_model=DashboardPaperDetailResponse)
    def dashboard_paper(paper_id: str, authorization: str | None = Header(default=None)) -> DashboardPaperDetailResponse:
        authorize(authorization)
        paper = store.paper_row(paper_id)
        if paper is None:
            raise HTTPException(status_code=404, detail="paper not found")
        project_id = str(paper.get("project_id") or "")
        run_id = str(paper.get("run_id") or "")
        missing = [name for name in ("draft_markdown_path", "draft_latex_path", "evidence_bundle_path", "claim_ledger_path", "manifest_path") if not paper.get(name)]
        warnings = [DashboardFinding(severity="warn", source="control_plane_db", authority="paper artifact record", message=f"paper is missing artifact path(s): {', '.join(missing)}", suggested_action="generate or reconcile paper artifacts")] if missing else []
        return DashboardPaperDetailResponse(
            paper_id=paper_id,
            paper=paper,
            project=store.project_row(project_id) if project_id else None,
            run=store.run_row(run_id) if run_id else None,
            events=store.event_rows(limit=100, entity_id=paper_id) + (store.event_rows(limit=50, entity_id=project_id) if project_id else []),
            source_freshness=_db_freshness("paper/project/run aggregate"),
            warnings=warnings,
            conflicts=[],
        )

    @router.get("/api/events", response_model=DashboardEventsResponse)
    def dashboard_events(
        authorization: str | None = Header(default=None),
        page: int = Query(default=1, ge=1),
        page_size: int = Query(default=100, ge=1, le=500),
        entity_type: str = "",
        entity_id: str = "",
        event_type: str = "",
        search: str = "",
    ) -> DashboardEventsResponse:
        authorize(authorization)
        rows = store.event_rows(limit=1000, entity_type=entity_type, entity_id=entity_id, event_type=event_type, search=search)
        page_rows, safe_page, safe_size = _paginate(rows, page=page, page_size=page_size)
        return DashboardEventsResponse(
            page=DashboardPageMeta(page=safe_page, page_size=safe_size, total=len(rows), returned=len(page_rows), queue="events", filters={"entity_type": entity_type, "entity_id": entity_id, "event_type": event_type, "search": search}, sort="-event_id"),
            rows=page_rows,
            source_freshness=_db_freshness("append-only control event log"),
            conflicts=[],
        )

    def _dashboard_ideas_intake_response(*, legacy_notion_alias: bool = False, page_size: int = 50, include_latest_payload: bool = False) -> DashboardIntakeResponse:
        intake_reader = getattr(store, "dashboard_ideas_intake_parts", None)
        if callable(intake_reader):
            intake_parts = intake_reader(page_size=page_size, include_latest_payload=include_latest_payload)
            latest = intake_parts.get("latest_sync")
            projection = intake_parts.get("queued_projection") or []
            recent = intake_parts.get("recent_events") or []
            projection_counts = intake_parts.get("projection_counts") or {}
            freshness = {
                **_db_freshness("Supabase-native ideas workbench"),
                "idea_intake": _freshness_for_observation("idea_intake", "latest Supabase-native ideas intake observation", latest),
            }
        else:
            latest = store.latest_dashboard_observation(source="idea_intake") if include_latest_payload else _latest_dashboard_observation_metadata("idea_intake")
            if hasattr(store, "idea_workbench_projection"):
                try:
                    projection = store.idea_workbench_projection(limit=page_size)
                except TypeError:
                    projection = store.idea_workbench_projection()[:page_size]
            else:
                projection = store.queue_notion_projection()[:page_size]
            recent = store.event_rows(limit=20, event_type="ideas.intake")
            if not recent:
                recent = store.event_rows(limit=20, event_type="notion.intake")
            projection_counts = store.status_counts()
            freshness = _intake_freshness()
        skipped_reasons: dict[str, int] = {}
        if latest:
            payload = latest.payload or {}
            if payload.get("skipped_reasons"):
                skipped_reasons = {str(reason): int(count or 0) for reason, count in (payload.get("skipped_reasons") or {}).items()}
            else:
                for item in payload.get("skipped_rows") or []:
                    reason = str(item.get("reason") or "unknown") if isinstance(item, dict) else "unknown"
                    skipped_reasons[reason] = skipped_reasons.get(reason, 0) + 1
            if not include_latest_payload:
                latest = latest.model_copy(update={"payload": {"payload_omitted": True, "skipped_row_count": payload.get("skipped_row_count", len(payload.get("skipped_rows") or []))}})
        warnings = []
        if not projection:
            warnings.append(DashboardFinding(severity="warn", source="idea_intake", authority="Supabase-native ideas workbench", message="No Supabase-native ideas are visible", observed_at=utc_now(), suggested_action="load ideas into Supabase before resuming the queue"))
        return DashboardIntakeResponse(
            source="control_api_intake_notion" if legacy_notion_alias else "control_api_intake_ideas",
            authority="Legacy Notion projection alias; Supabase ideas are canonical" if legacy_notion_alias else "Supabase-native ideas workbench; Notion is provenance only",
            latest_sync=latest,
            projection_counts=projection_counts,
            queued_projection=projection,
            skipped_reasons=skipped_reasons,
            recent_events=recent,
            source_freshness=freshness,
            warnings=warnings,
            conflicts=[],
        )

    @router.get("/api/intake/ideas", response_model=DashboardIntakeResponse)
    def dashboard_ideas_intake(
        authorization: str | None = Header(default=None),
        page_size: int = Query(default=50, ge=1, le=200),
        include_latest_payload: bool = Query(default=False),
    ) -> DashboardIntakeResponse:
        authorize(authorization)
        return _dashboard_ideas_intake_response(page_size=page_size, include_latest_payload=include_latest_payload)

    @router.get("/api/research/facility")
    def dashboard_research_facility(
        authorization: str | None = Header(default=None),
        page_size: int = Query(default=50, ge=1, le=200),
    ) -> dict[str, Any]:
        authorize(authorization)
        rows = store.research_facility_workbench_projection(limit=page_size) if hasattr(store, "research_facility_workbench_projection") else []
        counts = (
            store.research_facility_workbench_counts()
            if hasattr(store, "research_facility_workbench_counts")
            else {}
        )
        if not counts:
            for row in rows:
                status = str(row.get("status") or "unknown")
                counts[status] = counts.get(status, 0) + 1
        return {
            "ok": True,
            "authority": "Research Facility ledgers: sources, candidates, admissions, lineage",
            "rows": rows,
            "counts": counts,
            "page": {
                "page_size": page_size,
                "returned": len(rows),
                "counts_scope": "all_rows" if hasattr(store, "research_facility_workbench_counts") else "returned_rows",
            },
        }

    @router.post("/api/research/generate-batch")
    def dashboard_research_generate_batch(
        payload: dict[str, Any] | None = Body(default=None),
        authorization: str | None = Header(default=None),
    ) -> dict[str, Any]:
        authorize(authorization)
        from argparse import Namespace
        from scripts import research_facility, research_facility_scan

        body = payload or {}
        dry_run = bool(body.get("dry_run", True))
        max_candidates = max(1, min(int(body.get("max_candidates") or 3), 10))
        requested_by = str(body.get("requested_by") or "dashboard")[:80]
        source_specs = [
            {
                "title": "Provider-budget-aware idea generation scheduler",
                "summary": "Test whether local idea generation should check provider quota, rolling budget, and queue state before spending inference requests on new research candidates.",
                "url": "enoch://research-facility/smoke/provider-budget-scheduler",
            },
            {
                "title": "Counterexample-first candidate admission gate",
                "summary": "Test whether candidate ideas should carry explicit falsification probes before admission, reducing shallow incremental work and preventing positive-only framing.",
                "url": "enoch://research-facility/smoke/counterexample-admission-gate",
            },
            {
                "title": "Queue-safe candidate promotion ledger",
                "summary": "Test whether generated candidates can be promoted to queued projects only through an auditable ledger that preserves dry-run evidence and prevents accidental dispatch.",
                "url": "enoch://research-facility/smoke/queue-safe-promotion-ledger",
            },
        ][:max_candidates]
        records = [
            research_facility_scan.SourceRecord.from_parts(
                source_kind="internal_generated",
                title=spec["title"],
                url=spec["url"],
                summary=spec["summary"],
                payload_json={"smoke_test": True, "requested_by": requested_by},
            )
            for spec in source_specs
        ]
        candidates = [
            research_facility_scan.candidate_from_source(
                record,
                default_machine=os.environ.get("ENOCH_RESEARCH_DEFAULT_MACHINE", "192.168.1.77"),
                default_model=os.environ.get("ENOCH_RESEARCH_DEFAULT_MODEL", "gpt-5.5"),
                default_sandbox=os.environ.get("ENOCH_RESEARCH_DEFAULT_SANDBOX", "danger-full-access"),
            )
            for record in records
        ]
        plans = research_facility.plan_candidates(
            candidates,
            Namespace(
                default_machine=os.environ.get("ENOCH_RESEARCH_DEFAULT_MACHINE", "192.168.1.77"),
                default_model=os.environ.get("ENOCH_RESEARCH_DEFAULT_MODEL", "gpt-5.5"),
                default_sandbox=os.environ.get("ENOCH_RESEARCH_DEFAULT_SANDBOX", "danger-full-access"),
                admit_threshold=float(body.get("admit_threshold") or 72.0),
                review_threshold=float(body.get("review_threshold") or 58.0),
                history=[],
            ),
        )
        plan_json = [plan.to_json() for plan in plans]
        response = {
            "ok": True,
            "action": "dry_run_generate_candidates" if dry_run else "generate_candidates",
            "dry_run": dry_run,
            "queue_admitted": False,
            "candidate_count": len(plans),
            "admitted_count": sum(1 for plan in plans if plan.admission_decision == "admitted"),
            "needs_review_count": sum(1 for plan in plans if plan.admission_decision == "needs_review"),
            "rejected_count": sum(1 for plan in plans if plan.admission_decision == "rejected"),
            "queued_count": 0,
            "plans": plan_json,
        }
        if dry_run:
            return response
        if not hasattr(store, "record_research_facility_plans"):
            raise HTTPException(status_code=501, detail="Research Facility ledger writes require the Supabase control-plane store")
        response["ledger_result"] = store.record_research_facility_plans(plans, requested_by=requested_by, queue_admitted=False)
        return response

    @router.post("/api/research/generate-provider-batch")
    def dashboard_research_generate_provider_batch(
        payload: dict[str, Any] | None = Body(default=None),
        authorization: str | None = Header(default=None),
    ) -> dict[str, Any]:
        authorize(authorization)
        from argparse import Namespace
        from scripts import research_facility, research_provider_budget, research_provider_generate

        body = payload or {}
        dry_run = bool(body.get("dry_run", True))
        max_candidates = max(1, min(int(body.get("max_candidates") or 2), 5))
        requested_by = str(body.get("requested_by") or "dashboard")[:80]
        provider_base_url = os.environ.get("ENOCH_RESEARCH_PROVIDER_BASE_URL", "https://synthetic.int.exe.xyz").rstrip("/")
        provider_openai_base_url = os.environ.get("ENOCH_RESEARCH_PROVIDER_OPENAI_BASE_URL", f"{provider_base_url}/openai/v1").rstrip("/")
        provider_model = str(body.get("model") or os.environ.get("ENOCH_RESEARCH_PROVIDER_MODEL") or "hf:zai-org/GLM-5.1").strip()
        topic = str(body.get("topic") or "").strip()
        temperature = max(0.0, min(float(body.get("temperature") or 0.8), 1.5))
        seed = str(body.get("seed") or utc_now()).strip()
        estimated_requests = 1
        reserve_requests = max(1, int(body.get("reserve_requests") or 2))
        budget_timeout = max(1, min(int(body.get("budget_timeout") or 20), 60))
        generation_timeout = max(10, min(int(body.get("generation_timeout") or 180), 300))
        generation_max_tokens = max(1000, min(int(body.get("generation_max_tokens") or os.environ.get("ENOCH_RESEARCH_PROVIDER_MAX_TOKENS") or 8000), 16000))
        generation_attempts = max(1, min(int(body.get("generation_attempts") or os.environ.get("ENOCH_RESEARCH_PROVIDER_ATTEMPTS") or 2), 3))
        try:
            quota_payload = research_provider_budget.fetch_json(f"{provider_base_url}/v2/quotas", api_key="", timeout=budget_timeout)
            budget = research_provider_budget.synthetic_budget_status(
                quota_payload,
                min_remaining_credits=float(body.get("min_remaining_credits") or 5.0),
                min_rolling_remaining=int(body.get("min_rolling_remaining") or 10),
                estimated_requests=estimated_requests,
                reserve_requests=reserve_requests,
            )
        except Exception as exc:  # noqa: BLE001 - generation must fail closed if budget cannot be checked
            budget = {
                "ok": False,
                "provider": "synthetic",
                "checked_at": utc_now(),
                "estimated_requests": estimated_requests,
                "reserve_requests": reserve_requests,
                "failures": [f"provider budget check failed: {exc}"],
            }
        safe_budget_keys = {
            "ok",
            "provider",
            "checked_at",
            "estimated_requests",
            "reserve_requests",
            "remaining_credits",
            "min_remaining_credits",
            "rolling_remaining",
            "rolling_max",
            "rolling_limited",
            "rolling_next_tick_at",
            "weekly_next_regen_at",
            "weekly_next_regen_credits",
            "subscription_remaining",
            "subscription_renews_at",
            "failures",
        }
        safe_budget = {key: budget.get(key) for key in safe_budget_keys if key in budget}
        response: dict[str, Any] = {
            "ok": bool(budget.get("ok")),
            "action": "dry_run_provider_generate_candidates" if dry_run else "provider_generate_candidates",
            "dry_run": dry_run,
            "queue_admitted": False,
            "dispatch_started": False,
            "provider": "synthetic.new",
            "provider_model": provider_model,
            "max_candidates": max_candidates,
            "topic": topic,
            "temperature": temperature,
            "generation_max_tokens": generation_max_tokens,
            "generation_attempts": generation_attempts,
            "seed": seed,
            "budget": safe_budget,
            "queued_count": 0,
        }
        if not budget.get("ok"):
            response["action"] = "provider_generation_blocked"
            response["reason"] = "; ".join(str(item) for item in budget.get("failures") or ["provider budget unavailable"])
            return response
        if dry_run:
            response["reason"] = "provider budget passed; no provider request spent and no ledger rows written"
            return response
        if not hasattr(store, "record_research_facility_plans"):
            raise HTTPException(status_code=501, detail="Research Facility ledger writes require the Supabase control-plane store")
        try:
            generated = research_provider_generate.generate_provider_candidates(
                base_url=provider_openai_base_url,
                model=provider_model,
                api_key="",
                max_candidates=max_candidates,
                topic=topic,
                temperature=temperature,
                seed=seed,
                timeout=generation_timeout,
                max_tokens=generation_max_tokens,
                attempts=generation_attempts,
                default_machine=os.environ.get("ENOCH_RESEARCH_DEFAULT_MACHINE", "192.168.1.77"),
                default_model=os.environ.get("ENOCH_RESEARCH_DEFAULT_MODEL", "gpt-5.5"),
                default_sandbox=os.environ.get("ENOCH_RESEARCH_DEFAULT_SANDBOX", "danger-full-access"),
            )
        except Exception as exc:  # noqa: BLE001 - provider generation must fail closed without ledger writes
            response.update({
                "ok": False,
                "action": "provider_generation_failed",
                "reason": f"provider generation failed before ledger write: {exc}",
                "candidate_count": 0,
                "admitted_count": 0,
                "needs_review_count": 0,
                "rejected_count": 0,
            })
            return response
        generated_candidates = generated.get("candidates") or []
        if not generated_candidates:
            response.update({
                "ok": False,
                "action": "provider_generation_failed",
                "reason": "provider generation returned 0 usable candidates; no ledger rows written",
                "candidate_count": 0,
                "admitted_count": 0,
                "needs_review_count": 0,
                "rejected_count": 0,
                "provider_response_id": generated.get("provider_response_id", ""),
            })
            return response
        plans = research_facility.plan_candidates(
            generated_candidates,
            Namespace(
                default_machine=os.environ.get("ENOCH_RESEARCH_DEFAULT_MACHINE", "192.168.1.77"),
                default_model=os.environ.get("ENOCH_RESEARCH_DEFAULT_MODEL", "gpt-5.5"),
                default_sandbox=os.environ.get("ENOCH_RESEARCH_DEFAULT_SANDBOX", "danger-full-access"),
                admit_threshold=float(body.get("admit_threshold") or 72.0),
                review_threshold=float(body.get("review_threshold") or 58.0),
                history=[],
            ),
        )
        response["candidate_count"] = len(plans)
        response["admitted_count"] = sum(1 for plan in plans if plan.admission_decision == "admitted")
        response["needs_review_count"] = sum(1 for plan in plans if plan.admission_decision == "needs_review")
        response["rejected_count"] = sum(1 for plan in plans if plan.admission_decision == "rejected")
        response["provider_response_id"] = generated.get("provider_response_id", "")
        response["attempts_used"] = generated.get("attempts_used", 1)
        response["plans"] = [plan.to_json() for plan in plans]
        response["ledger_result"] = store.record_research_facility_plans(plans, requested_by=requested_by, queue_admitted=False)
        return response

    @router.post("/api/research/run-cycle")
    def dashboard_research_run_cycle(
        payload: dict[str, Any] | None = Body(default=None),
        authorization: str | None = Header(default=None),
    ) -> dict[str, Any]:
        """Run one bounded Research Facility cycle.

        This is intentionally a small automation step:
        provider quota check -> optional generation/admission ledgers -> explicit
        promotion of admitted candidates -> optional single dispatch -> optional
        positive-gated paper draft/finalization. It never unpauses the broad
        queue and every mutating stage is bounded by per-run limits.
        """

        authorize(authorization)
        from argparse import Namespace
        from scripts import research_facility, research_provider_budget, research_provider_generate

        if not hasattr(store, "research_facility_workbench_projection") or not hasattr(store, "record_research_facility_plans") or not hasattr(store, "promote_research_candidate"):
            raise HTTPException(status_code=501, detail="Research Facility run-cycle requires the Supabase control-plane store")

        body = payload or {}
        dry_run = bool(body.get("dry_run", True))
        enabled = bool(body.get("enabled", False))
        requested_by = str(body.get("requested_by") or "dashboard")[:80]
        def bounded_int(name: str, default: int, lower: int, upper: int) -> int:
            value = body.get(name)
            if value is None:
                value = default
            return max(lower, min(int(value), upper))
        allowed_models = body.get("allowed_models") if isinstance(body.get("allowed_models"), list) else ["hf:moonshotai/Kimi-K2.6", "hf:zai-org/GLM-5.1"]
        provider_model = str(body.get("model") or os.environ.get("ENOCH_RESEARCH_PROVIDER_MODEL") or "hf:zai-org/GLM-5.1").strip()
        if provider_model not in allowed_models:
            return {
                "ok": False,
                "action": "research_cycle_blocked",
                "dry_run": dry_run,
                "reason": f"provider model {provider_model!r} is not in the allowed model list",
                "allowed_models": allowed_models,
                "queue_admitted": False,
                "dispatch_started": False,
            }
        max_provider_requests = bounded_int("max_provider_requests_per_run", 1, 0, 3)
        max_promotions = bounded_int("max_promotions_per_run", 1, 0, 3)
        max_dispatches = bounded_int("max_dispatches_per_run", 0, 0, 1)
        max_paper_drafts = bounded_int("max_paper_drafts_per_run", 0, 0, 1)
        max_publication_rewrites = bounded_int("max_publication_rewrites_per_run", 0, 0, 1)
        wait_for_completion = bool(body.get("wait_for_completion", False))
        max_wait_seconds = bounded_int("max_wait_seconds", 0, 0, 1800)
        poll_interval_seconds = bounded_int("poll_interval_seconds", 10, 2, 60)
        min_admission_score = max(0.0, min(float(body.get("min_admission_score") or body.get("admit_threshold") or 72.0), 100.0))
        max_candidates = max(1, min(int(body.get("max_candidates") or 2), 5))
        topic = str(body.get("topic") or "").strip()
        temperature = max(0.0, min(float(body.get("temperature") or 0.6), 1.5))
        seed = str(body.get("seed") or utc_now()).strip()
        provider_base_url = os.environ.get("ENOCH_RESEARCH_PROVIDER_BASE_URL", "https://synthetic.int.exe.xyz").rstrip("/")
        provider_openai_base_url = os.environ.get("ENOCH_RESEARCH_PROVIDER_OPENAI_BASE_URL", f"{provider_base_url}/openai/v1").rstrip("/")
        generation_timeout = max(10, min(int(body.get("generation_timeout") or 240), 300))
        generation_max_tokens = max(1000, min(int(body.get("generation_max_tokens") or os.environ.get("ENOCH_RESEARCH_PROVIDER_MAX_TOKENS") or 8000), 16000))
        generation_attempts = max(1, min(int(body.get("generation_attempts") or os.environ.get("ENOCH_RESEARCH_PROVIDER_ATTEMPTS") or 2), 3))

        active = store.active_items()
        counts = store.status_counts()
        blocked_count = int(counts.get("blocked") or 0)
        stop_reasons: list[str] = []
        if active:
            stop_reasons.append("active worker lane already exists")
        if blocked_count and bool(body.get("stop_if_dashboard_attention", True)):
            stop_reasons.append(f"{blocked_count} blocked item(s) need attention")
        if not dry_run and not enabled:
            stop_reasons.append("live run-cycle requires enabled=true")

        estimated_requests = max_provider_requests
        budget: dict[str, Any]
        try:
            quota_payload = research_provider_budget.fetch_json(f"{provider_base_url}/v2/quotas", api_key="", timeout=max(1, min(int(body.get("budget_timeout") or 20), 60)))
            budget = research_provider_budget.synthetic_budget_status(
                quota_payload,
                min_remaining_credits=float(body.get("min_remaining_credits") or 5.0),
                min_rolling_remaining=int(body.get("min_rolling_remaining") or 10),
                estimated_requests=estimated_requests,
                reserve_requests=max(1, int(body.get("reserve_requests") or 2)),
            )
        except Exception as exc:  # noqa: BLE001 - fail closed if budget cannot be checked
            budget = {
                "ok": False,
                "provider": "synthetic",
                "checked_at": utc_now(),
                "estimated_requests": estimated_requests,
                "reserve_requests": max(1, int(body.get("reserve_requests") or 2)),
                "failures": [f"provider budget check failed: {exc}"],
            }
        if not budget.get("ok") and max_provider_requests:
            stop_reasons.append("; ".join(str(item) for item in budget.get("failures") or ["provider budget unavailable"]))

        def promotable_rows() -> list[dict[str, Any]]:
            rows = list(store.research_facility_workbench_projection(limit=100))
            candidates = [
                row for row in rows
                if str(row.get("admission_decision") or "") == "admitted"
                and not str(row.get("admitted_idea_id") or "").strip()
                and float(row.get("total_score") or 0) >= min_admission_score
            ]
            return sorted(candidates, key=lambda r: float(r.get("total_score") or 0), reverse=True)

        initial_promotable = promotable_rows()
        response: dict[str, Any] = {
            "ok": not stop_reasons,
            "action": "dry_run_research_cycle" if dry_run else "research_cycle",
            "dry_run": dry_run,
            "enabled": enabled,
            "queue_admitted": False,
            "dispatch_started": False,
            "provider": "synthetic.new",
            "provider_model": provider_model,
            "allowed_models": allowed_models,
            "policy": {
                "max_provider_requests_per_run": max_provider_requests,
                "max_promotions_per_run": max_promotions,
                "max_dispatches_per_run": max_dispatches,
                "max_paper_drafts_per_run": max_paper_drafts,
                "max_publication_rewrites_per_run": max_publication_rewrites,
                "min_admission_score": min_admission_score,
                "require_budget_ok": True,
                "stop_if_queue_active": True,
                "stop_if_dashboard_attention": bool(body.get("stop_if_dashboard_attention", True)),
                "wait_for_completion": wait_for_completion,
                "max_wait_seconds": max_wait_seconds,
            },
            "budget": {key: budget.get(key) for key in {
                "ok", "provider", "checked_at", "estimated_requests", "reserve_requests", "remaining_credits",
                "min_remaining_credits", "rolling_remaining", "rolling_max", "rolling_limited",
                "rolling_next_tick_at", "weekly_next_regen_at", "weekly_next_regen_credits",
                "subscription_remaining", "subscription_renews_at", "failures",
            } if key in budget},
            "initial_promotable_count": len(initial_promotable),
            "planned_promotions": [row.get("candidate_id") for row in initial_promotable[:max_promotions]],
            "generated_count": 0,
            "promoted_count": 0,
            "dispatched_count": 0,
            "queued_count": 0,
            "stages": [],
        }
        flags = store.flags() if hasattr(store, "flags") else None
        queue_paused = bool(getattr(flags, "queue_paused", False))
        if not dry_run and queue_paused:
            guardrail = "research autopilot is active but broad queue is paused"
            response.setdefault("guardrails", []).append(guardrail)
            if hasattr(store, "append_event"):
                store.append_event(
                    idempotency_key=f"research-guardrail:queue-paused:{requested_by}:{utc_now()}",
                    event_type="research.guardrail.queue_paused",
                    entity_type="research",
                    entity_id="run-cycle",
                    payload={"message": guardrail, "queue_paused": True, "dry_run": dry_run, "requested_by": requested_by},
                )

        if stop_reasons:
            response["reason"] = "; ".join(stop_reasons)
            if hasattr(store, "append_event"):
                store.append_event(
                    idempotency_key=f"research-cycle:{'dry' if dry_run else 'live'}:{requested_by}:{utc_now()}",
                    event_type="research.run_cycle.blocked",
                    entity_type="research",
                    entity_id="run-cycle",
                    payload=jsonable_encoder(response),
                )
            return response
        if dry_run:
            response["reason"] = "dry-run only; provider was not called and no ledgers, queue rows, dispatches, or papers were written"
            response["would_generate"] = max_provider_requests > 0
            response["would_promote_up_to"] = max_promotions
            response["would_dispatch_up_to"] = max_dispatches
            response["would_wait_for_completion"] = wait_for_completion and max_wait_seconds > 0
            response["would_draft_papers_up_to"] = max_paper_drafts
            response["would_finalize_papers_up_to"] = max_publication_rewrites
            if hasattr(store, "append_event"):
                store.append_event(
                    idempotency_key=f"research-cycle:dry:{requested_by}:{utc_now()}",
                    event_type="research.run_cycle.dry_run",
                    entity_type="research",
                    entity_id="run-cycle",
                    payload=jsonable_encoder(response),
                )
            return response

        generated_plans = []
        if max_provider_requests:
            try:
                generated = research_provider_generate.generate_provider_candidates(
                    base_url=provider_openai_base_url,
                    model=provider_model,
                    api_key="",
                    max_candidates=max_candidates,
                    topic=topic,
                    temperature=temperature,
                    seed=seed,
                    timeout=generation_timeout,
                    max_tokens=generation_max_tokens,
                    attempts=generation_attempts,
                    default_machine=os.environ.get("ENOCH_RESEARCH_DEFAULT_MACHINE", "192.168.1.77"),
                    default_model=os.environ.get("ENOCH_RESEARCH_DEFAULT_MODEL", "gpt-5.5"),
                    default_sandbox=os.environ.get("ENOCH_RESEARCH_DEFAULT_SANDBOX", "danger-full-access"),
                )
                generated_plans = research_facility.plan_candidates(
                    generated.get("candidates") or [],
                    Namespace(
                        default_machine=os.environ.get("ENOCH_RESEARCH_DEFAULT_MACHINE", "192.168.1.77"),
                        default_model=os.environ.get("ENOCH_RESEARCH_DEFAULT_MODEL", "gpt-5.5"),
                        default_sandbox=os.environ.get("ENOCH_RESEARCH_DEFAULT_SANDBOX", "danger-full-access"),
                        admit_threshold=min_admission_score,
                        review_threshold=float(body.get("review_threshold") or 58.0),
                        history=[],
                    ),
                )
                ledger_result = store.record_research_facility_plans(generated_plans, requested_by=requested_by, queue_admitted=False)
                response["generated_count"] = len(generated_plans)
                response["provider_response_id"] = generated.get("provider_response_id", "")
                response["attempts_used"] = generated.get("attempts_used", 1)
                response["ledger_result"] = ledger_result
                response["stages"].append({"stage": "provider_generation", "ok": True, "candidate_count": len(generated_plans), "ledger_result": ledger_result})
            except Exception as exc:  # noqa: BLE001 - provider output is external and must not break long-haul ticks
                warning = f"provider generation skipped: {exc}"
                response.setdefault("warnings", []).append(warning)
                response["stages"].append({"stage": "provider_generation", "ok": False, "reason": warning})

        promoted: list[dict[str, Any]] = []
        for row in promotable_rows()[:max_promotions]:
            result = store.promote_research_candidate(str(row.get("candidate_id")), requested_by=requested_by, dry_run=False)
            promoted.append(result)
        response["promotions"] = promoted
        response["promoted_count"] = sum(1 for item in promoted if item.get("ok") and not item.get("already_promoted"))
        response["queued_count"] = sum(int(item.get("queued_count") or 0) for item in promoted)
        response["stages"].append({"stage": "promotion", "ok": True, "promoted_count": response["promoted_count"], "queued_count": response["queued_count"]})

        if max_dispatches and promoted:
            active_after_promotion = store.active_items()
            if active_after_promotion:
                response["stages"].append({"stage": "dispatch", "ok": False, "reason": "active worker lane exists after promotion"})
            else:
                project_id = str(promoted[0].get("idea_id") or promoted[0].get("candidate_id") or "").strip()
                candidate = store.queue_row(project_id)
                if candidate and str(candidate.get("status") or "") == "queued":
                    try:
                        live, event_id, updated_candidate = _live_dispatch(candidate, requested_by, force_preflight=True, allow_paused=True)
                    except HTTPException as exc:
                        if int(exc.status_code) != 409:
                            raise
                        response["dispatch"] = {
                            "event_id": None,
                            "candidate": candidate,
                            "live": None,
                            "backpressure": True,
                            "detail": jsonable_encoder(exc.detail),
                        }
                        response["stages"].append({
                            "stage": "dispatch",
                            "ok": True,
                            "action": "dispatch_backpressure",
                            "project_id": project_id,
                            "reason": "dispatch conflict/backpressure; queued work remains safe for the queue pump or next tick",
                            "detail": jsonable_encoder(exc.detail),
                        })
                    else:
                        response["dispatch_started"] = True
                        response["dispatched_count"] = 1
                        response["dispatch"] = {"event_id": event_id, "candidate": updated_candidate, "live": live}
                        response["stages"].append({"stage": "dispatch", "ok": True, "project_id": project_id, "event_id": event_id})
                else:
                    response["stages"].append({"stage": "dispatch", "ok": False, "reason": "promoted candidate was not queued", "project_id": project_id})

        wait_result = {"action": "skipped", "reason": "wait_for_completion disabled"}
        if response.get("dispatch_started") and wait_for_completion:
            if max_wait_seconds <= 0:
                wait_result = {"action": "skipped", "reason": "max_wait_seconds is 0"}
            else:
                dispatched_project_id = str((response.get("dispatch", {}).get("candidate") or {}).get("project_id") or "")
                deadline = time.monotonic() + max_wait_seconds
                polls = 0
                last_status = ""
                while True:
                    polls += 1
                    row = store.queue_row(dispatched_project_id) if dispatched_project_id else None
                    active_now = store.active_items()
                    last_status = str((row or {}).get("status") or "")
                    if not active_now and last_status not in {"dispatching", "running", "awaiting_wake", "wake_received", "reconciling"}:
                        wait_result = {
                            "action": "completed",
                            "project_id": dispatched_project_id,
                            "status": last_status,
                            "polls": polls,
                        }
                        break
                    if time.monotonic() >= deadline:
                        wait_result = {
                            "action": "timeout",
                            "project_id": dispatched_project_id,
                            "status": last_status,
                            "active_count": len(active_now),
                            "polls": polls,
                        }
                        break
                    time.sleep(poll_interval_seconds)
            response["wait"] = wait_result
            response["stages"].append({"stage": "wait_for_completion", **wait_result})

        drafted_papers: list[dict[str, Any]] = []
        finalized_papers: list[dict[str, Any]] = []
        if max_paper_drafts:
            if response.get("dispatch_started") and wait_for_completion and wait_result.get("action") != "completed":
                response["stages"].append({
                    "stage": "paper_draft",
                    "ok": False,
                    "reason": "dispatched work did not complete inside this bounded run; paper stage skipped",
                    "wait": wait_result,
                })
            elif store.active_items():
                response["stages"].append({"stage": "paper_draft", "ok": False, "reason": "active worker lane exists; paper stage skipped"})
            else:
                for draft_index in range(max_paper_drafts):
                    draft_response = draft_next(
                        DraftNextRequest(force=False, requested_by=requested_by, dry_run=False),
                        authorization=f"Bearer {config.control_api_bearer_token}",
                    )
                    draft_payload = draft_response.model_dump(mode="json")
                    drafted_papers.append(draft_payload)
                    response["stages"].append({"stage": "paper_draft", "ok": draft_response.ok, "action": draft_response.action, "reason": draft_response.reason})
                    if draft_response.action != "drafted" or draft_response.paper is None:
                        break
                    if len(finalized_papers) < max_publication_rewrites:
                        paper_id = draft_response.paper.paper_id
                        rewrite_response = _rewrite_paper_review_draft(
                            paper_id,
                            PaperReviewRewriteDraftRequest(
                                idempotency_key=f"research-cycle:{requested_by}:{draft_index}:{paper_id}:{utc_now()}",
                                requested_by=requested_by,
                                force=True,
                            ),
                        )
                        rewrite_payload = rewrite_response.model_dump(mode="json")
                        finalized_papers.append(rewrite_payload)
                        response["stages"].append({
                            "stage": "publication_finalization",
                            "ok": rewrite_response.ok,
                            "paper_id": paper_id,
                            "event_id": rewrite_response.event_id,
                            "review_status": str((rewrite_payload.get("item") or {}).get("review_status") or ""),
                        })
        response["paper_drafts"] = drafted_papers
        response["paper_drafted_count"] = sum(1 for item in drafted_papers if item.get("action") == "drafted")
        response["publication_finalizations"] = finalized_papers
        response["publication_finalized_count"] = len(finalized_papers)
        response["reason"] = "bounded research cycle completed; broad queue pause preserved and paper stages were positive-gated"
        if hasattr(store, "append_event"):
            store.append_event(
                idempotency_key=f"research-cycle:live:{requested_by}:{utc_now()}",
                event_type="research.run_cycle.live",
                entity_type="research",
                entity_id="run-cycle",
                payload=jsonable_encoder(response),
            )
        return response

    @router.post("/api/research/promote-candidate")
    def dashboard_research_promote_candidate(
        payload: dict[str, Any] | None = Body(default=None),
        authorization: str | None = Header(default=None),
    ) -> dict[str, Any]:
        authorize(authorization)
        body = payload or {}
        candidate_id = str(body.get("candidate_id") or "").strip()
        if not candidate_id:
            raise HTTPException(status_code=400, detail="candidate_id is required")
        dry_run = bool(body.get("dry_run", True))
        requested_by = str(body.get("requested_by") or "dashboard")[:80]
        if not hasattr(store, "promote_research_candidate"):
            raise HTTPException(status_code=501, detail="Research Facility promotion requires the Supabase control-plane store")
        return store.promote_research_candidate(candidate_id, requested_by=requested_by, dry_run=dry_run)

    @router.get("/api/research/provider-budget")
    def dashboard_research_provider_budget(
        authorization: str | None = Header(default=None),
        estimated_requests: int = Query(default=2, ge=0, le=100),
        reserve_requests: int = Query(default=2, ge=0, le=100),
        min_remaining_credits: float = Query(default=5.0, ge=0.0),
        min_rolling_remaining: int = Query(default=10, ge=0),
        timeout: int = Query(default=20, ge=1, le=60),
    ) -> dict[str, Any]:
        authorize(authorization)
        from scripts import research_provider_budget

        base_url = os.environ.get("ENOCH_RESEARCH_PROVIDER_BASE_URL", "https://synthetic.int.exe.xyz").rstrip("/")
        try:
            payload = research_provider_budget.fetch_json(f"{base_url}/v2/quotas", api_key="", timeout=timeout)
            result = research_provider_budget.synthetic_budget_status(
                payload,
                min_remaining_credits=min_remaining_credits,
                min_rolling_remaining=min_rolling_remaining,
                estimated_requests=estimated_requests,
                reserve_requests=reserve_requests,
            )
        except Exception as exc:  # noqa: BLE001 - provider checks must fail closed but stay operator-readable
            result = {
                "ok": False,
                "provider": "synthetic",
                "checked_at": utc_now(),
                "estimated_requests": estimated_requests,
                "reserve_requests": reserve_requests,
                "failures": [f"provider budget check failed: {exc}"],
            }
        safe_keys = {
            "ok",
            "provider",
            "checked_at",
            "estimated_requests",
            "reserve_requests",
            "remaining_credits",
            "min_remaining_credits",
            "rolling_remaining",
            "rolling_max",
            "rolling_limited",
            "rolling_next_tick_at",
            "weekly_next_regen_at",
            "weekly_next_regen_credits",
            "subscription_remaining",
            "subscription_renews_at",
            "failures",
        }
        response = {key: result.get(key) for key in safe_keys if key in result}
        response.update({"base_url": base_url, "auth_mode": "exe_http_proxy", "payload_json": None})
        return response

    @router.get("/api/intake/notion", response_model=DashboardIntakeResponse)
    def dashboard_notion_intake(
        authorization: str | None = Header(default=None),
        page_size: int = Query(default=50, ge=1, le=200),
        include_latest_payload: bool = Query(default=False),
    ) -> DashboardIntakeResponse:
        authorize(authorization)
        _require_legacy_notion_api_enabled()
        return _dashboard_ideas_intake_response(legacy_notion_alias=True, page_size=page_size, include_latest_payload=include_latest_payload)

    @router.post("/pause", response_model=ControlStateResponse)
    def pause(payload: PauseRequest, authorization: str | None = Header(default=None)) -> ControlStateResponse:
        authorize(authorization)
        store.pause(reason=payload.reason, paused_by=payload.paused_by, maintenance_mode=payload.maintenance_mode)
        return state_response()

    @router.post("/resume", response_model=ControlStateResponse)
    def resume(payload: ResumeRequest, authorization: str | None = Header(default=None)) -> ControlStateResponse:
        authorize(authorization)
        store.resume(resumed_by=payload.resumed_by, maintenance_mode=payload.maintenance_mode)
        return state_response()

    @router.post("/queue/mark-paused", response_model=ControlStateResponse)
    def mark_queue_item_paused(payload: MarkQueueItemPausedRequest, authorization: str | None = Header(default=None)) -> ControlStateResponse:
        authorize(authorization)
        if not store.mark_queue_item_paused(project_id=payload.project_id, reason=payload.reason, updated_by=payload.updated_by):
            raise HTTPException(status_code=404, detail="queue item not found")
        return state_response()

    @router.post("/import/legacy-snapshot", response_model=ImportSnapshotResponse)
    def import_snapshot(payload: ImportSnapshotRequest, authorization: str | None = Header(default=None)) -> ImportSnapshotResponse:
        authorize(authorization)
        try:
            inserted, projects, queue_items, papers = store.import_snapshot(payload)
        except IdempotencyConflict as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        response = ImportSnapshotResponse(inserted_event=inserted, imported_projects=projects, imported_queue_items=queue_items, imported_papers=papers)
        store.upsert_dashboard_observation(
            source="snapshot_mirror",
            status="ok",
            ttl_seconds=900,
            payload={"source": payload.source, "imported_projects": projects, "imported_queue_items": queue_items, "imported_papers": papers, "inserted_event": inserted},
        )
        return response

    @router.post("/intake/notion-ideas", response_model=NotionIntakeResponse)
    def intake_notion_ideas(payload: NotionIntakeRequest, authorization: str | None = Header(default=None)) -> NotionIntakeResponse:
        authorize(authorization)
        _require_legacy_notion_api_enabled()
        if payload.default_machine_target == "worker.example":
            configured_worker = urlparse(config.worker_wake_gate_url).hostname or ""
            if configured_worker:
                payload = payload.model_copy(update={"default_machine_target": configured_worker})
        try:
            inserted, created, updated, skipped, candidates, skipped_rows = store.ingest_notion_ideas(payload)
        except IdempotencyConflict as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        response = NotionIntakeResponse(
            dry_run=payload.dry_run,
            inserted_event=inserted,
            created=created,
            updated=updated,
            skipped=skipped,
            candidates=candidates,
            skipped_rows=skipped_rows,
        )
        if not payload.dry_run:
            store.upsert_dashboard_observation(
                source="notion_sync",
                status="ok" if skipped == 0 else "warn",
                ttl_seconds=3600,
                payload=response.model_dump(mode="json"),
            )
        return response

    @router.post("/intake/ideas", response_model=IdeaIntakeResponse)
    def intake_ideas(payload: IdeaIntakeRequest, authorization: str | None = Header(default=None)) -> IdeaIntakeResponse:
        authorize(authorization)
        if payload.default_machine_target == "worker.example":
            configured_worker = urlparse(config.worker_wake_gate_url).hostname or ""
            if configured_worker:
                payload = payload.model_copy(update={"default_machine_target": configured_worker})
        try:
            inserted, created, updated, skipped, candidates, skipped_rows = store.ingest_ideas(payload)
        except IdempotencyConflict as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        response = IdeaIntakeResponse(
            dry_run=payload.dry_run,
            inserted_event=inserted,
            created=created,
            updated=updated,
            skipped=skipped,
            candidates=candidates,
            skipped_rows=skipped_rows,
        )
        if not payload.dry_run:
            store.upsert_dashboard_observation(
                source="idea_intake",
                status="ok" if skipped == 0 else "warn",
                ttl_seconds=3600,
                payload=response.model_dump(mode="json"),
            )
        return response


    @router.post("/api/intake/notion-observation")
    def record_notion_observation(payload: dict[str, Any], authorization: str | None = Header(default=None)) -> dict[str, Any]:
        authorize(authorization)
        _require_legacy_notion_api_enabled()
        status = str(payload.get("status") or "ok")
        if status not in {"ok", "warn", "error", "unavailable"}:
            status = "warn"
        observation = store.upsert_dashboard_observation(
            source="notion_sync",
            status=status,
            ttl_seconds=int(payload.get("ttl_seconds") or 3600),
            payload=payload.get("payload") if isinstance(payload.get("payload"), dict) else payload,
        )
        return {"ok": True, "observation": observation.model_dump(mode="json")}

    @router.post("/api/intake/ideas-observation")
    def record_ideas_observation(payload: dict[str, Any], authorization: str | None = Header(default=None)) -> dict[str, Any]:
        authorize(authorization)
        status = str(payload.get("status") or "ok")
        if status not in {"ok", "warn", "error", "unavailable"}:
            status = "warn"
        observation = store.upsert_dashboard_observation(
            source="idea_intake",
            status=status,
            ttl_seconds=int(payload.get("ttl_seconds") or 3600),
            payload=payload.get("payload") if isinstance(payload.get("payload"), dict) else payload,
        )
        return {"ok": True, "observation": observation.model_dump(mode="json")}


    @router.post("/worker/preflight", response_model=WorkerPreflightResponse)
    def worker_preflight(payload: WorkerPreflightRequest, authorization: str | None = Header(default=None)) -> WorkerPreflightResponse:
        authorize(authorization)
        response = run_worker_preflight(payload, store.flags())
        _record_preflight_observations(response)
        return response

    @router.post("/api/preflight", response_model=WorkerPreflightResponse)
    def dashboard_preflight(payload: WorkerPreflightRequest, authorization: str | None = Header(default=None)) -> WorkerPreflightResponse:
        authorize(authorization)
        return worker_preflight(payload, authorization)

    @router.post("/dispatch-next", response_model=DispatchNextResponse)
    def dispatch_next(payload: DispatchNextRequest, authorization: str | None = Header(default=None)) -> DispatchNextResponse:
        authorize(authorization)
        if not payload.dry_run:
            active = store.active_items()
            if active:
                return DispatchNextResponse(ok=True, action="noop", reason="active GB10 lane already exists", active_count=len(active))
            candidate = store.next_dispatch_candidate()
            if not candidate:
                return DispatchNextResponse(ok=True, action="noop", reason="no queued candidate", active_count=0)
            live, event_id, updated_candidate = _live_dispatch(candidate, payload.requested_by, payload.force_preflight)
            return DispatchNextResponse(ok=True, action="live_dispatch", reason="live dispatch accepted by worker", candidate=updated_candidate, active_count=1, event_id=event_id, live=live)
        graph = build_dispatch_graph(store)
        result = graph.invoke({"requested_by": payload.requested_by, "dry_run": True})
        action = result.get("action") or "noop"
        return DispatchNextResponse(
            ok=action in {"paused", "noop", "dry_run_dispatch"},
            action=action,
            reason=result.get("reason") or "",
            candidate=result.get("candidate"),
            active_count=int(result.get("active_count") or 0),
            event_id=result.get("event_id"),
        )

    @router.post("/dispatch-one", response_model=DispatchNextResponse)
    def dispatch_one(payload: DispatchOneRequest, authorization: str | None = Header(default=None)) -> DispatchNextResponse:
        authorize(authorization)
        project_id = str(payload.project_id or "").strip()
        if not project_id:
            raise HTTPException(status_code=400, detail="project_id is required")
        active = store.active_items()
        if active:
            raise HTTPException(status_code=409, detail="active GB10 lane already exists")
        candidate = store.queue_row(project_id)
        if not candidate:
            raise HTTPException(status_code=404, detail="project_id was not found in the queue")
        if str(candidate.get("status") or "").strip() != "queued":
            raise HTTPException(status_code=409, detail="project_id is not queued")
        manual_review = str(candidate.get("manual_review_required") or "").strip().lower() in {"1", "true", "yes", "on"}
        if manual_review:
            raise HTTPException(status_code=409, detail="project_id is blocked by manual_review_required")
        if payload.dry_run:
            return DispatchNextResponse(
                ok=True,
                action="dry_run_dispatch_one",
                reason="dry-run selected explicit queued candidate; no state mutated",
                candidate=candidate,
                active_count=0,
            )
        live, event_id, updated_candidate = _live_dispatch(
            candidate,
            payload.requested_by,
            payload.force_preflight,
            allow_paused=True,
        )
        return DispatchNextResponse(
            ok=True,
            action="live_dispatch_one",
            reason="explicit live dispatch accepted by worker; global queue pause preserved",
            candidate=updated_candidate,
            active_count=1,
            event_id=event_id,
            live=live,
        )

    @router.get("/queue")
    def queue(authorization: str | None = Header(default=None)) -> dict:
        authorize(authorization)
        return {"ok": True, "rows": store.queue_rows(), "counts": store.status_counts(), "active": store.active_items()}

    @router.get("/papers")
    def papers(authorization: str | None = Header(default=None)) -> dict:
        authorize(authorization)
        return {"ok": True, "rows": store.paper_rows()}

    @router.get("/export/snapshot", response_model=ExportSnapshotResponse)
    def export_snapshot(authorization: str | None = Header(default=None)) -> ExportSnapshotResponse:
        authorize(authorization)
        snapshot = store.export_snapshot()
        return ExportSnapshotResponse(
            flags=store.flags(),
            queue_rows=snapshot["queue_rows"],
            paper_rows=snapshot["paper_rows"],
            events=snapshot["events"],
        )

    @router.get("/projections/notion/queue", response_model=ProjectionResponse)
    def notion_queue_projection(authorization: str | None = Header(default=None)) -> ProjectionResponse:
        authorize(authorization)
        _require_legacy_notion_api_enabled()
        rows = store.queue_notion_projection()
        return ProjectionResponse(rows=rows, counts=store.status_counts())

    @router.get("/projections/ideas/workbench", response_model=ProjectionResponse)
    def ideas_workbench_projection(authorization: str | None = Header(default=None)) -> ProjectionResponse:
        authorize(authorization)
        rows = store.idea_workbench_projection() if hasattr(store, "idea_workbench_projection") else store.queue_notion_projection()
        counts: dict[str, int] = {}
        for row in rows:
            key = str(row.get("idea_status") or row.get("queue_status") or "unknown")
            counts[key] = counts.get(key, 0) + 1
        return ProjectionResponse(rows=rows, counts=counts)

    @router.get("/projections/notion/papers", response_model=ProjectionResponse)
    def notion_papers_projection(authorization: str | None = Header(default=None)) -> ProjectionResponse:
        authorize(authorization)
        _require_legacy_notion_api_enabled()
        rows = store.paper_notion_projection()
        counts: dict[str, int] = {}
        for row in rows:
            key = str(row.get("paper_status") or "unknown")
            counts[key] = counts.get(key, 0) + 1
        return ProjectionResponse(rows=rows, counts=counts)

    @router.get("/projections/notion/execution-updates", response_model=ProjectionResponse)
    def notion_execution_updates_projection(authorization: str | None = Header(default=None)) -> ProjectionResponse:
        authorize(authorization)
        _require_legacy_notion_api_enabled()
        rows = store.notion_execution_update_projection()
        return ProjectionResponse(rows=rows, counts={"updates": len(rows)})

    def _candidate_project_dir(candidate: dict[str, Any]) -> Path:
        project_id = str(candidate.get("project_id") or "").strip()
        project_dir_text = str(candidate.get("project_dir") or project_id).strip()
        root = config.expanded_project_root.resolve()
        project_dir = Path(project_dir_text).expanduser()
        if not project_dir.is_absolute():
            return (root / project_dir).resolve()
        resolved = project_dir.resolve()
        try:
            resolved.relative_to(root)
            return resolved
        except ValueError:
            # Completed worker rows can carry a worker-absolute path that is not
            # valid on the VM. Use a VM-local artifact root and keep the source
            # path only for evidence sync.
            return (root / project_id).resolve()

    def _prepare_draft_evidence(candidate: dict[str, Any]) -> dict[str, Any]:
        project_id = str(candidate.get("project_id") or "").strip()
        artifact_root = _candidate_project_dir(candidate)
        evidence_sync = _sync_remote_project_evidence(
            config,
            project_id=project_id,
            artifact_root=artifact_root,
            source_project_dir=str(candidate.get("project_dir") or "") if str(candidate.get("project_dir") or "").startswith("/") else "",
            source_run_id=str(candidate.get("current_run_id") or candidate.get("run_id") or ""),
        )
        return {"artifact_root": str(artifact_root), "evidence_sync": evidence_sync, "local_evidence_present": _local_paper_evidence_present(artifact_root)}

    @router.post("/papers/draft-next", response_model=DraftNextResponse)
    def draft_next(payload: DraftNextRequest, authorization: str | None = Header(default=None)) -> DraftNextResponse:
        authorize(authorization)
        candidates = eligible_paper_draft_candidates(store.queue_rows(), store.paper_rows())
        skipped: list[dict[str, Any]] = []
        if not candidates:
            return DraftNextResponse(ok=True, action="noop", reason="no eligible completed paper-draft candidate without paper remains")
        for candidate in candidates:
            evidence = _prepare_draft_evidence(candidate)
            legacy_finalize_positive = str(candidate.get("last_run_state") or "").strip() == "finalize_positive"
            if not legacy_finalize_positive and not evidence["local_evidence_present"]:
                skipped.append({"project_id": candidate.get("project_id"), "run_id": candidate.get("current_run_id"), "reason": "missing paper evidence", "evidence_sync": evidence.get("evidence_sync")})
                continue
            decision_gate = {"eligible": True, "reason": "legacy finalize_positive state"}
            if not legacy_finalize_positive:
                decision_gate = paper_draft_decision_gate(str(evidence.get("artifact_root") or ""))
                if not decision_gate.get("eligible"):
                    skipped.append({
                        "project_id": candidate.get("project_id"),
                        "run_id": candidate.get("current_run_id"),
                        "reason": "project decision is not paper-positive",
                        "decision_gate": decision_gate,
                        "evidence_sync": evidence.get("evidence_sync"),
                    })
                    continue
            paper = _paper_record_from_candidate(candidate, force=payload.force)
            if payload.dry_run:
                return DraftNextResponse(
                    ok=True,
                    action="dry_run_draft",
                    reason="eligible paper-positive candidate found; dry_run prevented artifact writes",
                    paper=paper,
                    candidate=draft_candidate_payload(candidate),
                )
            candidate_for_write = {**candidate, "project_dir": evidence.get("artifact_root") or candidate.get("project_dir")}
            writer = write_paper_artifacts(config, candidate_for_write, paper, force=payload.force)
            writer = {**writer, "evidence_sync": evidence.get("evidence_sync"), "artifact_root": evidence.get("artifact_root"), "decision_gate": decision_gate}
            store.update_project_dir(str(candidate.get("project_id") or ""), str(candidate_for_write["project_dir"]))
            store.upsert_paper(paper)
            try:
                backfill_inserted, backfill_created, backfill_updated, backfill_skipped, backfill_errors = store.backfill_paper_reviews(
                    PaperReviewBackfillRequest(
                        idempotency_key=f"paper-review-backfill:{paper.paper_id}:{paper.updated_at}",
                        requested_by=payload.requested_by,
                        paper_ids=[paper.paper_id],
                        dry_run=False,
                    )
                )
                writer["review_backfill"] = {
                    "inserted_event": backfill_inserted,
                    "created": backfill_created,
                    "updated": backfill_updated,
                    "skipped": backfill_skipped,
                    "errors": backfill_errors,
                }
            except IdempotencyConflict as exc:
                writer["review_backfill"] = {"inserted_event": False, "created": 0, "updated": 0, "skipped": 0, "errors": [{"reason": str(exc)}]}
            store.append_event(idempotency_key=f"paper-draft:{paper.paper_id}:{paper.updated_at}", event_type="paper.drafted", entity_type="paper", entity_id=paper.paper_id, payload={"requested_by": payload.requested_by, "paper": paper.model_dump(mode="json"), "writer": writer})
            reason = f"paper draft created with {writer.get('provider')} / {writer.get('model')}"
            if writer.get("fallback_used"):
                reason += " (fallback used)"
            return DraftNextResponse(ok=True, action="drafted", reason=reason, paper=paper, candidate=draft_candidate_payload(candidate))
        return DraftNextResponse(ok=True, action="noop", reason="eligible paper-draft candidates lacked sufficient positive local or synced evidence", candidate={"skipped": skipped[:10]})

    return router
