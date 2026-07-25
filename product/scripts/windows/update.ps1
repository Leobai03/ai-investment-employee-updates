param(
    [switch]$CheckOnly,
    [switch]$Automatic,
    [string]$PackagePath = "",
    [string]$Repository = ""
)
. (Join-Path $PSScriptRoot "Common.ps1")

$statusFile = Join-Path $script:RuntimeDir "update-status.json"
$lockFile = Join-Path $script:RuntimeDir "update.lock"
$defaultRepository = "Leobai03/ai-investment-employee-updates"
$lockStream = $null

function Get-CurrentVersion {
    $versionFile = Join-Path $script:ProductRoot "VERSION"
    if (Test-Path -LiteralPath $versionFile) {
        return (Get-Content -LiteralPath $versionFile -Raw).Trim().TrimStart("v")
    }
    $initFile = Join-Path $script:ProductRoot "app\__init__.py"
    $content = Get-Content -LiteralPath $initFile -Raw
    if ($content -match '__version__\s*=\s*"([0-9]+\.[0-9]+\.[0-9]+)"') {
        return $Matches[1]
    }
    throw "无法识别当前产品版本。"
}

function Convert-Version {
    param([Parameter(Mandatory = $true)][string]$Value)
    $normalized = $Value.Trim().TrimStart("v").Split("+")[0].Split("-")[0]
    try {
        return [Version]$normalized
    } catch {
        throw "GitHub 返回了无效版本号：$Value"
    }
}

function Write-UpdateStatus {
    param(
        [Parameter(Mandatory = $true)][string]$State,
        [Parameter(Mandatory = $true)][string]$Message,
        [string]$LatestVersion = "",
        [bool]$Available = $false,
        [string]$BackupRoot = ""
    )
    $payload = [ordered]@{
        state = $State
        message = $Message
        current_version = Get-CurrentVersion
        latest_version = $LatestVersion
        update_available = $Available
        repository = $Repository
        automatic = (Get-EnvValue -Name "AUTO_UPDATE_ENABLED") -ne "0"
        last_checked_at = (Get-Date).ToString("o")
        backup_root = $BackupRoot
    }
    $payload | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath $statusFile -Encoding UTF8
}

function Fail-Update {
    param([Parameter(Mandatory = $true)][string]$Message)
    Write-UpdateStatus -State "error" -Message $Message
    if ($Automatic) {
        Write-Warning $Message
        exit 0
    }
    throw $Message
}

function Get-LatestRelease {
    $uri = "https://api.github.com/repos/$Repository/releases/latest"
    $headers = @{
        "Accept" = "application/vnd.github+json"
        "User-Agent" = "ai-investment-employee-updater"
        "X-GitHub-Api-Version" = "2022-11-28"
    }
    return Invoke-RestMethod -Method Get -Uri $uri -Headers $headers -TimeoutSec 20
}

function Get-Asset {
    param(
        [Parameter(Mandatory = $true)]$Release,
        [Parameter(Mandatory = $true)][string]$Name
    )
    return @($Release.assets | Where-Object { $_.name -eq $Name }) | Select-Object -First 1
}

function Read-ApplyResult {
    param([Parameter(Mandatory = $true)][string]$Output)
    $lines = @($Output -split "`r?`n" | Where-Object { $_.Trim() })
    if ($lines.Count -eq 0) {
        throw "更新核心没有返回结果。"
    }
    return $lines[-1] | ConvertFrom-Json
}

New-Item -ItemType Directory -Force -Path $script:RuntimeDir | Out-Null
if (-not $Repository) {
    $Repository = Get-EnvValue -Name "UPDATE_REPOSITORY"
}
if (-not $Repository) {
    $Repository = $defaultRepository
}
if ($Repository -notmatch '^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$') {
    Fail-Update -Message "GitHub 更新仓库格式不正确：$Repository"
}
if ($Automatic -and (Get-EnvValue -Name "AUTO_UPDATE_ENABLED") -eq "0") {
    exit 0
}

