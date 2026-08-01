<?php
/**
 * MIND UI-bibliotek: auth, MongoDB-hjelpere (rå ext-mongodb, uten composer),
 * secrets-kryptering. PHP 8.1-kompatibel.
 */
declare(strict_types=1);

const MIND_DB = 'mind';
const SECRETS_FILE = '/etc/mind/secrets.conf';
const ENC_KEY_FILE = '/etc/mind/enc_key';
const AGENTWORK_DIR = __DIR__ . '/agentwork';

session_name('MINDSESS');
session_start();

function is_authed(): bool {
    return !empty($_SESSION['mind_auth']);
}

function require_auth_api(): void {
    if (!is_authed()) {
        http_response_code(401);
        header('Content-Type: application/json');
        echo json_encode(['error' => 'unauthorized']);
        exit;
    }
}

/**
 * Tilkoblingsstreng til MINDs dedikerte mongod (127.0.0.1:27018, auth pa).
 * Bruker/passord ligger ALDRI i denne filen (repoet er offentlig) - de leses
 * runtime fra /etc/mind/secrets.conf via read_secrets().
 */
function mind_mongo_uri(): string {
    $s = read_secrets();
    $u = (string)($s['MONGODB_MIND_USER'] ?? '');
    $p = (string)($s['MONGODB_MIND_PASSWORD'] ?? '');
    if ($u === '' || $p === '') {
        error_log('MIND: MONGODB_MIND_USER/-PASSWORD mangler i ' . SECRETS_FILE);
        return 'mongodb://127.0.0.1:27018/';
    }
    return 'mongodb://' . rawurlencode($u) . ':' . rawurlencode($p)
         . '@127.0.0.1:27018/?authSource=admin';
}

function mongo(): MongoDB\Driver\Manager {
    static $m = null;
    if ($m === null) $m = new MongoDB\Driver\Manager(mind_mongo_uri());
    return $m;
}

function oid_str($id): string {
    return $id instanceof MongoDB\BSON\ObjectId ? (string)$id : (string)$id;
}

/** find -> array av assosiative arrays (BSON via JSON-rundtur). */
function mfind(string $coll, array $filter = [], array $opts = []): array {
    $q = new MongoDB\Driver\Query(empty($filter) ? new stdClass() : $filter, $opts);
    $cur = mongo()->executeQuery(MIND_DB . '.' . $coll, $q);
    $out = [];
    foreach ($cur as $doc) {
        $arr = json_decode(json_encode($doc), true);
        if (isset($doc->_id)) $arr['_id'] = oid_str($doc->_id);
        $out[] = $arr;
    }
    return $out;
}

function mfindone(string $coll, array $filter = [], array $opts = []): ?array {
    $opts['limit'] = 1;
    $r = mfind($coll, $filter, $opts);
    return $r[0] ?? null;
}

function mexec(string $coll, MongoDB\Driver\BulkWrite $bulk): void {
    mongo()->executeBulkWrite(MIND_DB . '.' . $coll, $bulk);
}

function minsert(string $coll, array $doc): void {
    $b = new MongoDB\Driver\BulkWrite();
    $b->insert($doc);
    mexec($coll, $b);
}

function mupdate(string $coll, array $filter, array $update, bool $upsert = false, bool $multi = false): void {
    $b = new MongoDB\Driver\BulkWrite();
    $b->update($filter, $update, ['upsert' => $upsert, 'multi' => $multi]);
    mexec($coll, $b);
}

function maggregate(string $coll, array $pipeline): array {
    $cmd = new MongoDB\Driver\Command([
        'aggregate' => $coll, 'pipeline' => $pipeline, 'cursor' => new stdClass(),
    ]);
    $cur = mongo()->executeCommand(MIND_DB, $cmd);
    $out = [];
    foreach ($cur as $doc) $out[] = json_decode(json_encode($doc), true);
    return $out;
}

function oid(string $id): MongoDB\BSON\ObjectId {
    return new MongoDB\BSON\ObjectId($id);
}

/** Legg hendelse i hjerteslag-køen. */
function mind_event(string $type, string $text, array $payload = [], int $priority = 3): void {
    minsert('events', [
        'ts' => microtime(true), 'type' => $type, 'text' => $text,
        'payload' => empty($payload) ? new stdClass() : $payload,
        'priority' => $priority, 'processed' => false,
    ]);
}

function get_settings(): array {
    return mfindone('settings', ['_id' => 'main']) ?? [];
}

// ------------------------------------------------------------------ secrets

