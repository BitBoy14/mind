<?php
/**
 * Beskyttet artefakt-visning.
 *
 * Serverer filer fra ARTIFACT_DIR – en katalog UTENFOR webroot og repo, slik at
 * innholdet aldri kan hentes direkte av nginx eller havne i den offentlige
 * git-historikken. Krever nøyaktig samme innloggede sesjon som dashbordet
 * (lib.php: MINDSESS + $_SESSION['mind_auth']).
 *
 *   ?f=<filnavn>  – vis én fil (bilde/pdf inline, md/txt escapet som tekst)
 *   uten ?f       – enkel liste over katalogen
 *
 * Alt som ikke er eksplisitt tillatt gir 403 med en generisk melding: en
 * uinnlogget – eller gjettende – klient skal ikke kunne skille «finnes ikke»
 * fra «har ikke lov», og skal aldri få en redirect som røper hvor filen ligger.
 */
declare(strict_types=1);
require __DIR__ . '/lib.php';

const ARTIFACT_DIR = '/var/lib/mind/artifacts';

/** Tillatte utvidelser -> MIME-type. Alt annet avvises. */
const ARTIFACT_TYPES = [
    'png'  => 'image/png',
    'jpg'  => 'image/jpeg',
    'jpeg' => 'image/jpeg',
    'pdf'  => 'application/pdf',
    'md'   => 'text/plain',
    'txt'  => 'text/plain',
];

/** Utvidelser som vises som escapet tekst i en HTML-side i stedet for å sendes rått. */
const ARTIFACT_TEXT_EXT = ['md', 'txt'];

function deny(string $why = 'Ingen tilgang'): never {
    http_response_code(403);
    header('Content-Type: text/html; charset=utf-8');
    echo '<!doctype html><meta charset="utf-8"><title>403</title>'
       . '<p style="font:14px sans-serif">403 – ' . htmlspecialchars($why, ENT_QUOTES, 'UTF-8') . '</p>';
    exit;
}

if (!is_authed()) deny();

function artifact_page(string $title, string $bodyHtml): string {
    return '<!doctype html><html lang="no"><head><meta charset="utf-8">'
         . '<meta name="viewport" content="width=device-width, initial-scale=1">'
         . '<title>' . htmlspecialchars($title, ENT_QUOTES, 'UTF-8') . ' – MIND</title><style>'
         . 'body{margin:0;padding:20px;background:#E8DCC4;color:#3E2F1C;'
         . "font:14px/1.6 -apple-system,'Segoe UI',Roboto,sans-serif;overflow-wrap:break-word}"
         . 'h1{font-size:17px;letter-spacing:1px;margin:0 0 14px}'
         . 'a{color:#8B3E22;text-decoration:none}a:hover{text-decoration:underline}'
         . 'ul{list-style:none;padding:0;margin:0}'
         . 'li{padding:7px 10px;background:#F4ECDA;border:1px solid #8F754A;'
         . 'border-radius:6px;margin-bottom:6px;display:flex;gap:10px;justify-content:space-between}'
         . '.dim{color:#7A5C3E;font-size:12px;white-space:nowrap}'
         . 'pre{background:#F4ECDA;border:1px solid #8F754A;border-radius:6px;'
         . 'padding:12px;white-space:pre-wrap;font:13px/1.5 ui-monospace,monospace}'
         . '</style></head><body>' . $bodyHtml . '</body></html>';
}

// ------------------------------------------------------------------ listevisning
if (!isset($_GET['f']) || $_GET['f'] === '') {
    $files = [];
    foreach (@scandir(ARTIFACT_DIR) ?: [] as $name) {
        if ($name === '.' || $name === '..') continue;
        $path = ARTIFACT_DIR . '/' . $name;
        if (!is_file($path)) continue;
        $ext = strtolower((string)pathinfo($name, PATHINFO_EXTENSION));
        if (!isset(ARTIFACT_TYPES[$ext])) continue;
        $files[] = [$name, (int)filesize($path)];
    }
    sort($files);

    $li = '';
    foreach ($files as [$name, $size]) {
        $esc = htmlspecialchars($name, ENT_QUOTES, 'UTF-8');
        $li .= '<li><a href="?f=' . rawurlencode($name) . '">' . $esc . '</a>'
             . '<span class="dim">' . number_format($size / 1024, 1, ',', ' ') . ' kB</span></li>';
    }
    if ($li === '') $li = '<li class="dim">Ingen artefakter.</li>';

    echo artifact_page('Artefakter',
        '<h1>ARTEFAKTER</h1><ul>' . $li . '</ul>'
        . '<p class="dim">' . count($files) . ' fil(er) i ' . htmlspecialchars(ARTIFACT_DIR, ENT_QUOTES, 'UTF-8') . '</p>');
    exit;
}

// ------------------------------------------------------------------ enkeltfil
$raw = (string)$_GET['f'];

// Streng sanitering FØR filsystemet berøres: ingen katalogseparatorer, ingen
// «..», ingen nullbytes – kun et flatt navn av [A-Za-z0-9._-].
if (strpos($raw, '/') !== false || strpos($raw, '\\') !== false
    || strpos($raw, '..') !== false || strpos($raw, "\0") !== false) {
    deny();
}
$name = basename($raw);
if ($name === '' || $name === '.' || !preg_match('/^[A-Za-z0-9._-]+$/', $name)) deny();

$ext = strtolower((string)pathinfo($name, PATHINFO_EXTENSION));
if (!isset(ARTIFACT_TYPES[$ext])) deny();

// Belte og bukseseler: uansett hva som slapp gjennom over må den oppløste
// stien ligge under artefaktkatalogen (fanger bl.a. symlenker ut av den).
$base = realpath(ARTIFACT_DIR);
$path = realpath(ARTIFACT_DIR . '/' . $name);
if ($base === false || $path === false || !is_file($path)
    || strpos($path, $base . '/') !== 0) {
    deny();
}

$mime = ARTIFACT_TYPES[$ext];

if (in_array($ext, ARTIFACT_TEXT_EXT, true)) {
    // Markdown rendres bevisst IKKE – innholdet er upålitelig og vises escapet
    // som ren tekst, slik at ingen HTML/JS fra en artefakt kan kjøre her.
    $text = (string)@file_get_contents($path);
    header('Content-Type: text/html; charset=utf-8');
    echo artifact_page($name,
        '<h1>' . htmlspecialchars($name, ENT_QUOTES, 'UTF-8') . '</h1>'
        . '<p><a href="artifact.php">&larr; alle artefakter</a></p>'
        . '<pre>' . htmlspecialchars($text, ENT_QUOTES, 'UTF-8') . '</pre>');
    exit;
}

header('Content-Type: ' . $mime);
header('Content-Length: ' . (string)filesize($path));
header('Content-Disposition: inline; filename="' . $name . '"');
header('X-Content-Type-Options: nosniff');
header('Cache-Control: private, max-age=300');
readfile($path);