try {
    $lockStream = [System.IO.File]::Open(
        $lockFile,
        [System.IO.FileMode]::OpenOrCreate,
        [System.IO.FileAccess]::ReadWrite,
        [System.IO.FileShare]::None
    )
} catch {
    if ($Automatic) { exit 0 }
    throw "另一个更新任务正在运行。"
}

try {
    $currentVersion = Get-CurrentVersion
    $latestVersion = ""
    $archivePath = ""
    $checksumPath = ""

    if ($PackagePath) {
        $archivePath = (Resolve-Path -LiteralPath $PackagePath).Path
        $checksumPath = "$archivePath.sha256"
        if (-not (Test-Path -LiteralPath $checksumPath)) {
            Fail-Update -Message "离线更新包缺少 SHA-256 文件：$checksumPath"
        }
        if ([System.IO.Path]::GetFileName($archivePath) -match '_v([0-9]+\.[0-9]+\.[0-9]+)\.zip$') {
            $latestVersion = $Matches[1]
        } else {
            Fail-Update -Message "离线更新包文件名没有版本号。"
        }
    } else {
        Write-UpdateStatus -State "checking" -Message "正在检查 GitHub 新版本。"
        try {
            $release = Get-LatestRelease
        } catch {
            Fail-Update -Message "GitHub 更新检查失败：$($_.Exception.Message)"
        }
        $latestVersion = ([string]$release.tag_name).Trim().TrimStart("v")
        $available = (Convert-Version $latestVersion) -gt (Convert-Version $currentVersion)
        if (-not $available) {
            Write-UpdateStatus -State "current" -Message "当前已经是最新版本。" -LatestVersion $latestVersion
            Write-Host "当前已经是最新版本 v$currentVersion。" -ForegroundColor Green
            exit 0
        }
        Write-UpdateStatus -State "available" -Message "发现新版本 v$latestVersion。" -LatestVersion $latestVersion -Available $true
        if ($CheckOnly) {
            Write-Host "发现新版本 v$latestVersion。" -ForegroundColor Yellow
            exit 0
        }

        $archiveName = "AI投研数字员工_Update_v$latestVersion.zip"
        $checksumName = "$archiveName.sha256"
        $archiveAsset = Get-Asset -Release $release -Name $archiveName
        $checksumAsset = Get-Asset -Release $release -Name $checksumName
        if (-not $archiveAsset -or -not $checksumAsset) {
            Fail-Update -Message "GitHub Release 缺少更新包或 SHA-256 文件。"
        }
        $cacheDir = Join-Path $script:RuntimeDir "update-cache\v$latestVersion"
        New-Item -ItemType Directory -Force -Path $cacheDir | Out-Null
        $archivePath = Join-Path $cacheDir $archiveName
        $checksumPath = Join-Path $cacheDir $checksumName
        Write-UpdateStatus -State "downloading" -Message "正在下载 v$latestVersion。" -LatestVersion $latestVersion -Available $true
        Invoke-WebRequest -UseBasicParsing -Uri $archiveAsset.browser_download_url -OutFile $archivePath -TimeoutSec 180
        Invoke-WebRequest -UseBasicParsing -Uri $checksumAsset.browser_download_url -OutFile $checksumPath -TimeoutSec 60
    }

    if ((Convert-Version $latestVersion) -le (Convert-Version $currentVersion)) {
        Write-UpdateStatus -State "current" -Message "更新包不高于当前版本，未执行覆盖。" -LatestVersion $latestVersion
        exit 0
    }

    $checksumText = Get-Content -LiteralPath $checksumPath -Raw
    if ($checksumText -notmatch '(?i)\b([a-f0-9]{64})\b') {
        Fail-Update -Message "SHA-256 文件格式不正确。"
    }
    $expectedHash = $Matches[1].ToLowerInvariant()
    $actualHash = (Get-FileHash -LiteralPath $archivePath -Algorithm SHA256).Hash.ToLowerInvariant()
    if ($actualHash -ne $expectedHash) {
        Fail-Update -Message "更新包 SHA-256 校验失败，已拒绝安装。"
    }

    $stageRoot = Join-Path $script:RuntimeDir "update-stage\$([Guid]::NewGuid().ToString('N'))"
    New-Item -ItemType Directory -Force -Path $stageRoot | Out-Null
    Expand-Archive -LiteralPath $archivePath -DestinationPath $stageRoot -Force
    $packageRoot = Join-Path $stageRoot "AI投研数字员工_Update"
    $core = Join-Path $script:ProductRoot "scripts\update_core.py"
    & $script:VenvPython $core verify --package-root $packageRoot | Out-Null
    if ($LASTEXITCODE -ne 0) {
        Fail-Update -Message "更新包内部文件校验失败。"
    }

    Write-UpdateStatus -State "installing" -Message "正在安装 v$latestVersion；老板资料已进入保护流程。" -LatestVersion $latestVersion -Available $true
    $wasRunning = Test-DeskHealth -Port 8765
    Stop-ResearchDesk | Out-Null
    Start-Sleep -Seconds 1

    $installRoot = (Resolve-Path (Join-Path $script:ProductRoot "..")).Path
    $applyOutput = (& $script:VenvPython $core apply `
        --package-root $packageRoot `
        --install-root $installRoot `
        --current-version $currentVersion 2>&1 | Out-String)
    if ($LASTEXITCODE -ne 0) {
        if ($wasRunning -or $Automatic) {
            Start-ResearchDesk -NoBrowser
        }
        Fail-Update -Message "程序文件安装失败：$applyOutput"
    }
    $applyResult = Read-ApplyResult -Output $applyOutput
    $backupRoot = [string]$applyResult.backup_root

    try {
        Ensure-ProductEnvironment -ForceDependencies
        Start-ResearchDesk -NoBrowser
        if (-not (Wait-DeskHealth -Port 8765 -Attempts 60)) {
            throw "新版健康检查未通过。"
        }
        $health = Invoke-RestMethod -Method Get -Uri "http://127.0.0.1:8765/api/health" -TimeoutSec 5
        if ([string]$health.version -ne $latestVersion) {
            throw "启动版本与目标版本不一致。"
        }
        Write-UpdateStatus -State "updated" -Message "已自动升级到 v$latestVersion，老板全部资料保持原位。" -LatestVersion $latestVersion -BackupRoot $backupRoot
        Write-Host "升级完成：v$currentVersion → v$latestVersion" -ForegroundColor Green
    } catch {
        $upgradeError = $_.Exception.Message
        Stop-ResearchDesk | Out-Null
        $rollbackOutput = (& $script:VenvPython $core rollback `
            --backup-root $backupRoot `
            --install-root $installRoot `
            --restore-userdata 2>&1 | Out-String)
        if ($LASTEXITCODE -ne 0) {
            Write-UpdateStatus -State "error" -Message "新版启动失败，且自动回滚失败：$rollbackOutput" -LatestVersion $latestVersion -BackupRoot $backupRoot
            throw "新版启动失败，自动回滚也失败。请联系交付人员。"
        }
        Ensure-ProductEnvironment -ForceDependencies
        if ($wasRunning -or $Automatic) {
            Start-ResearchDesk -NoBrowser
        }
        Write-UpdateStatus -State "rolled_back" -Message "新版未通过健康检查，已自动恢复 v$currentVersion 和升级前资料。原因：$upgradeError" -LatestVersion $latestVersion -BackupRoot $backupRoot
        Write-Warning "新版启动失败，已经自动回滚到 v$currentVersion。"
        if (-not $Automatic) { exit 1 }
    }
} finally {
    if ($lockStream) {
        $lockStream.Dispose()
    }
}
