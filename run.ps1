<#
.SYNOPSIS
    hipy-server 前后端一键「编译 + 启动」脚本（可选管理 nginx）。

.DESCRIPTION
    统一管理后端 hipy-server (FastAPI) 与前端 hipy-ui/dashboard (Vue2) 的编译与启动，
    默认「先编译再启动」后端 + 前端(开发模式)，后台运行，日志写入 logs\ 目录。

    默认端口：
        后端        http://127.0.0.1:5707   (取自 app\configs\.env 的 PORT)
        前端 Dev    http://localhost:8080
        前端 Prod   http://localhost:8081   (npm run preview, 需先构建)

    说明：
        - 后端「编译」= python -m compileall 语法检查；加 -Install 时先 pip install。
        - 前端「编译」= 装依赖(缺 node_modules 或 -Install)；
          FrontendMode=Prod 时额外执行 npm run build:prod。
        - 启动均以后台进程运行，用 -Mode Stop 停止；-Mode Status 查看状态。
        - 脚本会自动为编译/启动设置 HTTP(S)_PROXY（默认 127.0.0.1:7897），
          避免 IDE 注入的坏代理导致下载卡死；-NoProxy 可关闭。

.PARAMETER Target
    操作对象：Backend | Frontend | Nginx | All（默认 All）。
    注意：All = Backend + Frontend，不包含 Nginx；Nginx 需显式指定 -Target Nginx。

.PARAMETER Mode
    操作类型：Build | Start | BuildStart | Stop | Restart | Status（默认 BuildStart）。

.PARAMETER FrontendMode
    前端模式：Dev | Prod（默认 Dev）。Prod 会构建生产包并以 preview 方式启动。

.PARAMETER Python
    后端 Python 解释器。默认优先 venv\Scripts\python.exe，否则用 PATH 中的 python。

.PARAMETER FrontendDir
    前端目录。默认 ..\hipy-ui\dashboard（相对本脚本所在目录）。

.PARAMETER NginxDir
    nginx 安装目录，仅 Target=Nginx 时使用。默认 D:\ProgramFiles\nginx-1.20.2。

.PARAMETER Proxy
    编译/启动时使用的 HTTP 代理。默认 http://127.0.0.1:7897。

.PARAMETER NoProxy
    不使用代理，直连。

.PARAMETER Install
    Build 时强制重新安装依赖（后端 pip install，前端 npm install）。

.PARAMETER Help
    显示本帮助。

.EXAMPLE
    .\run.ps1
    编译并启动后端 + 前端(Dev)。

.EXAMPLE
    .\run.ps1 -Target Backend -Mode Build
    只编译后端（语法检查）。

.EXAMPLE
    .\run.ps1 -Target Backend -Mode Start
    只启动后端。

.EXAMPLE
    .\run.ps1 -Target Frontend -Mode Build
    只安装/编译前端（Dev 模式仅装依赖）。

.EXAMPLE
    .\run.ps1 -Target Frontend -Mode BuildStart -FrontendMode Prod
    构建前端生产包并本地预览（http://localhost:8081）。

