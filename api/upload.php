<?php
/**
 * Chatvedlegg: multipart-mottak for filer og bilder brukeren drar inn i
 * chatfeltet (eller limer inn fra utklippstavlen).
 *
 * Hvorfor et EGET endepunkt ved siden av action.php: action.php leser
 * php://input som JSON. En multipart-kropp finnes ikke der – den ligger i
 * $_FILES – så de to formatene kan ikke dele inngang uten å gjøre begge
 * uklare. Auth-kravet er likevel nøyaktig det samme (lib.php:
 * MINDSESS + $_SESSION['mind_auth'] via require_auth_api()).
 *
 * Endepunktet gjør HELE sendingen, ikke bare filmottaket: det lagrer filene
 * OG skriver chatmeldingen. Alternativet – laste opp først, sende melding
 * etterpå – ville latt klienten oppgi vedleggsmetadata selv, og da måtte
 * serveren uansett verifisere alt på nytt. Her er metadataen serverens egen.
 *
 * Svar: JSON. {ok:true, attachments:[...]} eller {ok:false, error:"..."}.
 */
declare(strict_types=1);
require __DIR__ . '/../lib.php';
header('Content-Type: application/json');

function ufail(string $msg, int $code = 400): never {
    http_response_code($code);
    echo json_encode(['ok' => false, 'error' => $msg]);
    exit;
}

require_auth_api();

if (($_SERVER['REQUEST_METHOD'] ?? '') !== 'POST') ufail('kun POST', 405);

// En kropp som sprenger post_max_size forkastes av PHP FØR skriptet kjører:
// $_POST og $_FILES er da tomme, mens Content-Length forteller at klienten
// faktisk sendte noe. Uten denne sjekken ville brukeren fått «ingen filer»
// som forklaring på at han sendte for mye.
if (empty($_POST) && empty($_FILES) && (int)($_SERVER['CONTENT_LENGTH'] ?? 0) > 0) {
    ufail('Sendingen var for stor totalt sett (maks ' . ini_get('post_max_size')
        . ' per melding). Send færre filer om gangen.', 413);
}

$text = trim((string)($_POST['text'] ?? ''));

// ------------------------------------------------------------ normaliser $_FILES
// PHP gir multipart-felt med samme navn som «array av kolonner», ikke som
// liste av filer. Snu det til én rad per fil før noe annet skjer.
$raw = $_FILES['files'] ?? null;
$incoming = [];
if (is_array($raw) && isset($raw['name'])) {
    if (is_array($raw['name'])) {
        foreach (array_keys($raw['name']) as $i) {
            $incoming[] = [
                'name'     => (string)$raw['name'][$i],
                'type'     => (string)$raw['type'][$i],
                'tmp_name' => (string)$raw['tmp_name'][$i],
                'error'    => (int)$raw['error'][$i],
                'size'     => (int)$raw['size'][$i],
            ];
        }
    } else {
        $incoming[] = [
            'name' => (string)$raw['name'], 'type' => (string)$raw['type'],
            'tmp_name' => (string)$raw['tmp_name'], 'error' => (int)$raw['error'],
            'size' => (int)$raw['size'],
        ];
    }
}
// Tomme filfelt (ingen fil valgt) teller ikke som forsøk.
$incoming = array_values(array_filter($incoming,
    fn($f) => $f['error'] !== UPLOAD_ERR_NO_FILE));

if (!$incoming) ufail('ingen filer i sendingen');
if (count($incoming) > UPLOAD_MAX_FILES) {
    ufail('maks ' . UPLOAD_MAX_FILES . ' vedlegg per melding (fikk ' . count($incoming) . ')');
}

/** PHP-ens egne opplastingsfeil oversatt til noe en bruker kan handle på. */
function upload_err_text(int $err): string {
    return [
        UPLOAD_ERR_INI_SIZE   => 'filen er større enn serveren tar imot',
        UPLOAD_ERR_FORM_SIZE  => 'filen er større enn skjemaet tillater',
        UPLOAD_ERR_PARTIAL    => 'opplastingen ble avbrutt underveis',
        UPLOAD_ERR_NO_TMP_DIR => 'serveren mangler midlertidig katalog',
        UPLOAD_ERR_CANT_WRITE => 'serveren fikk ikke skrevet filen',
        UPLOAD_ERR_EXTENSION  => 'opplastingen ble stoppet av en PHP-utvidelse',
    ][$err] ?? 'ukjent opplastingsfeil (' . $err . ')';
}

