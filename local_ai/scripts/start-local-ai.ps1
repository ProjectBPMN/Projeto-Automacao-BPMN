[CmdletBinding()]
param(
    [switch]$WithExtractor,
    [switch]$SkipHashVerification,
    [string]$HybridManifest = '',
    [ValidateRange(1, 4)][int]$CpuThreads = 4,
    [ValidateRange(1, 16)][int]$MaxEmbedBatch = 4,
    [ValidateRange(10, 180)][int]$ServiceStartupTimeoutSeconds = 120,
    [ValidateRange(30, 300)][int]$ExtractorStartupTimeoutSeconds = 120
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest
. (Join-Path $PSScriptRoot 'local-ai-common.ps1')

Initialize-LocalAiRuntimeDirectories

$token = Get-DotEnvValue -Path $N8nEnvPath -Name 'IA_LOCAL_API_TOKEN'
if ([string]::IsNullOrWhiteSpace($token)) {
    throw "IA_LOCAL_API_TOKEN deve estar preenchido em $N8nEnvPath antes de expor a API em 0.0.0.0."
}

$configuredHybrid = Get-DotEnvValue -Path $N8nEnvPath -Name 'LOCAL_AI_HYBRID_MANIFEST'
$selectedHybrid = if ([string]::IsNullOrWhiteSpace($HybridManifest)) {
    $configuredHybrid
}
else {
    $HybridManifest
}
$hybridManifest = Resolve-LocalAiPath -ConfiguredValue $selectedHybrid -DefaultPath (Join-Path $LocalAiRoot 'artifacts\local_hybrid_manifest.json')
$embeddingRevision = Get-DotEnvValue -Path $N8nEnvPath -Name 'LOCAL_AI_EMBED_MODEL_REVISION'
if ([string]::IsNullOrWhiteSpace($embeddingRevision)) {
    throw "LOCAL_AI_EMBED_MODEL_REVISION deve estar preenchido em $N8nEnvPath."
}
$embeddingPath = Join-Path $ModelsRoot 'granite-embedding-97m-multilingual-r2'
$extractorModelPath = Join-Path $ModelsRoot 'granite-4.0-h-350m-Q4_K_M.gguf'
$extractorBinary = Join-Path $RuntimeRoot 'llama-b10018\llama-server.exe'

if (-not (Test-Path -LiteralPath $hybridManifest -PathType Leaf)) {
    throw "Manifesto híbrido obrigatório ausente: $hybridManifest. Treine/aprove o bundle antes de iniciar em produção."
}
if (-not (Test-Path -LiteralPath $embeddingPath -PathType Container)) {
    throw "Granite Embedding local ausente: $embeddingPath"
}
if (-not $SkipHashVerification) {
    Write-Host 'Validando hashes dos modelos locais...'
    Test-LocalModelManifest -IncludeExtractor:$WithExtractor | Out-Null
}

$trackedService = Get-TrackedProcess -StatePath $ServiceStatePath -IdentityPattern '(?i)(-m\s+local_ai|local_ai)'
if ($null -ne $trackedService) {
    throw "Serviço local_ai já está ativo com PID $($trackedService.ProcessId)."
}
$trackedExtractor = Get-TrackedProcess -StatePath $ExtractorStatePath -IdentityPattern '(?i)llama-server'
if ($null -ne $trackedExtractor) {
    throw "Extractor já está ativo com PID $($trackedExtractor.ProcessId)."
}
Remove-Item -LiteralPath $ServiceStatePath, $ExtractorStatePath -Force -ErrorAction SilentlyContinue

if (Test-TcpPort -Address '127.0.0.1' -Port 8090) {
    throw 'A porta 8090 já está ocupada por um processo não rastreado.'
}
if ($WithExtractor -and (Test-TcpPort -Address '127.0.0.1' -Port 8091)) {
    throw 'A porta 8091 já está ocupada por um processo não rastreado.'
}

$timestamp = [DateTime]::UtcNow.ToString('yyyyMMdd-HHmmss')
$serviceStdout = Join-Path $LogRoot "local-ai-$timestamp.out.log"
$serviceStderr = Join-Path $LogRoot "local-ai-$timestamp.err.log"
$extractorStdout = Join-Path $LogRoot "extractor-$timestamp.out.log"
$extractorStderr = Join-Path $LogRoot "extractor-$timestamp.err.log"
$serviceProcess = $null
$extractorProcess = $null

try {
    if ($WithExtractor) {
        if (-not (Test-Path -LiteralPath $extractorBinary -PathType Leaf)) {
            throw "llama-server ausente: $extractorBinary"
        }
        if (-not (Test-Path -LiteralPath $extractorModelPath -PathType Leaf)) {
            throw "Modelo GGUF ausente: $extractorModelPath"
        }
        $extractorArguments = @(
            '--model', "`"$extractorModelPath`"",
            '--alias', 'ibm-granite/granite-4.0-h-350m-GGUF-Q4_K_M',
            '--host', '127.0.0.1',
            '--port', '8091',
            '--threads', '2',
            '--threads-batch', '2',
            '--ctx-size', '512',
            '--batch-size', '128',
            '--ubatch-size', '128',
            '--parallel', '1',
            '--n-predict', '128',
            '--no-webui'
        )
        $extractorProcess = Start-Process -FilePath $extractorBinary -ArgumentList $extractorArguments -WorkingDirectory $RepositoryRoot -WindowStyle Hidden -RedirectStandardOutput $extractorStdout -RedirectStandardError $extractorStderr -PassThru
        Write-ProcessState -Path $ExtractorStatePath -ProcessId $extractorProcess.Id -Component 'extractor' -Identity 'llama-server' -StdoutLog $extractorStdout -StderrLog $extractorStderr
        Wait-JsonHealth -Uri 'http://127.0.0.1:8091/health' -TimeoutSeconds $ExtractorStartupTimeoutSeconds | Out-Null
    }

    $pythonw = Join-Path $RepositoryRoot '.venv\Scripts\pythonw.exe'
    $python = if (Test-Path -LiteralPath $pythonw -PathType Leaf) {
        $pythonw
    }
    else {
        (Get-Command pythonw -ErrorAction Stop).Source
    }
    $environment = [ordered]@{
        LOCAL_AI_MODE = 'production'
        LOCAL_AI_HOST = '0.0.0.0'
        LOCAL_AI_PORT = '8090'
        LOCAL_AI_API_TOKEN = $token
        LOCAL_AI_CPU_THREADS = [string]$CpuThreads
        LOCAL_AI_MAX_CONCURRENT = '1'
        # Lotes pequenos reduzem o pico temporário do encoder no computador
        # de 8 GB sem alterar embeddings, probabilidades ou decisões.
        LOCAL_AI_MAX_EMBED_BATCH = [string]$MaxEmbedBatch
        LOCAL_AI_DEV_FALLBACK = 'off'
        LOCAL_AI_ALLOW_MODEL_DOWNLOAD = 'false'
        LOCAL_AI_EMBED_BACKEND = 'pytorch_fp32'
        LOCAL_AI_EMBED_MODEL_REVISION = $embeddingRevision
        LOCAL_AI_EMBED_MODEL_PATH = $embeddingPath
        LOCAL_AI_MAX_CANDIDATES = '20'
        LOCAL_AI_HYBRID_MANIFEST = $hybridManifest
        LOCAL_AI_EXTRACTOR_ENABLED = if ($WithExtractor) { 'true' } else { 'false' }
        LOCAL_AI_EXTRACTOR_URL = 'http://127.0.0.1:8091/v1'
        LOCAL_AI_EXTRACTOR_MODEL = 'ibm-granite/granite-4.0-h-350m-GGUF-Q4_K_M'
        HF_HUB_OFFLINE = '1'
        TRANSFORMERS_OFFLINE = '1'
        TOKENIZERS_PARALLELISM = 'false'
        PYTHONUNBUFFERED = '1'
    }
    $previousEnvironment = @{}
    foreach ($entry in $environment.GetEnumerator()) {
        $previousEnvironment[$entry.Key] = [Environment]::GetEnvironmentVariable($entry.Key, 'Process')
        [Environment]::SetEnvironmentVariable($entry.Key, [string]$entry.Value, 'Process')
    }
    try {
        $serviceProcess = Start-Process -FilePath $python -ArgumentList @('-m', 'local_ai', '--host', '0.0.0.0', '--port', '8090') -WorkingDirectory $RepositoryRoot -WindowStyle Hidden -RedirectStandardOutput $serviceStdout -RedirectStandardError $serviceStderr -PassThru
    }
    finally {
        foreach ($entry in $previousEnvironment.GetEnumerator()) {
            [Environment]::SetEnvironmentVariable($entry.Key, $entry.Value, 'Process')
        }
    }
    Write-ProcessState -Path $ServiceStatePath -ProcessId $serviceProcess.Id -Component 'local_ai' -Identity '-m local_ai' -StdoutLog $serviceStdout -StderrLog $serviceStderr
    $health = Wait-JsonHealth -Uri 'http://127.0.0.1:8090/health' -Token $token -TimeoutSeconds $ServiceStartupTimeoutSeconds
    if ($health.decision_ready -ne $true) {
        throw "Serviço respondeu, mas decision_ready=false. Consulte $serviceStderr"
    }

    # O Granite é lazy no processo Python. Aquecê-lo aqui comprova, antes de o
    # n8n receber tráfego, a dimensão, a revisão, o hash da árvore local e o
    # runtime PyTorch FP32. Isso também retira o custo de carga da primeira
    # decisão real e evita um health temporariamente ambíguo.
    $warmupBody = @{ input = 'verificacao tecnica de inicializacao do backend local' } | ConvertTo-Json -Compress
    try {
        $warmup = Invoke-RestMethod `
            -Method Post `
            -Uri 'http://127.0.0.1:8090/v1/embed?include_metadata=1' `
            -Headers @{ Authorization = "Bearer $token" } `
            -ContentType 'application/json; charset=utf-8' `
            -Body ([Text.Encoding]::UTF8.GetBytes($warmupBody)) `
            -TimeoutSec $ServiceStartupTimeoutSeconds
    }
    catch {
        throw "Falha no warm-up obrigatório do Granite PyTorch FP32: $($_.Exception.Message). Consulte $serviceStderr"
    }
    if (
        $warmup.result.dimension -ne 384 -or
        $warmup.result.backend.backend -ne 'granite_embedding_pytorch_fp32' -or
        $warmup.result.backend.runtime_backend -ne 'pytorch_fp32' -or
        $warmup.result.backend.precision -ne 'fp32' -or
        $warmup.result.backend.model_revision -ne $embeddingRevision -or
        $warmup.result.backend.scientific_eligible -ne $true
    ) {
        throw 'Warm-up retornou proveniência incompatível com Granite 97M PyTorch FP32.'
    }
    $health = Wait-JsonHealth -Uri 'http://127.0.0.1:8090/health' -Token $token -TimeoutSeconds 15
    if ($health.candidate_evaluation_eligible -ne $true) {
        throw "Backend e bundle não ficaram elegíveis para avaliação confirmatória. Consulte $serviceStderr"
    }
    if ($health.scientific_ready -ne $true) {
        Write-Warning 'Serviço operacional, porém scientific_ready=false; não use esta execução como resultado confirmatório.'
    }

    Write-Host "local_ai ativo: PID $($serviceProcess.Id), http://0.0.0.0:8090"
    Write-Host "Extractor: $(if ($WithExtractor) { "ativo em 127.0.0.1:8091 (PID $($extractorProcess.Id))" } else { 'desligado' })"
    Write-Host "Logs: $LogRoot"
}
catch {
    if ($null -ne $serviceProcess -and -not $serviceProcess.HasExited) {
        Stop-Process -Id $serviceProcess.Id -Force -ErrorAction SilentlyContinue
    }
    if ($null -ne $extractorProcess -and -not $extractorProcess.HasExited) {
        Stop-Process -Id $extractorProcess.Id -Force -ErrorAction SilentlyContinue
    }
    Remove-Item -LiteralPath $ServiceStatePath, $ExtractorStatePath -Force -ErrorAction SilentlyContinue
    throw
}
