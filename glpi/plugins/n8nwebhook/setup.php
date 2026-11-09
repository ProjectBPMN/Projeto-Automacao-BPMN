<?php

define('PLUGIN_N8NWEBHOOK_VERSION', '1.0.0');
define('PLUGIN_N8NWEBHOOK_MIN_GLPI_VERSION', '10.0.0');
define('PLUGIN_N8NWEBHOOK_MAX_GLPI_VERSION', '11.99.99');

function plugin_init_n8nwebhook() {
   global $PLUGIN_HOOKS;

   $PLUGIN_HOOKS['csrf_compliant']['n8nwebhook'] = true;
   $PLUGIN_HOOKS['item_add']['n8nwebhook'] = [
      'Ticket' => 'plugin_n8nwebhook_ticket_add'
   ];

   include_once __DIR__ . '/hook.php';
}

function plugin_version_n8nwebhook() {
   return [
      'name' => 'N8N Webhook Bridge',
      'version' => PLUGIN_N8NWEBHOOK_VERSION,
      'author' => 'Projeto IC',
      'license' => 'GPLv2+',
      'homepage' => 'http://localhost:5678',
      'requirements' => [
         'glpi' => [
            'min' => PLUGIN_N8NWEBHOOK_MIN_GLPI_VERSION,
            'max' => PLUGIN_N8NWEBHOOK_MAX_GLPI_VERSION,
         ]
      ]
   ];
}

function plugin_n8nwebhook_check_config($verbose = false) {
   return true;
}
