param([switch]$EnableMem0)
& (Join-Path $PSScriptRoot 'start.ps1') -Web -EnableMem0:$EnableMem0
