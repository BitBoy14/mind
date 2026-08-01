<?php
declare(strict_types=1);
require __DIR__ . '/lib.php';
$authed = is_authed();
?><!doctype html>
<html lang="no">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>MIND – hovedhjernen</title>
<style>
:root {
  --bg:#E8DCC4; --panel:#F4ECDA; --panel2:#E4D5B0; --border:#8F754A;
  --text:#3E2F1C; --dim:#7A5C3E; --accent:#B85C38; --accent-text:#8B3E22; --green:#5F7A3D;
  --red:#9C3A29; --amber:#8A5A18; --amber-dark:#6E4610; --purple:#7A4A6E;
}
* { box-sizing:border-box; }
body { margin:0; background:var(--bg); color:var(--text);
  font:14px/1.5 -apple-system,'Segoe UI',Roboto,sans-serif; }
a { color:var(--accent-text); text-decoration:none; }
svg.ic { vertical-align:-2px; flex-shrink:0; }
button { background:var(--panel2); color:var(--text); border:1px solid var(--border);
  border-radius:6px; padding:5px 11px; cursor:pointer; font-size:13px; }
button:hover { border-color:var(--accent); }
button.primary { background:var(--accent); color:#fff; border-color:var(--accent); font-weight:600; }
button.danger { border-color:var(--red); color:var(--red); }
input,select,textarea { background:var(--panel2); color:var(--text);
  border:1px solid var(--border); border-radius:6px; padding:6px 9px; font-size:13px; }
input:focus,textarea:focus { outline:none; border-color:var(--accent); }

#topbar { display:flex; align-items:center; gap:12px; padding:9px 16px;
  background:var(--panel); border-bottom:1px solid var(--border);
  position:sticky; top:0; z-index:50; flex-wrap:wrap; }
#topbar .logo { font-size:17px; font-weight:700; letter-spacing:2px; }
.pulse-dot { display:inline-block; width:10px; height:10px; border-radius:50%;
  background:var(--red); margin-right:5px; vertical-align:-1px; }
.pulse-dot.alive { background:var(--green); animation:beat 1.6s infinite; }
@keyframes beat { 0%,100%{transform:scale(1);opacity:1} 50%{transform:scale(1.45);opacity:.6} }
.spacer { flex:1; }
.badge { background:var(--red); color:#fff; border-radius:10px; padding:0 7px;
  font-size:11px; font-weight:700; }
.muted { color:var(--dim); font-size:12px; }
.tokline { font-size:12px; color:var(--dim); text-align:right; line-height:1.3; }

#grid { display:grid; grid-template-columns:1fr 1fr 400px; gap:12px;
  padding:12px 16px; align-items:start; }
