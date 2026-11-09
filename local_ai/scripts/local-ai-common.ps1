Set-StrictMode -Version Latest

$LocalAiScriptsRoot = $PSScriptRoot
$LocalAiRoot = (Resolve-Path -LiteralPath (Join-Path $LocalAiScriptsRoot '..')).Path
$RepositoryRoot = (Resolve-Path -LiteralPath (Join-Path $LocalAiRoot '..')).Path
$N8nEnvPath = Join-Path $RepositoryRoot 'n8n\.env'
$RuntimeRoot = Join-Path $LocalAiRoot 'runtime'
$StateRoot = Join-Path $RuntimeRoot 'state'
$LogRoot = Join-Path $RuntimeRoot 'logs'
$ModelsRoot = Join-Path $LocalAiRoot 'models'
$ServiceStatePath = Join-Path $StateRoot 'local-ai.pid.json'
$ExtractorStatePath = Join-Path $StateRoot 'extractor.pid.json'

function Initialize-LocalAiRuntimeDirectories {
    New-Item -ItemType Directory -Force -Path $StateRoot, $LogRoot | Out-Null
}

function Get-DotEnvValue {
    param(
        [Parameter(Mandatory = $true)][string]$Path,
        [Parameter(Mandatory = $true)][string]$Name
    )
    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) {
        return $null
    }
    $pattern = '^\s*' + [regex]::Escape($Name) + '\s*=(.*)$'
    foreach ($line in Get-Content -LiteralPath $Path) {
        if ($line -match $pattern) {
            $value = $Matches[1].Trim()
            if ($value.Length -ge 2) {
                $first = $value.Substring(0, 1)
                $last = $value.Substring($value.Length - 1, 1)
                if (($first -eq '"' -and $last -eq '"') -or ($first -eq "'" -and $last -eq "'")) {
                    $value = $value.Substring(1, $value.Length - 2)
                }
            }
            return $value
        }
    }
    return $null
}

function Resolve-LocalAiPath {
    param(
        [string]$ConfiguredValue,
        [Parameter(Mandatory = $true)][string]$DefaultPath
    )
    if ([string]::IsNullOrWhiteSpace($ConfiguredValue)) {
        return [IO.Path]::GetFullPath($DefaultPath)
    }
    if ([IO.Path]::IsPathRooted($ConfiguredValue)) {
        return [IO.Path]::GetFullPath($ConfiguredValue)
    }
    return [IO.Path]::GetFullPath((Join-Path $RepositoryRoot $ConfiguredValue))
}

function Read-ProcessState {
    param([Parameter(Mandatory = $true)][string]$Path)
    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) {
        return $null
    }
    try {
        $state = Get-Content -Raw -LiteralPath $Path | ConvertFrom-Json
        if ($null -eq $state.pid -or [int]$state.pid -le 0) {
            return $null
        }
        return $state
    }
    catch {
        return $null
    }
}

function Write-ProcessState {
    param(
        [Parameter(Mandatory = $true)][string]$Path,
        [Parameter(Mandatory = $true)][int]$ProcessId,
        [Parameter(Mandatory = $true)][string]$Component,
        [Parameter(Mandatory = $true)][string]$Identity,
        [Parameter(Mandatory = $true)][string]$StdoutLog,
        [Parameter(Mandatory = $true)][string]$StderrLog
    )
    [ordered]@{
        pid = $ProcessId
        component = $Component
        identity = $Identity
        started_utc = [DateTime]::UtcNow.ToString('o')
        stdout_log = $StdoutLog
        stderr_log = $StderrLog
    } | ConvertTo-Json | Set-Content -LiteralPath $Path -Encoding UTF8
}

