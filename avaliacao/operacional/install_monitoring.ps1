[CmdletBinding()]
param(
    [string]$TaskName = 'ProjetoIC-Monitoramento',
    [ValidateRange(1, 1440)][int]$IntervalMinutes = 1,
    [switch]$RunNow
)

$ErrorActionPreference = 'Stop'
$root = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
$python = Join-Path $root '.venv\Scripts\pythonw.exe'
$daemon = Join-Path $root 'avaliacao\operacional\monitor_daemon.py'
$runtime = Join-Path $root 'avaliacao\runtime\monitoring'

if (-not (Test-Path -LiteralPath $python -PathType Leaf)) {
    throw "Ambiente Python não encontrado em $python"
}

$runKey = 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Run'
$runName = 'ProjetoICMonitoramento'
$intervalSeconds = $IntervalMinutes * 60
$arguments = ('"{0}" --runtime-dir "{1}" --interval-seconds {2}' -f $daemon, $runtime, $intervalSeconds)
$runCommand = ('"{0}" {1}' -f $python, $arguments)

New-Item -Path $runKey -Force | Out-Null
Set-ItemProperty -Path $runKey -Name $runName -Value $runCommand

# Remove a tarefa antiga: nesta máquina o Agendador recusava o token interativo
# (0x800710E0). O pythonw no Run do usuário não cria uma janela de terminal.
$oldTask = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
if ($oldTask) {
    Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
}

if ($RunNow) {
    $existing = Get-CimInstance Win32_Process | Where-Object {
        $_.Name -eq 'pythonw.exe' -and
        $_.CommandLine -like ('*"{0}"*' -f $daemon)
    }
    foreach ($process in ($existing | Sort-Object ProcessId -Descending)) {
        Stop-Process -Id $process.ProcessId -Force -ErrorAction SilentlyContinue
    }
    Start-Process `
        -FilePath $python `
        -ArgumentList $arguments `
        -WorkingDirectory $root `
        -WindowStyle Hidden
}

[pscustomobject]@{
    InstallMode = 'HKCU_RUN_PYTHONW'
    RunEntry = $runName
    IntervalMinutes = $IntervalMinutes
    Daemon = $daemon
    RuntimeDirectory = $runtime
}
