# AI漫剧制作平台 一键启动脚本
# 按顺序启动：MySQL -> Redis -> 后端API -> ARQ Worker -> 前端Vite
param([switch]$Status)
$ErrorActionPreference = "SilentlyContinue"

$ProjectRoot = $PSScriptRoot
$ApiDir = Join-Path $ProjectRoot "services\api"
$WebDir = Join-Path $ProjectRoot "apps\web"
$Python = Join-Path $ApiDir ".venv\Scripts\python.exe"
$VenvPip = Join-Path $ApiDir ".venv\Scripts\pip.exe"
$ApiPort = 8001
$WebPort = 5174
$RedisPort = 6379
$MysqlPort = 3306
$LogDir = Join-Path $ProjectRoot "logs"
$PidDir = Join-Path $ProjectRoot ".run"
if (-not (Test-Path $LogDir)) { New-Item -ItemType Directory -Path $LogDir | Out-Null }
if (-not (Test-Path $PidDir)) { New-Item -ItemType Directory -Path $PidDir | Out-Null }

function W  { param($m) Write-Host "[$(Get-Date -Format 'HH:mm:ss')] $m" -ForegroundColor Cyan }
function OK { param($m) Write-Host "  [OK] $m" -ForegroundColor Green }
function WN { param($m) Write-Host "  [WARN] $m" -ForegroundColor Yellow }
function ER { param($m) Write-Host "  [FAIL] $m" -ForegroundColor Red }
function Test-Port { param($p) [bool](Get-NetTCPConnection -LocalPort $p -State Listen -ErrorAction SilentlyContinue) }
function Save-Pid { param($n,$id) Set-Content -Path (Join-Path $PidDir "$n.pid") -Value $id -Encoding UTF8 }
function Get-Pid { param($n) $f=Join-Path $PidDir "$n.pid"; if(Test-Path $f){[int](Get-Content $f -Raw)}else{$null} }

function Show-Status {
    Write-Host ""
    Write-Host "========== Service Status ==========" -ForegroundColor Magenta
    $mr = (Get-Service -Name "MySQL80" -ErrorAction SilentlyContinue).Status -eq "Running"
    $rr = Test-Port $RedisPort
    $ar = Test-Port $ApiPort
    $wr = Test-Port $WebPort
    $ap = Get-Pid "arq"
    $aq = $ap -and (Get-Process -Id $ap -ErrorAction SilentlyContinue)
    $svcs = @(
        @{N="MySQL";P=$MysqlPort;R=$mr},
        @{N="Redis";P=$RedisPort;R=$rr},
        @{N="Backend API";P=$ApiPort;R=$ar},
        @{N="ARQ Worker";P="--";R=[bool]$aq},
        @{N="Frontend";P=$WebPort;R=$wr}
    )
    foreach($s in $svcs){
        $st = if($s.R){"Running"}else{"Stopped"}
        $c = if($s.R){"Green"}else{"Red"}
        $ps = if($s.P -eq "--"){""}else{":$($s.P)"}
        Write-Host ("  {0,-16} {1,-8} {2}" -f $s.N,$st,$ps) -ForegroundColor $c
    }
    Write-Host "====================================" -ForegroundColor Magenta
    Write-Host ""
}

if ($Status) { Show-Status; return }

Write-Host ""
Write-Host "========== Starting AI Manga Studio ==========" -ForegroundColor Magenta
Write-Host ""

# 1. MySQL
W "Checking MySQL..."
$ms = Get-Service -Name "MySQL80" -ErrorAction SilentlyContinue
if ($ms -and $ms.Status -eq "Running") { OK "MySQL80 running" }
elseif ($ms) { W "Starting MySQL80..."; Start-Service -Name "MySQL80"; Start-Sleep 2; OK "MySQL80 started" }
else { WN "MySQL80 service not found" }

# 2. Redis
W "Checking Redis..."
if (Test-Port $RedisPort) { OK "Redis running on $RedisPort" }
else {
    $re = Get-ChildItem -Path "E:\专业软件\redis","C:\redis","D:\redis" -Filter "redis-server.exe" -ErrorAction SilentlyContinue | Select-Object -First 1 -ExpandProperty FullName
    if ($re) {
        W "Starting Redis..."
        $p = Start-Process -FilePath $re -ArgumentList "--port $RedisPort" -RedirectStandardOutput (Join-Path $LogDir "redis.log") -WindowStyle Hidden -PassThru
        Save-Pid "redis" $p.Id
        Start-Sleep 2
        if (Test-Port $RedisPort) { OK "Redis started PID $($p.Id)" } else { ER "Redis failed" }
    } else { WN "redis-server.exe not found" }
}