function Get-TrackedProcess {
    param(
        [Parameter(Mandatory = $true)][string]$StatePath,
        [Parameter(Mandatory = $true)][string]$IdentityPattern
    )
    $state = Read-ProcessState -Path $StatePath
    if ($null -eq $state) {
        return $null
    }
    $process = Get-CimInstance Win32_Process -Filter "ProcessId = $([int]$state.pid)" -ErrorAction SilentlyContinue
    if ($null -eq $process) {
        return $null
    }
    $commandLine = [string]$process.CommandLine
    if ($commandLine -notmatch $IdentityPattern) {
        return $null
    }
    return $process
}

function Test-TcpPort {
    param(
        [Parameter(Mandatory = $true)][string]$Address,
        [Parameter(Mandatory = $true)][int]$Port,
        [int]$TimeoutMilliseconds = 300
    )
    $client = [Net.Sockets.TcpClient]::new()
    try {
        $task = $client.ConnectAsync($Address, $Port)
        if (-not $task.Wait($TimeoutMilliseconds)) {
            return $false
        }
        return $client.Connected
    }
    catch {
        return $false
    }
    finally {
        $client.Dispose()
    }
}

function Invoke-JsonHealth {
    param(
        [Parameter(Mandatory = $true)][string]$Uri,
        [string]$Token = '',
        [int]$TimeoutSeconds = 3
    )
    $headers = @{}
    if (-not [string]::IsNullOrWhiteSpace($Token)) {
        $headers.Authorization = "Bearer $Token"
    }
    return Invoke-RestMethod -Method Get -Uri $Uri -Headers $headers -TimeoutSec $TimeoutSeconds
}

function Wait-JsonHealth {
    param(
        [Parameter(Mandatory = $true)][string]$Uri,
        [string]$Token = '',
        [int]$TimeoutSeconds = 45
    )
    $deadline = [DateTime]::UtcNow.AddSeconds($TimeoutSeconds)
    $lastError = $null
    while ([DateTime]::UtcNow -lt $deadline) {
        try {
            return Invoke-JsonHealth -Uri $Uri -Token $Token -TimeoutSeconds 3
        }
        catch {
            $lastError = $_.Exception.Message
            Start-Sleep -Milliseconds 500
        }
    }
    throw "Timeout aguardando $Uri. Último erro: $lastError"
}

function Test-LocalModelManifest {
    param([switch]$IncludeExtractor)
    $manifestPath = Join-Path $ModelsRoot 'manifest.json'
    if (-not (Test-Path -LiteralPath $manifestPath -PathType Leaf)) {
        throw "Manifesto de modelos ausente: $manifestPath"
    }
    $manifest = Get-Content -Raw -LiteralPath $manifestPath | ConvertFrom-Json
    $models = @($manifest.models)
    $roles = @('embedding')
    if ($IncludeExtractor) {
        $roles += 'optional_extractor'
    }
    foreach ($role in $roles) {
        $model = $models | Where-Object { $_.role -eq $role } | Select-Object -First 1
        if ($null -eq $model) {
            throw "Modelo '$role' ausente do manifesto $manifestPath"
        }
        $declaredRoot = Join-Path $ModelsRoot ([string]$model.local_path)
        $isDirectory = Test-Path -LiteralPath $declaredRoot -PathType Container
        foreach ($file in @($model.files)) {
            $filePath = if ($isDirectory) {
                Join-Path $declaredRoot ([string]$file.path)
            }
            else {
                Join-Path $ModelsRoot ([string]$file.path)
            }
            if (-not (Test-Path -LiteralPath $filePath -PathType Leaf)) {
                throw "Arquivo de modelo ausente: $filePath"
            }
            $actualLength = (Get-Item -LiteralPath $filePath).Length
            if ([long]$actualLength -ne [long]$file.bytes) {
                throw "Tamanho divergente para $filePath"
            }
            $actualHash = (Get-FileHash -Algorithm SHA256 -LiteralPath $filePath).Hash.ToLowerInvariant()
            if ($actualHash -ne ([string]$file.sha256).ToLowerInvariant()) {
                throw "SHA-256 divergente para $filePath"
            }
        }
    }
    return $manifest
}

