<?php
defined('MOODLE_INTERNAL') || die();

$capabilities = [
    'local/hermesagent:use' => [
        'riskbitmask' => RISK_CONFIG,
        'captype' => 'write',
        'contextlevel' => CONTEXT_SYSTEM,
    ],
    'local/hermesagent:configure' => [
        'riskbitmask' => RISK_CONFIG,
        'captype' => 'write',
        'contextlevel' => CONTEXT_SYSTEM,
    ],
    'local/hermesagent:manage_skills' => [
        'riskbitmask' => RISK_CONFIG,
        'captype' => 'write',
        'contextlevel' => CONTEXT_SYSTEM,
    ],
    'local/hermesagent:approve_tools' => [
        'riskbitmask' => RISK_CONFIG,
        'captype' => 'write',
        'contextlevel' => CONTEXT_SYSTEM,
    ],
];
