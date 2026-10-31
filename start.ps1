param([switch]$EnableMem0, [switch]$Web)
$ErrorActionPreference = 'Stop'
$python = Join-Path (Split-Path $PSScriptRoot -Parent) '.medix-venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $python)) { throw 'Missing isolated Python environment.' }
$previousKey = $env:OPENAI_API_KEY
$previousMem0Key = $env:MEM0_API_KEY
$previousConfigPath = $env:MEDIX_CONFIG_PATH
$localConfig = Join-Path $PSScriptRoot 'local.config.py'
if (Test-Path -LiteralPath $localConfig) { $env:MEDIX_CONFIG_PATH = $localConfig }
$hasConfigKey = & $python -c "import sys; sys.path.insert(0,sys.argv[1]); from config import LLM_CONFIG; print(LLM_CONFIG.get('api_key') not in ('',None,'not-configured'))" $PSScriptRoot
if (-not $env:OPENAI_API_KEY -and $hasConfigKey -ne 'True') {
    $secret = Read-Host 'OpenAI API Key (not saved)' -AsSecureString
    $credential = [System.Net.NetworkCredential]::new('', $secret)
    $env:OPENAI_API_KEY = $credential.Password
    $credential = $null
    $secret = $null
}
if ($EnableMem0 -and -not $env:MEM0_API_KEY) {
    $secret = Read-Host 'Mem0 API Key (not saved)' -AsSecureString
    $credential = [System.Net.NetworkCredential]::new('', $secret)
    $env:MEM0_API_KEY = $credential.Password
    $credential = $null
    $secret = $null
}
$env:PYTHONUTF8 = '1'
$env:HF_HOME = Join-Path (Split-Path $PSScriptRoot -Parent) '.medix-model-cache'
Push-Location $PSScriptRoot
try {
    & $python knowledge/scripts/migrate_legacy_db.py
    if ($LASTEXITCODE -ne 0) { throw 'Knowledge database setup failed.' }
    if ($Web) { & $python run_web.py } else { & $python main.py }
} finally {
    Pop-Location
    $env:OPENAI_API_KEY = $previousKey
    $env:MEM0_API_KEY = $previousMem0Key
    $env:MEDIX_CONFIG_PATH = $previousConfigPath
}