.EXAMPLE
    .\run.ps1 -Target Frontend -Mode Start
    只启动前端(Dev, http://localhost:8080)。

.EXAMPLE
    .\run.ps1 -Mode Stop
    停止后端 + 前端。

.EXAMPLE
    .\run.ps1 -Mode Status
    查看后端 + 前端运行状态。

.EXAMPLE
    .\run.ps1 -Target Nginx -Mode Restart
    重启 nginx。

.EXAMPLE
    Get-Help .\run.ps1 -Full
    查看完整帮助。

.NOTES
    依赖服务 Redis（用于登录 token / 验证码缓存）。配置读取 app\configs\.env：
        REDIS_HOST=192.168.120.153     # Redis 地址
        REDIS_PORT=6379                # 端口
        REDIS_DB=6                     # 库号
        REDIS_PWD=vrv@1234             # 密码（与 REDIS_PASSWORD 等价，任填其一）

    说明：
        - REDIS_PWD 与 REDIS_PASSWORD 等价（REDIS_PASSWORD 优先）。
        - 密码含 @ / : / 等特殊字符无需手动转义，程序会自动 urlencode。
        - 本机自带 Redis（D:\ProgramFiles\Redis-x64-3.0.504，requirepass 123456）时：
              REDIS_HOST=127.0.0.1 / REDIS_PORT=6379 / REDIS_DB=3 / REDIS_PASSWORD=123456
        - -Mode Status 会顺带显示 Redis 连接状态。
#>
[CmdletBinding()]
param(
    [ValidateSet('Backend', 'Frontend', 'Nginx', 'All')]
    [string]$Target = 'All',

    [ValidateSet('Build', 'Start', 'BuildStart', 'Stop', 'Restart', 'Status')]
    [string]$Mode = 'BuildStart',

    [ValidateSet('Dev', 'Prod')]
    [string]$FrontendMode = 'Dev',

    [string]$Python = '',
    [string]$FrontendDir = '',
    [string]$NginxDir = 'D:\ProgramFiles\nginx-1.20.2',
    [string]$Proxy = 'http://127.0.0.1:7897',
    [switch]$NoProxy,
    [switch]$Install,
    [switch]$Help
)

$ErrorActionPreference = 'Stop'

# 让中文在 Windows PowerShell 控制台正常输出
try {
    [Console]::OutputEncoding = [System.Text.Encoding]::UTF8
    $OutputEncoding = [System.Text.Encoding]::UTF8
} catch { }

# ---------------------------------------------------------------------------
# 路径 / 端口
# ---------------------------------------------------------------------------
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Definition
$RepoDir   = $ScriptDir
$AppDir    = Join-Path $RepoDir 'app'
$LogDir    = Join-Path $RepoDir 'logs'

if (-not $FrontendDir) {
    $FrontendDir = Join-Path $RepoDir '..\hipy-ui\dashboard'
}
$FrontendDir = [System.IO.Path]::GetFullPath($FrontendDir)

if (-not (Test-Path $LogDir)) { New-Item -ItemType Directory -Path $LogDir | Out-Null }

function Get-BackendPort {
    $port = 5707
    $envFile = Join-Path $AppDir 'configs\.env'
    if (Test-Path $envFile) {
        $line = Select-String -Path $envFile -Pattern '^\s*PORT\s*=' | Select-Object -First 1
        if ($line) {
            $raw = (($line.Line -split '=', 2)[1] -replace '#.*$', '').Trim().Trim('"').Trim("'")
            $parsed = 0
            if ([int]::TryParse($raw, [ref]$parsed) -and $parsed -gt 0 -and $parsed -lt 65536) {
                $port = $parsed
            } else {
                Write-Host "  [警告] 无法解析 configs\.env 中的 PORT='$raw'，使用默认 $port" -ForegroundColor Yellow
            }
        }
    }
    return $port
}

function Resolve-Python {
    if ($Python) { return $Python }
    $venvPy = Join-Path $RepoDir 'venv\Scripts\python.exe'
    if (Test-Path $venvPy) { return $venvPy }
    return 'python'
}

$BackendPort  = Get-BackendPort
$FrontendPort = if ($FrontendMode -eq 'Prod') { 8081 } else { 8080 }
$NginxExe     = Join-Path $NginxDir 'nginx.exe'

# ---------------------------------------------------------------------------
# 通用工具
# ---------------------------------------------------------------------------
function Write-Step { param([string]$Text) Write-Host "`n== $Text ==" -ForegroundColor Cyan }
function Write-Ok   { param([string]$Text) Write-Host "  $Text" -ForegroundColor Green }
function Write-Warn { param([string]$Text) Write-Host "  $Text" -ForegroundColor Yellow }

function Set-ProxyEnv {
    if ($NoProxy) {
        foreach ($n in 'HTTP_PROXY', 'HTTPS_PROXY', 'http_proxy', 'https_proxy', 'NO_PROXY', 'no_proxy') {
            Remove-Item "Env:$n" -ErrorAction SilentlyContinue
        }
    } else {
        $env:HTTP_PROXY  = $Proxy
        $env:HTTPS_PROXY = $Proxy
        $env:http_proxy  = $Proxy
        $env:https_proxy = $Proxy
        $env:NO_PROXY    = 'localhost,127.0.0.1'
        $env:no_proxy    = 'localhost,127.0.0.1'
    }
}

function Set-NodeCompat {
    # Node 17+ 需要 legacy provider 才能跑 webpack4 (vue-cli 3)
    try {
        $major = [int](((node -v) -replace '^v', '').Split('.')[0])
        if ($major -ge 17) { $env:NODE_OPTIONS = '--openssl-legacy-provider' }
    } catch {
        Write-Warn '未检测到 node，前端相关命令可能失败'
    }
}

function Get-ListenPids {
    param([int]$Port)
    try {
        return @(Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue |
            Select-Object -ExpandProperty OwningProcess -Unique)
    } catch {
        return @()
    }
}

function Test-PortListening {
    param([int]$Port)
    $pids = Get-ListenPids -Port $Port
    return [bool]($pids -and $pids.Count -gt 0)
}

function Stop-ByPort {
    param([int]$Port, [string]$Name)
    $pids = Get-ListenPids -Port $Port
    if (-not $pids -or $pids.Count -eq 0) {
        Write-Warn "$Name 端口 $Port 未监听，跳过"
        return
    }
    foreach ($procId in $pids) {
        try {
            Stop-Process -Id $procId -Force -ErrorAction Stop
            Write-Ok "$Name 已停止 (PID $procId, 端口 $Port)"
        } catch {
            Write-Warn "$Name 停止 PID $procId 失败：$($_.Exception.Message)"
        }
    }
}

function Show-PortStatus {
    param([int]$Port, [string]$Name, [string]$Url)
    $pids = Get-ListenPids -Port $Port
    if ($pids -and $pids.Count -gt 0) {
        Write-Host "  [运行] $Name  ($Url, PID $($pids -join ','))" -ForegroundColor Green
    } else {
        Write-Host "  [未运行] $Name  ($Url)" -ForegroundColor DarkGray
    }
}

function Wait-PortListening {
    # 轮询等待端口监听，避免固定 sleep 过早判定为未启动
    param([int]$Port, [int]$TimeoutSec = 30)
    $deadline = (Get-Date).AddSeconds($TimeoutSec)
    while ((Get-Date) -lt $deadline) {
        if (Test-PortListening -Port $Port) { return $true }
        Start-Sleep -Milliseconds 500
    }
    return $false
}

function Get-FrontendLogPort {
    # 从前端启动日志解析 dev server 实际端口（默认端口被占用时 vue-cli 会自动换端口）
    $log = Join-Path $LogDir 'frontend.out.log'
    if (-not (Test-Path $log)) { return $null }
    try {
        $m = Select-String -Path $log -Pattern '(?:localhost|127\.0\.0\.1):(\d+)' -AllMatches |
            ForEach-Object { $_.Matches } | Select-Object -Last 1
        if ($m) {
            $p = 0
            if ([int]::TryParse($m.Groups[1].Value, [ref]$p) -and $p -gt 0 -and $p -lt 65536) { return $p }
        }
    } catch { }
    return $null
}

function Resolve-FrontendPort {
    # 优先返回日志中记录且正在监听的端口，否则回退默认端口
    $p = Get-FrontendLogPort
    if ($p -and (Test-PortListening -Port $p)) { return $p }
    return $FrontendPort
}

function Stop-Frontend {
    $p = Resolve-FrontendPort
    Stop-ByPort -Port $p -Name '前端'
    if ($p -ne $FrontendPort) { Stop-ByPort -Port $FrontendPort -Name '前端' }
}

function Get-EnvValue {
    param([string]$File, [string]$Key)
    if (-not (Test-Path $File)) { return $null }
    $line = Select-String -Path $File -Pattern "^\s*$Key\s*=" | Select-Object -First 1
    if ($line) { return (($line.Line -split '=', 2)[1]).Trim() }
    return $null
}

function Show-RedisStatus {
    # 读取 .env 的 REDIS_* 配置并探测连通性（依赖 venv 中的 redis 库）
    $envFile = Join-Path $AppDir 'configs\.env'
    $h = Get-EnvValue -File $envFile -Key 'REDIS_HOST'
    $p = Get-EnvValue -File $envFile -Key 'REDIS_PORT'
    $d = Get-EnvValue -File $envFile -Key 'REDIS_DB'
    $w = Get-EnvValue -File $envFile -Key 'REDIS_PASSWORD'
    if (-not $w) { $w = Get-EnvValue -File $envFile -Key 'REDIS_PWD' }
    if (-not $h) { $h = '127.0.0.1' }
    if (-not $p) { $p = '6379' }
    if (-not $d) { $d = '0' }
    $target = "${h}:$p/$d"
    $py = Resolve-Python
    $code = 'import redis,sys;print(redis.Redis(host=sys.argv[1],port=int(sys.argv[2]),db=int(sys.argv[3]),password=(sys.argv[4] or None),socket_connect_timeout=3).ping())'
    try {
        & $py -c $code $h $p $d $w 2>&1 | Out-Null
        if ($LASTEXITCODE -eq 0) {
            Write-Host "  [运行] Redis ($target)" -ForegroundColor Green
        } else {
            Write-Host "  [异常] Redis ($target) 无法连接" -ForegroundColor Red
        }
    } catch {
        Write-Warn "Redis ($target) 检测失败：$($_.Exception.Message)"
    }
}

function Start-Background {
    param(
        [string]$FilePath,
        [string[]]$ArgumentList,
        [string]$WorkingDirectory,
        [string]$Name
    )
    $out = Join-Path $LogDir "$Name.out.log"
    $err = Join-Path $LogDir "$Name.err.log"
    $p = Start-Process -FilePath $FilePath -ArgumentList $ArgumentList `
        -WorkingDirectory $WorkingDirectory -WindowStyle Hidden `
        -RedirectStandardOutput $out -RedirectStandardError $err -PassThru
    Write-Ok "$Name 已后台启动 (PID $($p.Id))，日志：$out"
    return $p
}

function Save-ListenPid {
    # 记录真正监听端口的进程 PID（启动器可能是子进程，直接用 Start-Process 的 PID 会误导）
    param([int]$Port, [string]$Name)
    $pidFile = Join-Path $LogDir "$Name.pid"
    $pids = Get-ListenPids -Port $Port
    if ($pids -and $pids.Count -gt 0) {
        ($pids -join "`r`n") | Set-Content -Path $pidFile -Encoding ASCII
    } else {
        Remove-Item $pidFile -ErrorAction SilentlyContinue
    }
}

# ---------------------------------------------------------------------------
# 后端
# ---------------------------------------------------------------------------
function Build-Backend {
    Write-Step '编译后端 (语法检查)'
    $py = Resolve-Python
    Set-ProxyEnv
    if ($Install) {
        Write-Host "  pip install -r requirements.txt" -ForegroundColor DarkGray
        & $py -m pip install -r (Join-Path $AppDir 'requirements.txt')
        if ($LASTEXITCODE -ne 0) { throw '后端依赖安装失败' }
    }
    Push-Location $AppDir
    try {
        & $py -m compileall -q .
        if ($LASTEXITCODE -ne 0) { throw '后端编译(语法检查)失败' }
    } finally {
        Pop-Location
    }
    Write-Ok '后端编译通过'
}

function Start-Backend {
    Write-Step "启动后端 (端口 $BackendPort)"
    $py = Resolve-Python
    Stop-ByPort -Port $BackendPort -Name '后端'
    Set-ProxyEnv
    Start-Background -FilePath $py -ArgumentList @('main.py') `
        -WorkingDirectory $AppDir -Name 'backend' | Out-Null
    if (-not (Wait-PortListening -Port $BackendPort -TimeoutSec 30)) {
        Write-Warn "后端 30 秒内未监听端口 $BackendPort，请检查日志：$(Join-Path $LogDir 'backend.err.log')"
    }
    Save-ListenPid -Port $BackendPort -Name 'backend'
    Show-PortStatus -Port $BackendPort -Name '后端' -Url "http://127.0.0.1:$BackendPort"
}

# ---------------------------------------------------------------------------
# 前端
# ---------------------------------------------------------------------------
function Assert-FrontendDir {
    if (-not (Test-Path $FrontendDir)) {
        throw "前端目录不存在：$FrontendDir （可用 -FrontendDir 指定）"
    }
}

function Build-Frontend {
    Assert-FrontendDir
    Set-ProxyEnv
    Set-NodeCompat
    $nodeModules = Join-Path $FrontendDir 'node_modules'
    $needInstall = $Install -or (-not (Test-Path $nodeModules))
    Push-Location $FrontendDir
    try {
        if ($needInstall) {
            Write-Step '安装前端依赖 (npm install)'
            & npm install --no-audit --no-fund --legacy-peer-deps
            if ($LASTEXITCODE -ne 0) { throw '前端依赖安装失败' }
            Write-Ok '前端依赖安装完成'
        } else {
            Write-Warn '前端依赖已存在，跳过安装（-Install 可强制重装）'
        }
        if ($FrontendMode -eq 'Prod') {
            Write-Step '构建前端 (npm run build:prod)'
            & npm run build:prod
            if ($LASTEXITCODE -ne 0) { throw '前端构建失败' }
            Write-Ok '前端生产包构建完成 (dist\)'
        } else {
            Write-Ok '前端 Dev 模式无需构建'
        }
    } finally {
        Pop-Location
    }
}

function Start-Frontend {
    Assert-FrontendDir
    if (-not (Test-Path (Join-Path $FrontendDir 'node_modules'))) {
        throw '前端依赖未安装，请先执行：.\run.ps1 -Target Frontend -Mode Build'
    }
    if ($FrontendMode -eq 'Prod' -and -not (Test-Path (Join-Path $FrontendDir 'dist'))) {
        Write-Warn '未发现 dist 目录，正在构建生产包...'
        Build-Frontend
    }
    Set-ProxyEnv
    Set-NodeCompat
    $npmCmd = if ($FrontendMode -eq 'Prod') { 'run preview' } else { 'run dev' }
    Write-Step "启动前端 ($FrontendMode, 默认端口 $FrontendPort)"
    Stop-Frontend
    Start-Background -FilePath 'cmd.exe' -ArgumentList @('/c', "npm $npmCmd") `
        -WorkingDirectory $FrontendDir -Name 'frontend' | Out-Null
    # 端口被占用时 vue-cli 会自动换端口，轮询日志解析实际端口
    $resolvedPort = $FrontendPort
    $deadline = (Get-Date).AddSeconds(60)
    while ((Get-Date) -lt $deadline) {
        $lp = Get-FrontendLogPort
        if ($lp -and (Test-PortListening -Port $lp)) { $resolvedPort = $lp; break }
        if (Test-PortListening -Port $FrontendPort) { $resolvedPort = $FrontendPort; break }
        Start-Sleep -Milliseconds 500
    }
    if (-not (Test-PortListening -Port $resolvedPort)) {
        Write-Warn "前端 60 秒内未监听端口，请检查日志：$(Join-Path $LogDir 'frontend.err.log')"
    }
    Save-ListenPid -Port $resolvedPort -Name 'frontend'
    Show-PortStatus -Port $resolvedPort -Name '前端' -Url "http://localhost:$resolvedPort"
}

# ---------------------------------------------------------------------------
# nginx
# ---------------------------------------------------------------------------
function Invoke-Nginx {
    param([string[]]$NginxArgs)
    if (-not (Test-Path $NginxExe)) { throw "nginx 不存在：$NginxExe （可用 -NginxDir 指定）" }
    if ($NginxArgs.Count -eq 0) {
        Start-Process -FilePath $NginxExe -WorkingDirectory $NginxDir -WindowStyle Hidden | Out-Null
    } else {
        Start-Process -FilePath $NginxExe -ArgumentList $NginxArgs `
            -WorkingDirectory $NginxDir -WindowStyle Hidden -Wait | Out-Null
    }
}

function Test-NginxRunning {
    $procs = @(Get-Process -Name 'nginx' -ErrorAction SilentlyContinue)
    return ($procs.Count -gt 0)
}

function Start-Nginx {
    Write-Step '启动 nginx'
    if (Test-NginxRunning) { Write-Warn 'nginx 已在运行'; return }
    Invoke-Nginx -NginxArgs @()
    Start-Sleep -Seconds 2
    if (Test-NginxRunning) { Write-Ok "nginx 已启动 ($NginxDir)" } else { Write-Warn 'nginx 启动失败，请检查配置' }
}

function Stop-Nginx {
    Write-Step '停止 nginx'
    if (-not (Test-NginxRunning)) { Write-Warn 'nginx 未在运行'; return }
    Invoke-Nginx -NginxArgs @('-s', 'stop')
    Start-Sleep -Seconds 1
    if (Test-NginxRunning) { Write-Warn 'nginx 可能未完全停止' } else { Write-Ok 'nginx 已停止' }
}

function Restart-Nginx {
    Write-Step '重载/重启 nginx'
    if (Test-NginxRunning) {
        Invoke-Nginx -NginxArgs @('-s', 'reload')
        Write-Ok 'nginx 已发送 reload'
    } else {
        Start-Nginx
    }
}

function Show-NginxStatus {
    if (Test-NginxRunning) { Write-Host '  [运行] nginx' -ForegroundColor Green }
    else { Write-Host '  [未运行] nginx' -ForegroundColor DarkGray }
}

# ---------------------------------------------------------------------------
# 主流程
# ---------------------------------------------------------------------------
if ($Help) {
    Get-Help $MyInvocation.MyCommand.Definition -Full
    return
}

Write-Host ''
Write-Host '  hipy-server 一键编译/启动脚本' -ForegroundColor Magenta
Write-Host "  目标=$Target  模式=$Mode  前端=$FrontendMode" -ForegroundColor DarkGray
Write-Host "  仓库=$RepoDir"
Write-Host "  前端=$FrontendDir"

$doBackend  = ($Target -eq 'Backend' -or $Target -eq 'All')
$doFrontend = ($Target -eq 'Frontend' -or $Target -eq 'All')
$doNginx    = ($Target -eq 'Nginx')

switch ($Mode) {
    'Build' {
        if ($doBackend)  { Build-Backend }
        if ($doFrontend) { Build-Frontend }
        if ($doNginx)    { Write-Warn 'nginx 无编译步骤' }
    }
    'Start' {
        if ($doBackend)  { Start-Backend }
        if ($doFrontend) { Start-Frontend }
        if ($doNginx)    { Start-Nginx }
    }
    'BuildStart' {
        if ($doBackend)  { Build-Backend; Start-Backend }
        if ($doFrontend) { Build-Frontend; Start-Frontend }
        if ($doNginx)    { Start-Nginx }
    }
    'Stop' {
        if ($doBackend)  { Write-Step '停止后端';  Stop-ByPort -Port $BackendPort -Name '后端' }
        if ($doFrontend) { Write-Step '停止前端';  Stop-Frontend }
        if ($doNginx)    { Stop-Nginx }
    }
    'Restart' {
        if ($doBackend)  { Write-Step '停止后端'; Stop-ByPort -Port $BackendPort -Name '后端'; Start-Backend }
        if ($doFrontend) { Write-Step '停止前端'; Stop-Frontend; Start-Frontend }
        if ($doNginx)    { Restart-Nginx }
    }
    'Status' {
        Write-Step '运行状态'
        if ($doBackend)  { Show-PortStatus -Port $BackendPort -Name '后端' -Url "http://127.0.0.1:$BackendPort" }
        if ($doFrontend) { $fp = Resolve-FrontendPort; Show-PortStatus -Port $fp -Name '前端' -Url "http://localhost:$fp" }
        if ($doBackend)  { Show-RedisStatus }
        if ($doNginx)    { Show-NginxStatus }
    }
}

Write-Host ''
Write-Host '完成。' -ForegroundColor Magenta
