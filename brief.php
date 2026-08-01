<?php
/**
 * Beskyttet visning av MINDs daglige brief.
 *
 * Briefen bygges av /opt/mind-brief/generate_brief.py (cron 06:30) og lagres i
 * mind-basens samling 'briefs' – ett dokument per dato. Denne siden viser den
 * nyeste og markerer den som sett.
 *
 * Auth er nøyaktig den samme som artifact.php bruker: innlogget sesjon fra
 * lib.php (MINDSESS + $_SESSION['mind_auth']). Uinnlogget gir 403 med en
 * generisk melding og aldri noe av innholdet.
 *
 * Markdownen kommer fra en generator som destillerer tekst fra databasen, og
 * behandles derfor som upålitelig: hele dokumentet escapes FØRST, og de små
 * markdown-reglene (overskrift, punktliste, fet, kode) legges på etterpå. Da
 * finnes det ingen vei fra innholdet til kjørende HTML eller JS – samme
 * grunnholdning som artifact.php, som viser .md-artefakter rått escapet.
 */
declare(strict_types=1);
require __DIR__ . '/lib.php';

function deny(string $why = 'Ingen tilgang'): never {
    http_response_code(403);
    header('Content-Type: text/html; charset=utf-8');
    echo '<!doctype html><meta charset="utf-8"><title>403</title>'
       . '<p style="font:14px sans-serif">403 – ' . htmlspecialchars($why, ENT_QUOTES, 'UTF-8') . '</p>';
    exit;
}

if (!is_authed()) deny();

function brief_page(string $title, string $bodyHtml): string {
    return '<!doctype html><html lang="no"><head><meta charset="utf-8">'
         . '<meta name="viewport" content="width=device-width, initial-scale=1">'
         . '<title>' . htmlspecialchars($title, ENT_QUOTES, 'UTF-8') . ' – MIND</title><style>'
         . 'body{margin:0 auto;padding:20px;max-width:760px;background:#E8DCC4;color:#3E2F1C;'
         . "font:15px/1.65 -apple-system,'Segoe UI',Roboto,sans-serif;overflow-wrap:break-word}"
         . 'h1{font-size:19px;letter-spacing:1px;margin:0 0 6px}'
         . 'h2{font-size:15px;letter-spacing:1px;text-transform:uppercase;color:#8B3E22;'
         . 'margin:22px 0 8px;border-bottom:1px solid #8F754A;padding-bottom:4px}'
         . 'h3{font-size:14px;margin:16px 0 6px}'
         . 'a{color:#8B3E22;text-decoration:none}a:hover{text-decoration:underline}'
         . 'ul{list-style:none;padding:0;margin:0 0 10px}'
         . 'li{padding:7px 10px;background:#F4ECDA;border:1px solid #8F754A;'
         . 'border-radius:6px;margin-bottom:6px}'
         . 'li.sub{margin-left:18px;background:#EFE5CE;font-size:14px}'
         . 'p{margin:0 0 10px}'
         . 'code{background:#F4ECDA;border:1px solid #8F754A;border-radius:4px;'
         . 'padding:0 4px;font:13px ui-monospace,monospace}'
         . '.dim{color:#7A5C3E;font-size:12px}'
         . '</style></head><body>' . $bodyHtml . '</body></html>';
}

/**
 * Minimal markdown -> HTML. Escaper FØRST, formaterer etterpå: etter
 * htmlspecialchars() finnes det ingen «<» igjen i teksten, så ingen tagg kan
 * oppstå fra innholdet – bare de taggene denne funksjonen selv skriver.
 * Lenker rendres bevisst ikke (en href fra upålitelig tekst er en åpen dør).
 */
function brief_md_to_html(string $md): string {
    $esc = htmlspecialchars($md, ENT_QUOTES, 'UTF-8');
    $inline = static function (string $s): string {
        $s = preg_replace('/\*\*(.+?)\*\*/u', '<strong>$1</strong>', $s) ?? $s;
        return preg_replace('/`([^`]+)`/u', '<code>$1</code>', $s) ?? $s;
    };

    $out = '';
    $inList = false;
    $closeList = static function () use (&$out, &$inList): void {
        if ($inList) { $out .= '</ul>'; $inList = false; }
    };

    foreach (preg_split('/\R/u', $esc) ?: [] as $line) {
        $trim = rtrim($line);
        if ($trim === '') { $closeList(); continue; }

        if (preg_match('/^(#{1,3})\s+(.*)$/u', $trim, $m)) {
            $closeList();
            $lvl = strlen($m[1]);
            $out .= '<h' . $lvl . '>' . $inline($m[2]) . '</h' . $lvl . '>';
            continue;
        }
        if (preg_match('/^(\s*)[-*]\s+(.*)$/u', $trim, $m)) {
            if (!$inList) { $out .= '<ul>'; $inList = true; }
            $cls = strlen($m[1]) >= 2 ? ' class="sub"' : '';
            $out .= '<li' . $cls . '>' . $inline($m[2]) . '</li>';
            continue;
        }
        $closeList();
        $out .= '<p>' . $inline($trim) . '</p>';
    }
    $closeList();
    return $out;
}

// ------------------------------------------------------------------ nyeste brief
// Sortering på dato først (feltet er 'YYYY-MM-DD', så leksikografisk = kronologisk),
// generert_ts som tiebreaker hvis to dokumenter skulle dele dato.
$brief = mfindone('briefs', [], ['sort' => ['dato' => -1, 'generert_ts' => -1]]);

if ($brief === null || !isset($brief['innhold_md'])) {
    echo brief_page('Daglig brief',
        '<h1>DAGLIG BRIEF</h1>'
        . '<p class="dim">Ingen brief er generert ennå. Den lages hver morgen kl. 06:30.</p>'
        . '<p><a href="index.php">&larr; dashbordet</a></p>');
    exit;
}

// Markér som lest. Skjer før utskrift, men feiler den, skal briefen likevel vises.
try {
    mupdate('briefs', ['_id' => oid((string)$brief['_id'])],
            ['$set' => ['sett' => true, 'sett_ts' => microtime(true)]]);
} catch (Throwable $e) {
    error_log('MIND brief.php: kunne ikke markere brief som sett: ' . $e->getMessage());
}

$dato = (string)($brief['dato'] ?? '');
$gen  = (string)($brief['generert_ts'] ?? '');

header('Content-Type: text/html; charset=utf-8');
header('Cache-Control: private, no-store');
echo brief_page('Daglig brief ' . $dato,
    brief_md_to_html((string)$brief['innhold_md'])
    . '<p class="dim">Generert ' . htmlspecialchars($gen, ENT_QUOTES, 'UTF-8')
    . ' · <a href="index.php">dashbordet</a> · <a href="artifact.php">artefakter</a></p>');
