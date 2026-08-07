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
/* Hindrer at mobile nettlesere blåser opp skriftstørrelser på egen hånd. */
html { -webkit-text-size-adjust:100%; text-size-adjust:100%; }
body { margin:0; background:var(--bg); color:var(--text);
  font:14px/1.5 -apple-system,'Segoe UI',Roboto,sans-serif;
  /* arves av alt innhold: lange URL-er/ID-er bryter i stedet for å
     sprenge kolonnen og gi horisontal scrolling på smal skjerm */
  overflow-wrap:break-word; }
a { color:var(--accent-text); text-decoration:none; }
svg.ic { vertical-align:-2px; flex-shrink:0; }
button { background:var(--panel2); color:var(--text); border:1px solid var(--border);
  border-radius:6px; padding:5px 11px; cursor:pointer; font-size:13px; }
button:hover { border-color:var(--accent); }
button.primary { background:var(--accent); color:#fff; border-color:var(--accent); font-weight:600; }
button.danger { border-color:var(--red); color:var(--red); }
/* Innsiktssiden er et eget dokument, ikke en modal i enside-appen, så den må
   være en ekte <a> for å kunne navigeres til. Den skal likevel se ut og
   oppføre seg som knappene den står blant. */
a.knappelenke { display:inline-flex; align-items:center; gap:5px;
  background:var(--panel2); color:var(--text); border:1px solid var(--border);
  border-radius:6px; padding:5px 11px; font-size:13px; text-decoration:none; }
a.knappelenke:hover { border-color:var(--accent); }
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
/* Tekst som bare er med når det er plass (skrivebord), og motstykket som bare
   er med når det er trangt (telefon). Se mobilseksjonen nederst. */
.mobonly { display:none; }

#grid { display:grid; grid-template-columns:1fr 1fr 400px; gap:12px;
  padding:12px 16px; align-items:start; }
/* min-width:0 opphever grid-elementers auto-minimum, som ellers lar bredt
   innhold presse hele rutenettet ut i bredden. */
#grid > div { min-width:0; }
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
/* avbrudd bestilt, prosessen ennå ikke bekreftet død – og avbrudd som slo feil */
.status-cancelling { color:var(--amber); } .status-cancel_failed { color:var(--purple); }
/* Verktøystatuser. Egne klasser fordi de betyr noe annet enn oppgavestatusene:
   «i drift» er en varig tilstand, ikke et ferdig resultat. */
.vstatus { font-size:10px; text-transform:uppercase; border-radius:4px;
  padding:0 5px; border:1px solid currentColor; margin-right:5px; }
.v-drift { color:var(--green); } .v-bygging { color:var(--amber); }
.v-prototyp { color:var(--purple); } .v-pauset { color:var(--dim); }
.v-avviklet { color:var(--red); }
.vsti { font-family:ui-monospace,SFMono-Regular,Menlo,monospace; font-size:12px;
  color:var(--dim); }
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

/* dra-og-slipp i chatten */
#chatpanel .panel { position:relative; }
/* Overlegget ligger over hele chatpanelet, men er usynlig for musen: uten
   pointer-events:none ville det selv stjålet drop-hendelsen det annonserer. */
#chatdrop { position:absolute; inset:6px; z-index:6; display:none;
  align-items:center; justify-content:center; pointer-events:none;
  border:2px dashed var(--accent); border-radius:10px;
  background:rgba(184,92,56,.12); color:var(--accent-text);
  font-size:14px; font-weight:600; letter-spacing:.4px; }
#chatpanel.dragover #chatdrop { display:flex; }
#chattray { display:flex; flex-wrap:wrap; gap:6px; padding:8px 10px 0; }
#chattray:empty { display:none; }
.att { display:flex; align-items:center; gap:6px; max-width:220px;
  background:var(--panel2); border:1px solid var(--border);
  border-radius:8px; padding:4px 7px; font-size:12px; }
.att img { width:34px; height:34px; object-fit:cover; border-radius:5px; display:block; }
.att .nm { overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }
.att .x { cursor:pointer; color:var(--dim); font-weight:700; padding:0 2px; }
.att .x:hover { color:var(--red); }
/* vedlegg inne i en chatboble */
.msg .atts { display:flex; flex-wrap:wrap; gap:6px; margin-top:6px; }
.msg .atts img { max-width:200px; max-height:160px; border-radius:7px; display:block; }
.msg .atts .fil { display:inline-flex; align-items:center; gap:5px;
  background:rgba(255,255,255,.22); border:1px solid rgba(255,255,255,.35);
  border-radius:7px; padding:4px 8px; font-size:12px; color:inherit; }
.msg.responder .atts .fil, .msg.brain .atts .fil {
  background:var(--panel); border-color:var(--border); }

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

/* ======================= mobil (telefon, ≤768px) =======================
   Ren responsivitet: layout, trykkmål og lesbarhet. Ørkentemaets farger,
   rammer og typografi er uendret, og ingenting her treffer skrivebordet.
   768px er felles mobilgrense for hele fila – se app-modus nederst. */
