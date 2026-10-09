# AI漫剧制作平台 一键停止脚本
$ErrorActionPreference = "SilentlyContinue"
$ProjectRoot = $PSScriptRoot
$PidDir = Join-Path $ProjectRoot ".run"

function Write-Step { param([string]$m) Write-Host "[$(Get-Date -Format 'HH:mm:ss')] $m" -ForegroundColor Cyan }
function Write-Ok { param([string]$m) Write-Host "  [OK] $m" -ForegroundColor Green }
function Write-Warn { param([string]$m) Write-Host "  [WARN] $m" -ForegroundColor Yellow }

function Stop-SavedProcess {
    param([string]$Name)
    $f = Join-Path $PidDir "$Name.pid"
    if (Test-Path $f) {
        $id = [int](Get-Content $f -Raw)
        $p = Get-Process -Id $id -ErrorAction SilentlyContinue
        if ($p) {
            Stop-Process -Id $id -Force
            Start-Sleep -Milliseconds 500
            if (Get-Process -Id $id -ErrorAction SilentlyContinue) { Write-Warn "$Name PID $id failed" } else { Write-Ok "$Name PID $id stopped" }
        } else { Write-Warn "$Name PID $id not running" }
        Remove-Item $f -Force
    } else { Write-Warn "No PID file for $Name" }
}

function Stop-ProcessByPort {
    param([int]$Port)
    $conns = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue
    foreach ($c in $conns) {
        $p = Get-Process -Id $c.OwningProcess -ErrorAction SilentlyContinue
        if ($p -and $p.ProcessName -ne "Idle") {
            Write-Step "Kill port $Port : $($p.ProcessName) PID $($p.Id)"
            Stop-Process -Id $c.OwningProcess -Force
            Start-Sleep -Milliseconds 300
        }
    }
}

Write-Host ""
Write-Host "========== Stop AI Manga Studio ==========" -ForegroundColor Magenta
Write-Step "Stopping Frontend..."
Stop-SavedProcess "web"
Stop-ProcessByPort 5174
Write-Step "Stopping ARQ Worker..."
Stop-SavedProcess "arq"
Write-Step "Stopping Backend API..."
Stop-SavedProcess "api"
Stop-ProcessByPort 8001
Write-Step "Stopping Redis..."
Stop-SavedProcess "redis"
Stop-ProcessByPort 6379
Write-Warn "MySQL80 service kept running"
Write-Host "========== Done ==========" -ForegroundColor Green
Write-Host ""