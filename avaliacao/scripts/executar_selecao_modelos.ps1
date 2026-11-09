param(
    [Parameter(Mandatory = $true)]
    [string]$Saida,
    [string]$Config = 'avaliacao\config\selecao_modelos_supervisionados_v2.json',
    [switch]$Resume,
    [switch]$SkipXai
)

$ErrorActionPreference = 'Stop'
$root = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
$output = [System.IO.Path]::GetFullPath((Join-Path $root $Saida))
$configPath = [System.IO.Path]::GetFullPath((Join-Path $root $Config))
if (-not (Test-Path -LiteralPath $configPath -PathType Leaf)) {
    throw "Arquivo de protocolo não encontrado: $configPath"
}
[System.IO.Directory]::CreateDirectory($output) | Out-Null
$pidPath = Join-Path $output 'execucao.pid'
$metadataPath = Join-Path $output 'execucao_lancamento.json'

$env:OMP_NUM_THREADS = '4'
$env:MKL_NUM_THREADS = '4'
$env:OPENBLAS_NUM_THREADS = '4'
$env:NUMEXPR_NUM_THREADS = '4'

$arguments = @(
    (Join-Path $root 'avaliacao\scripts\selecionar_modelos_supervisionados.py'),
    '--config',
    $configPath,
    '--saida',
    $output
)
if ($Resume) {
    $arguments += '--resume'
}
if ($SkipXai) {
    $arguments += '--skip-xai'
}

$stdout = Join-Path $output 'execucao.stdout.log'
$stderr = Join-Path $output 'execucao.stderr.log'
$preflightStdout = Join-Path $output 'preflight_viabilidade.stdout.log'
$preflightStderr = Join-Path $output 'preflight_viabilidade.stderr.log'
$preflightJson = Join-Path $output 'preflight_viabilidade.json'
$PID | Set-Content -LiteralPath $pidPath -Encoding ascii
@{
    schema = 'projeto-ic-lancamento-selecao-v2'
    started_at = [DateTimeOffset]::Now.ToString('o')
    launcher_pid = $PID
    output = $output
    config = $configPath
    resume = [bool]$Resume
    skip_xai = [bool]$SkipXai
    thread_limits = 4
} | ConvertTo-Json | Set-Content -LiteralPath $metadataPath -Encoding utf8
try {
    # Windows PowerShell transforma qualquer texto nativo em stderr em um
    # ErrorRecord quando ErrorActionPreference=Stop. Bibliotecas científicas
    # emitem FutureWarning em stderr mesmo com exit code 0; a decisão deve ser
    # feita pelo código de saída do Python, preservando o log completo.
    $previousErrorActionPreference = $ErrorActionPreference
    $ErrorActionPreference = 'Continue'
    & python (Join-Path $root 'avaliacao\scripts\validar_viabilidade_protocolo_selecao.py') `
        --config $configPath `
        --output $preflightJson `
        1> $preflightStdout 2> $preflightStderr
    $preflightExitCode = $LASTEXITCODE
    if ($preflightExitCode -ne 0) {
        $metadata = Get-Content -LiteralPath $metadataPath -Raw | ConvertFrom-Json
        $metadata | Add-Member -NotePropertyName finished_at -NotePropertyValue ([DateTimeOffset]::Now.ToString('o'))
        $metadata | Add-Member -NotePropertyName exit_code -NotePropertyValue $preflightExitCode
        $metadata | Add-Member -NotePropertyName preflight_status -NotePropertyValue 'INFEASIBLE'
        $metadata | ConvertTo-Json | Set-Content -LiteralPath $metadataPath -Encoding utf8
        exit $preflightExitCode
    }
    & python @arguments 1> $stdout 2> $stderr
    $exitCode = $LASTEXITCODE
    $ErrorActionPreference = $previousErrorActionPreference
    $metadata = Get-Content -LiteralPath $metadataPath -Raw | ConvertFrom-Json
    $metadata | Add-Member -NotePropertyName finished_at -NotePropertyValue ([DateTimeOffset]::Now.ToString('o'))
    $metadata | Add-Member -NotePropertyName exit_code -NotePropertyValue $exitCode
    $metadata | ConvertTo-Json | Set-Content -LiteralPath $metadataPath -Encoding utf8
    exit $exitCode
}
finally {
    if ($null -ne $previousErrorActionPreference) {
        $ErrorActionPreference = $previousErrorActionPreference
    }
    Remove-Item -LiteralPath $pidPath -Force -ErrorAction SilentlyContinue
}
