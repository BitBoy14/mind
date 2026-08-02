<?php
/**
 * Innsikt: full lesetilgang til hjernens indre liv – tanker, godkjenninger og
 * tokenøkonomi.
 *
 * Siden er RENT LESENDE. Den gjør ingen LLM-kall og koster derfor ingenting å
 * åpne, uansett hvor ofte. Alt hentes direkte fra MongoDB ved sidelast, så
 * innholdet er ferskt uten at noe må regenereres.
 *
 * Hensikten er symbiose, ikke kontroll: hjernen tenker 600+ tanker i døgnet og
 * fatter beslutninger mellom meldingene. Uten et sted å lese dem finnes de
 * bare i en database. Her er de lesbare.
 *
 * Krever nøyaktig samme innloggede sesjon som dashbordet (lib.php).
 */
declare(strict_types=1);
require __DIR__ . '/lib.php';

if (!is_authed()) {
    http_response_code(403);
    header('Content-Type: text/html; charset=utf-8');
    echo '<!doctype html><meta charset="utf-8"><title>MIND</title>'
       . '<p style="font-family:sans-serif;padding:2em">Logg inn i '
       . '<a href="./">dashbordet</a> først.</p>';
    exit;
}

$fane = $_GET['fane'] ?? 'tanker';
$sok  = trim((string)($_GET['q'] ?? ''));
$type = (string)($_GET['type'] ?? '');

function h(?string $s): string {
    return htmlspecialchars((string)$s, ENT_QUOTES, 'UTF-8');
}

function nb(float $n, int $dec = 0): string {
    return number_format($n, $dec, ',', ' ');
}

function naar(?float $ts): string {
    if (!$ts) return '–';
    return date('d.m. H:i', (int)$ts);
}

// ---------------------------------------------------------------- datauttrekk

/** Tanker, valgfritt filtrert på type og fritekst. */
function hent_tanker(string $type, string $sok): array {
    $filter = [];
    if ($type !== '') $filter['kind'] = $type;
    if ($sok !== '') $filter['text'] = new MongoDB\BSON\Regex(preg_quote($sok, '/'), 'i');
    return mfind('thoughts', $filter, ['sort' => ['ts' => -1], 'limit' => 1500]);
}

function tanketyper(): array {
    $ut = [];
    foreach (maggregate('thoughts', [
        ['$group' => ['_id' => '$kind', 'n' => ['$sum' => 1]]],
        ['$sort'  => ['n' => -1]],
    ]) as $r) $ut[(string)$r['_id']] = (int)$r['n'];
    return $ut;
}

/**
 * Godkjenninger koblet til det som faktisk skjedde etterpå.
 *
 * Et forslag uten utfall er bare en intensjon. Vi henter derfor hendelsen
 * hjernen skrev da avgjørelsen falt, slik at raden viser både hva den ba om,
 * hva du svarte, og hva den gjorde med svaret.
 */
function hent_forslag(): array {
    $props = mfind('admin_proposals', [], ['sort' => ['ts' => -1]]);
    foreach ($props as &$p) {
        $p['_hendelse'] = mfindone('events', [
            'type' => 'admin_decision',
            'payload.proposal_id' => (string)$p['_id'],
        ]);
    }
    return $props;
}

/** Aggregert tokenforbruk gruppert på ett felt. */
function forbruk_per(string $felt): array {
    return maggregate('tokens', [
        ['$group' => ['_id' => '$' . $felt,
            'n'   => ['$sum' => 1],
            'inn' => ['$sum' => '$input'],
            'ut'  => ['$sum' => '$output'],
            'cr'  => ['$sum' => '$cache_read'],
            'cc'  => ['$sum' => '$cache_creation']]],
        ['$sort' => ['ut' => -1]],
    ]);
}

/** Døgnprofil: forbruk per klokketime, for å se når den er dyr. */
function forbruk_per_time(): array {
    $rader = [];
    foreach (mfind('tokens', [], ['projection' => ['ts' => 1, 'output' => 1, 'role' => 1]]) as $t) {
        $k = date('d.m. H', (int)$t['ts']) . ':00';
        if (!isset($rader[$k])) $rader[$k] = ['n' => 0, 'ut' => 0, 'brain' => 0];
        $rader[$k]['n']++;
        $rader[$k]['ut'] += (int)($t['output'] ?? 0);
        if (($t['role'] ?? '') === 'brain') $rader[$k]['brain']++;
    }
    krsort($rader);
    return $rader;
}

$s = get_settings();
?><!doctype html>
<html lang="no">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>MIND – innsikt</title>
<style>
:root {
  --bg:#E8DCC4; --panel:#F4ECDA; --panel2:#E4D5B0; --border:#8F754A;
  --text:#3E2F1C; --dim:#7A5C3E; --accent:#B85C38; --accent-text:#8B3E22;
  --green:#5F7A3D; --red:#A33B25; --amber:#B8862F;
}
* { box-sizing:border-box; }
body { margin:0; background:var(--bg); color:var(--text);
  font:15px/1.6 -apple-system,'Segoe UI',Roboto,sans-serif; }
