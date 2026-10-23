<#
.SYNOPSIS
    把 hipy-server 后端 + hipy-ui 前端同步到手机 Termux 上的 ~/hipy, 并重启服务。

.DESCRIPTION
    默认动作:
      1) 自动定位手机(优先 ~/.ssh/config 里的 hipy, 其次 adb, 最后局域网扫描)
      2) 前端源码有更新时用 Node 16 自动重新 build (可用 -SkipBuild 跳过)
      3) 备份手机上的 app/ 与 dist/
      4) 上传后端 app/ (自动排除 .env、数据库、日志、Windows wheel)
      5) 上传前端 dist/ 与 phone/spa_server.py
      6) 执行数据库迁移: 新增 live_source 定时任务、切换 vod_zb_file
      7) 重启后端 + 前端并做健康检查

.EXAMPLE
    .\deploy-phone.ps1
    .\deploy-phone.ps1 -RefreshLive
    .\deploy-phone.ps1 -PhoneIp 192.168.1.101 -SkipFrontend
    .\deploy-phone.ps1 -SkipBuild -SkipRestart
    .\deploy-phone.ps1 -ForceBuild

.NOTES
    - 需要 Windows OpenSSH (ssh/scp) 和 tar
    - 手机 SSH: u0_a212@<ip>:8022, 密钥 ~/.ssh/id_ed25519_hipy
    - 前端 build 需要 nvm + Node 16.20.2; 脚本会自动执行 nvm use 16.20.2
#>
[CmdletBinding()]
param(
    [string]$PhoneIp = "",
    [string]$User = "u0_a212",
    [int]$SshPort = 8022,
    [string]$IdentityFile = "$env:USERPROFILE\.ssh\id_ed25519_hipy",
    [string]$FrontendDir = "",
    [switch]$SkipFrontend,
    [switch]$SkipBuild,
    [switch]$ForceBuild,
    [switch]$SkipBackend,
    [switch]$SkipDb,
    [switch]$SkipRestart,
    [switch]$RefreshLive,
    [switch]$NoVerify,
    [switch]$KeepTemp
)

$ErrorActionPreference = "Stop"
$ProgressPreference = "SilentlyContinue"

$RepoRoot = (Resolve-Path -LiteralPath $PSScriptRoot).Path
if (-not $FrontendDir) {
    $FrontendDir = Join-Path (Split-Path $RepoRoot -Parent) "hipy-ui\dashboard"
}
if (-not (Test-Path -LiteralPath (Join-Path $RepoRoot "app\main.py"))) {
    throw "仓库根目录不正确, 找不到 app\main.py: $RepoRoot"
}
if (-not (Test-Path -LiteralPath $IdentityFile)) {
    throw "SSH 私钥不存在: $IdentityFile"
}

$script:TarExe = (Get-Command tar -ErrorAction Stop).Source
$script:SshExe = (Get-Command ssh -ErrorAction Stop).Source
$script:ScpExe = (Get-Command scp -ErrorAction Stop).Source
$script:TempDir = Join-Path $env:TEMP ("hipy-deploy-" + (Get-Date -Format "yyyyMMdd_HHmmss"))

function Write-Step([string]$Message) {
    Write-Host ""
    Write-Host "==> $Message" -ForegroundColor Cyan
}
function Write-Info([string]$Message) { Write-Host "    $Message" -ForegroundColor Gray }
function Write-Warn([string]$Message) { Write-Host "[!] $Message" -ForegroundColor Yellow }
function Write-Ok([string]$Message) { Write-Host "[+] $Message" -ForegroundColor Green }

function Test-TcpPort {
    param([string]$TargetHost, [int]$Port, [int]$TimeoutMs = 900)
    $client = New-Object System.Net.Sockets.TcpClient
    try {
        $ar = $client.BeginConnect($TargetHost, $Port, $null, $null)
        if ($ar.AsyncWaitHandle.WaitOne($TimeoutMs)) {
            $client.EndConnect($ar)
            return $client.Connected
        }
    } catch {
    } finally {
        try { $client.Close() } catch { }
    }
    return $false
}