@media (max-width:1250px){ #grid{ grid-template-columns:1fr 1fr; } #chatpanel{grid-column:1/-1;} }
@media (max-width:850px){ #grid{ grid-template-columns:1fr; } }
.panel { background:var(--panel); border:1px solid var(--border); border-radius:10px;
  margin-bottom:12px; overflow:hidden; }
.panel h2 { margin:0; padding:9px 14px; font-size:13px; text-transform:uppercase;
  letter-spacing:1px; color:var(--dim); border-bottom:1px solid var(--border);
  display:flex; align-items:center; gap:8px; }
#grid > div:not(#chatpanel) > .panel > h2 { background:#F8F0DC; color:var(--text); }
#grid > div:not(#chatpanel) > .panel > h2 .muted { color:#6B5636; }
.panel .body { padding:10px 14px; max-height:460px; overflow-y:auto; }
.item { border-bottom:1px solid var(--border); padding:8px 0; }
.item:last-child { border-bottom:none; }
.ts { color:var(--dim); font-size:11px; }
.kindtag { font-size:10px; text-transform:uppercase; border:1px solid var(--border);
  border-radius:4px; padding:0 5px; color:var(--dim); margin-right:5px; }
.status-running { color:var(--amber); } .status-queued { color:var(--dim); }
.status-done { color:var(--green); } .status-failed,.status-cancelled { color:var(--red); }
.meter { height:9px; background:var(--panel2); border-radius:5px; overflow:hidden; margin:6px 0; }
.meter > div { height:100%; background:var(--accent); }
.tabs { display:flex; gap:4px; margin-bottom:8px; flex-wrap:wrap; }
.tabs button.active { border-color:var(--accent); color:var(--accent-text); }
.stagn { background:#F2D9A8; border:1px solid var(--amber); color:var(--amber-dark);
  padding:7px 10px; border-radius:7px; margin-bottom:8px; font-size:13px; }

#adminband { margin:12px 16px 0; }
#adminband .panel { border-color:var(--purple); }
#adminband h2 { color:var(--purple); }

/* chat */
#chatpanel .panel { display:flex; flex-direction:column; height:calc(100vh - 90px); margin-bottom:0; }
#chatlog { flex:1; overflow-y:auto; padding:12px; display:flex; flex-direction:column; gap:8px; }
.msg { max-width:88%; padding:7px 11px; border-radius:10px; white-space:pre-wrap; word-break:break-word; }
.msg.user { align-self:flex-end; background:var(--accent); color:#fff; }
.msg.responder { align-self:flex-start; background:var(--panel2); }
.msg.brain { align-self:flex-start; background:#EAD9E2; border:1px solid var(--purple); }
.msg.system { align-self:center; background:transparent; color:var(--dim); font-size:12px; }
.msg .who { font-size:10px; color:var(--dim); margin-bottom:2px; }
#chatform { display:flex; gap:8px; padding:10px; border-top:1px solid var(--border); }
#chatinput { flex:1; resize:none; height:60px; }

/* modal */
.modal-back { position:fixed; inset:0; background:rgba(62,47,28,.55); z-index:100;
  display:none; align-items:center; justify-content:center; padding:20px; }
.modal-back.open { display:flex; }
.modal { background:var(--panel); border:1px solid var(--border); border-radius:12px;
  max-width:820px; width:100%; max-height:88vh; overflow-y:auto; padding:18px 20px; }
.modal h3 { margin-top:0; }
.formrow { display:flex; gap:10px; align-items:center; margin-bottom:10px; flex-wrap:wrap; }
.formrow label { width:150px; color:var(--dim); font-size:13px; }
pre.doc { background:var(--panel2); border:1px solid var(--border); border-radius:8px;
  padding:12px; white-space:pre-wrap; word-break:break-word; font-size:12.5px; max-height:55vh; overflow:auto; }
.clicky { cursor:pointer; }
.clicky:hover { color:var(--accent-text); }

#login { max-width:340px; margin:16vh auto; text-align:center; }
#login input { width:100%; margin:12px 0; text-align:center; }
</style>
</head>
<body>

<?php if (!$authed): ?>
<div id="login">
  <div class="logo" style="font-size:34px; letter-spacing:8px;">MIND</div>
  <p class="muted">Persistent hovedhjerne · logg inn</p>
  <input type="password" id="pw" placeholder="Passord" autofocus
         onkeydown="if(event.key==='Enter')doLogin()">
  <button class="primary" style="width:100%" onclick="doLogin()">Logg inn</button>
  <p id="loginerr" style="color:var(--red)"></p>
</div>
<script>
async function doLogin(){
  const r = await fetch('api/action.php', {method:'POST',
    body: JSON.stringify({action:'login', password: document.getElementById('pw').value})});
  const j = await r.json().catch(()=>({}));
  if (j.ok) location.reload();
  else document.getElementById('loginerr').textContent = j.error || 'Innlogging feilet';
}
</script>
<?php else: ?>

<div id="topbar">
  <span class="logo">MIND</span>
  <span id="pulseinfo"><span class="pulse-dot"></span><span class="muted">venter …</span></span>
  <button id="runbtn" onclick="toggleRunning()">…</button>
  <button onclick="toggleJarvis()" id="jarvisbtn">Jarvis: ?</button>
  <span id="adminbadge" style="display:none" class="clicky" onclick="scrollToAdmin()">
    <svg class="ic" width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M14.7 6.3a1 1 0 0 0 0 1.4l1.6 1.6a1 1 0 0 0 1.4 0l3.77-3.77a6 6 0 0 1-7.94 7.94l-6.91 6.91a2.12 2.12 0 0 1-3-3l6.91-6.91a6 6 0 0 1 7.94-7.94l-3.76 3.76z"/></svg>
    <span class="badge" id="admincount">0</span></span>
  <span id="stagnbadge" style="display:none" title="Hjernen har flagget stagnasjon">
    <svg class="ic" width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M12 3.5 2 20h20L12 3.5z"/><path d="M12 10v4"/><path d="M12 17h.01"/></svg>
    tomgang</span>
  <span class="spacer"></span>
  <span class="tokline" id="tokline">tokens …</span>
  <button title="Nullstill token-teller" onclick="resetTokens()">↺</button>
  <button onclick="openSettings()"><svg class="ic" width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="3"/><path d="M19.4 13a7.97 7.97 0 0 0 0-2l2.1-1.6-2-3.4-2.5 1a8 8 0 0 0-1.7-1L14.9 3h-4l-.4 2.9a8 8 0 0 0-1.7 1l-2.5-1-2 3.4L6.4 11a7.97 7.97 0 0 0 0 2l-2.1 1.6 2 3.4 2.5-1a8 8 0 0 0 1.7 1l.4 2.9h4l.4-2.9a8 8 0 0 0 1.7-1l2.5 1 2-3.4L19.4 13z"/></svg> Innstillinger</button>
  <button onclick="doLogout()">Logg ut</button>
</div>

<div id="adminband"></div>

<div id="grid">
  <div>
    <div class="panel">
      <h2><svg class="ic" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="9"/><path d="M12 7v5l3.5 2"/></svg> Nå <span class="muted" id="cyclets"></span></h2>
      <div class="body" id="nowbody"></div>
    </div>
    <div class="panel">
      <h2><svg class="ic" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M3 9c2.5 0 2.5 3 5 3s2.5-3 5-3 2.5 3 5 3 2.5-3 5-3"/><path d="M3 17c2.5 0 2.5 3 5 3s2.5-3 5-3 2.5 3 5 3 2.5-3 5-3"/></svg> Tankestrøm</h2>
      <div class="body" id="thoughtsbody"></div>
    </div>
  </div>
  <div>
    <div class="panel">
      <h2><svg class="ic" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="5" y="4" width="14" height="17" rx="2"/><path d="M9 3.5h6a1 1 0 0 1 1 1V6H8V4.5a1 1 0 0 1 1-1z"/><path d="M8.5 13l2.2 2.2L15.5 11"/></svg> Agenter og oppgaver</h2>
      <div class="body" id="agentsbody"></div>
    </div>
    <div class="panel">
      <h2><svg class="ic" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M9 4a3 3 0 0 0-3 3 3 3 0 0 0-1 5.8A3 3 0 0 0 8 17a3 3 0 0 0 3 3V7a3 3 0 0 0-2-3z"/><path d="M15 4a3 3 0 0 1 3 3 3 3 0 0 1 1 5.8A3 3 0 0 1 16 17a3 3 0 0 1-3 3V7a3 3 0 0 1 2-3z"/></svg> Minnet</h2>
      <div class="body" id="membody"></div>
    </div>
  </div>
  <div id="chatpanel">
    <div class="panel">
      <h2>Chat <span class="muted">(/clear tømmer konteksten)</span></h2>
      <div id="chatlog"></div>
      <div id="chatform">
        <textarea id="chatinput" placeholder="Skriv til MIND …"
          onkeydown="if(event.key==='Enter'&&!event.shiftKey){event.preventDefault();sendChat();}"></textarea>
        <button class="primary" onclick="sendChat()">Send</button>
      </div>
    </div>
  </div>
</div>

<div class="modal-back" id="modalback" onclick="if(event.target===this)closeModal()">
  <div class="modal" id="modalbody"></div>
</div>

<script>
const ICO = {
  wrench: '<svg class="ic" width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M14.7 6.3a1 1 0 0 0 0 1.4l1.6 1.6a1 1 0 0 0 1.4 0l3.77-3.77a6 6 0 0 1-7.94 7.94l-6.91 6.91a2.12 2.12 0 0 1-3-3l6.91-6.91a6 6 0 0 1 7.94-7.94l-3.76 3.76z"/></svg>',
  gear: '<svg class="ic" width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="3"/><path d="M19.4 13a7.97 7.97 0 0 0 0-2l2.1-1.6-2-3.4-2.5 1a8 8 0 0 0-1.7-1L14.9 3h-4l-.4 2.9a8 8 0 0 0-1.7 1l-2.5-1-2 3.4L6.4 11a7.97 7.97 0 0 0 0 2l-2.1 1.6 2 3.4 2.5-1a8 8 0 0 0 1.7 1l.4 2.9h4l.4-2.9a8 8 0 0 0 1.7-1l2.5 1 2-3.4L19.4 13z"/></svg>',
  comment: '<svg class="ic" width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M21 11.5a8.4 8.4 0 0 1-.9 3.8 8.5 8.5 0 0 1-7.6 4.7 8.4 8.4 0 0 1-3.8-.9L3 21l1.9-5.7a8.4 8.4 0 0 1-.9-3.8 8.5 8.5 0 0 1 4.7-7.6 8.4 8.4 0 0 1 3.8-.9h.5a8.48 8.48 0 0 1 8 8v.5z"/></svg>',
  folder: '<svg class="ic" width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M3 7a2 2 0 0 1 2-2h4l2 2h8a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V7z"/></svg>',
  thought: '<svg class="ic" width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M7 15a4 4 0 1 1 .4-8 5 5 0 0 1 9.6 1.6A3.5 3.5 0 0 1 17 15H7z"/><circle cx="7" cy="19" r="1"/><circle cx="10.5" cy="21" r="0.8"/></svg>',
  file: '<svg class="ic" width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M14 3H7a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V8z"/><path d="M14 3v5h5"/></svg>',
  play: '<svg class="ic" width="12" height="12" viewBox="0 0 24 24" fill="currentColor" stroke="none"><path d="M6 4l14 8-14 8V4z"/></svg>',
  pause: '<svg class="ic" width="12" height="12" viewBox="0 0 24 24" fill="currentColor" stroke="none"><rect x="6" y="4" width="4" height="16"/><rect x="14" y="4" width="4" height="16"/></svg>',
  bolt: '<svg class="ic" width="12" height="12" viewBox="0 0 24 24" fill="currentColor" stroke="none"><path d="M13 2 3 14h7l-1 8 11-14h-8l1-6z"/></svg>',
};
let S = null;            // siste state
const cache = {};        // render-cache per seksjon
const esc = s => String(s ?? '').replace(/[&<>"']/g,
  c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const ago = ts => {
  if (!ts) return '–';
  const d = Math.max(0, (Date.now()/1000) - ts);
  if (d < 60) return Math.round(d) + 's siden';
  if (d < 3600) return Math.round(d/60) + 'm siden';
  if (d < 86400) return Math.round(d/3600) + 't siden';
  return Math.round(d/86400) + 'd siden';
};
const fmtN = n => (n||0).toLocaleString('nb-NO');

async function api(payload){
  const r = await fetch('api/action.php', {method:'POST', body: JSON.stringify(payload)});
  const j = await r.json().catch(()=>({ok:false,error:'ugyldig svar'}));
  if (!j.ok && j.error) alert(j.error);
  return j;
}

function render(id, slice, html){
  const key = JSON.stringify(slice);
  if (cache[id] === key) return;
  cache[id] = key;
  document.getElementById(id).innerHTML = html;
}

async function poll(){
  try {
    const r = await fetch('api/state.php');
    if (r.status === 401) { location.reload(); return; }
    S = await r.json();
    draw();
  } catch(e) { /* nettverksglipp – prøver igjen */ }
}

function draw(){
  const st = S.state, se = S.settings;

  // topbar
  const alive = st.daemon_alive;
  document.getElementById('pulseinfo').innerHTML =
    `<span class="pulse-dot ${alive?'alive':''}"></span>` +
    `<span class="muted">${alive ? 'puls ' + ago(st.last_pulse_ts) + ' · rytme ' + st.pulse_interval + 's'
                                 : 'daemon svarer ikke'}</span>`;
  const run = se.running;
  const rb = document.getElementById('runbtn');
  rb.innerHTML = run ? ICO.pause + ' Pause' : ICO.play + ' Start';
  rb.className = run ? '' : 'primary';
  document.getElementById('jarvisbtn').textContent = 'Jarvis: ' + (se.jarvis_link ? 'PÅ' : 'AV');
  const t = S.tokens;
  document.getElementById('tokline').innerHTML =
    `↑ inn ${fmtN(t.input)} · ↓ ut ${fmtN(t.output)}<br>${ICO.bolt} cache ${fmtN(t.cache_read)} lest / ${fmtN(t.cache_creation)} skrevet`;
  const pend = S.admin.pending.length;
  document.getElementById('adminbadge').style.display = pend ? '' : 'none';
  document.getElementById('admincount').textContent = pend;
  document.getElementById('stagnbadge').style.display = st.stagnation ? '' : 'none';

  drawAdmin(); drawNow(); drawThoughts(); drawAgents(); drawMemory(); drawChat();
}

function drawAdmin(){
  const p = S.admin.pending;
  render('adminband', p, !p.length ? '' : `
    <div class="panel"><h2>${ICO.wrench} Forslag til godkjenning (${p.length})</h2><div class="body">` +
    p.map(x => `
      <div class="item">
        <span class="kindtag">${esc(x.kind)}</span> <b>${esc(x.title)}</b>
        <div class="muted" style="white-space:pre-wrap">${esc(x.body)}</div>
        ${x.payload && x.payload.prompt_tekst ? `<details><summary class="muted clicky">ny prompttekst</summary><pre class="doc">${esc(x.payload.prompt_tekst)}</pre></details>` : ''}
        <div style="margin-top:6px">
          <button class="primary" onclick="decide('${x._id}',true)">Godkjenn</button>
          <button class="danger" onclick="decide('${x._id}',false)">Avvis</button>
          <span class="ts">${ago(x.ts)}</span>
        </div>
      </div>`).join('') + '</div></div>');
}

function drawNow(){
  const st = S.state;
  const res = st.resources;
  const cyc = S.cycles;
  document.getElementById('cyclets').textContent =
    st.last_cycle_ts ? '· siste syklus ' + ago(st.last_cycle_ts) : '';
  render('nowbody', [st.working_note, st.stagnation, res, cyc], `
    ${st.stagnation ? '<div class="stagn">Hjernen melder ærlig tomgang: ingen reell fremdrift å simulere akkurat nå.</div>' : ''}
    <div class="item"><b>Hva jeg holder på med:</b>
      <div style="white-space:pre-wrap">${esc(st.working_note || '(ingenting notert ennå)')}</div></div>
    ${res ? `<div class="item muted">Server: disk ${res.disk_pct?.toFixed(0)}% · RAM ${res.mem_pct?.toFixed(0)}% · load ${res.load?.toFixed(1)}</div>` : ''}
    ${cyc.map(c => `
      <div class="item">
        <span class="kindtag">${esc(c.kind)}</span><span class="ts">${ago(c.ts)}</span>
        <div style="white-space:pre-wrap">${esc(c.observations || '')}</div>
        ${(c.decisions||[]).length ? `<div class="muted">→ ${(c.decisions||[]).map(esc).join(' · ')}</div>` : ''}
      </div>`).join('') || '<div class="muted">Ingen sykluser ennå.</div>'}`);
}

function drawThoughts(){
  const th = S.thoughts;
  render('thoughtsbody', th, th.map(x => `
    <div class="item">
      <span class="kindtag">${esc(x.kind)}</span><span class="ts">${ago(x.ts)}</span>
      <div style="white-space:pre-wrap">${esc(x.text)}</div>
      ${(x.comments||[]).map(c => `<div class="muted" style="margin-left:14px">${ICO.comment} ${esc(c.text)} <span class="ts">${ago(c.ts)}</span></div>`).join('')}
      <span class="muted clicky" onclick="commentThought('${x._id}')">${ICO.comment} Kommentér</span>
    </div>`).join('') || '<div class="muted">Tankestrømmen er tom – hjernen har ikke tenkt høyt ennå.</div>');
}

function drawAgents(){
  const a = S.agents;
  const row = t => {
    const dur = t.started_ts ? Math.round(((t.finished_ts || Date.now()/1000) - t.started_ts)/60) : null;
    return `<div class="item">
      <span class="status-${esc(t.status)}">●</span> <b>${esc(t.title)}</b>
      <span class="kindtag">${esc(t.type)}</span>
      <span class="ts">${esc(t.status)}${dur !== null ? ' · ' + dur + ' min' : ''} · ${ago(t.finished_ts || t.started_ts || t.created_ts)}</span>
      ${t.progress ? `<div class="muted">${esc(t.progress)}</div>` : ''}
      ${t.result ? `<div class="muted" style="white-space:pre-wrap">${esc(String(t.result).slice(0,300))}</div>` : ''}
      <span class="muted clicky" onclick="openTask('${t._id}')">${ICO.folder} detaljer/filer</span>
    </div>`;
  };
  render('agentsbody', a,
    (a.running.length + a.queued.length + a.finished.length) === 0
      ? '<div class="muted">Ingen agentoppgaver ennå.</div>'
      : a.running.map(row).join('') + a.queued.map(row).join('') + a.finished.map(row).join(''));
}

let memTab = 'seksjoner';
function drawMemory(){
  const m = S.memory;
  const pct = Math.min(100, Math.round(100 * m.total_tokens / m.max_tokens));
  const tabs = ['seksjoner','detaljer','arkiv','logg','søk'];
  let inner = '';
  if (memTab === 'seksjoner') {
    inner = m.sections.map(s => `
      <div class="item clicky" onclick="openMemDoc('main','${s._id}')">
        <b>${esc(s.title)}</b>
        <span class="ts">viktighet ${s.importance} · ${fmtN(s.tokens)} tok · brukt ${s.use_count||0}x · sist ${ago(s.last_used_ts)}</span>
      </div>`).join('') || '<div class="muted">Tomt.</div>';
  } else if (memTab === 'logg') {
    inner = m.log.map(l => `
      <div class="item"><span class="kindtag">${esc(l.action)}</span>
      ${esc(l.detail)} <span class="ts">${ago(l.ts)} · ${esc(l.actor)}</span></div>`).join('')
      || '<div class="muted">Ingen kuratering logget ennå.</div>';
  } else if (memTab === 'søk') {
    inner = `<div class="formrow"><input id="memq" placeholder="Søk i hele minnet …" style="flex:1"
      onkeydown="if(event.key==='Enter')memSearch()"><button onclick="memSearch()">Søk</button></div>
      <div id="memhits"></div>`;
  } else {
    inner = `<div id="memlistbox" class="muted">laster …</div>`;
    loadMemList(memTab === 'detaljer' ? 'details' : 'archive');
  }
  render('membody', [m.sections, m.log, m.total_tokens, memTab, m.details_count, m.archive_count], `
    <div class="muted">Størrelse: ${fmtN(m.total_tokens)} / ${fmtN(m.max_tokens)} tokens
      · ${m.details_count} detaljminner · ${m.archive_count} i Arkivet</div>
    <div class="meter"><div style="width:${pct}%; background:${pct>85?'var(--red)':pct>60?'var(--amber)':'var(--accent)'}"></div></div>
    <div class="tabs">${tabs.map(x =>
      `<button class="${memTab===x?'active':''}" onclick="memTab='${x}';delete cache.membody;drawMemory()">${x}</button>`).join('')}</div>
    ${inner}`);
}

async function loadMemList(col){
  const j = await api({action:'memlist', col});
  const box = document.getElementById('memlistbox');
  if (!box || !j.ok) return;
  box.innerHTML = (j.docs||[]).map(d => `
    <div class="item clicky" style="color:var(--text)" onclick="openMemDoc('${col}','${d._id}')">
      <b>${esc(d.title)}</b> <span class="ts">${fmtN(d.tokens)} tok · ${ago(d.created_ts || d.archived_ts)}</span>
    </div>`).join('') || '<div class="muted">Tomt.</div>';
}

async function memSearch(){
  const q = document.getElementById('memq').value.trim();
  if (!q) return;
  const j = await api({action:'memsearch', q});
  document.getElementById('memhits').innerHTML = (j.hits||[]).map(h => `
    <div class="item clicky" onclick="openMemDoc('${h._col}','${h._id}')">
      <span class="kindtag">${esc(h._col)}</span><b>${esc(h.title)}</b></div>`).join('')
    || '<div class="muted">Ingen treff.</div>';
}

let chatCount = -1;
function drawChat(){
  const log = document.getElementById('chatlog');
  const key = JSON.stringify(S.chat);
  if (cache.chat === key) return;
  cache.chat = key;
  const nearBottom = log.scrollHeight - log.scrollTop - log.clientHeight < 120;
  log.innerHTML = S.chat.map(m => {
    const cls = {user:'user', responder:'responder', brain:'brain', system:'system'}[m.role] || 'system';
    const whoIcon = m.role === 'brain' ? ICO.thought : '';
    const whoText = m.role === 'brain' ? (m.marker || 'Hovedhjernen')
                  : m.role === 'responder' ? 'MIND' : '';
    return `<div class="msg ${cls}">${whoText ? `<div class="who">${whoIcon} ${esc(whoText)}</div>` : ''}${esc(m.text)}</div>`;
  }).join('') || '<div class="msg system">Chatten er tom. Si hei!</div>';
  if (nearBottom || chatCount === -1) log.scrollTop = log.scrollHeight;
  chatCount = S.chat.length;
}

async function sendChat(){
  const inp = document.getElementById('chatinput');
  const text = inp.value.trim();
  if (!text) return;
  inp.value = '';
  if (text !== '/clear') {
    // optimistisk visning
    const log = document.getElementById('chatlog');
    log.insertAdjacentHTML('beforeend', `<div class="msg user">${esc(text)}</div>`);
    log.scrollTop = log.scrollHeight;
  }
  await api({action:'chat_send', text});
  poll();
}

async function commentThought(id){
  const text = prompt('Kommentar til hjernen (går rett inn i neste pulsslag):');
  if (text && text.trim()) { await api({action:'comment_thought', id, text:text.trim()}); poll(); }
}
async function decide(id, approve){
  await api({action:'proposal_decide', id, approve}); poll();
}
async function toggleRunning(){
  await api({action:'toggle_running', running: !S.settings.running}); poll();
}
async function toggleJarvis(){
  const on = !S.settings.jarvis_link;
  if (on && !confirm('Slå PÅ Jarvis-koblingen? Hjernen får da lese Jarvis-status og legge ideer i Jarvis-køen.')) return;
  await api({action:'toggle_jarvis', on}); poll();
}
async function resetTokens(){
  if (confirm('Nullstille token-telleren?')) { await api({action:'reset_tokens'}); poll(); }
}
async function doLogout(){ await api({action:'logout'}); location.reload(); }
function scrollToAdmin(){ document.getElementById('adminband').scrollIntoView({behavior:'smooth'}); }

// ------- modaler -------
function openModal(html){
  document.getElementById('modalbody').innerHTML = html;
  document.getElementById('modalback').classList.add('open');
}
function closeModal(){ document.getElementById('modalback').classList.remove('open'); }

async function openMemDoc(col, id){
  const j = await api({action:'memdoc', col: col === 'seksjoner' ? 'main' : col, id});
  if (!j.ok) return;
  const d = j.doc;
  openModal(`<h3>${esc(d.title)}</h3>
    <p class="muted">${col} · ${fmtN(d.tokens)} tokens
      ${d.importance ? '· viktighet ' + d.importance : ''}
      ${(d.pointers||[]).length ? '· pekere: ' + d.pointers.map(esc).join(', ') : ''}</p>
    <pre class="doc">${esc(d.content)}</pre>
    <button onclick="closeModal()">Lukk</button>`);
}

async function openTask(id){
  const j = await api({action:'task_files', id});
  if (!j.ok) return;
  openModal(`<h3>Agentoppgave</h3>
    <details open><summary class="muted clicky">Oppdrag</summary>
      <pre class="doc">${esc(j.brief)}</pre></details>
    ${j.result ? `<details open><summary class="muted clicky">Resultat</summary><pre class="doc">${esc(j.result)}</pre></details>` : ''}
    <p><b>Filer:</b></p>
    <div>${(j.files||[]).map(f =>
      `<div class="clicky" onclick="openFile('${id}','${esc(f)}')">${ICO.file} ${esc(f)}</div>`).join('')
      || '<span class="muted">ingen filer</span>'}</div>
    <p><button onclick="closeModal()">Lukk</button></p>`);
}

async function openFile(task, path){
  const j = await api({action:'read_file', task, path});
  if (!j.ok) return;
  openModal(`<h3>${ICO.file} ${esc(path)}</h3><pre class="doc">${esc(j.content)}</pre>
    <button onclick="closeModal()">Lukk</button>`);
}

function openSettings(){
  const se = S.settings;
  const opts = sel => S.models.map(m =>
    `<option value="${esc(m)}" ${m===sel?'selected':''}>${esc(m)}</option>`).join('');
  openModal(`<h3>${ICO.gear} Innstillinger</h3>
    <div class="formrow"><label>Motor</label>
      <label style="width:auto"><input type="radio" name="engine" value="api" ${se.engine==='api'?'checked':''}> A: Anthropic API</label>
      <label style="width:auto"><input type="radio" name="engine" value="claude_code" ${se.engine==='claude_code'?'checked':''}> B: Claude Code headless</label>
    </div>
    <div class="formrow"><label>Anthropic API-nøkkel</label>
      <input type="password" id="set_apikey" placeholder="${se.api_key_set ? '•••••• (lagret – skriv for å bytte)' : 'sk-ant-…'}" style="flex:1"></div>
    <div class="formrow"><label>Hovedhjernen</label><select id="set_brain">${opts(se.brain_model)}</select></div>
    <div class="formrow"><label>Agenter</label><select id="set_agent">${opts(se.agent_model)}</select></div>
    <div class="formrow"><label>Responder</label><select id="set_responder">${opts(se.responder_model)}</select></div>
    <div class="formrow"><label>Puls-vakten</label><select id="set_pulse">${opts(se.pulse_model)}</select></div>
    <div class="formrow"><label>Maks parallelle agenter</label>
      <input type="number" id="set_maxagents" value="${se.max_parallel_agents}" min="1" max="23" style="width:80px"></div>
    <div class="formrow"><label>Natt-økt (time)</label>
      <input type="number" id="set_night" value="${se.night_curation_hour}" min="0" max="23" style="width:80px"></div>
    <p><button class="primary" onclick="saveSettings()">Lagre</button>
       <button onclick="api({action:'refresh_models'}).then(()=>{poll();closeModal();})">↻ Oppdater modelliste</button>
       <button onclick="closeModal()">Avbryt</button></p>`);
}

async function saveSettings(){
  const payload = {
    action: 'save_settings',
    engine: document.querySelector('input[name=engine]:checked')?.value,
    brain_model: document.getElementById('set_brain').value,
    agent_model: document.getElementById('set_agent').value,
    responder_model: document.getElementById('set_responder').value,
    pulse_model: document.getElementById('set_pulse').value,
    max_parallel_agents: document.getElementById('set_maxagents').value,
    night_curation_hour: document.getElementById('set_night').value,
  };
  const key = document.getElementById('set_apikey').value.trim();
  if (key) payload.api_key = key;
  await api(payload);
  closeModal(); poll();
}

poll();
setInterval(poll, 2500);
</script>
<?php endif; ?>
</body>
</html>