@media (max-width:768px){

  /* Topplinjen brytes over flere rader på telefon og la den ta ~20 % av
     skjermen i all evighet. Den scroller heller bort her; innholdet er
     viktigere enn statuslinjen på en 844px høy skjerm. */
  #topbar { position:static; padding:8px 10px; gap:7px; }
  #topbar .logo { font-size:16px; }
  #topbar button { padding:9px 11px; }
  /* Ikonene står støtt alene; ordene ved siden av koster en hel knapperad.
     .nomob er det samme for tekst som ikke sitter i en knapp, og .mobonly er
     den korte varianten som trer inn i stedet. */
  .btxt, .nomob { display:none; }
  .mobonly { display:inline; }
  .spacer { display:none; }
  /* Token-linjen legges NEDERST (order) i stedet for midt imellom knappene.
     Ellers deler den knapperaden i to og tvinger fram en tredje rad. To
     knapperader + én tokenrad gir ~145px mot ~200px før – på en 667px skjerm
     er det en drøy halv panelhøyde spart. Topplinjen er ikke sticky her, så
     resten scroller uansett bort. */
  .tokline { flex:1 1 100%; text-align:left; order:99;
    font-size:11.5px; line-height:1.25; }

  /* Trykkvennlige mål: minst 44px høyde på alt som kan trykkes. */
  button { min-height:44px; padding:9px 14px; font-size:14px; }
  /* 16px i skrivefelt er terskelen der iOS Safari slutter å auto-zoome
     ved fokus – derfor akkurat 16, ikke 15. Radio/avkryssing holdes utenfor
     så de ikke blir 44px høye bokser. */
  input:not([type=radio]):not([type=checkbox]), select, textarea {
    min-height:44px; padding:9px 11px; font-size:16px; }

  /* Mer av den smale skjermen går til innhold. */
  #grid { padding:10px; gap:10px; }
  #adminband { margin:10px 10px 0; }
  .panel { margin-bottom:10px; }
  .panel h2 { padding:10px 12px; }
  .panel .body { max-height:340px; padding:10px 12px; }

  /* Sekundærtekst var 10–12px – lesbar uten å måtte zoome. Ingenting under
     12px: det er terskelen der en arm-lengde unna blir gjetting. */
  .muted, .ts { font-size:12.5px; }
  .kindtag { font-size:12px; padding:1px 6px; }
  /* avsendernavnet over hver chatboble lå på 10px */
  .msg .who { font-size:12px; margin-bottom:3px; }
  /* «Kommentér» og «detaljer/filer» er inline-lenker; gi dem tommelhøyde. */
  .item span.clicky { display:inline-block; padding:9px 2px; }

  /* Chatten er hovedinngangen på telefon. Den lå nederst, etter fire
     paneler (~2000px scrolling); her flyttes den øverst – rett under
     eventuelle forslag til godkjenning, som fortsatt kommer først. */
  #chatpanel { order:-1; }
  /* dvh følger den synlige delen av vinduet, så adresselinje og
     mobiltastatur ikke dytter skrivefeltet og Send-knappen ut av syne.
     vh-linjen over er fallback for eldre nettlesere. */
  #chatpanel .panel { height:70vh; height:clamp(320px, 68dvh, 620px); }
  #chatlog { padding:10px; gap:7px; }
  .msg { max-width:92%; }
  #chatform { padding:8px; gap:6px; }
  #chatinput { height:56px; }

  /* Modaler fyller skjermen i stedet for å bli en smal boks i en boks. */
  .modal-back { padding:8px; }
  .modal { padding:14px; max-height:92dvh; border-radius:10px; }
  .formrow { flex-direction:column; align-items:stretch; gap:6px; margin-bottom:14px; }
  .formrow label { width:auto; }
  .formrow select, .formrow input:not([type=number]):not([type=radio]) { width:100%; }
  pre.doc { font-size:13px; max-height:50dvh; }

  #login { margin:9vh auto; padding:0 18px; max-width:100%; }
}

/* Berøringsskjermer BREDERE enn mobilgrensen falt mellom stolene: nettbrett i
   portrett, store telefoner i landskap, og telefoner der brukeren har slått på
   «Be om skrivebordsversjon» (da blåses layoutbredden opp til ~980px). De fikk
   skrivebordets 27px-knapper og 13px-skrift på en skjerm som betjenes med
   tommelen. pointer:coarse treffer kun berøring – en mus matcher aldri, så
   skrivebordet er uberørt. */
@media (min-width:769px) and (max-width:1000px) and (pointer:coarse){
  #grid { grid-template-columns:1fr; }
  #chatpanel { order:-1; grid-column:auto; }
  button { min-height:44px; padding:9px 14px; font-size:14px; }
  input:not([type=radio]):not([type=checkbox]), select, textarea {
    min-height:44px; padding:9px 11px; font-size:16px; }
  .item span.clicky { display:inline-block; padding:9px 2px; }
  .muted, .ts { font-size:12.5px; }
  .kindtag { font-size:12px; padding:1px 6px; }
  .msg .who { font-size:12px; margin-bottom:3px; }
}

/* Telefon i LANDSKAP faller utenfor regelen over (bredden blir 700–950px),
   men høyden er da knapp og fingeren er fortsatt fingeren. pointer:coarse
   gjør at dette kun treffer berøringsskjermer – aldri en vanlig skjerm. */
@media (max-height:520px) and (pointer:coarse){
  #topbar { position:static; }
  button { min-height:44px; }
  input:not([type=radio]):not([type=checkbox]), select, textarea {
    min-height:44px; font-size:16px; }
  #chatpanel { order:-1; }
  #chatpanel .panel { height:82vh; height:calc(100dvh - 20px); }
  .panel .body { max-height:60vh; }
  .modal { max-height:96dvh; }
}

/* ================== MOBIL V2: app-modus (telefon, ≤768px) ==================
   På telefon er dashbordet ikke lenger ett langt dokument, men en app: en
   fast app-linje øverst, en skuffemeny til venstre, og ÉN seksjon om gangen
   som fyller skjermen. Chat er standardvisningen.

   Alt her ligger inne i @media (max-width:768px) – de tre elementene under
   er den eneste nye regelen utenfor, og den skjuler dem på skrivebordet.
   Skrivebordsvisningen er dermed bit for bit uendret. */
#appbar, #scrim, #drawer { display:none; }

