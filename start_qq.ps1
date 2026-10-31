param([string]$Proxy = '', [string]$Archive = '', [switch]$PrepareOnly)
$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
$candidates = @('.venv-integration/Scripts/python.exe', '.venv/Scripts/python.exe', '../.medix-venv/Scripts/python.exe')
$python = $null
foreach ($candidate in $candidates) {
    if (Test-Path -LiteralPath $candidate) { $python = (Resolve-Path -LiteralPath $candidate).Path; break }
}
if (-not $python) { $python = (Get-Command python -ErrorAction Stop).Source }
$arguments = @('qq/napcat_runtime.py')
if ($Proxy) { $arguments += @('--proxy', $Proxy) }
if ($Archive) { $arguments += @('--archive', $Archive) }
if ($PrepareOnly) { $arguments += '--prepare-only' }
& $python @arguments
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
if (-not $PrepareOnly) {
    Start-Process -FilePath (Join-Path $PSScriptRoot 'data/napcat/login.html')
}
