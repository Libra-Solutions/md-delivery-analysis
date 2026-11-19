# Daily delivery analytics sync, run by Windows Task Scheduler.
# Output goes to a dated log under the results folder (not in git).
$ErrorActionPreference = 'Continue'
$repo = Split-Path -Parent $PSScriptRoot
$uv = 'C:\Users\CWogu\AppData\Local\Microsoft\WinGet\Packages\astral-sh.uv_Microsoft.Winget.Source_8wekyb3d8bbwe\uv.exe'
$results = if ($env:GITHUB_ANALYSIS_RESULTS) { $env:GITHUB_ANALYSIS_RESULTS } else { Join-Path $env:USERPROFILE 'github-analysis-results' }
$logDir = Join-Path $results 'logs'
New-Item -ItemType Directory -Force $logDir | Out-Null
$log = Join-Path $logDir ("daily-sync-{0}.log" -f (Get-Date -Format 'yyyy-MM-dd'))

Set-Location $repo
$env:PYTHONIOENCODING = 'utf-8'
"=== Sync started $(Get-Date -Format o) ===" | Out-File -Append -Encoding utf8 $log
& $uv run delivery-analysis sync *>&1 | ForEach-Object { "$_" } | Out-File -Append -Encoding utf8 $log
$code = $LASTEXITCODE
"=== Sync finished $(Get-Date -Format o), exit $code ===" | Out-File -Append -Encoding utf8 $log

# Keep 30 days of logs.
Get-ChildItem $logDir -Filter 'daily-sync-*.log' | Where-Object { $_.LastWriteTime -lt (Get-Date).AddDays(-30) } | Remove-Item -Force
exit $code
