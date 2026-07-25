. (Join-Path $PSScriptRoot "Common.ps1")

New-Item -ItemType Directory -Force -Path $script:RuntimeDir | Out-Null
$log = Join-Path $script:RuntimeDir "app.err.log"
if (-not (Test-Path -LiteralPath $log)) {
    Set-Content -LiteralPath $log -Value "目前还没有错误日志。请先运行 Windows_启动研究台.cmd。" -Encoding UTF8
}
Start-Process "notepad.exe" -ArgumentList "`"$log`""

