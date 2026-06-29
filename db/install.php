<?php
defined('MOODLE_INTERNAL') || die();

function xmldb_local_hermesagent_install(): bool {
    global $DB;

    if (!$DB->get_manager()->table_exists('local_hermesagent_settings')) {
        return true;
    }

    $defaults = [
        ['name' => 'bridge_port', 'value' => '9118', 'description' => 'Local port for ACP bridge'],
        ['name' => 'hermes_model', 'value' => '', 'description' => 'Override model for this plugin'],
        ['name' => 'hermes_home', 'value' => '', 'description' => 'Custom HERMES_HOME path'],
        ['name' => 'bridge_status', 'value' => 'stopped', 'description' => 'Bridge status'],
        ['name' => 'last_schema_refresh', 'value' => '0', 'description' => 'Last schema refresh timestamp'],
    ];

    foreach ($defaults as $s) {
        if (!$DB->record_exists('local_hermesagent_settings', ['name' => $s['name']])) {
            $DB->insert_record('local_hermesagent_settings', (object)[
                'name' => $s['name'],
                'value' => $s['value'],
                'description' => $s['description'],
                'timemodified' => time(),
            ]);
        }
    }

    return true;
}
