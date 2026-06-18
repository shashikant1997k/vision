"""The read-only monitoring console (single-page app served at GET /).

Self-contained: no external CDN / framework (works on an offline line PC) —
vanilla JS + inline SVG charts. Multi-view console (Overview, Live, Batches +
drill-down, OEE, Reject analytics, Serialization, Challenge tests, Events, Audit)
matching enterprise line-monitoring layouts, polling the read-only /api/*.
"""

from __future__ import annotations

DASHBOARD_HTML = r"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<title>Vision Inspection — Monitoring Console</title>
<meta name="viewport" content="width=device-width, initial-scale=1">
<style>
 :root{--accent:#3d6bf5;--bg:#eef1f6;--card:#fff;--bd:#d9dee8;--tx:#1b1f24;--mut:#5b6472;
   --ok:#1a7f37;--bad:#e5484d;--warn:#b8860b}
 *{box-sizing:border-box}
 body{margin:0;font-family:system-ui,-apple-system,Segoe UI,sans-serif;background:var(--bg);color:var(--tx);font-size:14px}
 #app{display:flex;min-height:100vh}
 nav{width:210px;background:#10213f;color:#cdd7ea;flex-shrink:0;display:flex;flex-direction:column}
 nav .brand{padding:16px 18px;font-weight:700;color:#fff;font-size:1.05rem;border-bottom:1px solid #20335a}
 nav a{display:flex;align-items:center;gap:10px;padding:11px 18px;color:#cdd7ea;text-decoration:none;cursor:pointer;border-left:3px solid transparent}
 nav a:hover{background:#16294a}
 nav a.active{background:#1b3157;color:#fff;border-left-color:var(--accent)}
 nav a .ico{width:18px;text-align:center;opacity:.85}
 main{flex:1;display:flex;flex-direction:column;min-width:0}
 header{background:var(--card);border-bottom:1px solid var(--bd);padding:10px 20px;display:flex;align-items:center;gap:16px}
 header .title{font-weight:600;font-size:1.1rem}
 header .sp{flex:1}
 .pill{padding:4px 12px;border-radius:20px;font-weight:600;font-size:.8rem}
 .pill.run{background:#e6f4ea;color:var(--ok)}.pill.idle{background:#eceff3;color:var(--mut)}
 .pill.alarm{background:#fde8e8;color:var(--bad)}
 #clock{color:var(--mut);font-variant-numeric:tabular-nums;font-size:.85rem}
 #conn{font-size:.8rem;font-weight:600}
 .content{padding:20px;overflow:auto}
 h2{font-size:1rem;margin:18px 0 10px;color:var(--mut);text-transform:uppercase;letter-spacing:.04em}
 h2:first-child{margin-top:0}
 .cards{display:flex;gap:14px;flex-wrap:wrap}
 .kpi{background:var(--card);border:1px solid var(--bd);border-radius:12px;padding:16px 20px;flex:1;min-width:140px}
 .kpi .n{font-size:2rem;font-weight:700;line-height:1.1}.kpi .l{color:var(--mut);font-size:.82rem;margin-top:4px}
 .grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(320px,1fr));gap:16px}
 .card{background:var(--card);border:1px solid var(--bd);border-radius:12px;padding:16px 18px}
 .card h3{margin:0 0 12px;font-size:.95rem}
 table{border-collapse:collapse;width:100%}
 th,td{padding:8px 10px;text-align:left;border-bottom:1px solid #eef1f5;font-size:.86rem}
 th{color:var(--mut);font-weight:600;font-size:.76rem;text-transform:uppercase}
 tr.click{cursor:pointer}tr.click:hover{background:#f5f8ff}
 .ok{color:var(--ok);font-weight:600}.bad{color:var(--bad);font-weight:600}.warn{color:var(--warn);font-weight:600}
 .bar{height:18px;border-radius:4px;background:var(--accent)}
 .barbg{background:#eef1f5;border-radius:4px;flex:1;height:18px}
 .brow{display:flex;align-items:center;gap:10px;margin:6px 0}
 .brow .lab{width:130px;font-size:.82rem;color:var(--mut);overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
 .brow .val{width:54px;text-align:right;font-variant-numeric:tabular-nums;font-weight:600}
 .tok{padding:6px 10px;border:1px solid var(--bd);border-radius:6px;font-size:.85rem}
 button{background:var(--accent);color:#fff;border:0;border-radius:6px;padding:7px 14px;cursor:pointer;font-weight:600}
 button.sec{background:#fff;color:var(--tx);border:1px solid var(--bd)}
 .muted{color:var(--mut);font-size:.8rem}
 .sev-critical{color:var(--bad);font-weight:700}.sev-major{color:var(--warn);font-weight:600}.sev-minor{color:var(--mut)}
 .back{cursor:pointer;color:var(--accent);font-weight:600;margin-bottom:10px;display:inline-block}
 .empty{color:var(--mut);padding:20px;text-align:center}
</style></head><body>
<div id="app">
 <nav>
   <div class="brand">⬢ Vision Inspection</div>
   <a data-v="overview"><span class="ico">▦</span>Overview</a>
   <a data-v="live"><span class="ico">●</span>Live line</a>
   <a data-v="batches"><span class="ico">▤</span>Batches</a>
   <a data-v="oee"><span class="ico">◴</span>OEE &amp; downtime</a>
   <a data-v="rejects"><span class="ico">▾</span>Reject analytics</a>
   <a data-v="serial"><span class="ico">#</span>Serialization</a>
   <a data-v="challenge"><span class="ico">✔</span>Challenge tests</a>
   <a data-v="events"><span class="ico">!</span>Events</a>
   <a data-v="audit"><span class="ico">≣</span>Audit trail</a>
 </nav>
 <main>
  <header>
    <span class="title" id="viewtitle">Overview</span>
    <span class="pill idle" id="state">● Idle</span>
    <span class="sp"></span>
    <span id="conn"></span>
    <span id="clock"></span>
    <input class="tok" id="tok" placeholder="API token" style="width:140px">
    <button class="sec" onclick="saveTok()">Connect</button>
  </header>
  <div class="content" id="view"></div>
 </main>
</div>
<script>
let tok = localStorage.getItem('vis_tok')||'';
let cur = (location.hash||'#overview').slice(1);
let detail = null;            // selected batch id for drill-down
document.getElementById('tok').value = tok;
function saveTok(){tok=document.getElementById('tok').value.trim();localStorage.setItem('vis_tok',tok);render();}
async function get(p){const r=await fetch(p,{headers:tok?{Authorization:'Bearer '+tok}:{}});
  if(!r.ok){throw new Error(r.status==401?'unauthorized — enter token':r.status);}return r.json();}
function h(html){return html;}
function esc(s){return String(s==null?'':s).replace(/[&<>]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;'}[c]));}
function n(v,d){return (v==null||v==='')?(d==null?'—':d):v;}
function setConn(ok,msg){const e=document.getElementById('conn');e.textContent=ok?'● online':('● '+msg);
  e.style.color=ok?'var(--ok)':'var(--bad)';}
function bars(obj,max){const keys=Object.keys(obj||{});if(!keys.length)return '<div class="muted">no data</div>';
  const mx=max||Math.max(...keys.map(k=>obj[k]))||1;
  return keys.map(k=>`<div class="brow"><span class="lab">${esc(k)}</span>
    <span class="barbg"><span class="bar" style="width:${Math.round(100*obj[k]/mx)}%;display:block"></span></span>
    <span class="val">${obj[k]}</span></div>`).join('');}
function gauge(pct){const p=Math.max(0,Math.min(100,pct||0));const r=52,c=2*Math.PI*r,off=c*(1-p/100);
  const col=p>=85?'var(--ok)':p>=60?'var(--warn)':'var(--bad)';
  return `<svg width="140" height="140" viewBox="0 0 140 140"><circle cx="70" cy="70" r="${r}" fill="none" stroke="#eef1f5" stroke-width="14"/>
   <circle cx="70" cy="70" r="${r}" fill="none" stroke="${col}" stroke-width="14" stroke-linecap="round"
    stroke-dasharray="${c}" stroke-dashoffset="${off}" transform="rotate(-90 70 70)"/>
   <text x="70" y="68" text-anchor="middle" font-size="26" font-weight="700">${p.toFixed(0)}%</text>
   <text x="70" y="90" text-anchor="middle" font-size="11" fill="#5b6472">OEE</text></svg>`;}

const views={
 async overview(){const o=await get('/api/overview');const c=o.counters||{},oee=o.oee||{},a=o.analytics||{};
   applyState(o.status);
   return h(`<div class="cards">
     <div class="kpi"><div class="n">${n(c.total,0)}</div><div class="l">Total inspected</div></div>
     <div class="kpi"><div class="n ok">${n(c.passed,0)}</div><div class="l">Passed</div></div>
     <div class="kpi"><div class="n bad">${n(c.failed,0)}</div><div class="l">Rejected</div></div>
     <div class="kpi"><div class="n">${n(c.yield,'—')}%</div><div class="l">Yield</div></div></div>
    <div class="grid" style="margin-top:16px">
     <div class="card"><h3>OEE (latest batch ${esc(n(o.latest_batch&&o.latest_batch.batch_no,''))})</h3>
       <div style="display:flex;gap:18px;align-items:center">${gauge((oee.oee||0)*100)}
        <div style="flex:1">${bars({Availability:Math.round((oee.availability||0)*100),
          Performance:Math.round((oee.performance||0)*100),Quality:Math.round((oee.quality||0)*100)},100)}</div></div></div>
     <div class="card"><h3>Top reject reasons (Pareto)</h3>${bars(a.defects_by_tool)}</div>
    </div>
    <h2>Recent batches</h2><div class="card">${batchTable((await get('/api/batches')).batches.slice(0,6))}</div>`);},

 async live(){const c=await get('/api/counters');const s=await get('/api/status');applyState(s);
   let cams='';try{const bs=(await get('/api/batches')).batches;
     if(bs.length){const a=await get('/api/analytics/'+bs[0].id);
       cams=(a.per_camera||[]).map(x=>`<tr><td>${esc(x.camera)}</td><td>${x.total}</td>
         <td class="ok">${x.passed}</td><td class="bad">${x.failed}</td></tr>`).join('');}}catch(e){}
   return h(`<div class="cards">
     <div class="kpi"><div class="n">${n(c.total,0)}</div><div class="l">Total</div></div>
     <div class="kpi"><div class="n ok">${n(c.passed,0)}</div><div class="l">Pass</div></div>
     <div class="kpi"><div class="n bad">${n(c.failed,0)}</div><div class="l">Reject</div></div>
     <div class="kpi"><div class="n">${n(c.yield,'—')}%</div><div class="l">Yield</div></div></div>
    <div class="grid" style="margin-top:16px">
     <div class="card"><h3>By camera</h3><table><tr><th>Camera</th><th>Total</th><th>Pass</th><th>Fail</th></tr>
       ${cams||'<tr><td colspan=4 class="muted">no data</td></tr>'}</table></div>
     <div class="card"><h3>Reject reasons</h3>${bars(c.reject_reasons||{})}</div></div>`);},

 async batches(){if(detail!==null)return batchDetail(detail);
   const b=(await get('/api/batches')).batches;
   return h(`<div class="card">${batchTable(b,true)}</div>`);},

 async oee(){const b=(await get('/api/batches')).batches;if(!b.length)return empty();
   const o=await get('/api/oee/'+b[0].id);
   return h(`<div class="grid"><div class="card"><h3>OEE — ${esc(b[0].batch_no)}</h3>
     <div style="display:flex;gap:18px;align-items:center">${gauge((o.oee||0)*100)}
      <div style="flex:1">${bars({Availability:Math.round((o.availability||0)*100),
       Performance:Math.round((o.performance||0)*100),Quality:Math.round((o.quality||0)*100)},100)}</div></div></div>
     <div class="card"><h3>Detail</h3><table>
      ${kv('Run time (s)',o.run_time_s)}${kv('Down time (s)',o.down_time_s)}
      ${kv('Target rate',o.target_rate)}${kv('Ideal cycle (s)',o.ideal_cycle_s)}
      ${kv('Good',o.good)}${kv('Total',o.total)}</table>
      <h3 style="margin-top:14px">Downtime by reason</h3>${bars(o.downtime_by_reason||{})}</div></div>`);},

 async rejects(){const b=(await get('/api/batches')).batches;if(!b.length)return empty();
   const a=await get('/api/analytics/'+b[0].id);
   return h(`<div class="grid"><div class="card"><h3>Defects by tool (Pareto) — ${esc(a.batch_no)}</h3>${bars(a.defects_by_tool)}</div>
     <div class="card"><h3>Rejects by lane</h3>${bars(a.rejects_by_lane)}</div></div>`);},

 async serial(){const b=(await get('/api/batches')).batches;if(!b.length)return empty();
   const r=await get('/api/reconciliation/'+b[0].id);
   const dups=(r.duplicate_serials||[]).map(d=>`<tr><td>${esc(d.serial)}</td><td class="bad">${d.seen_count}×</td></tr>`).join('');
   return h(`<div class="cards">
     <div class="kpi"><div class="n">${n(r.unique_serials,0)}</div><div class="l">Unique serials</div></div>
     <div class="kpi"><div class="n ${r.duplicate_serials&&r.duplicate_serials.length?'bad':''}">${(r.duplicate_serials||[]).length}</div><div class="l">Duplicates</div></div>
     <div class="kpi"><div class="n">${n(r.reconciliation_pct,'—')}%</div><div class="l">Reconciliation</div></div>
     <div class="kpi"><div class="n ${r.reconciled?'ok':'bad'}">${r.reconciled?'✓':'✗'}</div><div class="l">Reconciled</div></div></div>
    <h2>Duplicate serials</h2><div class="card"><table><tr><th>Serial</th><th>Seen</th></tr>
     ${dups||'<tr><td colspan=2 class="muted">none — good</td></tr>'}</table></div>`);},

 async challenge(){const t=(await get('/api/challenges')).challenges;
   const rows=t.map(x=>`<tr><td>${esc(x.completed_at||'').slice(0,19)}</td><td>${esc(x.trigger)}</td>
     <td class="${x.result==='pass'?'ok':'bad'}">${esc((x.result||'').toUpperCase())}</td>
     <td>${esc(x.gate||'')}</td><td>${(x.shots||[]).length}</td></tr>`).join('');
   return h(`<div class="card"><table><tr><th>Completed</th><th>Trigger</th><th>Result</th><th>Gate</th><th>Shots</th></tr>
     ${rows||'<tr><td colspan=5 class="muted">no challenge tests yet</td></tr>'}</table></div>`);},

 async events(){const e=(await get('/api/events')).events;
   const rows=e.map(x=>`<tr><td>${esc(x.ts||'').slice(0,19)}</td>
     <td class="${x.severity==='alarm'?'bad':x.severity==='warn'?'warn':''}">${esc((x.severity||'').toUpperCase())}</td>
     <td>${esc(x.source)}</td><td>${esc(x.message)}</td></tr>`).join('');
   return h(`<div class="card"><table><tr><th>Time</th><th>Severity</th><th>Source</th><th>Message</th></tr>
     ${rows||'<tr><td colspan=4 class="muted">no events</td></tr>'}</table></div>`);},

 async audit(){const e=(await get('/api/audit')).entries;
   const rows=e.map(x=>`<tr><td>${x.id}</td><td>${esc((x.ts||'').slice(0,19))}</td><td>${esc(x.user)}</td>
     <td>${esc(x.action)}</td><td>${esc(x.entity)}</td><td>${x.signed?'✓':''}</td></tr>`).join('');
   return h(`<div class="card"><table><tr><th>#</th><th>Time</th><th>User</th><th>Action</th><th>Entity</th><th>Signed</th></tr>
     ${rows||'<tr><td colspan=6 class="muted">no entries</td></tr>'}</table></div>`);},
};

function kv(k,v){return `<tr><td class="muted">${esc(k)}</td><td>${esc(n(v))}</td></tr>`;}
function empty(){return '<div class="empty">No batches yet. Start a batch in the application.</div>';}
function batchTable(b,click){if(!b||!b.length)return '<div class="empty">No batches.</div>';
  return `<table><tr><th>Batch</th><th>Product</th><th>Status</th><th>Total</th><th>Pass</th><th>Fail</th><th>Started</th></tr>`+
   b.map(x=>`<tr class="${click?'click':''}" ${click?`onclick="openBatch(${x.id})"`:''}>
     <td>${esc(x.batch_no)}</td><td>${esc(x.product)}</td>
     <td>${x.status==='open'?'<span class="ok">open</span>':esc(x.status)}</td>
     <td>${x.total}</td><td class="ok">${x.passed}</td><td class="bad">${x.failed}</td>
     <td class="muted">${esc((x.started_at||'').slice(0,19))}</td></tr>`).join('')+`</table>`;}
async function batchDetail(id){const s=await get('/api/batch/'+id);const r=s.reconciliation||{};
  let oee={};try{oee=await get('/api/oee/'+id);}catch(e){}
  let ch=[];try{ch=(await get('/api/challenges')).challenges.filter(c=>c.batch_id===id);}catch(e){}
  return h(`<span class="back" onclick="closeBatch()">&larr; All batches</span>
   <h2>Batch ${esc(s.batch_no)} — ${esc(n(s.product,''))}</h2>
   <div class="cards">
    <div class="kpi"><div class="n">${n(s.total,0)}</div><div class="l">Inspected</div></div>
    <div class="kpi"><div class="n ok">${n(s.passed,0)}</div><div class="l">Pass</div></div>
    <div class="kpi"><div class="n bad">${n(s.failed,0)}</div><div class="l">Fail</div></div>
    <div class="kpi"><div class="n">${n(s.pass_rate,'—')}%</div><div class="l">Pass rate</div></div></div>
   <div class="grid" style="margin-top:16px">
    <div class="card"><h3>Reconciliation ${r.reconciled?'<span class="ok">✓</span>':(r.units_in?'<span class="bad">✗</span>':'')}</h3>
     <table>${kv('Units in',r.units_in)}${kv('Good',r.good)}${kv('Rejected',r.rejected)}
      ${kv('Samples',r.samples_removed)}${kv('Unaccounted',r.unaccounted)}${kv('Yield %',r.yield_pct)}
      ${kv('Reconciliation %',r.reconciliation_pct)}${kv('Unique serials',r.unique_serials)}
      ${kv('Duplicates',(r.duplicate_serials||[]).length)}</table></div>
    <div class="card"><h3>Defects (Pareto)</h3>${bars(s.defects_by_tool)}
     <h3 style="margin-top:14px">OEE</h3>${oee.oee!=null?bars({OEE:Math.round(oee.oee*100),
       Availability:Math.round((oee.availability||0)*100),Performance:Math.round((oee.performance||0)*100),
       Quality:Math.round((oee.quality||0)*100)},100):'<div class="muted">n/a</div>'}</div></div>
   <h2>Challenge tests this batch</h2><div class="card"><table><tr><th>Completed</th><th>Trigger</th><th>Result</th></tr>
    ${ch.map(c=>`<tr><td>${esc((c.completed_at||'').slice(0,19))}</td><td>${esc(c.trigger)}</td>
      <td class="${c.result==='pass'?'ok':'bad'}">${esc((c.result||'').toUpperCase())}</td></tr>`).join('')
      ||'<tr><td colspan=3 class="muted">none</td></tr>'}</table></div>`);}
function openBatch(id){detail=id;render();}
function closeBatch(){detail=null;render();}

function applyState(s){if(!s)return;const e=document.getElementById('state');
  const alarm=s.alarm;const run=s.running;
  e.className='pill '+(alarm?'alarm':run?'run':'idle');
  e.textContent=alarm?'● ALARM':run?'● RUNNING':'● Idle';}

async function render(){
  document.querySelectorAll('nav a').forEach(a=>a.classList.toggle('active',a.dataset.v===cur));
  const titles={overview:'Overview',live:'Live line',batches:'Batches',oee:'OEE & downtime',
   rejects:'Reject analytics',serial:'Serialization',challenge:'Challenge tests',events:'Events',audit:'Audit trail'};
  document.getElementById('viewtitle').textContent=titles[cur]||'Overview';
  const view=document.getElementById('view');
  try{view.innerHTML=await (views[cur]||views.overview)();setConn(true);}
  catch(e){setConn(false,e.message);
    if(String(e.message).includes('token'))view.innerHTML='<div class="empty">Enter the API token (top right) to connect.</div>';}
}
document.querySelectorAll('nav a').forEach(a=>a.onclick=()=>{cur=a.dataset.v;detail=null;location.hash=cur;render();});
window.onhashchange=()=>{cur=(location.hash||'#overview').slice(1);render();};
function tick(){document.getElementById('clock').textContent=new Date().toLocaleString();}
tick();setInterval(tick,1000);
render();setInterval(render,4000);   // auto-refresh the active view
</script></body></html>"""
