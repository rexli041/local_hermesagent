<?php
/**
 * API endpoint — proxies to ACP bridge
 *
 * @package    local_hermesagent
 * @copyright  2026
 * @license    https://www.gnu.org/copyleft/gpl.html GNU GPL v3 or later
 */

require_once(__DIR__ . '/../../config.php');
require_once(__DIR__ . '/lib.php');

require_login();
require_capability('local/hermesagent:use', context_system::instance());

$PAGE->set_context(context_system::instance());

// CSRF protection: validate sesskey for all actions.
$action = required_param('action', PARAM_ALPHA);
if ($action === 'stream') {
    // SSE stream passes sesskey as a query parameter — confirm it matches current session.
    $stream_sesskey = optional_param('sesskey', '', PARAM_ALPHANUM);
    if ($stream_sesskey === '' || !confirm_sesskey($stream_sesskey)) {
        send_json_response(['error' => 'Invalid sesskey']);
    }
} else {
    // All other actions require a valid sesskey (POST body or standard Moodle mechanism).
    require_sesskey();
}

switch ($action) {
    case 'send':
        api_send_message();
        break;
    case 'stream':
        api_stream_response();
        break;
    case 'status':
        api_bridge_status();
        break;
    case 'history':
        api_get_history();
        break;
    case 'conversations':
        api_list_conversations();
        break;
    case 'tool_response':
        api_tool_response();
        break;
    default:
        send_json_response(['error' => 'Unknown action']);
}

/**
 * Send a message to the ACP bridge
 */
function api_send_message(): void {
    global $DB, $USER;
    
    $message = required_param('message', PARAM_TEXT);
    $conversationid = required_param('conversationid', PARAM_INT);
    
    if (empty($message)) {
        send_json_response(['error' => 'Empty message']);
    }

    // Check conversation ownership
    $conv = $DB->get_record('local_hermesagent_conversations', [
        'id' => $conversationid,
        'usermodified' => $USER->id,
    ], '*');

    if (!$conv) {
        send_json_response(['error' => 'Invalid conversation']);
    }

    // Save user message
    $rec = new stdClass();
    $rec->conversationid = $conversationid;
    $rec->role = 'user';
    $rec->content = $message;
    $rec->timemodified = time();
    $msgid = $DB->insert_record('local_hermesagent_messages', $rec);

    // Update conversation timestamp
    $conv->timemodified = time();
    if ($conv->name == 'New conversation') {
        $conv->name = clean_param(substr($message, 0, 60), PARAM_NOTAGS);
    }
    $DB->update_record('local_hermesagent_conversations', $conv);
    
    send_json_response([
        'messageid' => $msgid,
        'conversationid' => $conversationid,
    ]);
}

/**
 * Stream response from ACP bridge
 */
function api_stream_response(): void {
    global $DB, $USER;
    
    $conversationid = required_param('conversationid', PARAM_INT);

    // Check conversation ownership
    $conv = $DB->get_record('local_hermesagent_conversations', [
        'id' => $conversationid,
        'usermodified' => $USER->id,
    ], '*');

    if (!$conv) {
        header('Content-Type: text/event-stream');
        header('Cache-Control: no-cache');
        echo "event: error\ndata: " . json_encode(['error' => 'Invalid conversation']) . "\n\n";
        die();
    }

    $bridge_port = local_hermesagent_get_bridge_port();
    $bridge_url = "http://127.0.0.1:$bridge_port";
    
    // Build messages array from conversation history
    $messages = $DB->get_records('local_hermesagent_messages', ['conversationid' => $conversationid], 'id ASC');
    
    $history = [];
    foreach ($messages as $msg) {
        $history[] = [
            'role' => $msg->role,
            'content' => $msg->content,
        ];
    }
    
    // Get conversation's ACP session ID
    $conv = $DB->get_record('local_hermesagent_conversations', ['id' => $conversationid]);
    $acp_session = $conv ? $conv->acp_session_id : null;
    
    // Get loaded skills
    $skills = local_hermesagent_get_skills(null, true);
    $skill_content = '';
    foreach ($skills as $skill) {
        $skill_content .= "## {$skill->name}\n{$skill->description}\n\n{$skill->content}\n\n";
    }
    
    // Build request to ACP bridge
    $request = [
        'messages' => $history,
        'session_id' => $acp_session,
        'skills' => $skill_content,
        'model' => local_hermesagent_get_setting('hermes_model', ''),
    ];
    
    // Set headers for SSE streaming
    header('Content-Type: text/event-stream');
    header('Cache-Control: no-cache');
    header('X-Accel-Buffering: no');
    header('Connection: keep-alive');
    
    // Call ACP bridge with streaming
    $ch = curl_init();
    curl_setopt_array($ch, [
        CURLOPT_URL => $bridge_url . '/v1/chat/completions',
        CURLOPT_POST => true,
        CURLOPT_POSTFIELDS => json_encode($request),
        CURLOPT_HTTPHEADER => ['Content-Type: application/json'],
        CURLOPT_RETURNTRANSFER => false,
        CURLOPT_HEADER => false,
        CURLOPT_TIMEOUT => 300,
        CURLOPT_WRITEFUNCTION => function($curl, $data) use ($conversationid, $DB) {
            static $assistant_content = '';
            static $message_id = null;
            
            // Parse SSE data
            $lines = explode("\n", $data);
            foreach ($lines as $line) {
                if (strpos($line, 'data: ') === 0) {
                    $payload = substr($line, 6);
                    $json = json_decode($payload, true);
                    if (!$json) continue;
                    if (isset($json['done']) && $json['done']) {
                        // Finalize
                        flush();
                        return strlen($data);
                    }
                    
                    if (isset($json['session_id']) && $message_id === null) {
                        // New session
                        $assistant_content = '';
                        // Create message record
                        $rec = new stdClass();
                        $rec->conversationid = $conversationid;
                        $rec->role = 'assistant';
                        $rec->content = '';
                        $rec->timemodified = time();
                        $message_id = $DB->insert_record('local_hermesagent_messages', $rec);
                        
                        // Update ACP session ID
                        $conv = $DB->get_record('local_hermesagent_conversations', ['id' => $conversationid]);
                        if ($conv) {
                            $conv->acp_session_id = $json['session_id'];
                            $DB->update_record('local_hermesagent_conversations', $conv);
                        }
                        
                        echo "event: session\ndata: " . json_encode(['session_id' => $json['session_id']]) . "\n\n";
                        flush();
                        continue;
                    }
                    
                    if (isset($json['delta'])) {
                        $assistant_content .= $json['delta'];
                        echo "event: message\ndata: " . json_encode(['delta' => $json['delta'], 'full' => $assistant_content]) . "\n\n";
                        flush();
                    }
                    
                    if (isset($json['tool_call'])) {
                        echo "event: tool_call\ndata: " . json_encode($json['tool_call']) . "\n\n";
                        flush();
                    }
                }
            }
            
            return strlen($data);
        },
    ]);
    
    curl_exec($ch);
    $http_code = curl_getinfo($ch, CURLINFO_HTTP_CODE);
    curl_close($ch);
    
    if ($http_code !== 200) {
        echo "event: error\ndata: " . json_encode(['error' => 'Bridge error', 'code' => $http_code]) . "\n\n";
    }
    
    echo "event: done\ndata: [DONE]\n\n";
    flush();
    
    die();
}