function enc_key(): string {
    $hex = trim((string)@file_get_contents(ENC_KEY_FILE));
    return $hex ? hex2bin($hex) : '';
}

/** AES-256-CBC, iv||ct, base64 – samme format som Python-siden dekrypterer. */
function encrypt_secret(string $value): string {
    $key = enc_key();
    $iv = random_bytes(16);
    $ct = openssl_encrypt($value, 'aes-256-cbc', $key, OPENSSL_RAW_DATA, $iv);
    return base64_encode($iv . $ct);
}

/** Motstykke til encrypt_secret(); tom streng ved manglende/ugyldig verdi. */
function decrypt_secret(string $value_b64): string {
    if ($value_b64 === '') return '';
    $raw = base64_decode($value_b64);
    if ($raw === false || strlen($raw) <= 16) return '';
    $iv = substr($raw, 0, 16);
    $ct = substr($raw, 16);
    return (string)openssl_decrypt($ct, 'aes-256-cbc', enc_key(), OPENSSL_RAW_DATA, $iv);
}

/**
 * Varsle høylytt hvis secrets.conf har videre tilgang enn tiltenkt.
 * Filen deles nødvendigvis av to systembrukere (daemonen kjører som
 * mads, php-fpm som www-data), så 0660 (eier+gruppe) er selve målet –
 * ikke 0600. Vi varsler dersom "andre" har noen tilgang i det hele
 * tatt, eller dersom modus er videre enn 0660 (f.eks. 664/666/777).
 */
function check_secrets_file_perms(): void {
    if (!file_exists(SECRETS_FILE)) return;
    $mode = fileperms(SECRETS_FILE) & 0777;
    if (($mode & 0007) !== 0 || ($mode & ~0660) !== 0) {
        error_log(sprintf(
            'MIND SIKKERHETSVARSEL: %s har modus %o – forventet maks 0660 (eier+gruppe, ingen tilgang for andre). Kjør: chmod 660 %s',
            SECRETS_FILE, $mode, SECRETS_FILE
        ));
    }
}

/** Les secrets.conf med delt lås (for å unngå å lese en fil under skriving). */
function read_secrets(): array {
    check_secrets_file_perms();
    $fh = @fopen(SECRETS_FILE, 'c+');
    if ($fh === false) return [];
    $data = [];
    if (flock($fh, LOCK_SH)) {
        $raw = stream_get_contents($fh);
        $data = json_decode((string)$raw, true) ?: [];
        flock($fh, LOCK_UN);
    }
    fclose($fh);
    return $data;
}

/** Read-modify-write av secrets.conf under eksklusiv lås (unngår tapt skriving ved samtidighet). */
function save_secret(string $name, string $value): void {
    check_secrets_file_perms();
    $fh = fopen(SECRETS_FILE, 'c+');
    if ($fh === false) {
        throw new RuntimeException('Kan ikke åpne ' . SECRETS_FILE);
    }
    if (!flock($fh, LOCK_EX)) {
        fclose($fh);
        throw new RuntimeException('Kan ikke låse ' . SECRETS_FILE);
    }
    $raw = stream_get_contents($fh);
    $data = json_decode((string)$raw, true) ?: [];
    $data[$name . '_enc'] = encrypt_secret($value);
    ftruncate($fh, 0);
    rewind($fh);
    fwrite($fh, json_encode($data));
    fflush($fh);
    flock($fh, LOCK_UN);
    fclose($fh);
}

function secret_is_set(string $name): bool {
    $data = read_secrets();
    return !empty($data[$name . '_enc']);
}

/**
 * Fingeravtrykk av selve UI-en.
 *
 * index.php inneholder markup, CSS og JS i én fil, så filens innhold ER
 * versjonen. Dashbordet er en langlivet enside-app: den henter bare data med
 * fetch og laster aldri dokumentet på nytt. Uten dette merket beholder en fane
 * som stod åpen under en utrulling gammel CSS og markup i det uendelige – mens
 * innholdet fortsetter å oppdatere seg, slik at siden ser levende ut og
 * ingenting røper at layouten er utdatert. state.php sender samme verdi, og
 * klienten laster siden på nytt når de to avviker.
 */
function ui_version(): string {
    static $v = null;
    if ($v === null) {
        $h = @md5_file(__DIR__ . '/index.php');
        $v = $h === false ? 'ukjent' : substr($h, 0, 12);
    }
    return $v;
}

/** Innloggingspassordet lagres/leses som en vanlig secret (login_password_enc), ikke hardkodet. */
define('LOGIN_PASSWORD', decrypt_secret(read_secrets()['login_password_enc'] ?? ''));
