<?php

function plugin_n8nwebhook_install() {
   return true;
}

function plugin_n8nwebhook_uninstall() {
   return true;
}

function plugin_n8nwebhook_ticket_add(CommonDBTM $item) {
   if (!($item instanceof Ticket)) {
      return true;
   }

   $ticket_id = (int)($item->fields['id'] ?? 0);
   if ($ticket_id <= 0) {
      return true;
   }

   $payload = [
      'ticket_id' => $ticket_id,
      'id' => $ticket_id,
      'name' => (string)($item->fields['name'] ?? ''),
      'status' => (int)($item->fields['status'] ?? 0),
      'type' => (int)($item->fields['type'] ?? 0),
      'itilcategories_id' => (int)($item->fields['itilcategories_id'] ?? 0),
      'date' => (string)($item->fields['date'] ?? ''),
      'date_mod' => (string)($item->fields['date_mod'] ?? ''),
      'source' => 'glpi-plugin-n8nwebhook',
   ];

   $prod_url = trim((string)getenv('N8N_GLPI_WEBHOOK_URL'));
   $test_url = trim((string)getenv('N8N_GLPI_WEBHOOK_TEST_URL'));
   $webhook_key = trim((string)getenv('N8N_GLPI_WEBHOOK_KEY'));
   $send_test = strtolower(trim((string)getenv('N8N_GLPI_WEBHOOK_SEND_TEST')));
   $test_enabled = in_array($send_test, ['1', 'true', 'yes'], true);

   if ($webhook_key !== '') {
      $prod_url = plugin_n8nwebhook_append_key($prod_url, $webhook_key);
      $test_url = plugin_n8nwebhook_append_key($test_url, $webhook_key);
      $payload['webhook_key'] = $webhook_key;
   }

   if ($prod_url !== '') {
      plugin_n8nwebhook_post_json($prod_url, $payload);
   }

   if ($test_enabled && $test_url !== '') {
      plugin_n8nwebhook_post_json($test_url, $payload);
   }

   return true;
}

function plugin_n8nwebhook_append_key(string $url, string $key): string {
   if ($url === '') {
      return $url;
   }
   $sep = (strpos($url, '?') === false) ? '?' : '&';
   return $url . $sep . 'key=' . rawurlencode($key);
}

function plugin_n8nwebhook_post_json(string $url, array $payload): void {
   $json = json_encode($payload, JSON_UNESCAPED_UNICODE | JSON_UNESCAPED_SLASHES);
   if ($json === false) {
      error_log('[n8nwebhook] Falha ao serializar payload JSON.');
      return;
   }

   $timeout = (int)getenv('N8N_GLPI_WEBHOOK_TIMEOUT');
   if ($timeout <= 0) {
      $timeout = 8;
   }

   $max_attempts = (int)getenv('N8N_GLPI_WEBHOOK_RETRIES');
   if ($max_attempts <= 0) {
      $max_attempts = 3;
   }
   $sleep_ms = (int)getenv('N8N_GLPI_WEBHOOK_RETRY_SLEEP_MS');
   if ($sleep_ms < 0) {
      $sleep_ms = 500;
   }

   $last_http_code = 0;
   $last_error = 'none';
   $last_response = false;

   for ($attempt = 1; $attempt <= $max_attempts; $attempt++) {
      $ch = curl_init($url);
      curl_setopt($ch, CURLOPT_CUSTOMREQUEST, 'POST');
      curl_setopt($ch, CURLOPT_POSTFIELDS, $json);
      curl_setopt($ch, CURLOPT_RETURNTRANSFER, true);
      curl_setopt($ch, CURLOPT_TIMEOUT, $timeout);
      curl_setopt($ch, CURLOPT_CONNECTTIMEOUT, $timeout);
      curl_setopt($ch, CURLOPT_HTTPHEADER, [
         'Content-Type: application/json',
         'X-Webhook-Key: ' . (string)getenv('N8N_GLPI_WEBHOOK_KEY'),
         'Content-Length: ' . strlen($json),
      ]);
      $last_response = curl_exec($ch);
      $last_http_code = (int)curl_getinfo($ch, CURLINFO_HTTP_CODE);
      $last_error = curl_error($ch) ?: 'none';
      curl_close($ch);

      if ($last_response !== false && $last_http_code < 400) {
         return;
      }

      if ($attempt < $max_attempts && $sleep_ms > 0) {
         usleep($sleep_ms * 1000 * $attempt);
      }
   }

   error_log(
      '[n8nwebhook] Erro POST webhook URL=' . $url
      . ' HTTP=' . $last_http_code
      . ' CURL=' . $last_error
      . ' tentativas=' . $max_attempts
   );
}