# 3. Python venv + deps
W "Checking Python venv..."
if (-not (Test-Path $Python)) { W "Creating venv..."; Push-Location $ApiDir; python -m venv .venv; Pop-Location; OK "venv created" }
if (-not (Test-Path (Join-Path $ApiDir ".venv\Lib\site-packages\fastapi"))) {
    W "Installing backend deps..."
    Push-Location $ApiDir
    & $VenvPip install --no-cache-dir -q fastapi==0.115.6 "starlette>=0.37.2,<0.42.0" "uvicorn[standard]" "sqlalchemy[asyncio]" asyncmy alembic pydantic pydantic-settings "python-jose[cryptography]" bcrypt cryptography python-multipart redis arq langgraph langchain-core litellm httpx loguru orjson email-validator phonenumbers 2>&1 | Out-Null
    Pop-Location
    OK "Backend deps installed"
} else { OK "Backend deps ready" }

# 3.5 Database Migration
# Alembic 为数据库 Schema 唯一变更通道：后端启动前先执行迁移；失败仅 WARN 不中断启动
W "Running database migrations..."
Push-Location $ApiDir
& $Python -m alembic upgrade head > (Join-Path $LogDir "alembic.log") 2>&1
if ($LASTEXITCODE -eq 0) { OK "Database schema up to date" } else { WN "Alembic migration failed (WARN only), see logs\alembic.log" }
Pop-Location

# 4. Backend API
W "Starting Backend API..."
if (Test-Port $ApiPort) { OK "Backend API running on $ApiPort" }
else {
    Push-Location $ApiDir
    # --reload 开启代码热重载：修改后端 Python 代码后自动重启 API，无需手动重启
    $p = Start-Process -FilePath $Python -ArgumentList "-m","uvicorn","app.main:app","--host","0.0.0.0","--port","$ApiPort","--reload" -RedirectStandardOutput (Join-Path $LogDir "api.log") -RedirectStandardError (Join-Path $LogDir "api.err.log") -WindowStyle Hidden -PassThru
    Pop-Location
    Save-Pid "api" $p.Id
    $ready=$false
    for($i=0;$i -lt 30;$i++){ Start-Sleep 1; if(Test-Port $ApiPort){$ready=$true;break} }
    if($ready){ OK "Backend API started PID $($p.Id) port $ApiPort" } else { ER "Backend API timeout, see logs\api.log" }
}

# 5. ARQ Worker
W "Starting ARQ Worker..."
$ap = Get-Pid "arq"
if ($ap -and (Get-Process -Id $ap -ErrorAction SilentlyContinue)) { OK "ARQ Worker running PID $ap" }
else {
    Push-Location $ApiDir
    $p = Start-Process -FilePath $Python -ArgumentList "-m","arq","app.tasks.worker.WorkerSettings" -RedirectStandardOutput (Join-Path $LogDir "arq.log") -RedirectStandardError (Join-Path $LogDir "arq.err.log") -WindowStyle Hidden -PassThru
    Pop-Location
    Save-Pid "arq" $p.Id
    Start-Sleep 2
    if (Get-Process -Id $p.Id -ErrorAction SilentlyContinue) { OK "ARQ Worker started PID $($p.Id)" } else { ER "ARQ Worker failed, see logs\arq.log" }
}

# 6. Frontend
W "Checking frontend deps..."
if (-not (Test-Path (Join-Path $WebDir "node_modules\vite"))) {
    W "Installing frontend deps..."
    Push-Location $WebDir; npm install --no-audit --no-fund 2>&1 | Out-Null; Pop-Location
    OK "Frontend deps installed"
} else { OK "Frontend deps ready" }

W "Starting Frontend..."
if (Test-Port $WebPort) { OK "Frontend running on $WebPort" }
else {
    Push-Location $WebDir
    $p = Start-Process -FilePath "node" -ArgumentList "node_modules/vite/bin/vite.js","--host","0.0.0.0","--port","$WebPort" -RedirectStandardOutput (Join-Path $LogDir "web.log") -RedirectStandardError (Join-Path $LogDir "web.err.log") -WindowStyle Hidden -PassThru
    Pop-Location
    Save-Pid "web" $p.Id
    $ready=$false
    for($i=0;$i -lt 30;$i++){ Start-Sleep 1; if(Test-Port $WebPort){$ready=$true;break} }
    if($ready){ OK "Frontend started PID $($p.Id) port $WebPort" } else { ER "Frontend timeout, see logs\web.log" }
}

Write-Host ""
Write-Host "========== All Services Started ==========" -ForegroundColor Green
Write-Host "  Backend API: http://localhost:$ApiPort" -ForegroundColor White
Write-Host "  API Docs:    http://localhost:$ApiPort/docs" -ForegroundColor White
Write-Host "  Frontend:    http://localhost:$WebPort" -ForegroundColor Yellow
Write-Host "  Account:     admin / 123456" -ForegroundColor White
Write-Host "==========================================" -ForegroundColor Green

# 前端启动成功时自动打开浏览器访问前端页面
if (Test-Port $WebPort) {
    W "Opening browser to http://localhost:$WebPort ..."
    Start-Process "http://localhost:$WebPort"
} else {
    WN "Frontend not ready, open http://localhost:$WebPort manually"
}
Show-Status