@media (max-width:768px){

  /* Topplinjen med sine ni kontroller er erstattet av app-linje + skuff. */
  #topbar { display:none; }
  /* data-msec settes kun av JS på innlogget side, så innloggingsskjermen
     beholder sin egen sentrering. */
  body[data-msec] { padding-top:56px; overflow-x:hidden; }

  /* ---------- app-linje ---------- */
  #appbar { display:flex; align-items:center; gap:6px;
    position:fixed; top:0; left:0; right:0; height:56px; z-index:70;
    padding:0 4px; background:var(--panel); border-bottom:1px solid var(--border); }
  #appbar button { min-height:44px; }
  #hambtn, #apprun { width:46px; padding:0; display:flex; align-items:center;
    justify-content:center; position:relative; }
  #hambtn { background:transparent; border:none; color:var(--text); }
  #hambtn:hover { border:none; }
  /* Uleste forslag må nå fram selv om brukeren står i chatten. */
  #hambdg { display:none; position:absolute; top:6px; right:6px;
    min-width:16px; height:16px; line-height:16px; border-radius:8px;
    background:var(--red); color:#fff; font-size:10px; font-weight:700;
    text-align:center; padding:0 3px; }
  #appttl { flex:1; min-width:0; line-height:1.15; }
  #appttl b { font-size:17px; }
  #appttl span { display:block; font-size:11.5px; color:var(--dim);
    white-space:nowrap; overflow:hidden; text-overflow:ellipsis; }
  #apppulse { flex:0 0 auto; padding-right:2px; }
  #apppulse .pulse-dot { margin:0; }

  /* ---------- skuff ---------- */
  #scrim { display:block; position:fixed; inset:0; z-index:80;
    background:rgba(62,47,28,.5); opacity:0; pointer-events:none;
    transition:opacity .26s ease; }
  body.drawer-open #scrim { opacity:1; pointer-events:auto; }
  #drawer { display:flex; flex-direction:column;
    position:fixed; top:0; bottom:0; left:0; width:min(84vw,320px); z-index:90;
    background:var(--panel); border-right:1px solid var(--border);
    box-shadow:2px 0 18px rgba(62,47,28,.3); overscroll-behavior:contain;
    transform:translateX(-102%);
    transition:transform .26s cubic-bezier(.22,.61,.36,1); }
  body.drawer-open #drawer { transform:translateX(0); }
  #drawer .dtop { display:flex; align-items:center; gap:8px;
    padding:6px 6px 6px 16px; border-bottom:1px solid var(--border); }
  #drawer .dtop .logo { flex:1; font-size:19px; font-weight:700; letter-spacing:3px; }
  #drawer .dtop button { width:46px; padding:0; background:transparent;
    border:none; color:var(--dim); font-size:19px; }
  #dnav { flex:1; overflow-y:auto; padding:8px; }
  .dnav-item { display:flex; align-items:center; gap:12px; width:100%;
    min-height:52px; margin-bottom:2px; padding:0 12px; font-size:16px;
    text-align:left; background:transparent; border:1px solid transparent;
    border-radius:9px; color:var(--text); }
  .dnav-item .lbl { flex:1; }
  .dnav-item .cnt { font-size:12px; color:var(--dim); }
  .dnav-item .badge { font-size:11px; }
  .dnav-item.on { background:var(--panel2); border-color:var(--accent);
    color:var(--accent-text); font-weight:600; }
  .dfoot { border-top:1px solid var(--border); padding:8px;
    display:flex; flex-wrap:wrap; gap:6px; }
  .dfoot button, .dfoot a.knappelenke { flex:1 1 44%; min-height:48px; }
  .dfoot a.knappelenke { justify-content:center; }
  .dfoot .tokline { flex:1 1 100%; text-align:left; font-size:11.5px;
    padding:4px 4px 0; }

  /* ---------- én seksjon om gangen, i fullskjerm ---------- */
  #grid { display:block; padding:0; gap:0; }
  #adminband { margin:0; }
  /* .mon settes av mGo() på seksjonen som er valgt – alle andre er borte. */
  .msec { display:none; }
  .msec.mon { display:block; }

  /* Rammen går kant til kant; kun panelets .body scroller, slik at
     app-linjen står stille (dokumentet selv scroller ikke).
     To former må treffes: seksjoner der .msec er selve panelet (Nå,
     Tankestrøm, Agenter, Minnet) og seksjoner der .msec er en beholder
     rundt panelet (#chatpanel, #adminband). */
  body[data-msec] :is(.mon > .panel, .panel.mon) {
    display:flex; flex-direction:column; height:calc(100dvh - 56px);
    margin:0; border:none; border-radius:0; }
  /* Seksjonsnavnet står allerede i app-linjen. */
  body[data-msec] :is(.mon > .panel, .panel.mon) > h2 { display:none; }
  body[data-msec] :is(.mon > .panel, .panel.mon) > .body {
    flex:1; max-height:none; padding:12px 14px 22px; }
  body[data-msec="admin"] #adminband:empty::after {
    content:'Ingen forslag venter på godkjenning.';
    display:block; padding:34px 20px; text-align:center;
    color:var(--dim); font-size:14px; }

  /* Chatten som meldingsapp: boblene fyller flaten, skrivefeltet er en
     avrundet komponerelinje nederst. */
  body[data-msec] #chatpanel > .panel { height:calc(100dvh - 56px); }
  body[data-msec="chat"] #chatlog { padding:12px 10px; gap:8px; }
  body[data-msec="chat"] #chatform { padding:8px; gap:8px; align-items:flex-end; }
  body[data-msec="chat"] #chatinput {
    height:48px; max-height:120px; border-radius:22px; padding:12px 16px;
    font-family:inherit; }
  body[data-msec="chat"] #chatform button { border-radius:22px; min-width:70px; }

  /* Mindre tekst i blikket: lange fritekstblokker klippes til fem linjer
     og folder seg ut ved trykk. Chatbobler er aldri klippet. */
  .mclamp { display:-webkit-box; -webkit-line-clamp:5; line-clamp:5;
    -webkit-box-orient:vertical; overflow:hidden; cursor:pointer; }
  .mclamp.mopen { display:block; -webkit-line-clamp:unset; line-clamp:unset; }

  /* Trykkmål ≥44px også i 641–768-båndet, som før falt utenfor. */
  button { min-height:44px; padding:9px 14px; font-size:14px; }
  input:not([type=radio]):not([type=checkbox]), select, textarea {
    min-height:44px; padding:9px 11px; font-size:16px; }
  .item span.clicky { display:inline-block; padding:9px 2px; }
}

/* Brukere som har bedt om mindre bevegelse skal ikke få skuffen til å gli. */
@media (prefers-reduced-motion:reduce){
  #drawer, #scrim { transition:none; }
}
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

<!-- App-linje, mørklegging og skuffemeny: skjult på skrivebord (se CSS),
     og eneste inngang til navigasjonen på telefon. -->
<div id="appbar">
  <button id="hambtn" onclick="mDrawer(true)" aria-label="Åpne meny"
          aria-expanded="false" aria-controls="drawer">
    <svg class="ic" width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><path d="M4 7h16"/><path d="M4 12h16"/><path d="M4 17h16"/></svg>
    <span id="hambdg"></span>
  </button>
  <div id="appttl"><b id="appttl_t">Chat</b><span id="appttl_s"></span></div>
  <span id="apppulse"><span class="pulse-dot"></span></span>
  <button id="apprun" onclick="toggleRunning()" aria-label="Start eller pause">…</button>
</div>
<div id="scrim" onclick="mDrawer(false)"></div>
<nav id="drawer" aria-label="Seksjoner" aria-hidden="true">
  <div class="dtop">
    <span class="logo">MIND</span>
    <button onclick="mDrawer(false)" aria-label="Lukk meny">✕</button>
  </div>
  <div id="dnav"></div>
  <div class="dfoot">
    <button id="djarvisbtn" onclick="toggleJarvis()">Jarvis</button>
    <a class="knappelenke" href="innsikt.php">Innsikt</a>
    <button onclick="mDrawer(false);openSettings()">Innstillinger</button>
    <button onclick="doLogout()">Logg ut</button>
    <button onclick="resetTokens()" title="Nullstill token-teller">↺ Tokens</button>
    <div class="tokline" id="dtok"></div>
  </div>
