<?php
/** Handlinger fra dashbordet (POST JSON: {action: ..., ...}). */
declare(strict_types=1);
require __DIR__ . '/../lib.php';
header('Content-Type: application/json');

$in = json_decode((string)file_get_contents('php://input'), true) ?: [];
$action = $in['action'] ?? '';

function ok(array $extra = []): void {
    echo json_encode(array_merge(['ok' => true], $extra));
    exit;
}

function fail(string $msg, int $code = 400): void {
    http_response_code($code);
    echo json_encode(['ok' => false, 'error' => $msg]);
    exit;
}

// ---- innlogging (uten auth) ----
if ($action === 'login') {
    if (($in['password'] ?? '') === LOGIN_PASSWORD) {
        $_SESSION['mind_auth'] = true;
        refresh_models(); // §2.1: modelliste hentes oppdatert ved hver innlogging
        ok();
    }
    fail('Feil passord', 401);
}

require_auth_api();

/** Hent modelliste fra Anthropic (via lagret nøkkel); cache i settings. */
function refresh_models(): array {
    $models = ['claude-fable-5', 'claude-opus-5', 'claude-sonnet-5', 'claude-haiku-4-5'];
    $data = read_secrets();
    if (!empty($data['anthropic_api_key_enc'])) {
        $key = '';
        $raw = base64_decode($data['anthropic_api_key_enc']);
        if ($raw !== false && strlen($raw) > 16) {
            $iv = substr($raw, 0, 16);
            $ct = substr($raw, 16);
            $key = (string)openssl_decrypt($ct, 'aes-256-cbc', enc_key(), OPENSSL_RAW_DATA, $iv);
        }
        if ($key) {
            $ch = curl_init('https://api.anthropic.com/v1/models?limit=100');
            curl_setopt_array($ch, [
                CURLOPT_RETURNTRANSFER => true, CURLOPT_TIMEOUT => 15,
                CURLOPT_HTTPHEADER => ['x-api-key: ' . $key, 'anthropic-version: 2023-06-01'],
            ]);
            $resp = curl_exec($ch);
            if ($resp !== false) {
                $j = json_decode((string)$resp, true);
                $ids = array_column($j['data'] ?? [], 'id');
                if ($ids) $models = $ids;
            }
        }
    }
    mupdate('settings', ['_id' => 'main'],
        ['$set' => ['models_cache' => ['models' => $models, 'ts' => microtime(true)]]], true);
    return $models;
}

