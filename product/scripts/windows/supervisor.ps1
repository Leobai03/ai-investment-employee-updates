. (Join-Path $PSScriptRoot "Common.ps1")

New-Item -ItemType Directory -Force -Path $script:RuntimeDir | Out-Null
$supervisorPid = Join-Path $script:RuntimeDir "windows-supervisor.pid"
Set-Content -LiteralPath $supervisorPid -Value $PID -Encoding ASCII
$nextUpdateCheck = Get-Date
$intervalText = Get-EnvValue -Name "AUTO_UPDATE_INTERVAL_HOURS"
$updateIntervalHours = 6
if ($intervalText -match '^[0-9]+$' -and [int]$intervalText -ge 1) {
    $updateIntervalHours = [int]$intervalText
}
$powerShellExe = Join-Path $env:SystemRoot "System32\WindowsPowerShell\v1.0\powershell.exe"
$updateScript = Join-Path $PSScriptRoot "update.ps1"

try {
    while ($true) {
        if ((Get-Date) -ge $nextUpdateCheck -and (Get-EnvValue -Name "AUTO_UPDATE_ENABLED") -ne "0") {
            try {
                & $powerShellExe -NoLogo -NoProfile -ExecutionPolicy Bypass -File $updateScript -Automatic
            } catch {
                $line = "$(Get-Date -Format o)  自动更新检查失败：$($_.Exception.Message)"
                Add-Content -LiteralPath (Join-Path $script:RuntimeDir "windows-supervisor.log") -Value $line -Encoding UTF8
            }
            $nextUpdateCheck = (Get-Date).AddHours($updateIntervalHours)
        }
        if (-not (Test-DeskHealth -Port 8765)) {
            try {
                Start-ResearchDesk -NoBrowser
            } catch {
                $line = "$(Get-Date -Format o)  $($_.Exception.Message)"
                Add-Content -LiteralPath (Join-Path $script:RuntimeDir "windows-supervisor.log") -Value $line -Encoding UTF8
            }
        }
        Start-Sleep -Seconds 20
    }
} finally {
    Remove-Item -LiteralPath $supervisorPid -Force -ErrorAction SilentlyContinue
}