/**
 * Godtar serverens egen typegjetning (finfo) mot utvidelsen.
 *
 * Bilder og PDF må treffe eksakt – der er byte-signaturen entydig, og en
 * feilmatch betyr at noen prøver å smugle en annen filtype inn. Tekstformater
 * har ingen signatur i det hele tatt: finfo svarer text/plain på .md og .log,
 * men kan finne på application/json, text/csv eller text/x-* avhengig av
 * innholdet. Der holder det å kreve at innholdet ER tekst.
 */
function upload_mime_ok(string $ext, string $sniffed): bool {
    $want = UPLOAD_TYPES[$ext] ?? '';
    if ($want === '') return false;
    if (in_array($ext, UPLOAD_INLINE_EXT, true)) return $sniffed === $want;
    return str_starts_with($sniffed, 'text/')
        || $sniffed === 'application/json'
        || $sniffed === 'application/csv';
}

// ------------------------------------------------------------ valider ALT først
// Ingenting lagres før hver eneste fil er godkjent. En melding der halvparten
// av vedleggene kom fram, og resten ble avvist, er verre enn en som feilet
// rent: brukeren ville ikke se hva som manglet.
$plan = [];
foreach ($incoming as $f) {
    $vis = basename(str_replace('\\', '/', $f['name']));
    $vis = (string)preg_replace('/[\x00-\x1F\x7F]/', '', $vis);
    $vis = mb_substr($vis, 0, 120);
    if ($vis === '') $vis = 'vedlegg';

    if ($f['error'] !== UPLOAD_ERR_OK) ufail('«' . $vis . '»: ' . upload_err_text($f['error']));
    if (!is_uploaded_file($f['tmp_name'])) ufail('«' . $vis . '»: ikke en gyldig opplasting');

    $size = (int)filesize($f['tmp_name']);
    if ($size <= 0) ufail('«' . $vis . '» er tom');
    if ($size > UPLOAD_MAX_BYTES) {
        ufail('«' . $vis . '» er ' . upload_fmt_size($size) . ' – maks er '
            . upload_fmt_size(UPLOAD_MAX_BYTES) . ' per fil');
    }

    $ext = strtolower((string)pathinfo($vis, PATHINFO_EXTENSION));
    if (!isset(UPLOAD_TYPES[$ext])) {
        ufail('«' . $vis . '»: filtypen er ikke tillatt. Tillatt: '
            . implode(', ', array_keys(UPLOAD_TYPES)) . '.');
    }

    $sniffed = 'application/octet-stream';
    $fi = finfo_open(FILEINFO_MIME_TYPE);
    if ($fi !== false) {
        $sniffed = (string)finfo_file($fi, $f['tmp_name']);
        finfo_close($fi);
    }
    if (!upload_mime_ok($ext, $sniffed)) {
        ufail('«' . $vis . '»: innholdet ser ut som ' . $sniffed
            . ', ikke ' . UPLOAD_TYPES[$ext] . ' slik utvidelsen lover');
    }

    // Lagringsnavnet er ALDRI brukerens: tidsstempel + tilfeldighet gjør det
    // unikt, og bare [A-Za-z0-9._-] slipper gjennom, så det kan verken
    // inneholde katalogseparatorer eller «..».
    $stamme = (string)preg_replace('/[^A-Za-z0-9._-]+/', '-',
        (string)pathinfo($vis, PATHINFO_FILENAME));
    $stamme = (string)preg_replace('/\.{2,}/', '.', $stamme);
    $stamme = trim(mb_substr($stamme, 0, 48), '-._');
    if ($stamme === '') $stamme = 'vedlegg';

    $plan[] = [
        'tmp'    => $f['tmp_name'],
        'vis'    => $vis,
        'ext'    => $ext,
        'size'   => $size,
        'mime'   => UPLOAD_TYPES[$ext],
        'lagret' => date('Ymd-His') . '-' . bin2hex(random_bytes(5)) . '-' . $stamme . '.' . $ext,
    ];
}

