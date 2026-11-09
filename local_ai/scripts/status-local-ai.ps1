[CmdletBinding()]
param([switch]$Json)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest
. (Join-Path $PSScriptRoot 'local-ai-common.ps1')

$token = Get-DotEnvValue -Path $N8nEnvPath -Name 'IA_LOCAL_API_TOKEN'
$serviceState = Read-ProcessState -Path $ServiceStatePath
$serviceProcess = Get-TrackedProcess -StatePath $ServiceStatePath -IdentityPattern '(?i)(-m\s+local_ai|local_ai)'
$extractorState = Read-ProcessState -Path $ExtractorStatePath
$extractorProcess = Get-TrackedProcess -StatePath $ExtractorStatePath -IdentityPattern '(?i)llama-server'

$servicePortListening = Test-TcpPort -Address '127.0.0.1' -Port 8090
$serviceHealth = $null
$serviceError = if ($servicePortListening) { $null } else { 'porta 8090 não está em escuta' }
if ($servicePortListening) {
    try {
        $serviceHealth = Invoke-JsonHealth -Uri 'http://127.0.0.1:8090/health' -Token $token -TimeoutSeconds 3
    }
    catch {
        $serviceError = $_.Exception.Message
    }
}

$extractorPortListening = Test-TcpPort -Address '127.0.0.1' -Port 8091
$extractorHealth = $null
$extractorError = if ($extractorPortListening) { $null } else { 'porta 8091 não está em escuta' }
if ($extractorPortListening) {
    try {
        $extractorHealth = Invoke-JsonHealth -Uri 'http://127.0.0.1:8091/health' -TimeoutSeconds 2
    }
    catch {
        $extractorError = $_.Exception.Message
    }
}

$status = [ordered]@{
    checked_utc = [DateTime]::UtcNow.ToString('o')
    service = [ordered]@{
        pid = if ($null -ne $serviceProcess) { [int]$serviceProcess.ProcessId } else { $null }
        tracked = $null -ne $serviceState
        running = $null -ne $serviceProcess
        port_8090_listening = $servicePortListening
        health = if ($null -ne $serviceHealth) { [string]$serviceHealth.status } else { 'unavailable' }
        decision_ready = if ($null -ne $serviceHealth) { [bool]$serviceHealth.decision_ready } else { $false }
        scientific_ready = if ($null -ne $serviceHealth) { [bool]$serviceHealth.scientific_ready } else { $false }
        error = $serviceError
        stdout_log = if ($null -ne $serviceState) { [string]$serviceState.stdout_log } else { $null }
        stderr_log = if ($null -ne $serviceState) { [string]$serviceState.stderr_log } else { $null }
    }
    extractor = [ordered]@{
        enabled_by_default = $false
        pid = if ($null -ne $extractorProcess) { [int]$extractorProcess.ProcessId } else { $null }
        tracked = $null -ne $extractorState
        running = $null -ne $extractorProcess
        port_8091_listening = $extractorPortListening
        health = if ($null -ne $extractorHealth) { [string]$extractorHealth.status } else { 'unavailable' }
        error = $extractorError
        stdout_log = if ($null -ne $extractorState) { [string]$extractorState.stdout_log } else { $null }
        stderr_log = if ($null -ne $extractorState) { [string]$extractorState.stderr_log } else { $null }
    }
}

if ($Json) {
    $status | ConvertTo-Json -Depth 5
}
else {
    [PSCustomObject]@{
        Component = 'local_ai'
        PID = $status.service.pid
        Running = $status.service.running
        Port = $status.service.port_8090_listening
        Health = $status.service.health
        DecisionReady = $status.service.decision_ready
        ScientificReady = $status.service.scientific_ready
    }
    [PSCustomObject]@{
        Component = 'extractor (optional)'
        PID = $status.extractor.pid
        Running = $status.extractor.running
        Port = $status.extractor.port_8091_listening
        Health = $status.extractor.health
        DecisionReady = $null
        ScientificReady = $null
    }
}
