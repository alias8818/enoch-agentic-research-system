from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
import re
import shlex
import subprocess
from typing import Any, Callable
from urllib.parse import urlparse

from fastapi import APIRouter, Header, HTTPException, Query
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
    :root { color-scheme: dark; --bg:#07111f; --bg2:#0b1220; --panel:#101827; --panel2:#132033; --text:#eef6ff; --muted:#9fb1c7; --line:#283852; --good:#4ade80; --warn:#fbbf24; --bad:#fb7185; --info:#60a5fa; --critical:#f43f5e; font-family: Inter, ui-sans-serif, system-ui, -apple-system, Segoe UI, sans-serif; }
    * { box-sizing:border-box; } body { margin:0; background:radial-gradient(circle at 18% 0%, rgba(37,99,235,.30), transparent 30%), linear-gradient(135deg,#05070b,var(--bg)); color:var(--text); line-height:1.45; }
    header { border-bottom:1px solid var(--line); background:rgba(7,17,31,.92); backdrop-filter:blur(14px); position:sticky; top:0; z-index:10; }
    .wrap { width:min(1460px, calc(100vw - 32px)); margin:0 auto; } .top { display:flex; justify-content:space-between; gap:18px; align-items:center; padding:16px 0; }
    h1 { margin:0; font-size:clamp(1.35rem, 2vw, 2.2rem); letter-spacing:-.04em; } h2 { margin:0 0 10px; } h3 { margin:14px 0 8px; }
    .sub,.muted { color:var(--muted); } .mono { font-family:ui-monospace,SFMono-Regular,Menlo,Monaco,Consolas,monospace; }
    input,select,button { background:#0b1220; color:var(--text); border:1px solid var(--line); border-radius:11px; padding:9px 11px; } button { cursor:pointer; } button:hover, nav a:hover { border-color:var(--info); }
    nav { display:flex; gap:8px; flex-wrap:wrap; padding:0 0 14px; } nav a { color:var(--text); text-decoration:none; border:1px solid var(--line); border-radius:999px; padding:7px 11px; background:#0b1220; } nav a.active { border-color:var(--info); color:#bfdbfe; box-shadow:0 0 0 1px rgba(96,165,250,.2) inset; }
    main { padding:22px 0 44px; } .hero { display:grid; grid-template-columns:2fr 1fr; gap:14px; align-items:stretch; } .grid { display:grid; grid-template-columns:repeat(4,minmax(0,1fr)); gap:14px; } .grid.two { grid-template-columns:repeat(2,minmax(0,1fr)); } .grid.three { grid-template-columns:repeat(3,minmax(0,1fr)); }
    .card { background:linear-gradient(180deg,rgba(16,24,39,.97),rgba(11,18,32,.97)); border:1px solid var(--line); border-radius:18px; padding:16px; box-shadow:0 16px 44px rgba(0,0,0,.25); overflow:auto; } .card.tight { padding:12px; }
    .label { color:var(--muted); font-size:.84rem; text-transform:uppercase; letter-spacing:.05em; } .value { font-size:2rem; font-weight:850; margin-top:5px; letter-spacing:-.04em; }
    .pill { display:inline-flex; gap:7px; align-items:center; border:1px solid var(--line); border-radius:999px; padding:5px 9px; font-size:.84rem; margin:2px; } .good { color:var(--good); } .warn { color:var(--warn); } .bad,.critical { color:var(--critical); } .info { color:var(--info); }
    section { margin-top:16px; } table { width:100%; border-collapse:collapse; font-size:.91rem; } th,td { text-align:left; border-bottom:1px solid var(--line); padding:9px 7px; vertical-align:top; } th { color:var(--muted); font-weight:650; }
    a { color:#93c5fd; } .truncate { max-width:420px; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; display:inline-block; vertical-align:bottom; }
    .banner { border:1px solid var(--line); border-radius:18px; padding:16px; background:#0b1220; } .banner.good { border-color:rgba(74,222,128,.42); background:rgba(20,83,45,.18); } .banner.warn { border-color:rgba(251,191,36,.5); background:rgba(113,63,18,.18); } .banner.critical { border-color:rgba(244,63,94,.55); background:rgba(127,29,29,.22); }
    .row { display:flex; flex-wrap:wrap; gap:8px; align-items:center; } .toolbar { display:flex; gap:8px; flex-wrap:wrap; align-items:center; margin:12px 0; } .toolbar-note { color:var(--muted); margin-top:12px; } .activity-list { display:grid; gap:10px; } .card.tight strong { font-size:1rem; }
    details { border:1px solid var(--line); border-radius:14px; padding:10px 12px; background:rgba(11,18,32,.72); margin-top:10px; } summary { cursor:pointer; color:#bfdbfe; } pre { white-space:pre-wrap; color:#cbd5e1; margin:10px 0 0; max-height:480px; overflow:auto; }
    @media (max-width:1000px) { .hero,.grid,.grid.two,.grid.three { grid-template-columns:repeat(2,minmax(0,1fr)); } .top { align-items:flex-start; flex-direction:column; } }
    @media (max-width:620px) { .hero,.grid,.grid.two,.grid.three { grid-template-columns:1fr; } }
  </style>
</head>
<body>
<header>
  <div class="wrap top"><div><h1>Enoch Control Status Dashboard</h1><div class="sub">Professional operator console backed by bounded control-plane read models</div></div><div class="row"><input id="token" placeholder="Bearer token" type="password" /><button onclick="saveToken()">Save</button><button onclick="route()">Refresh</button></div></div>
  <div class="wrap"><nav id="nav"></nav></div>
</header>
<main class="wrap"><div id="status" class="pill warn">Loading…</div><div id="app" class="banner warn">Loading dashboard cards…</div></main>
<script>
const pages=[['overview','Overview'],['projects','Projects'],['queue:active','Active'],['queue:queued','Queued'],['queue:blocked','Blocked'],['runs','Runs'],['papers','Papers'],['events','Events'],['automation','Publication Automation'],['intake','Ideas'],['observability','Observability']];
const $=id=>document.getElementById(id); const AI_ACTOR='ai-publication-pipeline'; const AI_NOTE='AI-generated publication pipeline; operator claims no personal authorship credit.';
const esc=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
function token(){return localStorage.getItem('enochControlToken')||'';} function saveToken(){localStorage.setItem('enochControlToken',$('token').value.trim());route();}
async function api(path,opts={}){const headers={Authorization:'Bearer '+token(),...(opts.headers||{})}; const r=await fetch(path,{cache:'no-store',...opts,headers}); if(!r.ok) throw new Error(path+' -> '+r.status+' '+await r.text()); return r.json();}
async function postJson(path,payload){return api(path,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(payload)});}
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
function cell(c,v,r){if(c==='project_id')return `${linkProject(v)}${r.project_name?`<div class="muted">${esc(r.project_name)}</div>`:''}`; if(c==='current_run_id'||c==='run_id')return linkRun(v); if(c==='paper_id')return linkPaper(v); if(c==='automation')return r.paper_id?`<a href="#automation:${encodeURIComponent(r.paper_id)}">Open ${esc(r.project_name||r.paper_id)}</a>`:''; if(c==='review')return r.paper_id?`<a href="#automation:${encodeURIComponent(r.paper_id)}">Open ${esc(r.project_name||r.paper_id)}</a>`:''; if(c==='paper_title')return `<strong>${esc(r.project_name||r.paper_id||'Untitled')}</strong><div class="muted mono">${shortId(r.paper_id||'')}</div>`; if(c==='notion_page_url'&&v)return `<a href="${esc(v)}">Source</a>`; if(c==='artifact_paths_present')return Object.entries(v||{}).map(([k,ok])=>`<span class="pill ${ok?'good':'warn'}">${esc(k.replace('_path','').replaceAll('_',' '))}: ${ok?'yes':'no'}</span>`).join(''); if(c==='payload_summary')return payloadDigest(v||{}); if(c==='paper_status'||c==='related_paper_status')return `<span class="truncate ${statusClass(v)}">${esc(paperStatusLabel(v))}</span>`; if(c==='review_status'||c==='related_review_status'||c==='automation_status')return `<span class="truncate ${statusClass(v)}">${esc(automationStatusLabel(v))}</span>`; if(c==='status'||c==='queue_status')return `<span class="truncate ${statusClass(v)}">${esc(queueStatusLabel(v))}</span>`; if(c==='state'||c==='last_run_state'||c==='gate_state')return `<span class="truncate ${statusClass(v)}">${esc(runStateLabel(v))}</span>`; if(c==='entity_id')return shortId(v); if(c==='created_at'||c==='updated_at'||c==='generated_at')return formatTime(v); if(typeof v==='boolean')return `<span class="pill ${v?'good':'warn'}">${v?'yes':'no'}</span>`; if(Array.isArray(v))return `<span class="truncate">${esc(v.join('; '))}</span>`; if(v&&typeof v==='object')return '<span class="muted">details hidden</span>'; return `<span class="truncate ${statusClass(v)}">${esc(v)}</span>`;}
function tableRows(rows,cols,empty='No rows match this view'){return `<table><thead><tr>${cols.map(c=>`<th>${esc(c.replaceAll('_',' '))}</th>`).join('')}</tr></thead><tbody>${(rows||[]).map(r=>`<tr>${cols.map(c=>`<td>${cell(c,r[c],r)}</td>`).join('')}</tr>`).join('')||`<tr><td colspan="${cols.length}">${esc(empty)}</td></tr>`}</tbody></table>`;}
function pageMeta(page,label='Showing'){return `<div class="muted">${esc(label)} ${esc(page?.returned??0)} items · ${page?.has_more?'more available':'end of list'}</div>`;}
function operatorQuestionCards(counts={},operators={},pipeline={}){const attention=Number(operators.needs_attention ?? counts.blocked ?? 0), running=Number(counts.active||operators.running||0), write=Number(pipeline.write_needed||0), publish=Number(pipeline.publish_ready||operators.ready_to_publish||0), done=Number(operators.complete_no_paper||0); return `<section class="card"><h2>What do I need to know?</h2><div class="muted">Primary dashboard cards answer operator questions first. Raw states stay in drill-down/debug views.</div><section class="grid">${card('What needs me?',attention,attention?'warn':'good',attention?'Open Needs attention and resolve blockers/questions.':'Nothing needs operator action.')}${card('What is running?',running,running?'info':'good',running?'Work is executing or waiting on callback.':'No active worker lane.')}${card('What can be written?',write,write?'warn':'good',write?'Only positive, decision-gated runs count here.':'No actionable paper-positive runs need drafts.')}${card('What can be published?',publish,publish?'good':'info',publish?'Finalized publication drafts are ready for corpus import.':'No finalized publication drafts waiting.')}${card('What is done / no paper?',done,'muted','Completed non-positive or non-writable rows; no paper action.')}</section></section>`;}
function paperPipelineCards(pipeline={},papers={}){const write=Number(pipeline.write_needed||0), finalize=Number(pipeline.finalize_needed||0), publish=Number(pipeline.publish_ready||0), raw=Number(pipeline.raw_completed_no_paper_candidates||0), blocked=Number(pipeline.not_writable_by_decision_gate||0), next=pipeline.next_write_candidate||null; const nextText=next?`Next: ${esc(next.project_name||next.project_id||'untitled')}`:'No live write candidate'; return `<section class="card"><h2>Paper pipeline</h2><div class="muted">Back-to-basics paper state: write only paper-positive runs, finalize the draft, then publish/import it. These are separate steps.</div><section class="grid">${card('1. Write papers',write,write?'warn':'good',`Actionable paper-positive runs with no live paper row. ${nextText}`)}${card('2. Finalize drafts',finalize,finalize?'warn':'good','Publication drafts missing automated finalization package')}${card('3. Publish/import',publish,publish?'good':'info','Finalized publication drafts ready for corpus import')}</section><details><summary>Debug paper counts</summary><div class="muted">Raw completed/no-paper rows are informational, not write work.</div><section class="grid">${card('Live paper rows',papers.all||0,'info',`${papers.publication_draft||0} publication draft rows · ${papers.archived||0} archived/no-paper rows`)}${card('Raw completed/no-paper candidates',raw,'muted','Before the decision gate; not actionable by itself.')}${card('Rejected by decision gate',blocked,blocked?'good':'muted','Negative, missing, malformed, unknown, or otherwise non-positive decisions.')}</section></details></section>`;}
function workState(counts,operators={},pipeline={}){const attention=operators.needs_attention ?? counts.blocked ?? 0, write=Number(pipeline.write_needed||0), finalize=Number(pipeline.finalize_needed||0), publish=Number(pipeline.publish_ready||operators.ready_to_publish||0), active=counts.active||operators.running||0, queued=counts.queued||operators.ready_queue||0; if(attention)return {label:'Needs attention', tone:'warn', detail:`${attention} item${attention===1?'':'s'} need operator action`}; if(write)return {label:'Papers to write', tone:'warn', detail:`${write} paper-positive run${write===1?'':'s'} still need first paper drafts`}; if(finalize)return {label:'Drafts to finalize', tone:'warn', detail:`${finalize} publication draft${finalize===1?'':'s'} need automated finalization`}; if(publish)return {label:'Ready to publish', tone:'good', detail:`${publish} finalized publication draft${publish===1?'':'s'} ready for corpus import`}; if(active)return {label:'Work running', tone:'info', detail:`${active} active item${active===1?'':'s'} in progress`}; if(queued)return {label:'Ready to dispatch', tone:'info', detail:`${queued} queued item${queued===1?'':'s'} waiting`}; return {label:'Work is idle', tone:'good', detail:'No active, queued, or paper-pipeline work needs action right now'};}
async function overviewPage(){renderNav('overview'); const [overview,memory,health]=await Promise.all([api('/control/api/v1/overview?active_limit=8&event_limit=6'),api('/control/api/v1/observability/memory'),api('/control/api/v1/observability/health')]); const counts=overview.counts||{}, papers=overview.paper_counts||{}, ops=overview.operator_counts||{}, pipeline=overview.paper_pipeline||{}, state=workState(counts,ops,pipeline); $('status').className='pill '+state.tone; $('status').textContent=`Overview · ${state.label}`; $('app').className=''; $('app').innerHTML=`<section class="banner ${state.tone}"><h2>${esc(state.label)}</h2><div>${esc(state.detail)}</div><div class="muted">Last refreshed ${esc(formatTime(overview.generated_at))}. Showing bounded, operator-safe summaries.</div></section>${operatorQuestionCards(counts,ops,pipeline)}${paperPipelineCards(pipeline,papers)}<section class="grid two"><div class="card"><h2>Active work</h2><div class="muted">Only work currently running or awaiting callback appears here.</div>${tableRows(overview.active_items||[],['operator_stage_label','project_id','current_run_id','operator_next_step','updated_at'],'No active work right now')}</div><div class="card"><h2>System health</h2><div class="row"><span class="pill ${memory.memory_warn?'warn':'good'}">Controller memory ${esc(Number(memory.rss_mib||0).toFixed(0))} MiB</span><span class="pill">Peak ${esc(Number(memory.peak_rss_mib||0).toFixed(0))} MiB</span><span class="pill ${health.route_observability_enabled?'good':'warn'}">Route observations ${health.route_observability_enabled?'on':'off'}</span></div><div class="muted">Memory is shown as a secondary health signal, not the primary work status.</div></div></section><section class="card"><h2>Recent activity</h2><div class="muted">Formatted control-plane events. Large payloads stay hidden.</div>${activityCards(overview.recent_events||[])}</section>`;}
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
function eventControls(params){const size=params.get('page_size')||'50', sort=params.get('sort')||'recent', term=params.get('search')||'', type=params.get('entity_type')||'', id=params.get('entity_id')||'', event=params.get('event_type')||''; return `<div class="toolbar-note">Find events by type, entity id, or payload text. Filter by entity/event type and sort the activity stream.</div><div class="toolbar"><input id="eventSearch" value="${esc(term)}" placeholder="Find events or payload text" onkeydown="if(event.key==='Enter') applyEventFilters()"/><input id="eventType" value="${esc(event)}" placeholder="event type"/><input id="entityType" value="${esc(type)}" placeholder="entity type"/><input id="entityId" value="${esc(id)}" placeholder="entity id"/><select id="eventSort"><option value="recent" ${sort==='recent'?'selected':''}>Newest first</option><option value="type" ${sort==='type'?'selected':''}>Event type</option><option value="entity" ${sort==='entity'?'selected':''}>Entity</option></select><select id="eventPageSize">${['25','50','100','200'].map(v=>`<option value="${v}" ${size===v?'selected':''}>${v} per page</option>`).join('')}</select><button onclick="applyEventFilters()">Apply</button><button onclick="location.hash='events'">Reset</button></div>`;}
function applyEventFilters(){const params=new URLSearchParams(); const term=$('eventSearch')?.value||'', eventType=$('eventType')?.value||'', entityType=$('entityType')?.value||'', entityId=$('entityId')?.value||'', sort=$('eventSort')?.value||'recent', pageSize=$('eventPageSize')?.value||'50'; if(term)params.set('search',term); if(eventType)params.set('event_type',eventType); if(entityType)params.set('entity_type',entityType); if(entityId)params.set('entity_id',entityId); if(sort)params.set('sort',sort); if(pageSize)params.set('page_size',pageSize); location.hash='events'+(params.toString()?('?'+params.toString()):'');}
async function eventsPage(){renderNav('events'); const params=new URLSearchParams(location.hash.split('?')[1]||''); const cursor=params.get('cursor')||'', pageSize=params.get('page_size')||'50', term=params.get('search')||'', entityType=params.get('entity_type')||'', entityId=params.get('entity_id')||'', eventType=params.get('event_type')||'', sort=params.get('sort')||'recent'; const qs=new URLSearchParams({page_size:pageSize,cursor,search:term,entity_type:entityType,entity_id:entityId,event_type:eventType,sort}); const data=await api('/control/api/v1/events?'+qs.toString()); const nextParams=new URLSearchParams(params); if(data.page.next_cursor)nextParams.set('cursor',data.page.next_cursor); $('status').className='pill info'; $('status').textContent=`Activity log · ${data.page.returned} shown`; $('app').className=''; $('app').innerHTML=`<section class="card"><h2>Activity log</h2><div class="muted">Human-readable event stream. Payload fields are summarized as chips; large payloads are not printed into the table.</div>${eventControls(params)}${pageMeta(data.page,'Showing latest')}${activityCards(data.rows||[])}<div class="toolbar">${cursor?`<button onclick="history.back()">Previous view</button>`:''}${data.page.has_more?`<button onclick="location.hash='events?${nextParams.toString()}'">Next page</button>`:''}</div></section>`;}
async function observabilityPage(){renderNav('observability'); const [memory,health]=await Promise.all([api('/control/api/v1/observability/memory'),api('/control/api/v1/observability/health')]); $('status').className='pill '+(memory.memory_warn?'warn':'good'); $('status').textContent=`Observability · controller memory ${Number(memory.rss_mib||0).toFixed(0)} MiB`; $('app').className=''; $('app').innerHTML=`<section class="grid three">${card('Controller memory',Number(memory.rss_mib||0).toFixed(0),memory.memory_warn?'warn':'good','MiB RSS now')}${card('Peak memory',Number(memory.peak_rss_mib||0).toFixed(0),'info','MiB since process start')}${card('Route observations',health.route_observability_enabled?'On':'Off',health.route_observability_enabled?'good':'warn','Request timing and size sampling')}</section><section class="card"><h2>Diagnostics</h2><div class="muted">Technical route-observation evidence is collapsed here for debugging only.</div>${health.latest_route_observation?`<details><summary>Latest route observation JSONL</summary><pre>${esc(health.latest_route_observation)}</pre></details>`:'<span class="pill warn">No observation logged</span>'}${debugBlock('Memory details',memory)}${debugBlock('Health details',health)}</section>`;}
async function intakePage(){renderNav('intake'); const data=await api('/control/api/intake/ideas'); $('status').className='pill info'; $('status').textContent='Supabase ideas'; $('app').className=''; $('app').innerHTML=`<section class="grid two"><div class="card"><h2>Supabase idea workbench</h2><div class="muted">Native idea rows are the editable intake ledger. Legacy Notion fields, when present, are provenance only.</div>${tableRows([data.latest_sync||{}],['source','status','observed_at','authority'])}${debugBlock('Latest intake JSON',data.latest_sync||{})}</div><div class="card"><h2>Skipped reasons</h2>${tableRows(Object.entries(data.skipped_reasons||{}).map(([reason,count])=>({reason,count})),['reason','count'])}</div></section><section class="card"><h2>Idea workbench</h2>${tableRows(data.queued_projection||[],['idea_id','title','idea_status','queue_status','next_action_hint','paper_status','source_kind','updated_at'])}</section>`;}
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
async function route(){try{if(token())$('token').value=token(); const h=(location.hash||'#overview').slice(1); if(h==='projects'||h.startsWith('projects?')) return projectListPage('projects','all'); if(h.startsWith('queue:')) return queuePage((h.split(':')[1]||'active').split('?')[0]); if(h==='runs'||h.startsWith('runs?')) return runsPage(); if(h==='papers'||h.startsWith('papers?')) return papersPage(); if(h==='events'||h.startsWith('events?')) return eventsPage(); if(h==='automation'||h.startsWith('automation?')||h==='reviews'||h.startsWith('reviews?')) return reviewsPage(); if(h==='intake') return intakePage(); if(h==='observability') return observabilityPage(); if(h.startsWith('project:')) return detail('project',encodeURIComponent(decodeURIComponent(h.split(':')[1]||''))); if(h.startsWith('run:')) return detail('run',encodeURIComponent(decodeURIComponent(h.split(':')[1]||''))); if(h.startsWith('paper:')) return detail('paper',encodeURIComponent(decodeURIComponent(h.split(':')[1]||''))); if(h.startsWith('automation:')) return reviewDetail(encodeURIComponent(decodeURIComponent(h.split(':')[1]||''))); if(h.startsWith('review:')) return reviewDetail(encodeURIComponent(decodeURIComponent(h.split(':')[1]||''))); return overviewPage();}catch(e){$('status').className='pill bad';$('status').textContent='Error';$('app').className='banner critical';$('app').textContent=e.message;}}
function autoRefreshCurrentPage(){const h=(location.hash||'#overview').slice(1).split('?')[0]; if(h==='overview'||h==='observability') route();}
window.addEventListener('hashchange',route); route(); setInterval(autoRefreshCurrentPage,15000);
</script>
</body>
</html>
"""




def _local_high_signal_evidence_present(project_dir: Path) -> bool:
    return (project_dir / "run_notes.md").is_file() and (project_dir / ".omx" / "project_decision.json").is_file()


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


def _project_prompt(candidate: dict) -> str:
    title = str(candidate.get("project_name") or candidate.get("project_id") or "Untitled Project")
    return f"""# Enoch Research Action: {title}

You are running under the Enoch LangGraph hard-cutover controller.

Project ID: {candidate.get('project_id') or ''}
Source/provenance URL: {candidate.get('notion_page_url') or ''}
Origin status: {candidate.get('origin_idea_status') or ''}

## Mission
Turn this idea into a concrete, evidence-backed research result. Work autonomously inside the project directory. Prefer install/build/run/verify over blocking on missing ordinary dependencies. If the idea is not viable, produce a clear negative result with evidence.

## Operating constraints
- Do not require human input for installable, downloadable, compilable, or locally runnable dependencies.
- For GB10 work, start with a small smoke test, then calibrate throughput/utilization before any long run.
- Swap is intentionally disabled on GB10; use MemAvailable/UMA telemetry and earlyoom posture, not swap availability, for memory judgment.
- Leave durable artifacts: run_notes.md, commands/log paths, metrics, and a final .omx/project_decision.json.
- If final scientific closure truly needs human/private/external evidence, state that precisely and stop with a needs_review/blocker decision.
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


    def _live_dispatch(candidate: dict, requested_by: str, force_preflight: bool) -> tuple[dict, int | None, dict]:
        if not config.live_dispatch_enabled:
            raise HTTPException(status_code=501, detail="live dispatch is disabled by config.live_dispatch_enabled")
        if store.flags().queue_paused or store.flags().maintenance_mode:
            raise HTTPException(status_code=409, detail="control plane must be resumed and out of maintenance mode before live dispatch")
        if not config.worker_wake_gate_bearer_token:
            raise HTTPException(status_code=500, detail="worker wake-gate bearer token is not configured")
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
            raise HTTPException(status_code=409, detail={"message": "worker preflight failed", "preflight": preflight.model_dump(mode="json"), "force_preflight_ignored": not force_preflight})
        project_id = str(candidate.get("project_id") or "").strip()
        if not project_id:
            raise HTTPException(status_code=400, detail="candidate lacks project_id")
        project_dir = _safe_slug(str(candidate.get("project_dir") or project_id), project_id)
        run_id = _live_run_id(project_id)
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
            raise HTTPException(status_code=502, detail={"message": "worker dispatch failed", "status": dispatch.status, "error": dispatch.error, "body": dispatch.body})
        body = dispatch.body or {}
        session_id = str(((body.get("dispatch") or {}) if isinstance(body.get("dispatch"), dict) else {}).get("session_id") or "")
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

    def _record_preflight_observations(response: WorkerPreflightResponse) -> None:
        store.upsert_dashboard_observation(
            source="worker_preflight",
            status="ok" if response.ok else "warn",
            ttl_seconds=300,
            payload=response.model_dump(mode="json"),
        )
        dashboard_check = next((check for check in response.checks if check.name == "wake_gate_dashboard_api"), None)
        if dashboard_check is not None:
            dashboard_payload = dashboard_check.model_dump(mode="json")
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

    def _worker_observations_need_refresh(observations: dict[str, DashboardObservationRecord], active: list[dict]) -> bool:
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

    def _refresh_worker_observations_if_needed(observations: dict[str, DashboardObservationRecord], active: list[dict]) -> dict[str, DashboardObservationRecord]:
        if not _worker_observations_need_refresh(observations, active):
            return observations
        if not config.live_dispatch_enabled or not config.worker_wake_gate_url or not config.worker_wake_gate_bearer_token:
            return observations
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
        observations = store.latest_dashboard_observations()
        if refresh_worker:
            observations = _refresh_worker_observations_if_needed(observations, active)
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

    def _cached_observation_freshness(source: str, authority: str, scope: str = "global") -> dict[str, DashboardFreshness]:
        observation = store.latest_dashboard_observation(source=source, scope=scope)
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
        record = PaperRecord.model_validate(paper).model_copy(update={"paper_status": PaperStatus.PUBLICATION_DRAFT, "updated_at": utc_now()})
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

    def _dashboard_ideas_intake_response(*, legacy_notion_alias: bool = False) -> DashboardIntakeResponse:
        latest = store.latest_dashboard_observation(source="idea_intake")
        projection = store.idea_workbench_projection() if hasattr(store, "idea_workbench_projection") else store.queue_notion_projection()
        recent = store.event_rows(limit=20, event_type="ideas.intake")
        if not recent:
            recent = store.event_rows(limit=20, event_type="notion.intake")
        skipped_reasons: dict[str, int] = {}
        if latest:
            payload = latest.payload or {}
            for item in payload.get("skipped_rows") or []:
                reason = str(item.get("reason") or "unknown") if isinstance(item, dict) else "unknown"
                skipped_reasons[reason] = skipped_reasons.get(reason, 0) + 1
        warnings = []
        freshness = _intake_freshness()
        if not projection:
            warnings.append(DashboardFinding(severity="warn", source="idea_intake", authority="Supabase-native ideas workbench", message="No Supabase-native ideas are visible", observed_at=utc_now(), suggested_action="load ideas into Supabase before resuming the queue"))
        return DashboardIntakeResponse(
            source="control_api_intake_notion" if legacy_notion_alias else "control_api_intake_ideas",
            authority="Legacy Notion projection alias; Supabase ideas are canonical" if legacy_notion_alias else "Supabase-native ideas workbench; Notion is provenance only",
            latest_sync=latest,
            projection_counts=store.status_counts(),
            queued_projection=projection,
            skipped_reasons=skipped_reasons,
            recent_events=recent,
            source_freshness=freshness,
            warnings=warnings,
            conflicts=[],
        )

    @router.get("/api/intake/ideas", response_model=DashboardIntakeResponse)
    def dashboard_ideas_intake(authorization: str | None = Header(default=None)) -> DashboardIntakeResponse:
        authorize(authorization)
        return _dashboard_ideas_intake_response()

    @router.get("/api/intake/notion", response_model=DashboardIntakeResponse)
    def dashboard_notion_intake(authorization: str | None = Header(default=None)) -> DashboardIntakeResponse:
        authorize(authorization)
        _require_legacy_notion_api_enabled()
        return _dashboard_ideas_intake_response(legacy_notion_alias=True)

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