</nav>

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
  <a class="knappelenke" href="innsikt.php" title="Tanker, godkjenninger og tokenøkonomi – lesende, koster ingen tokens"><svg class="ic" width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M3 3v18h18"/><path d="M8 17v-5"/><path d="M13 17V8"/><path d="M18 17V5"/></svg> <span class="btxt">Innsikt</span></a>
  <button onclick="openSettings()"><svg class="ic" width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="3"/><path d="M19.4 13a7.97 7.97 0 0 0 0-2l2.1-1.6-2-3.4-2.5 1a8 8 0 0 0-1.7-1L14.9 3h-4l-.4 2.9a8 8 0 0 0-1.7 1l-2.5-1-2 3.4L6.4 11a7.97 7.97 0 0 0 0 2l-2.1 1.6 2 3.4 2.5-1a8 8 0 0 0 1.7 1l.4 2.9h4l.4-2.9a8 8 0 0 0 1.7-1l2.5 1 2-3.4L19.4 13z"/></svg> <span class="btxt">Innstillinger</span></button>
  <button onclick="doLogout()">Logg ut</button>
</div>

<div id="adminband" class="msec" data-sec="admin"></div>

<div id="grid">
  <div>
    <div class="panel msec" data-sec="now">
      <h2><svg class="ic" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="9"/><path d="M12 7v5l3.5 2"/></svg> Nå <span class="muted" id="cyclets"></span></h2>
      <div class="body" id="nowbody"></div>
    </div>
    <div class="panel msec" data-sec="thoughts">
      <h2><svg class="ic" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M3 9c2.5 0 2.5 3 5 3s2.5-3 5-3 2.5 3 5 3 2.5-3 5-3"/><path d="M3 17c2.5 0 2.5 3 5 3s2.5-3 5-3 2.5 3 5 3 2.5-3 5-3"/></svg> Tankestrøm</h2>
      <div class="body" id="thoughtsbody"></div>
    </div>
  </div>
  <div>
    <div class="panel msec" data-sec="agents">
      <h2><svg class="ic" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="5" y="4" width="14" height="17" rx="2"/><path d="M9 3.5h6a1 1 0 0 1 1 1V6H8V4.5a1 1 0 0 1 1-1z"/><path d="M8.5 13l2.2 2.2L15.5 11"/></svg> Agenter og oppgaver</h2>
      <div class="body" id="agentsbody"></div>
    </div>
    <div class="panel msec" data-sec="memory">
      <h2><svg class="ic" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M9 4a3 3 0 0 0-3 3 3 3 0 0 0-1 5.8A3 3 0 0 0 8 17a3 3 0 0 0 3 3V7a3 3 0 0 0-2-3z"/><path d="M15 4a3 3 0 0 1 3 3 3 3 0 0 1 1 5.8A3 3 0 0 1 16 17a3 3 0 0 1-3 3V7a3 3 0 0 1 2-3z"/></svg> Minnet</h2>
      <div class="body" id="membody"></div>
    </div>
    <!-- Verktøy MIND har bygget. Rader kommer fra samlingen 'tools' via
         api/state.php – samme innlogging som resten av dashbordet, og ingen
         skriving herfra (registrering går via tools/registrer_verktoy.py). -->
    <div class="panel msec" data-sec="tools">
      <h2><svg class="ic" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M14.7 6.3a1 1 0 0 0 0 1.4l1.6 1.6a1 1 0 0 0 1.4 0l3.77-3.77a6 6 0 0 1-7.94 7.94l-6.91 6.91a2.12 2.12 0 0 1-3-3l6.91-6.91a6 6 0 0 1 7.94-7.94l-3.76 3.76z"/></svg> Verktøy <span class="muted" id="toolscount"></span></h2>
      <div class="body" id="toolsbody"></div>
    </div>
  </div>
  <div id="chatpanel" class="msec" data-sec="chat">
    <div class="panel">
      <h2>Chat <span class="muted">(/clear tømmer konteksten)</span></h2>
      <div id="chatdrop">Slipp filer eller tekst her</div>
      <div id="chatlog"></div>
      <div id="chattray"></div>
      <div id="chatform">
        <textarea id="chatinput" placeholder="Skriv til MIND … (dra inn filer, eller lim inn et skjermbilde)"
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
  // brukt av skuffemenyen på telefon (samme motiv som panelenes overskrifter)
  clock: '<svg class="ic" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="9"/><path d="M12 7v5l3.5 2"/></svg>',
  stream: '<svg class="ic" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M3 9c2.5 0 2.5 3 5 3s2.5-3 5-3 2.5 3 5 3 2.5-3 5-3"/><path d="M3 17c2.5 0 2.5 3 5 3s2.5-3 5-3 2.5 3 5 3 2.5-3 5-3"/></svg>',
  tasks: '<svg class="ic" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="5" y="4" width="14" height="17" rx="2"/><path d="M9 3.5h6a1 1 0 0 1 1 1V6H8V4.5a1 1 0 0 1 1-1z"/><path d="M8.5 13l2.2 2.2L15.5 11"/></svg>',
  brain: '<svg class="ic" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M9 4a3 3 0 0 0-3 3 3 3 0 0 0-1 5.8A3 3 0 0 0 8 17a3 3 0 0 0 3 3V7a3 3 0 0 0-2-3z"/><path d="M15 4a3 3 0 0 1 3 3 3 3 0 0 1 1 5.8A3 3 0 0 1 16 17a3 3 0 0 1-3 3V7a3 3 0 0 1 2-3z"/></svg>',
  chat: '<svg class="ic" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M21 11.5a8.4 8.4 0 0 1-.9 3.8 8.5 8.5 0 0 1-7.6 4.7 8.4 8.4 0 0 1-3.8-.9L3 21l1.9-5.7a8.4 8.4 0 0 1-.9-3.8 8.5 8.5 0 0 1 4.7-7.6 8.4 8.4 0 0 1 3.8-.9h.5a8.48 8.48 0 0 1 8 8v.5z"/></svg>',
  wrench18: '<svg class="ic" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M14.7 6.3a1 1 0 0 0 0 1.4l1.6 1.6a1 1 0 0 0 1.4 0l3.77-3.77a6 6 0 0 1-7.94 7.94l-6.91 6.91a2.12 2.12 0 0 1-3-3l6.91-6.91a6 6 0 0 1 7.94-7.94l-3.76 3.76z"/></svg>',
  clip: '<svg class="ic" width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M21 12.2 12.5 20.7a5 5 0 0 1-7.1-7.1l8.5-8.5a3.3 3.3 0 1 1 4.7 4.7l-8.5 8.5a1.7 1.7 0 0 1-2.4-2.4l7.8-7.8"/></svg>',
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