function Get-PhoneFromSshConfig {
    $cfg = Join-Path $env:USERPROFILE ".ssh\config"
    if (-not (Test-Path -LiteralPath $cfg)) { return $null }
    $text = Get-Content -LiteralPath $cfg -Raw
    $block = [regex]::Match($text, '(?ms)Host\s+hipy\b(.*?)(?=\r?\nHost\s+|\z)')
    if (-not $block.Success) { return $null }
    $m = [regex]::Match($block.Groups[1].Value, '(?m)^\s*HostName\s+(\S+)')
    if ($m.Success) { return $m.Groups[1].Value }
    return $null
}

function Resolve-PhoneIp {
    if ($PhoneIp) {
        if (-not (Test-TcpPort -TargetHost $PhoneIp -Port $SshPort)) {
            throw "指定的手机 IP $PhoneIp 的 $SshPort 端口连不上"
        }
        return $PhoneIp
    }

    $fromConfig = Get-PhoneFromSshConfig
    if ($fromConfig -and (Test-TcpPort -TargetHost $fromConfig -Port $SshPort)) {
        Write-Info "使用 ~/.ssh/config 中的 hipy -> $fromConfig"
        return $fromConfig
    }

    # 尝试 adb (USB 连接时最可靠)
    $adbCandidates = @(
        "J:\Develop\Users\LJ\AppData\Local\Android\Sdk\platform-tools\adb.exe",
        (Join-Path $env:LOCALAPPDATA "Android\Sdk\platform-tools\adb.exe")
    )
    foreach ($adb in $adbCandidates) {
        if (-not (Test-Path -LiteralPath $adb)) { continue }
        try {
            $state = (& $adb get-state 2>$null | Out-String).Trim()
            if ($state -ne "device") { continue }
            $out = (& $adb shell "ip -4 addr show wlan0" 2>$null | Out-String)
            $m = [regex]::Match($out, 'inet\s+(\d+\.\d+\.\d+\.\d+)')
            if ($m.Success) {
                $ip = $m.Groups[1].Value
                if (Test-TcpPort -TargetHost $ip -Port $SshPort) {
                    Write-Info "通过 adb 找到手机: $ip"
                    return $ip
                }
            }
        } catch { }
    }

    # 复用已有的局域网扫描脚本
    $helper = Join-Path $env:USERPROFILE ".ssh\ssh-hipy.ps1"
    if (Test-Path -LiteralPath $helper) {
        Write-Info "扫描局域网查找 8022 端口 (可能需要十几秒)..."
        $output = (& powershell -NoProfile -ExecutionPolicy Bypass -File $helper -FindOnly 2>&1 | Out-String)
        $m = [regex]::Match($output, '手机 IP:\s*(\d+\.\d+\.\d+\.\d+)')
        if ($m.Success) { return $m.Groups[1].Value }
    }

    throw "没找到手机。请确认手机和电脑在同一 WiFi, 且手机已运行 bash ~/hipy/start_all.sh"
}

function Invoke-Ssh {
    param([string]$RemoteCommand, [switch]$AllowFail)
    # PowerShell 的 here-string 默认是 CRLF, 直接传给 Termux 的 bash 会把 \r 当成命令的一部分
    $RemoteCommand = $RemoteCommand -replace "`r`n", "`n" -replace "`r", "`n"
    $sshArgs = @(
        "-p", "$SshPort", "-i", $IdentityFile,
        "-o", "BatchMode=yes", "-o", "StrictHostKeyChecking=accept-new",
        "-o", "ConnectTimeout=10",
        "$User@$PhoneIp", $RemoteCommand
    )
    & $script:SshExe @sshArgs
    $code = $LASTEXITCODE
    if ($code -ne 0 -and -not $AllowFail) {
        throw "SSH 远端命令失败(exit=$code)"
    }
}

function Send-File {
    param([string]$LocalFile, [string]$RemoteName)
    $scpArgs = @(
        "-O", "-P", "$SshPort", "-i", $IdentityFile,
        "-o", "BatchMode=yes", "-o", "StrictHostKeyChecking=accept-new",
        $LocalFile, "${User}@${PhoneIp}:~/hipy/$RemoteName"
    )
    & $script:ScpExe @scpArgs
    if ($LASTEXITCODE -ne 0) {
        throw "scp 上传失败: $LocalFile -> ~/hipy/$RemoteName"
    }
}

