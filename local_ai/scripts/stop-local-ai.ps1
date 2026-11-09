[CmdletBinding()]
param(
    [ValidateSet('All', 'Service', 'Extractor')][string]$Component = 'All'
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest
. (Join-Path $PSScriptRoot 'local-ai-common.ps1')

function Stop-TrackedComponent {
    param(
        [Parameter(Mandatory = $true)][string]$Name,
        [Parameter(Mandatory = $true)][string]$StatePath,
        [Parameter(Mandatory = $true)][string]$IdentityPattern
    )
    $state = Read-ProcessState -Path $StatePath
    $process = Get-TrackedProcess -StatePath $StatePath -IdentityPattern $IdentityPattern
    if ($null -eq $process) {
        if ($null -ne $state) {
            Write-Warning "$Name não foi encerrado: o PID registrado não pertence mais ao processo esperado."
        }
        else {
            Write-Host "$Name já está parado."
        }
        Remove-Item -LiteralPath $StatePath -Force -ErrorAction SilentlyContinue
        return
    }
    $processId = [int]$process.ProcessId
    Stop-Process -Id $processId -Force -ErrorAction Stop
    $deadline = [DateTime]::UtcNow.AddSeconds(10)
    while ([DateTime]::UtcNow -lt $deadline) {
        if ($null -eq (Get-Process -Id $processId -ErrorAction SilentlyContinue)) {
            break
        }
        Start-Sleep -Milliseconds 200
    }
    if ($null -ne (Get-Process -Id $processId -ErrorAction SilentlyContinue)) {
        throw "Não foi possível encerrar $Name (PID $processId)."
    }
    Remove-Item -LiteralPath $StatePath -Force -ErrorAction SilentlyContinue
    Write-Host "$Name encerrado (PID $processId)."
}

if ($Component -in @('All', 'Service')) {
    Stop-TrackedComponent -Name 'local_ai' -StatePath $ServiceStatePath -IdentityPattern '(?i)(-m\s+local_ai|local_ai)'
}
if ($Component -in @('All', 'Extractor')) {
    Stop-TrackedComponent -Name 'extractor' -StatePath $ExtractorStatePath -IdentityPattern '(?i)llama-server'
}

