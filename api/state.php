<?php
/** Polling-endepunkt: hele dashbord-tilstanden som JSON (§7). */
declare(strict_types=1);
require __DIR__ . '/../lib.php';
require_auth_api();
header('Content-Type: application/json');

$s = get_settings();
$state = mfindone('state', ['_id' => 'main']) ?? [];
$resetTs = (float)($s['token_reset_ts'] ?? 0);

$tok = maggregate('tokens', [
    ['$match' => ['ts' => ['$gt' => $resetTs]]],
    ['$group' => ['_id' => null,
        'input' => ['$sum' => '$input'], 'output' => ['$sum' => '$output'],
        'cache_read' => ['$sum' => '$cache_read'],
        'cache_creation' => ['$sum' => '$cache_creation']]],
]);
$tokens = $tok[0] ?? ['input' => 0, 'output' => 0, 'cache_read' => 0, 'cache_creation' => 0];
unset($tokens['_id']);

$epoch = (float)($s['chat_epoch'] ?? 0);
$chat = array_reverse(mfind('chat', ['ts' => ['$gt' => $epoch]],
    ['sort' => ['ts' => -1], 'limit' => 60]));

$thoughts = mfind('thoughts', [], ['sort' => ['ts' => -1], 'limit' => 40]);

$agents = [
    'running' => mfind('agent_tasks', ['status' => 'running'], ['sort' => ['started_ts' => 1]]),
    'queued' => mfind('agent_tasks', ['status' => 'queued'], ['sort' => ['priority' => 1, 'created_ts' => 1]]),
    'finished' => mfind('agent_tasks', ['status' => ['$in' => ['done', 'failed', 'cancelled']]],
        ['sort' => ['finished_ts' => -1], 'limit' => 15]),
];
foreach ($agents as &$grp) {
    foreach ($grp as &$t) unset($t['brief']); // holde payloaden slank
}
unset($grp, $t);

$memSections = mfind('memory_main', [], [
    'sort' => ['importance' => -1],
    'projection' => ['content' => 0],
]);
$memTotal = 0;
foreach ($memSections as $sec) $memTotal += (int)($sec['tokens'] ?? 0);

$memory = [
    'sections' => $memSections,
    'total_tokens' => $memTotal,
    'max_tokens' => 150000,
    'details_count' => (maggregate('memory_details', [['$count' => 'n']])[0]['n'] ?? 0),
    'archive_count' => (maggregate('memory_archive', [['$count' => 'n']])[0]['n'] ?? 0),
    'log' => mfind('memory_log', [], ['sort' => ['ts' => -1], 'limit' => 25]),
];

$admin = [
    'pending' => mfind('admin_proposals', ['status' => 'pending'], ['sort' => ['ts' => 1]]),
    'decided' => mfind('admin_proposals', ['status' => ['$ne' => 'pending']],
        ['sort' => ['ts' => -1], 'limit' => 8]),
];

$cycles = mfind('cycles', [], ['sort' => ['ts' => -1], 'limit' => 8, 'projection' => ['raw' => 0]]);

$models = $s['models_cache']['models'] ?? ['claude-fable-5', 'claude-opus-5', 'claude-sonnet-5', 'claude-haiku-4-5'];

$lastPulse = (float)($state['last_pulse_ts'] ?? 0);
$alive = (microtime(true) - $lastPulse) < 120;

echo json_encode([
    // Lar en åpen fane oppdage at index.php er rullet ut på nytt (se ui_version()).
    'ui_version' => ui_version(),
    'settings' => [
        'engine' => $s['engine'] ?? 'claude_code',
        'brain_model' => $s['brain_model'] ?? '',
        'agent_model' => $s['agent_model'] ?? '',
        'responder_model' => $s['responder_model'] ?? '',
        'pulse_model' => $s['pulse_model'] ?? '',
        'running' => (bool)($s['running'] ?? false),
        'jarvis_link' => (bool)($s['jarvis_link'] ?? false),
        'max_parallel_agents' => (int)($s['max_parallel_agents'] ?? 8),
        'night_curation_hour' => (int)($s['night_curation_hour'] ?? 3),
        'api_key_set' => secret_is_set('anthropic_api_key'),
    ],
    'state' => [
        'working_note' => $state['working_note'] ?? '',
        'last_pulse_ts' => $lastPulse,
        'pulse_interval' => $state['pulse_interval'] ?? 10,
        'last_cycle_ts' => $state['last_cycle_ts'] ?? 0,
        'stagnation' => (bool)($state['stagnation'] ?? false),
        'resources' => $state['resources'] ?? null,
        'daemon_alive' => $alive,
    ],
    'tokens' => $tokens,
    'chat' => $chat,
    'thoughts' => $thoughts,
    'agents' => $agents,
    'memory' => $memory,
    'admin' => $admin,
    'cycles' => $cycles,
    'models' => $models,
    'now' => microtime(true),
]);