/**
 * Get bridge status
 */
function api_bridge_status(): void {
    $bridge_port = local_hermesagent_get_bridge_port();
    $bridge_status = local_hermesagent_get_setting('bridge_status', 'stopped');
    
    // Try to ping the bridge
    $online = false;
    $ch = curl_init("http://127.0.0.1:$bridge_port/health");
    curl_setopt_array($ch, [
        CURLOPT_RETURNTRANSFER => true,
        CURLOPT_TIMEOUT => 3,
    ]);
    $resp = curl_exec($ch);
    $http_code = curl_getinfo($ch, CURLINFO_HTTP_CODE);
    if ($resp !== false && $http_code === 200) {
        $online = true;
        local_hermesagent_set_setting('bridge_status', 'running');
        $bridge_status = 'running';
    }
    curl_close($ch);
    
    send_json_response([
        'status' => $bridge_status,
        'online' => $online,
        'port' => $bridge_port,
    ]);
}

/**
 * Get conversation history
 */
function api_get_history(): void {
    global $DB, $USER;

    $conversationid = required_param('conversationid', PARAM_INT);

    // Check conversation ownership
    $conv = $DB->get_record('local_hermesagent_conversations', [
        'id' => $conversationid,
        'usermodified' => $USER->id,
    ], '*');

    if (!$conv) {
        send_json_response(['error' => 'Invalid conversation']);
    }

    $messages = $DB->get_records('local_hermesagent_messages', ['conversationid' => $conversationid], 'id ASC');
    
    $result = [];
    foreach ($messages as $msg) {
        $result[] = [
            'id' => $msg->id,
            'role' => $msg->role,
            'content' => $msg->content,
            'timemodified' => $msg->timemodified,
        ];
    }
    
    send_json_response(['messages' => $result]);
}

/**
 * List conversations
 */
function api_list_conversations(): void {
    global $DB, $USER;
    
    $conversations = $DB->get_records('local_hermesagent_conversations', ['usermodified' => $USER->id], 'timemodified DESC');
    
    $result = [];
    foreach ($conversations as $conv) {
        $result[] = [
            'id' => $conv->id,
            'name' => $conv->name,
            'timemodified' => $conv->timemodified,
        ];
    }
    
    send_json_response(['conversations' => $result]);
}

/**
 * Handle tool response (approve/reject)
 */
function api_tool_response(): void {
    $messageid = required_param('messageid', PARAM_INT);
    $approved = required_param('approved', PARAM_BOOL);
    
    send_json_response([
        'status' => 'ok',
        'messageid' => $messageid,
        'approved' => $approved,
    ]);
}

/**
 * Send JSON response and exit
 */
function send_json_response(array $data): void {
    header('Content-Type: application/json');
    echo json_encode($data);
    die();
}
