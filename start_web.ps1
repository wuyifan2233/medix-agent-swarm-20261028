param([switch]$EnableMem0,
      [ValidateSet('DeepSeek', 'Existing')][string]$Provider = 'DeepSeek')
& (Join-Path $PSScriptRoot 'start.ps1') -Web -EnableMem0:$EnableMem0 -Provider $Provider