// Versjonen av markup/CSS/JS denne fanen faktisk kjører. Sammenlignes mot
// serverens verdi ved hver poll; se ui_version() i lib.php for hvorfor.
const UI_VERSION = <?= json_encode(ui_version()) ?>;

function reloadIfStale(serverVersion){
  if (!serverVersion || serverVersion === UI_VERSION) return false;
  // Én omlasting per serverversjon. Uten denne sperren ville en fane havnet i
  // evig omlasting hvis versjonene av en eller annen grunn aldri møtes.
  if (sessionStorage.getItem('mind_ui_reload') === serverVersion) return false;
  sessionStorage.setItem('mind_ui_reload', serverVersion);
  location.reload();
  return true;
}

async function poll(){
  try {
    const r = await fetch('api/state.php');
    if (r.status === 401) { location.reload(); return; }
    S = await r.json();
    if (reloadIfStale(S.ui_version)) return;
    draw();
  } catch(e) { /* nettverksglipp – prøver igjen */ }
}

function draw(){
  const st = S.state, se = S.settings;

  // topbar
  const alive = st.daemon_alive;
  document.getElementById('pulseinfo').innerHTML =
    `<span class="pulse-dot ${alive?'alive':''}"></span>` +
    `<span class="muted">${alive ? 'puls ' + ago(st.last_pulse_ts) +
                                   '<span class="nomob"> · rytme ' + st.pulse_interval + 's</span>'
                                 : 'daemon svarer ikke'}</span>`;
  const run = se.running;
  const rb = document.getElementById('runbtn');
  // Ordet forsvinner på telefon; pause-/spill-ikonet bærer betydningen alene,
  // og title gir den samme opplysningen til skjermleser og langtrykk.
  rb.innerHTML = run ? ICO.pause + ' <span class="btxt">Pause</span>'
                     : ICO.play + ' <span class="btxt">Start</span>';
  rb.title = run ? 'Pause' : 'Start';
  rb.className = run ? '' : 'primary';
  const jb = document.getElementById('jarvisbtn');
  jb.innerHTML = '<span class="btxt">Jarvis</span><span class="mobonly">J</span>: ' +
                 (se.jarvis_link ? 'PÅ' : 'AV');
  jb.title = 'Jarvis-kobling: ' + (se.jarvis_link ? 'på' : 'av');
  const t = S.tokens;
  const b = S.budget || {};
  // Døgnbudsjettet vises som en linje til, ikke som eget panel: det er tallet
  // man vil se i forbifarten, ved siden av totalforbruket.
  let budsjettlinje = '';
  if (b.limit > 0) {
    const pct = Math.min(100, Math.round(100 * b.used / b.limit));
    const farge = b.exhausted ? 'var(--red)' : pct >= 75 ? 'var(--amber)' : 'var(--green)';
    budsjettlinje =
      `<br><span style="color:${farge}">i dag ${fmtN(b.used)} / ${fmtN(b.limit)}` +
      (b.exhausted ? ' · budsjett brukt opp' : ` (${pct} %)`) + '</span>';
  }
  document.getElementById('tokline').innerHTML =
    `↑ inn ${fmtN(t.input)} · ↓ ut ${fmtN(t.output)}<br>${ICO.bolt} cache ${fmtN(t.cache_read)} lest / ${fmtN(t.cache_creation)} skrevet` +
    budsjettlinje;
  const pend = S.admin.pending.length;
  document.getElementById('adminbadge').style.display = pend ? '' : 'none';
  document.getElementById('admincount').textContent = pend;
  document.getElementById('stagnbadge').style.display = st.stagnation ? '' : 'none';

  drawAdmin(); drawNow(); drawThoughts(); drawAgents(); drawMemory(); drawTools(); drawChat();
  drawMobile();
}

