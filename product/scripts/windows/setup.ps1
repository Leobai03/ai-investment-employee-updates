. (Join-Path $PSScriptRoot "Common.ps1")

if ($env:OS -ne "Windows_NT") {
    throw "这个入口只能在 Windows 电脑上运行。"
}

Write-Section "天策 AI 投研数字员工｜Windows 首次配置"
Write-Host "将检查 ChatGPT、Codex CLI、Python 和产品依赖。"
Write-Host "只使用 Microsoft Store、winget 和 OpenAI 官方 npm 包。"

$winget = Get-Command "winget.exe" -ErrorAction SilentlyContinue
if (-not $winget) {
    throw "没有找到 winget。请先在 Microsoft Store 安装或更新「应用安装程序」，再重新运行。"
}

function Install-WingetPackage {
    param(
        [Parameter(Mandatory = $true)][string]$Id,
        [string]$Source = "winget"
    )
    & $winget.Source install --id $Id -e -s $Source --accept-package-agreements --accept-source-agreements
    if ($LASTEXITCODE -ne 0) {
        throw "安装 $Id 失败。请检查 Microsoft Store/winget 是否可用。"
    }
    Refresh-ProcessPath
}

Write-Section "1/5 ChatGPT Windows 客户端"
$chatGptInstalled = $false
try {
    $packages = @(Get-AppxPackage -ErrorAction Stop | Where-Object {
        $_.Name -match "ChatGPT" -or $_.PackageFamilyName -match "9PLM9XGG6VKS"
    })
    $chatGptInstalled = $packages.Count -gt 0
} catch {
    $chatGptInstalled = $false
}
if ($chatGptInstalled) {
    Write-Host "ChatGPT Windows 客户端已安装。" -ForegroundColor Green
} else {
    Write-Host "正在通过 Microsoft Store 安装 ChatGPT……"
    Install-WingetPackage -Id "9PLM9XGG6VKS" -Source "msstore"
}

Write-Section "2/5 Python"
$python = Get-CompatiblePython
if (-not $python) {
    Write-Host "正在安装 Python 3.14……"
    Install-WingetPackage -Id "Python.Python.3.14"
    $python = Get-CompatiblePython
}
if (-not $python) {
    throw "Python 已执行安装，但当前窗口仍未找到 Python 3.11+。请重启电脑后再次运行。"
}
$pythonVersion = & $python.Exe @($python.Prefix) --version
Write-Host "$pythonVersion 已就绪。" -ForegroundColor Green

Write-Section "3/5 Codex CLI 与 ChatGPT 登录"
$codex = Get-CodexCommand
if (-not $codex) {
    $npm = Get-Command "npm.cmd" -ErrorAction SilentlyContinue
    if (-not $npm) {
        Write-Host "正在安装 Node.js LTS（Codex CLI 的官方 npm 安装方式需要它）……"
        Install-WingetPackage -Id "OpenJS.NodeJS.LTS"
        $npm = Get-Command "npm.cmd" -ErrorAction SilentlyContinue
    }
    if (-not $npm) {
        throw "Node.js 安装后仍未找到 npm.cmd。请重启电脑后再次运行。"
    }
    Write-Host "正在安装 OpenAI Codex CLI……"
    & $npm.Source install -g "@openai/codex"
    if ($LASTEXITCODE -ne 0) {
        throw "Codex CLI 安装失败，请检查网络后重试。"
    }
    Refresh-ProcessPath
    $codex = Get-CodexCommand
}
if (-not $codex) {
    throw "Codex CLI 已执行安装，但未能找到 codex 命令。请重启电脑后再次运行。"
}
Set-EnvValue -Name "CODEX_BIN" -Value $codex
& $codex --version
if ($LASTEXITCODE -ne 0) {
    throw "Codex CLI 无法运行。"
}
& $codex app-server --help *> $null
if ($LASTEXITCODE -ne 0) {
    throw "当前 Codex CLI 没有可用的 app-server。请更新 Codex 后重试。"
}

$loginOutput = (& $codex login status 2>&1 | Out-String)
if ($loginOutput -match "Logged in") {
    Write-Host "Codex 已使用账号登录。" -ForegroundColor Green
} else {
    Write-Host "接下来会打开浏览器，请用老板自己的 ChatGPT 账号完成 Codex 登录。" -ForegroundColor Yellow
    & $codex login
    if ($LASTEXITCODE -ne 0) {
        Write-Warning "Codex 登录尚未完成。网页可以启动，但正式研究前需要再次运行 codex login。"
    }
}

Write-Section "4/5 AI 投研数字员工插件"
$marketplaceRoot = (Resolve-Path (Join-Path $script:ProductRoot "..\codex-plugin-marketplace") -ErrorAction SilentlyContinue)
if ($marketplaceRoot -and (Test-Path -LiteralPath (Join-Path $marketplaceRoot.Path ".agents\plugins\marketplace.json"))) {
    & $codex plugin marketplace add $marketplaceRoot.Path
    if ($LASTEXITCODE -ne 0) {
        Write-Warning "本地插件源可能已经添加；继续安装投研插件。"
    }
    $installedPlugins = (& $codex plugin list --json 2>&1 | Out-String)
    if ($installedPlugins -notmatch "ai-investment-employee") {
        & $codex plugin add "ai-investment-employee@boss-investment"
        if ($LASTEXITCODE -ne 0) {
            throw "AI 投研数字员工插件安装失败。也可以稍后双击 codex-plugin-marketplace\安装AI投研数字员工_Windows.cmd 重试。"
        }
    }
    Write-Host "AI 投研数字员工插件已安装。" -ForegroundColor Green
} else {
    Write-Warning "当前目录旁边没有 codex-plugin-marketplace；网页仍可使用，但 Codex 中的 `$ai-investment-employee 需要另行安装。"
}

Write-Section "5/5 产品环境和网页"
Ensure-ProductEnvironment
Start-ResearchDesk

Write-Host ""
Write-Host "Windows 首次配置完成。" -ForegroundColor Green
Write-Host "以后直接双击「Windows_启动研究台.cmd」即可。"
Write-Host "需要每次登录 Windows 自动运行时，再双击「Windows_安装开机自启.cmd」。"
