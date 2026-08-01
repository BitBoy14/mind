<?php
/**
 * MIND UI-bibliotek: auth, MongoDB-hjelpere (rå ext-mongodb, uten composer),
 * secrets-kryptering. PHP 8.1-kompatibel.
 */
declare(strict_types=1);

const MIND_DB = 'mind';
const LOGIN_PASSWORD = 'REDACTED';
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

function mongo(): MongoDB\Driver\Manager {
    static $m = null;
    if ($m === null) $m = new MongoDB\Driver\Manager('mongodb://127.0.0.1:27017');
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

function save_secret(string $name, string $value): void {
    $data = json_decode((string)@file_get_contents(SECRETS_FILE), true) ?: [];
    $data[$name . '_enc'] = encrypt_secret($value);
    file_put_contents(SECRETS_FILE, json_encode($data));
}

function secret_is_set(string $name): bool {
    $data = json_decode((string)@file_get_contents(SECRETS_FILE), true) ?: [];
    return !empty($data[$name . '_enc']);
}
