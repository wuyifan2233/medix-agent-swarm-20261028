param()
$ErrorActionPreference = 'Stop'
$env:PYTHONUTF8 = '1'
if (-not $env:HF_HOME) {
    $env:HF_HOME = Join-Path $PSScriptRoot '.medix-model-cache'
}
Push-Location $PSScriptRoot
try {
    conda run --no-capture-output -n medix python run_web.py
    if ($LASTEXITCODE -ne 0) { throw 'MediX exited with an error.' }
} finally {
    Pop-Location
}
