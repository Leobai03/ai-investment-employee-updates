. (Join-Path $PSScriptRoot "Common.ps1")

Write-Section "天策 AI 投研数字员工｜安装 Windows 开机自启"
Ensure-ProductEnvironment

$powerShellExe = Join-Path $env:SystemRoot "System32\WindowsPowerShell\v1.0\powershell.exe"
$supervisor = Join-Path $PSScriptRoot "supervisor.ps1"
$shell = New-Object -ComObject WScript.Shell
$shortcut = $shell.CreateShortcut($script:StartupShortcut)
$shortcut.TargetPath = $powerShellExe
$shortcut.Arguments = "-NoLogo -NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File `"$supervisor`""
$shortcut.WorkingDirectory = $script:ProductRoot
$shortcut.Description = "天策 AI 投研数字员工后台守护"
$shortcut.IconLocation = "$powerShellExe,0"
$shortcut.Save()

$existingPid = Join-Path $script:RuntimeDir "windows-supervisor.pid"
$supervisorRunning = $false
if (Test-Path -LiteralPath $existingPid) {
    $processId = [int](Get-Content -LiteralPath $existingPid -Raw)
    $supervisorRunning = Test-OwnedProcess -ProcessId $processId -ExpectedText "supervisor.ps1"
}
if (-not $supervisorRunning) {
    Start-Process `
        -FilePath $powerShellExe `
        -ArgumentList @("-NoLogo", "-NoProfile", "-ExecutionPolicy", "Bypass", "-WindowStyle", "Hidden", "-File", "`"$supervisor`"") `
        -WorkingDirectory $script:ProductRoot `
        -WindowStyle Hidden
}

if (-not (Wait-DeskHealth -Port 8765)) {
    throw "开机自启已创建，但研究台当前未能启动。请查看 Windows 运行日志。"
}
Write-Host "安装完成：以后登录这个 Windows 账号后，研究台会自动运行。" -ForegroundColor Green
Write-Host "关闭浏览器不会停止任务；关机、睡眠或断网期间不会执行。"
Start-Process $script:AppUrl

