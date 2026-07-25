. (Join-Path $PSScriptRoot "Common.ps1")

Write-Section "天策 AI 投研数字员工｜Windows 自检"
$allGood = $true

$os = Get-CimInstance Win32_OperatingSystem
Write-Host "Windows：$($os.Caption)（Build $($os.BuildNumber)）"
Write-Host "产品目录：$script:ProductRoot"
Write-Host "网页地址：$script:AppUrl"

$chatGptPackages = @(Get-AppxPackage -ErrorAction SilentlyContinue | Where-Object {
    $_.Name -match "ChatGPT" -or $_.PackageFamilyName -match "9PLM9XGG6VKS"
})
if ($chatGptPackages.Count -gt 0) {
    Write-Host "✓ ChatGPT Windows 客户端已安装" -ForegroundColor Green
} else {
    Write-Host "✗ 未检测到 ChatGPT Windows 客户端" -ForegroundColor Red
    $allGood = $false
}

$python = Get-CompatiblePython
if ($python) {
    Write-Host "✓ Python：$(& $python.Exe @($python.Prefix) --version)" -ForegroundColor Green
} else {
    Write-Host "✗ 未找到 Python 3.11+" -ForegroundColor Red
    $allGood = $false
}

if (Test-Path -LiteralPath $script:VenvPython) {
    & $script:VenvPython -c "import fastapi, uvicorn, openai, docx, reportlab" 2>$null
    if ($LASTEXITCODE -eq 0) {
        Write-Host "✓ 产品 Python 环境完整" -ForegroundColor Green
    } else {
        Write-Host "✗ 产品依赖不完整" -ForegroundColor Red
        $allGood = $false
    }
} else {
    Write-Host "✗ 产品 Python 环境尚未创建" -ForegroundColor Red
    $allGood = $false
}

$codex = Get-CodexCommand
if ($codex) {
    Write-Host "✓ Codex：$codex" -ForegroundColor Green
    & $codex --version
    & $codex app-server --help *> $null
    if ($LASTEXITCODE -eq 0) {
        Write-Host "✓ Codex App Server 可用" -ForegroundColor Green
    } else {
        Write-Host "✗ Codex App Server 不可用" -ForegroundColor Red
        $allGood = $false
    }
    $login = (& $codex login status 2>&1 | Out-String)
    if ($login -match "Logged in") {
        Write-Host "✓ Codex 已登录" -ForegroundColor Green
    } else {
        Write-Host "✗ Codex 尚未登录 ChatGPT" -ForegroundColor Red
        $allGood = $false
    }
    $plugins = (& $codex plugin list --json 2>&1 | Out-String)
    if ($plugins -match "ai-investment-employee") {
        Write-Host "✓ AI 投研数字员工插件已安装" -ForegroundColor Green
    } else {
        Write-Host "✗ 未检测到 AI 投研数字员工插件" -ForegroundColor Red
        $allGood = $false
    }
} else {
    Write-Host "✗ 未找到 Codex CLI" -ForegroundColor Red
    $allGood = $false
}

if (Test-DeskHealth -Port 8765) {
    Write-Host "✓ 研究台正在运行，只监听本机地址" -ForegroundColor Green
    try {
        $listeners = @(Get-NetTCPConnection -LocalPort 8765 -State Listen -ErrorAction Stop)
        $nonLocal = @($listeners | Where-Object { $_.LocalAddress -notin @("127.0.0.1", "::1") })
        if ($nonLocal.Count -gt 0) {
            Write-Host "✗ 端口 8765 存在非本机监听" -ForegroundColor Red
            $allGood = $false
        }
    } catch {
        Write-Host "! 无法读取端口监听详情，但网页健康检查已通过" -ForegroundColor Yellow
    }
} else {
    Write-Host "! 研究台当前未运行" -ForegroundColor Yellow
}

if (Test-Path -LiteralPath $script:StartupShortcut) {
    Write-Host "✓ 当前 Windows 用户已安装开机自启" -ForegroundColor Green
} else {
    Write-Host "! 尚未安装开机自启" -ForegroundColor Yellow
}

Write-Host ""
Write-Host "电源提醒：若要按时自动收集，请在「设置 → 系统 → 电源和电池」中把接通电源后的睡眠设为「从不」。" -ForegroundColor Yellow
Write-Host "关机、睡眠或断网期间任务不会执行；恢复后只补一份最近错过的正式计划。"

if (-not $allGood) {
    Write-Host ""
    Write-Host "自检未全部通过，请先运行「Windows_首次配置.cmd」。" -ForegroundColor Red
    exit 1
}
Write-Host ""
Write-Host "Windows 核心依赖自检通过。" -ForegroundColor Green