function drawAdmin(){
  const p = S.admin.pending;
  render('adminband', p, !p.length ? '' : `
    <div class="panel"><h2>${ICO.wrench} Forslag til godkjenning (${p.length})</h2><div class="body">` +
    p.map(x => `
      <div class="item">
        <span class="kindtag">${esc(x.kind)}</span> <b>${esc(x.title)}</b>
        <div class="muted mclamp" style="white-space:pre-wrap">${esc(x.body)}</div>
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
      <div class="mclamp" style="white-space:pre-wrap">${esc(st.working_note || '(ingenting notert ennå)')}</div></div>
    ${res ? `<div class="item muted">Server: disk ${res.disk_pct?.toFixed(0)}% · RAM ${res.mem_pct?.toFixed(0)}% · load ${res.load?.toFixed(1)}</div>` : ''}
    ${cyc.map(c => `
      <div class="item">
        <span class="kindtag">${esc(c.kind)}</span><span class="ts">${ago(c.ts)}</span>
        <div class="mclamp" style="white-space:pre-wrap">${esc(c.observations || '')}</div>
        ${(c.decisions||[]).length ? `<div class="muted">→ ${(c.decisions||[]).map(esc).join(' · ')}</div>` : ''}
      </div>`).join('') || '<div class="muted">Ingen sykluser ennå.</div>'}`);
}

function drawThoughts(){
  const th = S.thoughts;
  render('thoughtsbody', th, th.map(x => `
    <div class="item">
      <span class="kindtag">${esc(x.kind)}</span><span class="ts">${ago(x.ts)}</span>
      <div class="mclamp" style="white-space:pre-wrap">${esc(x.text)}</div>
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
      ${t.selfinit ? '<span class="kindtag" title="Hjernen fant på denne selv">selvinitiert</span>' : ''}
      <span class="ts">${esc(t.status)}${dur !== null ? ' · ' + dur + ' min' : ''} · ${ago(t.finished_ts || t.started_ts || t.created_ts)}</span>
      ${t.progress ? `<div class="muted">${esc(t.progress)}</div>` : ''}
      ${t.result ? `<div class="muted mclamp" style="white-space:pre-wrap">${esc(String(t.result).slice(0,300))}</div>` : ''}
      ${t.cancel_kill ? `<div class="muted">avbrudd: ${esc(t.cancel_kill.result || '')} – ${esc(t.cancel_kill.detail || '')}</div>` : ''}
      <span class="muted clicky" onclick="openTask('${t._id}')">${ICO.folder} detaljer/filer</span>
      ${['queued','running','cancelling'].includes(t.status)
        ? ` <span class="muted clicky" onclick="cancelTask('${t._id}')">✕ avbryt</span>` : ''}
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

// ------------------------------------------------------------------ verktøy
// Ren visning. Rader legges inn av tools/registrer_verktoy.py, aldri herfra:
// dashbordet fikk ingen nye skrive-endepunkter av denne modulen.
const VSTATUS = {
  'i drift': 'v-drift', 'under bygging': 'v-bygging', 'prototyp': 'v-prototyp',
  'pauset': 'v-pauset', 'avviklet': 'v-avviklet',
};

function drawTools(){
  const v = S.tools || [];
  // Under bygging øverst: det er den eneste statusen der noe er i bevegelse.
  const rekkefolge = t => (t.status === 'under bygging' ? 0 : 1);
  const sortert = v.slice().sort((a, b) => rekkefolge(a) - rekkefolge(b));
  document.getElementById('toolscount').textContent = v.length ? '· ' + v.length : '';
  render('toolsbody', v, sortert.map(t => `
    <div class="item">
      <span class="vstatus ${VSTATUS[t.status] || 'v-pauset'}">${esc(t.status)}</span>
      <b>${esc(t.name)}</b>
      <span class="ts">${esc(t.created || '')}</span>
      <div class="vsti">${esc(t.path)}</div>
      <div class="muted">${esc(t.stack)}</div>
      <div class="mclamp" style="white-space:pre-wrap">${esc(t.does)}</div>
      <div class="muted mclamp" style="white-space:pre-wrap"><i>Hvorfor:</i> ${esc(t.why)}</div>
    </div>`).join('')
    || '<div class="muted">Ingen verktøy registrert ennå. Agenter legger dem inn med tools/registrer_verktoy.py.</div>');
}

const fmtBytes = b => b < 1024 ? b + ' B'
  : b < 1048576 ? Math.round(b / 1024) + ' KB'
  : (b / 1048576).toFixed(1).replace('.', ',') + ' MB';

/** Ett lagret vedlegg. Filene ligger utenfor webroot, så URL-en går alltid
 *  gjennom vedlegg.php, som krever den samme innloggede sesjonen. */
function attHtml(a){
  const u = 'vedlegg.php?f=' + encodeURIComponent(a.path || '');
  return (a.mime || '').startsWith('image/')
    ? `<a href="${u}" target="_blank" rel="noopener"><img src="${u}" alt="${esc(a.name)}" loading="lazy"></a>`
    : `<a class="fil" href="${u}" target="_blank" rel="noopener">${ICO.clip} ${esc(a.name)} · ${fmtBytes(a.size || 0)}</a>`;
}

/** Teksten slik den skal SES i boblen.
 *  «[Vedlegg: … → /var/lib/mind/uploads/…]»-linjene i meldingen er skrevet
 *  for hovedhjernen, som bare ser tekst. I dashbordet tegnes de samme
 *  vedleggene som miniatyrer rett under, så her ville linjene med den lange
 *  serverstien bare vært støy. De blir stående urørt i databasen. */
function chatTekst(m){
  const t = m.text || '';
  if (!(m.attachments || []).length) return t;
  return t.replace(/^\[Vedlegg: .*\]$/gm, '').replace(/\n+$/, '');
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
    const atts = m.attachments || [];
    return `<div class="msg ${cls}">${whoText ? `<div class="who">${whoIcon} ${esc(whoText)}</div>` : ''}${esc(chatTekst(m))}${
      atts.length ? `<div class="atts">${atts.map(attHtml).join('')}</div>` : ''}</div>`;
  }).join('') || '<div class="msg system">Chatten er tom. Si hei!</div>';
  if (nearBottom || chatCount === -1) log.scrollTop = log.scrollHeight;
  chatCount = S.chat.length;
}

// ---------------------------------------------- vedlegg på vei ut (dra/lim inn)
let pendingAtts = [];                 // {file, url} – url er objekt-URL for bilder
const ATT_EXT = ['png','jpg','jpeg','gif','webp','pdf','txt','md','csv','json','log'];
const ATT_MAX_BYTES = 15 * 1024 * 1024;
const ATT_MAX = 8;

function drawTray(){
  const t = document.getElementById('chattray');
  if (!t) return;
  t.innerHTML = pendingAtts.map((a, i) => `<span class="att">${
    a.url ? `<img src="${a.url}" alt="">` : ICO.clip}<span class="nm">${esc(a.file.name)}</span>` +
    `<span class="muted">${fmtBytes(a.file.size)}</span>` +
    `<span class="x" title="Fjern vedlegget" onclick="removeAtt(${i})">×</span></span>`).join('');
}

function removeAtt(i){
  const a = pendingAtts.splice(i, 1)[0];
  if (a && a.url) URL.revokeObjectURL(a.url);
  drawTray();
}

/** Et bilde fra utklippstavlen kommer uten brukbart filnavn. Uten navn har
 *  filen heller ingen utvidelse, og serveren har da ingenting å kjenne typen
 *  på – så vi gir den ett før den legges i skuffen. */
function normFile(f){
  if (f.name && f.name.lastIndexOf('.') > 0) return f;
  const ext = {'image/png':'png', 'image/jpeg':'jpg', 'image/gif':'gif',
               'image/webp':'webp', 'application/pdf':'pdf'}[f.type];
  if (!ext) return f;
  return new File([f], 'utklipp-' + Date.now() + '.' + ext, {type: f.type});
}

/** Klientsjekken er høflighet, ikke sikkerhet: api/upload.php validerer alt på
 *  nytt. Poenget er å si fra med én gang i stedet for etter opplastingen. */
function addFiles(filer){
  const avvist = [];
  for (const f of filer) {
    const ext = (f.name.split('.').pop() || '').toLowerCase();
    if (pendingAtts.length >= ATT_MAX)  { avvist.push(`${f.name} – maks ${ATT_MAX} vedlegg per melding`); continue; }
    if (!ATT_EXT.includes(ext))         { avvist.push(`${f.name} – filtypen er ikke tillatt`); continue; }
    if (f.size > ATT_MAX_BYTES)         { avvist.push(`${f.name} – ${fmtBytes(f.size)}, maks er 15 MB`); continue; }
    pendingAtts.push({file: f, url: f.type.startsWith('image/') ? URL.createObjectURL(f) : null});
  }
  drawTray();
  if (avvist.length) alert('Kunne ikke legge ved:\n' + avvist.join('\n'));
}

function settInnTekst(inp, tekst){
  const a = inp.selectionStart ?? inp.value.length;
  const b = inp.selectionEnd ?? a;
  inp.value = inp.value.slice(0, a) + tekst + inp.value.slice(b);
  inp.focus();
  inp.setSelectionRange(a + tekst.length, a + tekst.length);
}

(function initChatDropp(){
  const panel = document.getElementById('chatpanel');
  const inp = document.getElementById('chatinput');
  if (!panel || !inp) return;

  // dragenter/dragleave fyres også når markøren krysser grensen til et BARN
  // av panelet. Uten dybdetelleren blinker markeringen av og på mens man drar
  // over chatloggen.
  let dybde = 0;
  const av = () => { dybde = 0; panel.classList.remove('dragover'); };
  panel.addEventListener('dragenter', e => { e.preventDefault(); dybde++; panel.classList.add('dragover'); });
  panel.addEventListener('dragover',  e => { e.preventDefault(); if (e.dataTransfer) e.dataTransfer.dropEffect = 'copy'; });
  panel.addEventListener('dragleave', () => { if (--dybde <= 0) av(); });
  panel.addEventListener('drop', e => {
    e.preventDefault(); av();
    const dt = e.dataTransfer;
    if (!dt) return;
    if (dt.files && dt.files.length) { addFiles([...dt.files].map(normFile)); return; }
    const t = dt.getData('text/plain') || dt.getData('text/uri-list') || '';
    if (t) settInnTekst(inp, t);
  });

  inp.addEventListener('paste', e => {
    const filer = [...(e.clipboardData ? e.clipboardData.items : [])]
      .filter(i => i.kind === 'file').map(i => i.getAsFile()).filter(Boolean);
    if (!filer.length) return;          // ren tekst limes inn som vanlig
    e.preventDefault();
    addFiles(filer.map(normFile));
  });

  // Bommer man på panelet, ville nettleseren ellers navigert fanen til filen –
  // og da er både chatten og alt uskrevet borte.
  ['dragover', 'drop'].forEach(n => window.addEventListener(n, e => {
    if (!panel.contains(e.target)) e.preventDefault();
  }));
})();

async function sendChat(){
  const inp = document.getElementById('chatinput');
  const text = inp.value.trim();
  // /clear er en kommando, ikke en melding: den skal tømme konteksten, ikke
  // laste opp det som tilfeldigvis lå i vedleggsskuffen først.
  if (text === '/clear') { pendingAtts.forEach(a => a.url && URL.revokeObjectURL(a.url));
                           pendingAtts = []; drawTray(); }
  else if (pendingAtts.length) return sendChatMedVedlegg(text);
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

/** Vedlegg kan ikke sendes som JSON, så denne veien går til api/upload.php,
 *  som lagrer filene OG skriver chatmeldingen i én operasjon. */
async function sendChatMedVedlegg(text){
  const inp = document.getElementById('chatinput');
  const sendes = pendingAtts;
  const fd = new FormData();
  fd.append('text', text);
  sendes.forEach(a => fd.append('files[]', a.file, a.file.name));
  pendingAtts = []; inp.value = ''; drawTray();

  const log = document.getElementById('chatlog');
  log.insertAdjacentHTML('beforeend',
    `<div class="msg user">${esc(text)}<div class="atts">${sendes.map(a =>
      a.url ? `<img src="${a.url}" alt="">`
            : `<span class="fil">${ICO.clip} ${esc(a.file.name)}</span>`).join('')}</div></div>`);
  log.scrollTop = log.scrollHeight;

  let j;
  try {
    const r = await fetch('api/upload.php', {method:'POST', body: fd});
    if (r.status === 401) { location.reload(); return; }
    j = await r.json();
  } catch (e) {
    j = {ok:false, error:'Opplastingen nådde ikke fram: ' + e};
  }
  if (!j.ok) {
    // Legg alt tilbake slik det stod. Ellers har brukeren mistet både teksten
    // og filene han nettopp fant fram, og har ingen måte å få dem igjen på.
    pendingAtts = sendes; inp.value = text; drawTray();
    alert(j.error || 'opplasting feilet');
  }
  // Uansett utfall: tving en ny tegning, slik at den optimistiske boblen (som
  // peker på objekt-URL-er vi straks frigir) erstattes av serverens versjon.
  cache.chat = null;
  await poll();
  if (j.ok) sendes.forEach(a => a.url && URL.revokeObjectURL(a.url));
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

async function cancelTask(id){
  // Setter bare avbruddsflagget; daemonen dreper prosessgruppen og skriver
  // den verifiserte slutt-statusen (cancelled / cancel_failed).
  if (!confirm('Avbryte oppgaven? Prosessen drepes (SIGTERM, så SIGKILL).')) return;
  const j = await api({action:'cancel_task', id});
  if (!j.ok) alert(j.error || 'kunne ikke avbryte');
  poll();
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
    <div class="formrow"><label>Døgnbudsjett (ut-tokens)</label>
      <input type="number" id="set_budget" value="${(S.budget && S.budget.limit) || 0}" min="0" step="50000" style="width:130px">
      <span class="muted">0 = ingen brems. Stopper kun autonome økter; chat svarer alltid.</span></div>
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
    daily_token_budget: document.getElementById('set_budget').value,
  };
  const key = document.getElementById('set_apikey').value.trim();
  if (key) payload.api_key = key;
  await api(payload);
  closeModal(); poll();
}

// =================== mobil-app: skuffemeny + én seksjon ===================
// Alt her er inert på skrivebord: CSS-en som gir app-linje, skuff og
// «vis kun én seksjon» ligger i @media (max-width:768px), så selv om
// data-msec settes uansett, endres ingenting over 768px.
const MOBQ = window.matchMedia('(max-width:768px)');
const MSECS = [
  {id:'chat',     label:'Chat',        icon:ICO.chat},
  {id:'now',      label:'Nå',          icon:ICO.clock},
  {id:'thoughts', label:'Tankestrøm',  icon:ICO.stream},
  {id:'agents',   label:'Agenter',     icon:ICO.tasks},
  {id:'memory',   label:'Minnet',      icon:ICO.brain},
  {id:'tools',    label:'Verktøy',     icon:ICO.wrench18},
  {id:'admin',    label:'Godkjenning', icon:ICO.wrench18},
];
let mSec = 'chat';   // chat er standardvisningen

function mBuildNav(){
  document.getElementById('dnav').innerHTML = MSECS.map(s =>
    `<button class="dnav-item" data-go="${s.id}" onclick="mGo('${s.id}')">
       ${s.icon}<span class="lbl">${s.label}</span>
       <span class="cnt" data-cnt="${s.id}"></span></button>`).join('');
}

function mGo(sec){
  if (!MSECS.some(s => s.id === sec)) sec = 'chat';
  mSec = sec;
  document.body.dataset.msec = sec;
  document.querySelectorAll('.msec').forEach(e =>
    e.classList.toggle('mon', e.dataset.sec === sec));
  document.querySelectorAll('#dnav .dnav-item').forEach(b =>
    b.classList.toggle('on', b.dataset.go === sec));
  const s = MSECS.find(x => x.id === sec);
  document.getElementById('appttl_t').textContent = s.label;
  mDrawer(false);
  mSub();
  // Ny seksjon skal alltid starte på toppen; chatten på siste melding.
  if (sec === 'chat') {
    const log = document.getElementById('chatlog');
    if (log) log.scrollTop = log.scrollHeight;
  } else {
    const b = document.querySelector(`[data-sec="${sec}"] .body`);
    if (b) b.scrollTop = 0;
  }
}

function mDrawer(open){
  document.body.classList.toggle('drawer-open', !!open);
  document.getElementById('drawer').setAttribute('aria-hidden', open ? 'false' : 'true');
  document.getElementById('hambtn').setAttribute('aria-expanded', open ? 'true' : 'false');
}

// Undertittelen i app-linjen bærer det ene tallet seksjonen faktisk trenger,
// slik at panelenes overskriftsrad kan skjules helt.
function mSub(){
  const el = document.getElementById('appttl_s');
  if (!S) { el.textContent = ''; return; }
  const st = S.state, a = S.agents, m = S.memory;
  let t = '';
  if (mSec === 'chat')          t = st.daemon_alive ? 'puls ' + ago(st.last_pulse_ts) : 'daemon svarer ikke';
  else if (mSec === 'now')      t = st.last_cycle_ts ? 'siste syklus ' + ago(st.last_cycle_ts) : 'ingen sykluser ennå';
  else if (mSec === 'thoughts') t = S.thoughts.length + ' tanker';
  else if (mSec === 'agents')   t = a.running.length + ' kjører · ' + a.queued.length + ' i kø';
  else if (mSec === 'memory')   t = Math.round(100 * m.total_tokens / m.max_tokens) + '% av minnet brukt';
  else if (mSec === 'tools')    t = (S.tools || []).length + ' verktøy';
  else if (mSec === 'admin')    t = S.admin.pending.length + ' venter på svar';
  el.textContent = t;
}

function drawMobile(){
  const st = S.state, se = S.settings, a = S.agents, t = S.tokens;
  const pend = S.admin.pending.length;

  document.querySelector('#apppulse .pulse-dot').className =
    'pulse-dot' + (st.daemon_alive ? ' alive' : '');
  const ar = document.getElementById('apprun');
  ar.innerHTML = se.running ? ICO.pause : ICO.play;
  ar.title = se.running ? 'Pause' : 'Start';
  ar.className = se.running ? '' : 'primary';

  const hb = document.getElementById('hambdg');
  hb.style.display = pend ? 'block' : 'none';
  hb.textContent = pend;

  const cnt = (sec, html) => {
    const el = document.querySelector(`#dnav [data-cnt="${sec}"]`);
    if (el) el.innerHTML = html;
  };
  cnt('thoughts', S.thoughts.length || '');
  cnt('agents', a.running.length ? `<span class="badge" style="background:var(--amber)">${a.running.length}</span>` : '');
  cnt('memory', Math.round(100 * S.memory.total_tokens / S.memory.max_tokens) + '%');
  cnt('tools', (S.tools || []).length || '');
  cnt('admin', pend ? `<span class="badge">${pend}</span>` : '');
  cnt('now', st.stagnation ? '<span class="badge" style="background:var(--amber)">!</span>' : '');

  document.getElementById('djarvisbtn').textContent = 'Jarvis: ' + (se.jarvis_link ? 'PÅ' : 'AV');
  document.getElementById('dtok').innerHTML =
    `↑ ${fmtN(t.input)} · ↓ ${fmtN(t.output)} · cache ${fmtN(t.cache_read)}`;
  mSub();
}

// Klipte fritekstblokker folder seg ut ved trykk (kun på telefon).
document.addEventListener('click', e => {
  if (!MOBQ.matches) return;
  const c = e.target.closest('.mclamp');
  if (c) c.classList.toggle('mopen');
});
document.addEventListener('keydown', e => {
  if (e.key === 'Escape' && document.body.classList.contains('drawer-open')) mDrawer(false);
});
// Skuffen skal aldri henge igjen hvis vinduet vokser forbi mobilgrensen.
MOBQ.addEventListener('change', e => { if (!e.matches) mDrawer(false); });

// Kantsveip: dra inn fra venstre kant for å åpne, dra skuffen mot venstre
// for å lukke. Kun vannrette drag teller, så loddrett scrolling er urørt.
(function(){
  let x0 = null, y0 = null, wasOpen = false;
  addEventListener('touchstart', e => {
    x0 = null;
    if (!MOBQ.matches || e.touches.length !== 1) return;
    const t = e.touches[0], open = document.body.classList.contains('drawer-open');
    if (!open && t.clientX > 24) return;          // åpning: kun fra kanten
    if (open && !e.target.closest('#drawer')) return;
    x0 = t.clientX; y0 = t.clientY; wasOpen = open;
  }, {passive:true});
  addEventListener('touchend', e => {
    if (x0 === null) return;
    const t = e.changedTouches[0], dx = t.clientX - x0, dy = Math.abs(t.clientY - y0);
    if (Math.abs(dx) > 55 && Math.abs(dx) > dy) {
      if (!wasOpen && dx > 0) mDrawer(true);
      else if (wasOpen && dx < 0) mDrawer(false);
    }
    x0 = null;
  }, {passive:true});
})();

mBuildNav();
mGo('chat');

poll();
setInterval(poll, 2500);
</script>
<?php endif; ?>
</body>
</html>
