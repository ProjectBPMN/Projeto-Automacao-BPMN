<?php
// Configura a API REST do GLPI com valores fornecidos pelo ambiente local.

if (!defined('GLPI_ROOT')) {
    define('GLPI_ROOT', '/var/www/html/glpi');
}
if (!defined('GLPI_CONFIG_DIR')) {
    define('GLPI_CONFIG_DIR', GLPI_ROOT . '/config');
}

function require_env_value(string $name): string {
    $value = trim((string) getenv($name));
    if ($value === '' || strtoupper($value) === 'CHANGE_ME') {
        fwrite(STDERR, "ERRO: variavel obrigatoria ausente: $name\n");
        exit(1);
    }
    return $value;
}

$token_plain = require_env_value('GLPI_APP_TOKEN');
$client_name = getenv('GLPI_API_CLIENT_NAME') ?: 'n8n-integracao-v9';
$db_host = getenv('GLPI_DB_HOST') ?: 'mariadb';
$db_name = getenv('GLPI_DB_NAME') ?: 'glpi';
$db_user = getenv('GLPI_DB_USER') ?: 'glpi_user';
$db_pass = require_env_value('GLPI_DB_PASSWORD');

$keyfile = GLPI_CONFIG_DIR . '/glpicrypt.key';
if (!file_exists($keyfile)) {
    fwrite(STDERR, "ERRO: arquivo de chave nao encontrado: $keyfile\n");
    exit(1);
}
$key = file_get_contents($keyfile);
if ($key === false || strlen($key) === 0) {
    fwrite(STDERR, "ERRO: nao foi possivel ler a chave GLPI\n");
    exit(1);
}

$nonce = random_bytes(SODIUM_CRYPTO_AEAD_XCHACHA20POLY1305_IETF_NPUBBYTES);
$encrypted = sodium_crypto_aead_xchacha20poly1305_ietf_encrypt(
    $token_plain,
    $nonce,
    $nonce,
    $key
);
$encrypted_b64 = base64_encode($nonce . $encrypted);

$pdo = new PDO("mysql:host=$db_host;dbname=$db_name;charset=utf8mb4", $db_user, $db_pass);
$pdo->setAttribute(PDO::ATTR_ERRMODE, PDO::ERRMODE_EXCEPTION);

$configs = [
    'enable_api' => '1',
    'enable_api_login_credentials' => '1',
    'enable_api_login_external_token' => '1',
    'are_apiclients_tokens_encrypted' => '1',
];
foreach ($configs as $name => $value) {
    $stmt = $pdo->prepare("UPDATE glpi_configs SET value = ? WHERE name = ?");
    $stmt->execute([$value, $name]);
}

$stmt = $pdo->prepare("SELECT id FROM glpi_apiclients WHERE name = ? LIMIT 1");
$stmt->execute([$client_name]);
$id = $stmt->fetchColumn();

if ($id) {
    $stmt = $pdo->prepare("UPDATE glpi_apiclients SET is_active = 1, app_token = ?, app_token_date = NOW(), ipv4_range_start = NULL, ipv4_range_end = NULL, ipv6 = NULL WHERE id = ?");
    $stmt->execute([$encrypted_b64, $id]);
} else {
    $stmt = $pdo->prepare("INSERT INTO glpi_apiclients (entities_id, is_recursive, name, date_creation, date_mod, is_active, app_token, app_token_date, dolog_method, comment) VALUES (0, 1, ?, NOW(), NOW(), 1, ?, NOW(), 0, 'Cliente API criado pelo projeto V9 n8n')");
    $stmt->execute([$client_name, $encrypted_b64]);
    $id = $pdo->lastInsertId();
}

$decoded = base64_decode($encrypted_b64);
$nonce2 = substr($decoded, 0, SODIUM_CRYPTO_AEAD_XCHACHA20POLY1305_IETF_NPUBBYTES);
$ciphertext = substr($decoded, SODIUM_CRYPTO_AEAD_XCHACHA20POLY1305_IETF_NPUBBYTES);
$decrypted = sodium_crypto_aead_xchacha20poly1305_ietf_decrypt($ciphertext, $nonce2, $nonce2, $key);

echo "API REST habilitada.\n";
echo "Cliente API: $client_name (id=$id)\n";
echo "Verificacao decrypt: " . ($decrypted === $token_plain ? "OK" : "FALHOU") . "\n";