// ------------------------------------------------------------ lagre
$maaned = date('Y-m');
$dir = UPLOAD_DIR . '/' . $maaned;
if (!is_dir($dir)) {
    // 02750: setgid holder gruppen (daemonens bruker) på alt som opprettes
    // her, slik at hovedhjernen kan LESE et vedlegg den får stien til.
    // «andre» har ingenting her.
    //
    // Merk: ingen chmod() etterpå. Kjernen arver både gruppe OG setgid fra
    // UPLOAD_DIR ved selve mkdir, men en chmod fra www-data på en katalog som
    // tilhører en ANNEN gruppe får kjernen til å fjerne setgid igjen i det
    // stille (POSIX). Det ga månedskataloger uten setgid, og dermed filer
    // daemonen ikke fikk åpne. Modusen fra mkdir er allerede riktig.
    if (!@mkdir($dir, 02750) && !is_dir($dir)) {
        error_log('MIND: klarte ikke opprette ' . $dir);
        ufail('serveren fikk ikke opprettet lagringskatalogen', 500);
    }
}

$atts = [];
$lagt = [];
foreach ($plan as $p) {
    $full = $dir . '/' . $p['lagret'];
    // copy(), ikke move_uploaded_file(): sistnevnte flytter med rename(2), som
    // beholder inoden – og dermed GRUPPEN – fra opplastingens midlertidige fil
    // (www-data). Da hjelper ikke setgid på katalogen, og daemonen (mads) står
    // igjen uten leserett på et vedlegg hovedhjernen nettopp fikk stien til.
    // copy() oppretter en NY fil i katalogen, som arver gruppen slik den skal.
    // Sikkerhetssjekken move_uploaded_file ellers gir – at kilden virkelig er
    // en opplastet fil – er allerede gjort med is_uploaded_file() over, og
    // PHP rydder bort den midlertidige filen selv når forespørselen er slutt.
    if (!@copy($p['tmp'], $full)) {
        foreach ($lagt as $u) @unlink($u);   // ingen halvveis sendinger
        error_log('MIND: kunne ikke kopiere opplastet fil til ' . $full);
        ufail('«' . $p['vis'] . '» kunne ikke lagres på serveren', 500);
    }
    @chmod($full, 0640);
    $lagt[] = $full;
    $atts[] = [
        'name' => $p['vis'],
        'path' => $maaned . '/' . $p['lagret'],   // relativ – vedlegg.php slår den opp
        'abs'  => $full,
        'mime' => $p['mime'],
        'size' => $p['size'],
    ];
}

// ------------------------------------------------------------ skriv chatmeldingen
// Vedlegget skrives BÅDE strukturert (attachments) og som lesbar tekst i
// selve meldingen. Den lesbare linjen er det som gjør at hovedhjernen ser
// vedlegget i hendelsesstrømmen og i chatlogg-utdraget uten at daemonen må
// lære et nytt felt; den strukturerte er det dashbordet tegner miniatyrer av.
$linjer = [];
foreach ($atts as $a) {
    $linjer[] = sprintf('[Vedlegg: %s → %s, %s, %s]',
        $a['name'], $a['abs'], $a['mime'], upload_fmt_size((int)$a['size']));
}
$vedleggstekst = implode("\n", $linjer);
$full_tekst = $text === '' ? $vedleggstekst : $text . "\n" . $vedleggstekst;

minsert('chat', [
    'ts' => microtime(true), 'role' => 'user', 'text' => $full_tekst,
    'marker' => null, 'attachments' => $atts,
]);

// Brukerteksten kortes, vedleggslinjene aldri: blir de klippet bort her,
// står hjernen igjen med en melding om en fil den ikke får vite navnet på.
mind_event('chat_msg',
    'Bruker i chat: ' . ($text === '' ? '' : mb_substr($text, 0, 300) . "\n") . $vedleggstekst,
    ['attachments' => $atts], 2);

echo json_encode(['ok' => true, 'attachments' => $atts]);