function New-Tar {
    param([string]$OutFile, [string]$Root, [string[]]$Items, [string[]]$Excludes = @())
    $tarArgs = @("--force-local", "-czf", $OutFile, "-C", $Root) + $Excludes + $Items
    & $script:TarExe @tarArgs
    if ($LASTEXITCODE -ne 0) { throw "打包失败: $OutFile" }
    if (-not (Test-Path -LiteralPath $OutFile)) { throw "打包产物不存在: $OutFile" }
}

function Test-DistStale {
    $distIndex = Join-Path $FrontendDir "dist\index.html"
    if (-not (Test-Path -LiteralPath $distIndex)) { return $true }
    $distTime = (Get-Item -LiteralPath $distIndex).LastWriteTimeUtc
    $latest = $null
    $srcDir = Join-Path $FrontendDir "src"
    if (Test-Path -LiteralPath $srcDir) {
        $latest = Get-ChildItem -LiteralPath $srcDir -Recurse -File |
            Sort-Object LastWriteTimeUtc -Descending | Select-Object -First 1
    }
    foreach ($name in @("public", "package.json", "package-lock.json", "vue.config.js", "babel.config.js", ".env.production", ".env.production.local")) {
        $path = Join-Path $FrontendDir $name
        if (-not (Test-Path -LiteralPath $path)) { continue }
        $item = Get-Item -LiteralPath $path
        if ($item.PSIsContainer) {
            $f = Get-ChildItem -LiteralPath $path -Recurse -File |
                Sort-Object LastWriteTimeUtc -Descending | Select-Object -First 1
            if ($f -and (-not $latest -or $f.LastWriteTimeUtc -gt $latest.LastWriteTimeUtc)) { $latest = $f }
        } elseif (-not $latest -or $item.LastWriteTimeUtc -gt $latest.LastWriteTimeUtc) {
            $latest = $item
        }
    }
    if (-not $latest) { return $false }
    return ($latest.LastWriteTimeUtc -gt $distTime.AddSeconds(2))
}

function Invoke-FrontendBuild {
    if (-not (Test-Path -LiteralPath (Join-Path $FrontendDir "package.json"))) {
        throw "前端目录不正确, 找不到 package.json: $FrontendDir"
    }
    Push-Location -LiteralPath $FrontendDir
    $oldNodeOptions = $env:NODE_OPTIONS
    try {
        $nvm = Get-Command nvm -ErrorAction SilentlyContinue
        if ($nvm) {
            Write-Info "nvm use 16.20.2"
            & $nvm.Source use 16.20.2 | Out-Host
            if ($LASTEXITCODE -ne 0) { throw "nvm use 16.20.2 失败" }
        }
        $nodeVersion = (& node -v 2>$null | Out-String).Trim()
        if ($nodeVersion -notmatch '^v16\.') {
            throw "当前 Node 是 $nodeVersion, 需要 16.x。请先执行: nvm use 16.20.2"
        }
        Write-Info "Node $nodeVersion, 开始 npm run build:prod (可能需要 1-2 分钟)..."
        $env:NODE_OPTIONS = "--max-old-space-size=6144"
        & npm run build:prod
        if ($LASTEXITCODE -ne 0) { throw "npm run build:prod 失败" }
    } finally {
        if ($null -eq $oldNodeOptions) {
            Remove-Item Env:NODE_OPTIONS -ErrorAction SilentlyContinue
        } else {
            $env:NODE_OPTIONS = $oldNodeOptions
        }
        Pop-Location
    }
    if (-not (Test-Path -LiteralPath (Join-Path $FrontendDir "dist\index.html"))) {
        throw "前端构建完成但找不到 dist\index.html"
    }
}

