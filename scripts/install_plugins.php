<?php
define('CLI_SCRIPT', true);
define('CACHE_DISABLE_ALL', true);

if (function_exists('opcache_reset')) {
    opcache_reset();
}

require('/var/www/html/config.php');
require_once($CFG->libdir . '/upgradelib.php');
require_once($CFG->libdir . '/clilib.php');

echo "=== Installing new plugins ===\n";
upgrade_noncore(true);
echo "=== Done ===\n";
