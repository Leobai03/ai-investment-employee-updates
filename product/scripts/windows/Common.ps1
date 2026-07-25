$ErrorActionPreference = "Stop"
Set-StrictMode -Version 2.0

$script:ProductRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
$script:RuntimeDir = Join-Path $script:ProductRoot "runtime"
$script:VenvPython = Join-Path $script:ProductRoot ".venv\Scripts\python.exe"
$script:AppUrl = "http://127.0.0.1:8765"
$script:DemoUrl = "http://127.0.0.1:8766"
$script:StartupShortcut = Join-Path ([Environment]::GetFolderPath("Startup")) "AI投研数字员工.lnk"

function Write-Section {
    param([Parameter(Mandatory = $true)][string]$Title)
    Write-Host ""
    Write-Host $Title -ForegroundColor Cyan
    Write-Host ("-" * $Title.Length) -ForegroundColor DarkGray
}

function Refresh-ProcessPath {
    $machinePath = [Environment]::GetEnvironmentVariable("Path", "Machine")
    $userPath = [Environment]::GetEnvironmentVariable("Path", "User")
    $env:Path = (($machinePath, $userPath) -join ";").Trim(";")
}

function Get-EnvValue {
    param([Parameter(Mandatory = $true)][string]$Name)
    $envFile = Join-Path $script:ProductRoot ".env"
    if (-not (Test-Path $envFile)) {
        return ""
    }
    foreach ($line in Get-Content -LiteralPath $envFile -Encoding UTF8) {
        if ($line -match "^\s*$([Regex]::Escape($Name))\s*=(.*)$") {
            return $Matches[1].Trim().Trim('"').Trim("'")
        }
    }
    return ""
}

function Set-EnvValue {
    param(
        [Parameter(Mandatory = $true)][string]$Name,
        [AllowEmptyString()][string]$Value
    )
    $envFile = Join-Path $script:ProductRoot ".env"
    if (-not (Test-Path $envFile)) {
        Copy-Item -LiteralPath (Join-Path $script:ProductRoot ".env.example") -Destination $envFile
    }
    $lines = @(Get-Content -LiteralPath $envFile -Encoding UTF8)
    $updated = $false
    for ($index = 0; $index -lt $lines.Count; $index++) {
        if ($lines[$index] -match "^\s*$([Regex]::Escape($Name))\s*=") {
            $lines[$index] = "$Name=$Value"
            $updated = $true
            break
        }
    }
    if (-not $updated) {
        $lines += "$Name=$Value"
    }
    Set-Content -LiteralPath $envFile -Value $lines -Encoding UTF8
}

function Get-CompatiblePython {
    $candidates = @()
    $py = Get-Command "py.exe" -ErrorAction SilentlyContinue
    if ($py) {
        $candidates += [PSCustomObject]@{ Exe = $py.Source; Prefix = @("-3") }
    }
    $python = Get-Command "python.exe" -ErrorAction SilentlyContinue
    if ($python) {
        $candidates += [PSCustomObject]@{ Exe = $python.Source; Prefix = @() }
    }
    foreach ($candidate in $candidates) {
        try {
            $version = & $candidate.Exe @($candidate.Prefix) -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')" 2>$null
            if ($LASTEXITCODE -eq 0 -and [Version]$version -ge [Version]"3.11") {
                return $candidate
            }
        } catch {
            continue
        }
    }
    return $null
}

function Get-CodexCommand {
    if ($env:APPDATA) {
        $npmCodex = Join-Path $env:APPDATA "npm\codex.cmd"
        if (Test-Path -LiteralPath $npmCodex) {
            return $npmCodex
        }
    }
    $configured = Get-EnvValue -Name "CODEX_BIN"
    if ($configured -and (Test-Path -LiteralPath $configured)) {
        return (Resolve-Path -LiteralPath $configured).Path
    }
    foreach ($name in @("codex.exe", "codex.cmd", "codex")) {
        $command = Get-Command $name -ErrorAction SilentlyContinue
        if ($command) {
            return $command.Source
        }
    }
    return ""
}

function Ensure-ProductEnvironment {
    param([switch]$ForceDependencies)
    New-Item -ItemType Directory -Force -Path $script:RuntimeDir | Out-Null

    if (-not (Test-Path -LiteralPath $script:VenvPython)) {
        $python = Get-CompatiblePython
        if (-not $python) {
            throw "未找到 Python 3.11 或更高版本。请先运行「Windows_首次配置.cmd」。"
        }
        Write-Host "正在创建产品自己的 Python 环境……"
        & $python.Exe @($python.Prefix) -m venv (Join-Path $script:ProductRoot ".venv")
        if ($LASTEXITCODE -ne 0) {
            throw "Python 虚拟环境创建失败。"
        }
    }

    $requirements = Join-Path $script:ProductRoot "requirements.txt"
    $fingerprintFile = Join-Path $script:RuntimeDir "requirements.sha256"
    $requirementsHash = (Get-FileHash -LiteralPath $requirements -Algorithm SHA256).Hash.ToLowerInvariant()
    $installedHash = ""
    if (Test-Path -LiteralPath $fingerprintFile) {
        $installedHash = (Get-Content -LiteralPath $fingerprintFile -Raw).Trim().ToLowerInvariant()
    }
    $previousErrorActionPreference = $ErrorActionPreference
    try {
        $ErrorActionPreference = "Continue"
        & $script:VenvPython -c "import fastapi, uvicorn, openai, docx, reportlab" 2>$null
        $importsMissing = $LASTEXITCODE -ne 0
    } finally {
        $ErrorActionPreference = $previousErrorActionPreference
    }
    if ($ForceDependencies -or $importsMissing -or $installedHash -ne $requirementsHash) {
        Write-Host "正在安装产品依赖，首次运行可能需要几分钟……"
        & $script:VenvPython -m pip install --disable-pip-version-check -r $requirements
        if ($LASTEXITCODE -ne 0) {
            throw "产品依赖安装失败，请检查网络后重试。"
        }
        Set-Content -LiteralPath $fingerprintFile -Value $requirementsHash -Encoding ASCII
    }
}

