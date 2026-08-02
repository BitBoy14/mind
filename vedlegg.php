<?php
/**
 * Beskyttet visning av chatvedlegg.
 *
 * Serverer filer fra UPLOAD_DIR (lib.php) – en katalog UTENFOR webroot og
 * repo, slik at nginx aldri kan levere dem direkte og de aldri havner i den
 * offentlige git-historikken. Krever nøyaktig samme innloggede sesjon som
 * dashbordet (lib.php: MINDSESS + $_SESSION['mind_auth']).
 *
 *   ?f=2026-08/<filnavn>   – én fil
 *
 * Alt annet gir 403 med generisk melding: en uinnlogget – eller gjettende –
 * klient skal ikke kunne skille «finnes ikke» fra «har ikke lov».
 */
declare(strict_types=1);
require __DIR__ . '/lib.php';

function vedlegg_deny(): never {
    http_response_code(403);
    header('Content-Type: text/html; charset=utf-8');
    echo '<!doctype html><meta charset="utf-8"><title>403</title>'
       . '<p style="font:14px sans-serif">403 – ingen tilgang</p>';
    exit;
}

if (!is_authed()) vedlegg_deny();

$path = upload_resolve((string)($_GET['f'] ?? ''));
if ($path === null) vedlegg_deny();

$ext = strtolower((string)pathinfo($path, PATHINFO_EXTENSION));
if (!isset(UPLOAD_TYPES[$ext])) vedlegg_deny();

$inline = in_array($ext, UPLOAD_INLINE_EXT, true);

// Bilder og PDF sendes med sin egen type så nettleseren kan vise dem inline.
// ALT annet sendes som ren tekst OG som nedlasting: en .md eller .json er
// brukerinnhold, og skal aldri kunne tolkes som HTML i dette opphavet
// (nosniff stopper i tillegg gjetting på typen).
$mime = $inline ? UPLOAD_TYPES[$ext] : 'text/plain; charset=utf-8';
$navn = basename($path);

header('Content-Type: ' . $mime);
header('Content-Length: ' . (string)filesize($path));
header('Content-Disposition: ' . ($inline ? 'inline' : 'attachment')
     . '; filename="' . $navn . '"');
header('X-Content-Type-Options: nosniff');
header('Content-Security-Policy: default-src \'none\'; img-src \'self\'; style-src \'unsafe-inline\'');
header('Cache-Control: private, max-age=300');
readfile($path);