switch ($action) {

case 'logout':
    $_SESSION = [];
    session_destroy();
    ok();

case 'chat_send':
    $text = trim((string)($in['text'] ?? ''));
    if ($text === '') fail('tom melding');
    if ($text === '/clear') {
        // Tøm chat-konteksten fullstendig; minnehierarkiet består (§5)
        mupdate('settings', ['_id' => 'main'], ['$set' => ['chat_epoch' => microtime(true)]]);
        ok(['cleared' => true]);
    }
    minsert('chat', ['ts' => microtime(true), 'role' => 'user', 'text' => $text, 'marker' => null]);
    mind_event('chat_msg', 'Bruker i chat: ' . mb_substr($text, 0, 400), [], 2);
    ok();

case 'comment_thought':
    $id = (string)($in['id'] ?? '');
    $text = trim((string)($in['text'] ?? ''));
    if (!$id || $text === '') fail('mangler id/tekst');
    mupdate('thoughts', ['_id' => oid($id)],
        ['$push' => ['comments' => ['ts' => microtime(true), 'text' => $text]]]);
    $th = mfindone('thoughts', ['_id' => oid($id)]);
    mind_event('comment',
        'Brukerkommentar på tanke «' . mb_substr($th['text'] ?? '', 0, 120) . '»: ' . $text,
        ['thought_id' => $id], 1);
    ok();

case 'proposal_decide':
    $id = (string)($in['id'] ?? '');
    $approve = (bool)($in['approve'] ?? false);
    $p = mfindone('admin_proposals', ['_id' => oid($id)]);
    if (!$p) fail('ukjent forslag');
    $status = $approve ? 'approved' : 'rejected';
    mupdate('admin_proposals', ['_id' => oid($id)],
        ['$set' => ['status' => $status, 'decided_ts' => microtime(true)]]);
    $applied = '';
    if ($approve && ($p['kind'] ?? '') === 'prompt'
        && !empty($p['payload']['prompt_navn']) && !empty($p['payload']['prompt_tekst'])) {
        // Godkjente promptendringer tas i bruk umiddelbart (§8)
        mupdate('prompts', ['_id' => $p['payload']['prompt_navn']],
            ['$set' => ['text' => $p['payload']['prompt_tekst'],
                        'updated_ts' => microtime(true)]], true);
        $applied = ' Promptendringen er aktivert.';
    }
    mind_event('admin_decision',
        'Bruker ' . ($approve ? 'GODKJENTE' : 'AVVISTE') . ' forslaget «' .
        ($p['title'] ?? '') . '».' . $applied, ['proposal_id' => $id, 'approved' => $approve], 1);
    ok();

case 'toggle_running':
    $run = (bool)($in['running'] ?? false);
    mupdate('settings', ['_id' => 'main'], ['$set' => ['running' => $run]]);
    mind_event('system', $run ? 'Systemet ble STARTET fra dashbordet.'
                              : 'Systemet ble satt på PAUSE fra dashbordet.', [], 3);
    ok();

case 'toggle_jarvis':
    $on = (bool)($in['on'] ?? false);
    mupdate('settings', ['_id' => 'main'], ['$set' => ['jarvis_link' => $on]]);
    mind_event('system', 'Jarvis-koblingen ble slått ' . ($on ? 'PÅ' : 'AV') . '.', [], 2);
    ok();

case 'save_settings':
    $patch = [];
    foreach (['engine', 'brain_model', 'agent_model', 'responder_model', 'pulse_model'] as $k) {
        if (isset($in[$k]) && is_string($in[$k]) && $in[$k] !== '') $patch[$k] = $in[$k];
    }
    if (isset($in['max_parallel_agents'])) $patch['max_parallel_agents'] = max(1, (int)$in['max_parallel_agents']);
    if (isset($in['night_curation_hour'])) $patch['night_curation_hour'] = min(23, max(0, (int)$in['night_curation_hour']));
    if (!in_array($patch['engine'] ?? 'api', ['api', 'claude_code'], true)) unset($patch['engine']);
    if ($patch) mupdate('settings', ['_id' => 'main'], ['$set' => $patch]);
    if (!empty($in['api_key'])) {
        save_secret('anthropic_api_key', trim((string)$in['api_key']));
        refresh_models();
    }
    ok();

case 'reset_tokens':
    mupdate('settings', ['_id' => 'main'], ['$set' => ['token_reset_ts' => microtime(true)]]);
    ok();

case 'refresh_models':
    ok(['models' => refresh_models()]);

case 'memdoc':
    // Les ett minnedokument (hovedminne/detalj/arkiv) for utforskeren
    $col = ['main' => 'memory_main', 'details' => 'memory_details',
            'archive' => 'memory_archive'][$in['col'] ?? ''] ?? null;
    if (!$col) fail('ugyldig samling');
    $doc = mfindone($col, ['_id' => oid((string)($in['id'] ?? ''))]);
    if (!$doc) fail('ikke funnet', 404);
    ok(['doc' => $doc]);

case 'memlist':
    $col = ['details' => 'memory_details', 'archive' => 'memory_archive'][$in['col'] ?? ''] ?? null;
    if (!$col) fail('ugyldig samling');
    $sortKey = $col === 'memory_details' ? 'created_ts' : 'archived_ts';
    ok(['docs' => mfind($col, [], ['sort' => [$sortKey => -1], 'limit' => 100,
                                   'projection' => ['content' => 0]])]);

case 'memsearch':
    $q = trim((string)($in['q'] ?? ''));
    if ($q === '') fail('tomt søk');
    $regex = new MongoDB\BSON\Regex(preg_quote($q, '/'), 'i');
    $hits = [];
    foreach (['main' => 'memory_main', 'details' => 'memory_details', 'archive' => 'memory_archive'] as $label => $col) {
        foreach (mfind($col, ['$or' => [['title' => $regex], ['content' => $regex]]],
                       ['limit' => 15, 'projection' => ['content' => 0]]) as $d) {
            $d['_col'] = $label;
            $hits[] = $d;
        }
    }
    ok(['hits' => $hits]);

case 'cancel_task':
    // Dashbordet setter KUN avbruddsflagget. php-fpm (www-data) eier ikke
    // agentprosessen, så selve drapet – og den verifiserte slutt-statusen –
    // gjøres av daemonen (mind/agents.py: enforce_cancellations).
    $id = (string)($in['id'] ?? '');
    if (!$id) fail('mangler id');
    $t = mfindone('agent_tasks', ['_id' => oid($id)]);
    if (!$t) fail('ukjent oppgave', 404);
    if (!in_array($t['status'] ?? '', ['queued', 'running', 'cancelling'], true)) {
        fail('oppgaven er allerede avsluttet (' . ($t['status'] ?? '?') . ')');
    }
    mupdate('agent_tasks', ['_id' => oid($id)], ['$set' => [
        'cancel_requested' => true,
        'cancel_requested_ts' => microtime(true),
        'cancel_requested_by' => 'bruker',
        'cancel_reason' => 'avbrutt fra dashbordet',
        'status' => 'cancelling',
        'progress' => 'avbrudd bestilt – dreper prosessen …',
    ]]);
    mind_event('agent_cancel_requested',
        'Bruker avbrøt agentoppgaven «' . ($t['title'] ?? '') . '». Prosessen '
        . 'drepes og verifiseres av daemonen.', ['task_id' => $id], 1);
    ok();

case 'task_files':
    $id = (string)($in['id'] ?? '');
    $t = mfindone('agent_tasks', ['_id' => oid($id)]);
    if (!$t) fail('ukjent oppgave', 404);
    ok(['files' => $t['files'] ?? [], 'result' => $t['result'] ?? '', 'brief' => $t['brief'] ?? '']);

case 'read_file':
    // Filviser for agent-leveranser – begrenset til agentwork/
    $taskId = basename((string)($in['task'] ?? ''));
    $rel = (string)($in['path'] ?? '');
    $base = realpath(AGENTWORK_DIR . '/' . $taskId);
    if ($base === false) fail('ukjent arbeidskatalog', 404);
    $full = realpath($base . '/' . $rel);
    if ($full === false || strpos($full, $base . '/') !== 0 && $full !== $base) fail('ugyldig sti');
    if (!is_file($full)) fail('ikke en fil', 404);
    if (filesize($full) > 512 * 1024) fail('filen er for stor for visning');
    $content = (string)file_get_contents($full);
    if (!mb_check_encoding($content, 'UTF-8')) $content = '(binærfil – kan ikke vises)';
    ok(['content' => $content, 'path' => $rel]);

default:
    fail('ukjent handling: ' . $action);
}