a { color:var(--accent-text); }
header { position:sticky; top:0; z-index:20; background:var(--panel);
  border-bottom:1px solid var(--border); padding:10px 16px; }
header .rad { display:flex; align-items:center; gap:12px; flex-wrap:wrap; }
h1 { font-size:17px; margin:0; letter-spacing:1px; }
.faner { display:flex; gap:6px; margin-top:9px; flex-wrap:wrap; }
.faner a { padding:6px 13px; border:1px solid var(--border); border-radius:7px;
  text-decoration:none; color:var(--text); background:var(--panel2); font-size:14px; }
.faner a.on { background:var(--accent); color:#fff; border-color:var(--accent); font-weight:600; }
main { padding:14px 16px 60px; max-width:1000px; margin:0 auto; }
.kort { background:var(--panel); border:1px solid var(--border);
  border-radius:10px; padding:12px 15px; margin-bottom:11px; }
.dim { color:var(--dim); font-size:13px; }
.merk { display:inline-block; font-size:11px; text-transform:uppercase;
  letter-spacing:.5px; border:1px solid var(--border); border-radius:4px;
  padding:1px 7px; margin-right:7px; color:var(--dim); }
.merk.plan{border-color:#4A6FA5;color:#4A6FA5} .merk.ide{border-color:var(--green);color:var(--green)}
.merk.bekymring{border-color:var(--red);color:var(--red)}
.merk.laerdom{border-color:var(--amber);color:var(--amber)}
.merk.refleksjon{border-color:var(--dim)}
.godkjent { color:var(--green); font-weight:600; }
.avvist { color:var(--red); font-weight:600; }
.venter { color:var(--amber); font-weight:600; }
table { width:100%; border-collapse:collapse; font-size:14px; }
th,td { text-align:left; padding:6px 9px; border-bottom:1px solid var(--border); }
th { color:var(--dim); font-weight:600; font-size:12px; text-transform:uppercase; }
td.tall,th.tall { text-align:right; font-variant-numeric:tabular-nums; }
.stolpe { height:7px; background:var(--accent); border-radius:4px; min-width:2px; }
.sok { display:flex; gap:7px; margin-bottom:12px; flex-wrap:wrap; }
.sok input { flex:1; min-width:180px; padding:7px 11px; border:1px solid var(--border);
  border-radius:7px; background:var(--panel); color:var(--text); font-size:15px; }
.sok button { padding:7px 15px; border:1px solid var(--border); border-radius:7px;
  background:var(--accent); color:#fff; font-weight:600; cursor:pointer; font-size:14px; }
.varsel { background:#F6E3D8; border:1px solid var(--accent); border-left-width:4px;
  border-radius:8px; padding:12px 15px; margin-bottom:13px; }
details summary { cursor:pointer; color:var(--accent-text); font-size:13px; }
pre { background:var(--panel2); border:1px solid var(--border); border-radius:7px;
  padding:10px; white-space:pre-wrap; word-break:break-word; font-size:13px;
  max-height:340px; overflow:auto; }
.tomt { color:var(--dim); font-style:italic; padding:18px 0; }
@media (max-width:640px) {
  main { padding:11px 10px 50px; }
  .kort { padding:10px 12px; }
  table { font-size:13px; } th,td { padding:5px 6px; }
}
</style>
</head>
<body>
<header>
  <div class="rad">
    <h1>MIND · innsikt</h1>
    <span class="dim">lesende – koster ingen tokens</span>
    <span style="flex:1"></span>
    <a href="./">← dashbord</a>
  </div>
  <nav class="faner">
    <a href="?fane=tanker"      class="<?= $fane==='tanker'?'on':'' ?>">Tanker</a>
    <a href="?fane=godkjenning" class="<?= $fane==='godkjenning'?'on':'' ?>">Godkjenninger</a>
    <a href="?fane=tokens"      class="<?= $fane==='tokens'?'on':'' ?>">Tokenøkonomi</a>
  </nav>
</header>
<main>

<?php if ($fane === 'tanker'):
  $typer  = tanketyper();
  $tanker = hent_tanker($type, $sok);
  $totalt = array_sum($typer);
?>
  <div class="kort">
    <b><?= nb((float)$totalt) ?> tanker</b> logget siden oppstart.
    <span class="dim">Dette er hjernens indre monolog mellom meldingene – den
    skriver dem for seg selv, ikke for å bli lest.</span>
  </div>

  <form class="sok" method="get">
    <input type="hidden" name="fane" value="tanker">
    <input type="search" name="q" value="<?= h($sok) ?>" placeholder="Søk i tankene …">
    <?php if ($type !== ''): ?><input type="hidden" name="type" value="<?= h($type) ?>"><?php endif; ?>
    <button type="submit">Søk</button>
  </form>

  <div class="faner" style="margin-bottom:13px">
    <a href="?fane=tanker<?= $sok!==''?'&q='.urlencode($sok):'' ?>"
       class="<?= $type===''?'on':'' ?>">alle (<?= $totalt ?>)</a>
    <?php foreach ($typer as $k => $n): ?>
      <a href="?fane=tanker&type=<?= urlencode($k) ?><?= $sok!==''?'&q='.urlencode($sok):'' ?>"
         class="<?= $type===$k?'on':'' ?>"><?= h($k) ?> (<?= $n ?>)</a>
    <?php endforeach; ?>
  </div>

  <?php if (!$tanker): ?>
    <p class="tomt">Ingen tanker matcher.</p>
  <?php else: ?>
    <?php if (count($tanker) >= 1500): ?>
      <p class="dim">Viser de 1500 nyeste.</p>
    <?php endif; ?>
    <?php foreach ($tanker as $t): ?>
      <div class="kort">
        <span class="merk <?= h($t['kind'] ?? '') ?>"><?= h($t['kind'] ?? 'tanke') ?></span>
        <span class="dim"><?= naar($t['ts'] ?? null) ?></span>
        <div><?= nl2br(h($t['text'] ?? '')) ?></div>
        <?php foreach ($t['comments'] ?? [] as $c): ?>
          <div class="dim" style="margin-top:6px;padding-left:12px;border-left:2px solid var(--accent)">
            💬 <?= nl2br(h($c['text'] ?? '')) ?> <em><?= naar($c['ts'] ?? null) ?></em>
          </div>
        <?php endforeach; ?>
      </div>
    <?php endforeach; ?>
  <?php endif; ?>

<?php elseif ($fane === 'godkjenning'):
  $props = hent_forslag();
  $tellere = ['approved' => 0, 'rejected' => 0, 'pending' => 0];
  foreach ($props as $p) {
    $st = $p['status'] ?? 'pending';
    if (isset($tellere[$st])) $tellere[$st]++;
  }
?>
  <div class="kort">
    <b><?= count($props) ?> forslag</b> fra hjernen:
    <span class="godkjent"><?= $tellere['approved'] ?> godkjent</span> ·
    <span class="avvist"><?= $tellere['rejected'] ?> avvist</span> ·
    <span class="venter"><?= $tellere['pending'] ?> venter</span>
    <div class="dim" style="margin-top:5px">Alle er formulert av hjernen selv –
    ingen er bestilt. Kolonnen «utfall» viser hva den gjorde etter avgjørelsen.</div>
  </div>

  <?php if ($tellere['rejected'] === 0 && $tellere['approved'] > 5): ?>
    <div class="varsel">
      <b>Alt er godkjent så langt.</b> Porten registrerer, men filtrerer ikke –
      hjernen har ennå ikke fått vite hvor grensen går. Et avslag med begrunnelse
      er den eneste måten den lærer den på.
    </div>
  <?php endif; ?>

  <?php foreach ($props as $p):
    $st  = $p['status'] ?? 'pending';
    $kl  = ['approved'=>'godkjent','rejected'=>'avvist'][$st] ?? 'venter';
    $ord = ['approved'=>'GODKJENT','rejected'=>'AVVIST'][$st] ?? 'VENTER';
  ?>
    <div class="kort">
      <span class="merk"><?= h($p['kind'] ?? '') ?></span>
      <span class="<?= $kl ?>"><?= $ord ?></span>
      <span class="dim">· foreslått <?= naar($p['ts'] ?? null) ?><?php
        if (!empty($p['decided_ts'])) echo ' · avgjort ' . naar($p['decided_ts']); ?></span>
      <div style="margin:5px 0"><b><?= h($p['title'] ?? '') ?></b></div>
      <div class="dim"><?= nl2br(h($p['body'] ?? '')) ?></div>
      <?php if (!empty($p['payload']['prompt_tekst'])): ?>
        <details style="margin-top:7px">
          <summary>ny prompttekst for «<?= h((string)($p['payload']['prompt_navn'] ?? '')) ?>»</summary>
          <pre><?= h((string)$p['payload']['prompt_tekst']) ?></pre>
        </details>
      <?php endif; ?>
      <?php if (!empty($p['_hendelse']['text'])): ?>
        <div class="dim" style="margin-top:7px;padding-left:12px;border-left:2px solid var(--green)">
          <b>Utfall:</b> <?= h((string)$p['_hendelse']['text']) ?>
        </div>
      <?php endif; ?>
    </div>
  <?php endforeach; ?>

<?php else:
  $per_rolle  = forbruk_per('role');
  $per_modell = forbruk_per('model');
  $per_formal = array_slice(forbruk_per('purpose'), 0, 20);
  $per_time   = forbruk_per_time();
  $sum = ['n'=>0,'inn'=>0,'ut'=>0,'cr'=>0,'cc'=>0];
  foreach ($per_rolle as $r) foreach (['n','inn','ut','cr','cc'] as $k) $sum[$k] += (int)$r[$k];
  $maks_time = 0;
  foreach ($per_time as $r) $maks_time = max($maks_time, $r['ut']);
?>
  <div class="kort">
    <b><?= nb((float)$sum['n']) ?> LLM-kall</b> siden oppstart ·
    <?= nb((float)$sum['ut']) ?> ut-tokens ·
    <?= nb((float)$sum['cr']) ?> lest fra cache ·
    <?= nb((float)$sum['cc']) ?> skrevet til cache
    <div class="dim" style="margin-top:5px">Cache-lesning koster en tiendedel av
    vanlig input; cache-skriving koster litt mer enn vanlig. Høy lesning mot lav
    skriving er billig – motsatt er dyrt.</div>
  </div>

  <div class="kort">
    <h3 style="margin:0 0 8px">Per rolle</h3>
    <table>
      <tr><th>rolle</th><th class="tall">kall</th><th class="tall">ut</th>
          <th class="tall">cache lest</th><th class="tall">cache skrevet</th>
          <th class="tall">treffrate</th></tr>
      <?php foreach ($per_rolle as $r):
        $tot = (int)$r['cr'] + (int)$r['cc'];
        $rate = $tot > 0 ? (100 * (int)$r['cr'] / $tot) : null;
      ?>
        <tr>
          <td><?= h((string)$r['_id']) ?></td>
          <td class="tall"><?= nb((float)$r['n']) ?></td>
          <td class="tall"><?= nb((float)$r['ut']) ?></td>
          <td class="tall"><?= nb((float)$r['cr']) ?></td>
          <td class="tall"><?= nb((float)$r['cc']) ?></td>
          <td class="tall" style="<?= $rate !== null && $rate < 20 ? 'color:var(--red);font-weight:600' : '' ?>">
            <?= $rate === null ? '–' : nb($rate, 1) . ' %' ?></td>
        </tr>
      <?php endforeach; ?>
    </table>
  </div>

  <div class="kort">
    <h3 style="margin:0 0 8px">Per modell</h3>
    <table>
      <tr><th>modell</th><th class="tall">kall</th><th class="tall">ut</th>
          <th class="tall">cache lest</th><th class="tall">cache skrevet</th></tr>
      <?php foreach ($per_modell as $r): ?>
        <tr>
          <td><?= h((string)$r['_id']) ?></td>
          <td class="tall"><?= nb((float)$r['n']) ?></td>
          <td class="tall"><?= nb((float)$r['ut']) ?></td>
          <td class="tall"><?= nb((float)$r['cr']) ?></td>
          <td class="tall"><?= nb((float)$r['cc']) ?></td>
        </tr>
      <?php endforeach; ?>
    </table>
  </div>

  <div class="kort">
    <h3 style="margin:0 0 8px">Dyreste formål</h3>
    <table>
      <tr><th>formål</th><th class="tall">kall</th><th class="tall">ut-tokens</th></tr>
      <?php foreach ($per_formal as $r): ?>
        <tr>
          <td><?= h(mb_substr((string)$r['_id'], 0, 70)) ?></td>
          <td class="tall"><?= nb((float)$r['n']) ?></td>
          <td class="tall"><?= nb((float)$r['ut']) ?></td>
        </tr>
      <?php endforeach; ?>
    </table>
  </div>

  <div class="kort">
    <h3 style="margin:0 0 8px">Døgnprofil</h3>
    <div class="dim" style="margin-bottom:7px">Ut-tokens per klokketime – viser
    når den er dyr, og om nattetimene koster mens du sover.</div>
    <table>
      <tr><th>time</th><th class="tall">kall</th><th class="tall">herav hjernen</th>
          <th class="tall">ut</th><th style="width:34%"></th></tr>
      <?php foreach ($per_time as $k => $r): ?>
        <tr>
          <td><?= h($k) ?></td>
          <td class="tall"><?= $r['n'] ?></td>
          <td class="tall"><?= $r['brain'] ?></td>
          <td class="tall"><?= nb((float)$r['ut']) ?></td>
          <td><div class="stolpe" style="width:<?= $maks_time > 0 ? round(100*$r['ut']/$maks_time) : 0 ?>%"></div></td>
        </tr>
      <?php endforeach; ?>
    </table>
  </div>
<?php endif; ?>

</main>
</body>
</html>