function Format-Bytes([long]$Bytes) {
    if ($Bytes -ge 1GB) { return ("{0:N1} GB" -f ($Bytes / 1GB)) }
    if ($Bytes -ge 1MB) { return ("{0:N1} MB" -f ($Bytes / 1MB)) }
    return ("{0:N0} KB" -f ($Bytes / 1KB))
}

# ---------------------------------------------------------------------------
Write-Host "hipy 手机同步脚本" -ForegroundColor White
Write-Info "仓库: $RepoRoot"
Write-Info "前端: $FrontendDir"

$PhoneIp = Resolve-PhoneIp
Write-Ok "手机: ${User}@${PhoneIp}:$SshPort"

Write-Step "检查 SSH"
$null = Invoke-Ssh "echo ok >/dev/null && echo connected"
Write-Ok "SSH 连接正常"

New-Item -ItemType Directory -Force -Path $script:TempDir | Out-Null

try {
    # ---------------- 前端构建 ----------------
    $distTar = Join-Path $script:TempDir "dist.tgz"
    if (-not $SkipFrontend) {
        $needBuild = $ForceBuild -or ((-not $SkipBuild) -and (Test-DistStale))
        if ($needBuild) {
            Write-Step "构建前端 (Node 16)"
            Invoke-FrontendBuild
            Write-Ok "前端构建完成"
        } elseif ($SkipBuild) {
            Write-Warn "已指定 -SkipBuild, 直接使用现有 dist"
        } else {
            Write-Info "前端源码没有比 dist 更新, 跳过构建"
        }
        if (-not (Test-Path -LiteralPath (Join-Path $FrontendDir "dist\index.html"))) {
            throw "找不到前端 dist\index.html, 请去掉 -SkipFrontend/-SkipBuild 重新执行"
        }
        Write-Step "打包前端 dist"
        New-Tar -OutFile $distTar -Root $FrontendDir -Items @("dist")
        Write-Ok ("dist.tgz {0}" -f (Format-Bytes (Get-Item -LiteralPath $distTar).Length))
    }

    # ---------------- 后端打包 ----------------
    $appTar = Join-Path $script:TempDir "app.tgz"
    if (-not $SkipBackend) {
        Write-Step "打包后端 app/"
        $appExcludes = @(
            "--exclude=app/db/hipy.db",
            "--exclude=app/db/hipy.db-*",
            "--exclude=app/db/hipy.db.*",
            "--exclude=app/db/*.db",
            "--exclude=app/db/*.db.bak_*",
            "--exclude=app/db/*.sqlite3",
            "--exclude=app/log",
            "--exclude=app/log/*",
            "--exclude=app/whl",
            "--exclude=app/whl/*",
            "--exclude=app/media",
            "--exclude=app/media/*",
            "--exclude=app/.pytest_cache",
            "--exclude=app/.pytest_cache/*",
            "--exclude=app/t4/files/m3u/live_merged.m3u",
            "--exclude=app/t4/files/m3u/logo",
            "--exclude=app/t4/files/m3u/logo/*",
            "--exclude=app/t4/files/txt/e.xml",
            "--exclude=app/t4/files/json/live_merged_meta.json",
            "--exclude=app/t4/files/json/epg_index.json",
            "--exclude=app/t4/files/txt/mytv.txt",
            "--exclude=app/t4/files/txt/tv.txt",
            "--exclude=__pycache__",
            "--exclude=__pycache__/*",
            "--exclude=*.pyc",
            "--exclude=app/configs/.env",
            "--exclude=app/configs/.env.*"
        )
        New-Tar -OutFile $appTar -Root $RepoRoot -Items @("app") -Excludes $appExcludes
        Write-Ok ("app.tgz {0}" -f (Format-Bytes (Get-Item -LiteralPath $appTar).Length))
    }

    # ---------------- 备份手机 ----------------
    $ts = Get-Date -Format "yyyyMMdd_HHmmss"
    $backupDir = "~/hipy/backups/deploy_$ts"
    Write-Step "备份手机到 $backupDir"
    $backupCmd = "set -e; mkdir -p $backupDir; cp ~/hipy/app/db/hipy.db $backupDir/hipy.db.before; tar czf $backupDir/app_before.tar.gz -C ~/hipy app; if [ -d ~/hipy/dist ]; then tar czf $backupDir/dist_before.tar.gz -C ~/hipy dist; fi; echo backup_ok"
    $backupOut = Invoke-Ssh $backupCmd
    if (($backupOut -join "`n") -notmatch "backup_ok") { throw "手机备份失败" }
    Write-Ok "备份完成"

    # ---------------- 上传后端 ----------------
    if (-not $SkipBackend) {
        Write-Step "上传并解压后端"
        Send-File -LocalFile $appTar -RemoteName "_deploy_app.tgz"
        $appDeployCmd = @'
set -e
cd $HOME/hipy
tar xzf _deploy_app.tgz
rm -f _deploy_app.tgz
echo app_deploy_ok
'@
        $out = Invoke-Ssh $appDeployCmd
        if (($out -join "`n") -notmatch "app_deploy_ok") { throw "后端解压失败" }
        Write-Ok "后端已更新"
    }

    # ---------------- 上传前端 ----------------
    if (-not $SkipFrontend) {
        Write-Step "上传并替换前端 dist"
        Send-File -LocalFile $distTar -RemoteName "_deploy_dist.tgz"
        $distDeployCmd = @'
set -e
rm -rf $HOME/hipy/_deploy_dist
mkdir -p $HOME/hipy/_deploy_dist
tar xzf $HOME/hipy/_deploy_dist.tgz -C $HOME/hipy/_deploy_dist
rm -rf $HOME/hipy/dist
mv $HOME/hipy/_deploy_dist/dist $HOME/hipy/dist
rm -rf $HOME/hipy/_deploy_dist $HOME/hipy/_deploy_dist.tgz
echo dist_deploy_ok
'@
        $out = Invoke-Ssh $distDeployCmd
        if (($out -join "`n") -notmatch "dist_deploy_ok") { throw "前端替换失败" }
        Write-Ok "前端已更新"
    }

    # ---------------- spa_server (新增 /epg 反向代理) ----------------
    $spaLocal = Join-Path $RepoRoot "phone\spa_server.py"
    if (Test-Path -LiteralPath $spaLocal) {
        Write-Step "更新手机 spa_server.py"
        Send-File -LocalFile $spaLocal -RemoteName "spa_server.py"
        Write-Ok "spa_server.py 已更新"
    }

    # ---------------- 数据库迁移 ----------------
    if (-not $SkipBackend -and -not $SkipDb) {
        Write-Step "执行数据库迁移 (live_source 定时任务 + vod_zb_file)"
        $migrateCmd = @'
export HOME=/data/data/com.termux/files/home
export PREFIX=/data/data/com.termux/files/usr
PY=$HOME/.pyenv/versions/3.12.8
if [ ! -x "$PY/bin/python" ]; then
  PY=$(dirname "$(command -v python)")
  PY=$(dirname "$PY")
fi
export PATH=$PY/bin:$PREFIX/bin:$PREFIX/bin/applets:$PATH
export LD_LIBRARY_PATH=$PY/lib:$PREFIX/lib
export TMPDIR=$PREFIX/tmp
cd $HOME/hipy/app && python db/migrate_live_source.py
'@
        Invoke-Ssh $migrateCmd
        Write-Ok "数据库迁移完成"
    }

    if (-not $RefreshLive) {
        $hasLive = Invoke-Ssh 'test -s $HOME/hipy/app/t4/files/m3u/live_merged.m3u && echo yes || echo no'
        if (($hasLive -join "") -notmatch "yes") {
            Write-Warn "手机还没有 live_merged.m3u, 首次部署请加 -RefreshLive 生成一次"
        }
    }

    # ---------------- 手动跑一次直播聚合 ----------------
    if ($RefreshLive) {
        Write-Step "运行直播源聚合 (下载 m3u / 台标 / EPG, 可能需要 1-3 分钟)"
        $refreshCmd = @'
export HOME=/data/data/com.termux/files/home
export PREFIX=/data/data/com.termux/files/usr
PY=$HOME/.pyenv/versions/3.12.8
if [ ! -x "$PY/bin/python" ]; then
  PY=$(dirname "$(command -v python)")
  PY=$(dirname "$PY")
fi
export PATH=$PY/bin:$PREFIX/bin:$PREFIX/bin/applets:$PATH
export LD_LIBRARY_PATH=$PY/lib:$PREFIX/lib
export TMPDIR=$PREFIX/tmp
cd $HOME/hipy/app && python -m tasks.live_source
'@
        Invoke-Ssh $refreshCmd
        Write-Ok "直播聚合完成"
    }

    # ---------------- 重启 ----------------
    if (-not $SkipRestart) {
        Write-Step "重启后端 + 前端"
        $restartCmd = @'
set +e
pkill -f '[p]ython main.py' 2>/dev/null
pkill -f '[s]pa_server.py' 2>/dev/null
sleep 1
cd $HOME/hipy
setsid nohup bash start_backend.sh > backend.log 2>&1 < /dev/null &
setsid nohup bash start_frontend.sh > frontend.log 2>&1 < /dev/null &
for i in $(seq 1 40); do
  code=$(curl -s -o /dev/null -w '%{http_code}' -m 2 http://127.0.0.1:5707/docs 2>/dev/null)
  if [ "$code" = "200" ]; then break; fi
  sleep 1
done
sleep 1
curl -s -o /dev/null -w 'backend /docs -> %{http_code}\n' -m 8 http://127.0.0.1:5707/docs
curl -s -o /dev/null -w 'frontend / -> %{http_code}\n' -m 8 http://127.0.0.1:8080/
'@
        Invoke-Ssh $restartCmd
        Write-Ok "重启完成"
    }

    # ---------------- 验证 ----------------
    if (-not $NoVerify) {
        Write-Step "健康检查"
        $verifyCmd = @'
echo -n "backend /docs   : "; curl -s -o /dev/null -w '%{http_code}\n' -m 8 http://127.0.0.1:5707/docs
echo -n "frontend /      : "; curl -s -o /dev/null -w '%{http_code}\n' -m 8 http://127.0.0.1:8080/
echo -n "live m3u        : "; curl -s -o /dev/null -w '%{http_code}\n' -m 8 http://127.0.0.1:5707/files/m3u/live_merged.m3u
echo -n "epg CCTV1       : "; curl -s -o /dev/null -w '%{http_code}\n' -m 8 "http://127.0.0.1:5707/epg?ch=CCTV1&date=$(date +%F)"
echo -n "epg via frontend: "; curl -s -o /dev/null -w '%{http_code}\n' -m 8 "http://127.0.0.1:8080/epg?ch=CCTV1&date=$(date +%F)"
'@
        Invoke-Ssh $verifyCmd
    }

    # ---------------- 状态记录 ----------------
    $stateFile = Join-Path $RepoRoot ".deploy-phone-state.json"
    $commit = (& git -C $RepoRoot rev-parse --short HEAD 2>$null | Out-String).Trim()
    $state = [ordered]@{
        deployed_at = (Get-Date).ToString("yyyy-MM-dd HH:mm:ss")
        phone       = $PhoneIp
        user        = $User
        commit      = $commit
        backend     = (-not $SkipBackend)
        frontend    = (-not $SkipFrontend)
        refresh_live = [bool]$RefreshLive
    }
    $state | ConvertTo-Json | Set-Content -LiteralPath $stateFile -Encoding UTF8

    Write-Ok "全部完成"
    Write-Host ""
    Write-Host "手机网页: http://${PhoneIp}:8080" -ForegroundColor White
    Write-Host "后端接口: http://${PhoneIp}:5707/docs" -ForegroundColor White
    Write-Host "TVBox T4: http://${PhoneIp}:5707/config/0?sub=dzyyds" -ForegroundColor White
    Write-Host "TVBox T3: http://${PhoneIp}:5707/config/1?sub=dzyyds" -ForegroundColor White
} finally {
    if (-not $KeepTemp) {
        Remove-Item -LiteralPath $script:TempDir -Recurse -Force -ErrorAction SilentlyContinue
    } else {
        Write-Info "临时文件保留: $script:TempDir"
    }
}