function Test-DeskHealth {
    param([int]$Port = 8765)
    try {
        $response = Invoke-RestMethod -Method Get -Uri "http://127.0.0.1:$Port/api/health" -TimeoutSec 2
        return [bool]$response.ok
    } catch {
        return $false
    }
}

function Wait-DeskHealth {
    param(
        [int]$Port = 8765,
        [int]$Attempts = 50
    )
    for ($attempt = 0; $attempt -lt $Attempts; $attempt++) {
        if (Test-DeskHealth -Port $Port) {
            return $true
        }
        Start-Sleep -Milliseconds 500
    }
    return $false
}

function Test-OwnedProcess {
    param(
        [Parameter(Mandatory = $true)][int]$ProcessId,
        [Parameter(Mandatory = $true)][string]$ExpectedText
    )
    try {
        $process = Get-CimInstance Win32_Process -Filter "ProcessId = $ProcessId"
        if (-not $process) {
            return $false
        }
        $commandLine = [string]$process.CommandLine
        return $commandLine.Contains($script:ProductRoot) -and $commandLine.Contains($ExpectedText)
    } catch {
        return $false
    }
}

function Start-ResearchDesk {
    param(
        [switch]$Demo,
        [switch]$NoBrowser
    )
    Ensure-ProductEnvironment
    $port = if ($Demo) { 8766 } else { 8765 }
    $url = if ($Demo) { $script:DemoUrl } else { $script:AppUrl }
    $pidName = if ($Demo) { "demo.pid" } else { "app.pid" }
    $logPrefix = if ($Demo) { "demo" } else { "app" }
    $pidFile = Join-Path $script:RuntimeDir $pidName

    if (Test-DeskHealth -Port $port) {
        Write-Host "研究台已经在运行：$url" -ForegroundColor Green
        if (-not $NoBrowser) {
            Start-Process $url
        }
        return
    }

    if (Test-Path -LiteralPath $pidFile) {
        Remove-Item -LiteralPath $pidFile -Force
    }

    $oldDemo = $env:AI_RESEARCH_DEMO
    $oldPort = $env:AI_RESEARCH_PORT
    $oldDb = $env:AI_RESEARCH_DB
    try {
        if ($Demo) {
            $env:AI_RESEARCH_DEMO = "1"
            $env:AI_RESEARCH_PORT = "8766"
            $env:AI_RESEARCH_DB = Join-Path $script:ProductRoot "data\demo.db"
        } else {
            $env:AI_RESEARCH_DEMO = "0"
            $env:AI_RESEARCH_PORT = "8765"
        }
        $listenHost = Get-EnvValue -Name "AI_RESEARCH_HOST"
        if (-not $listenHost) {
            $listenHost = "127.0.0.1"
        }
        $process = Start-Process `
            -FilePath $script:VenvPython `
            -ArgumentList @("-m", "uvicorn", "app.main:app", "--host", $listenHost, "--port", "$port") `
            -WorkingDirectory $script:ProductRoot `
            -WindowStyle Hidden `
            -RedirectStandardOutput (Join-Path $script:RuntimeDir "$logPrefix.out.log") `
            -RedirectStandardError (Join-Path $script:RuntimeDir "$logPrefix.err.log") `
            -PassThru
        Set-Content -LiteralPath $pidFile -Value $process.Id -Encoding ASCII
    } finally {
        $env:AI_RESEARCH_DEMO = $oldDemo
        $env:AI_RESEARCH_PORT = $oldPort
        $env:AI_RESEARCH_DB = $oldDb
    }

    if (-not (Wait-DeskHealth -Port $port)) {
        throw "研究台启动失败。请双击「Windows_查看运行日志.cmd」查看原因。"
    }
    Write-Host "研究台已启动：$url" -ForegroundColor Green
    if ($Demo) {
        Write-Host "当前为演示模式，不会检索或虚构实时市场信息。" -ForegroundColor Yellow
    }
    if (-not $NoBrowser) {
        Start-Process $url
    }
}

function Stop-ResearchDesk {
    param([switch]$IncludeSupervisor)
    $stopped = $false

    if ($IncludeSupervisor) {
        $supervisorPid = Join-Path $script:RuntimeDir "windows-supervisor.pid"
        if (Test-Path -LiteralPath $supervisorPid) {
            $processId = [int](Get-Content -LiteralPath $supervisorPid -Raw)
            if (Test-OwnedProcess -ProcessId $processId -ExpectedText "supervisor.ps1") {
                Stop-Process -Id $processId -Force -ErrorAction SilentlyContinue
                $stopped = $true
            }
            Remove-Item -LiteralPath $supervisorPid -Force -ErrorAction SilentlyContinue
        }
    }

    foreach ($item in @(
        @{ Pid = "app.pid"; Expected = "uvicorn" },
        @{ Pid = "demo.pid"; Expected = "uvicorn" }
    )) {
        $pidFile = Join-Path $script:RuntimeDir $item.Pid
        if (-not (Test-Path -LiteralPath $pidFile)) {
            continue
        }
        $processId = [int](Get-Content -LiteralPath $pidFile -Raw)
        if (Test-OwnedProcess -ProcessId $processId -ExpectedText $item.Expected) {
            Stop-Process -Id $processId -Force -ErrorAction SilentlyContinue
            $stopped = $true
        }
        Remove-Item -LiteralPath $pidFile -Force -ErrorAction SilentlyContinue
    }
    return $stopped
}
