[CmdletBinding()]
param(
    [switch]$Force
)

$ErrorActionPreference = 'Stop'
$env:DOCKER_CONTEXT = 'desktop-linux'
$env:COMPOSE_CONVERT_WINDOWS_PATHS = '1'
$root = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
$n8nPath = Join-Path $root 'n8n\.env.homolog'
$glpiPath = Join-Path $root 'glpi\.env.homolog'

if (-not $Force -and ((Test-Path -LiteralPath $n8nPath) -or (Test-Path -LiteralPath $glpiPath))) {
    throw 'Arquivos de homologação já existem. Use -Force somente para rotacionar todos os segredos.'
}

function New-Secret([int]$Bytes = 32) {
    $buffer = [byte[]]::new($Bytes)
    [System.Security.Cryptography.RandomNumberGenerator]::Fill($buffer)
    return [Convert]::ToBase64String($buffer).TrimEnd('=').Replace('+','-').Replace('/','_')
}

$postgresBootstrap = New-Secret
$postgresRuntime = New-Secret
$mysqlRoot = New-Secret
$mysqlApp = New-Secret
$n8nPassword = New-Secret
$runnerToken = New-Secret
$glpiAppToken = New-Secret
$glpiApiPassword = New-Secret
$webhookKey = New-Secret
$fiscalKey = New-Secret
$localToken = New-Secret
$basicBytes = [Text.Encoding]::UTF8.GetBytes("homolog_api:$glpiApiPassword")
$glpiBasic = 'Basic ' + [Convert]::ToBase64String($basicBytes)

$common = [ordered]@{
    COMPOSE_PROJECT_NAME = 'projeto-ic-homolog'
    HOMOLOG_N8N_PORT = '15678'
    HOMOLOG_POSTGRES_PORT = '55432'
    HOMOLOG_GLPI_PORT = '19080'
    HOMOLOG_MAILPIT_PORT = '28025'
    POSTGRES_DB = 'triagem_homolog'
    POSTGRES_BOOTSTRAP_USER = 'triagem_homolog_admin'
    POSTGRES_BOOTSTRAP_PASSWORD = $postgresBootstrap
    POSTGRES_RUNTIME_USER = 'triagem_homolog_app'
    POSTGRES_RUNTIME_PASSWORD = $postgresRuntime
    MYSQL_ROOT_PASSWORD = $mysqlRoot
    MYSQL_DATABASE = 'glpi_homolog'
    MYSQL_USER = 'glpi_homolog_app'
    MYSQL_PASSWORD = $mysqlApp
    N8N_BASIC_AUTH_USER = 'homolog_admin'
    N8N_BASIC_AUTH_PASSWORD = $n8nPassword
    N8N_RUNNERS_AUTH_TOKEN = $runnerToken
    GLPI_APP_TOKEN = $glpiAppToken
    GLPI_AUTH_BASIC = $glpiBasic
    GLPI_WEBHOOK_KEY = $webhookKey
    FISCAL_WEBHOOK_KEY = $fiscalKey
    IA_LOCAL_API_TOKEN = $localToken
    IA_FAILOVER_ENABLED = 'false'
    TEST_MODE = 'true'
    TEST_AUTO_HUMAN_CONFIRMATION = 'false'
    N8N_PUBLIC_BASE_URL = 'http://localhost:15678'
    GLPI_UPSTREAM_PORT = '19080'
    GLPI_API_URL = 'http://host.docker.internal:19080/apirest.php'
}

$content = ($common.GetEnumerator() | ForEach-Object { '{0}={1}' -f $_.Key, $_.Value }) -join "`n"
[IO.File]::WriteAllText($n8nPath, $content + "`n", [Text.UTF8Encoding]::new($false))
[IO.File]::WriteAllText($glpiPath, $content + "`n", [Text.UTF8Encoding]::new($false))

[pscustomobject]@{
    Status = 'CREATED'
    N8nEnvironment = $n8nPath
    GlpiEnvironment = $glpiPath
    SecretsPrinted = $false
}
