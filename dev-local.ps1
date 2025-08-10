# Respondr Local Development Helper Script
# Usage:
#   .\dev-local.ps1                    # Start backend only
#   .\dev-local.ps1 -Full              # Start backend + frontend
#   .\dev-local.ps1 -Docker            # Use Docker
#   .\dev-local.ps1 -Test              # Run tests

param(
    [switch]$Full,
    [switch]$Docker,
    [switch]$Test,
    [switch]$Help
)

if ($Help) {
    Write-Host "Respondr Local Development Helper" -ForegroundColor Green
    Write-Host ""
    Write-Host "Usage:" -ForegroundColor Yellow
    Write-Host "  .\dev-local.ps1           # Backend only (FastAPI)" -ForegroundColor White
    Write-Host "  .\dev-local.ps1 -Full     # Backend + Frontend" -ForegroundColor White
    Write-Host "  .\dev-local.ps1 -Docker   # Docker Compose" -ForegroundColor White
    Write-Host "  .\dev-local.ps1 -Test     # Run webhook tests" -ForegroundColor White
    Write-Host ""
    Write-Host "Access URLs:" -ForegroundColor Yellow
    Write-Host "  Backend API: http://localhost:8000" -ForegroundColor Cyan
    Write-Host "  API Docs: http://localhost:8000/docs" -ForegroundColor Cyan
    Write-Host "  Frontend: http://localhost:3100 (if -Full)" -ForegroundColor Cyan
    exit 0
}

Write-Host "🛠️  Respondr Local Development Setup" -ForegroundColor Green
Write-Host "====================================" -ForegroundColor Green

# Helpers: ensure Redis is available locally when not using Docker Compose
function Test-RedisPort {
    param([string]$RedisHost = 'localhost', [int]$RedisPort = 6379, [int]$TimeoutMs = 1000)
    try {
        $tcp = New-Object Net.Sockets.TcpClient
        $iar = $tcp.BeginConnect($RedisHost, $RedisPort, $null, $null)
        $success = $iar.AsyncWaitHandle.WaitOne($TimeoutMs, $false)
        if ($success -and $tcp.Connected) { $tcp.Close(); return $true }
        $tcp.Close(); return $false
    } catch { return $false }
}

function Start-LocalRedis {
    Write-Host "Checking for Docker to start Redis..." -ForegroundColor Yellow
    $docker = Get-Command docker -ErrorAction SilentlyContinue
    if (-not $docker) {
        Write-Host "Docker not found; cannot auto-start Redis. Install Docker Desktop or run Redis manually." -ForegroundColor Red
        return $false
    }
    $running = (& docker ps --filter "name=respondr-redis" --filter "status=running" --format "{{.Names}}")
    if ($running) { Write-Host "Redis container already running (respondr-redis)" -ForegroundColor Green; return $true }
    $exists = (& docker ps -a --filter "name=respondr-redis" --format "{{.Names}}")
    if ($exists) { & docker rm -f respondr-redis | Out-Null }
    Write-Host "Starting Redis container on port 6379..." -ForegroundColor Yellow
    & docker run -d --name respondr-redis -p 6379:6379 redis:7-alpine | Out-Null
    Start-Sleep -Seconds 2
    return (Test-RedisPort -RedisHost 'localhost' -RedisPort 6379)
}

function Ensure-Redis {
    if (Test-RedisPort -RedisHost 'localhost' -RedisPort 6379) {
        Write-Host "✅ Redis detected at localhost:6379" -ForegroundColor Green
        return $true
    }
    Write-Host "ℹ️  Redis not detected locally. Attempting to start a Docker Redis..." -ForegroundColor Yellow
    $started = Start-LocalRedis
    if ($started) { Write-Host "✅ Redis started at localhost:6379" -ForegroundColor Green; return $true }
    Write-Host "⚠️  Could not start Redis automatically. The backend will run with in-memory storage only (data will reset on reload)." -ForegroundColor Yellow
    return $false
}

# Check if .env file exists
if (-not (Test-Path "backend\.env")) {
    Write-Host "❌ backend\.env file not found!" -ForegroundColor Red
    Write-Host "Please run create-secrets.ps1 first or copy from deployment." -ForegroundColor Yellow
    exit 1
}

if ($Docker) {
    Write-Host "🐳 Starting with Docker Compose..." -ForegroundColor Blue
    Write-Host ""
    Write-Host "Access points:" -ForegroundColor Yellow
    Write-Host "  • API: http://localhost:8000" -ForegroundColor Cyan
    Write-Host "  • Docs: http://localhost:8000/docs" -ForegroundColor Cyan
    Write-Host "  • Webhook: http://localhost:8000/webhook" -ForegroundColor Cyan
    Write-Host ""
    
    docker-compose -f docker-compose.local.yml up --build
    
} elseif ($Test) {
    Write-Host "🧪 Running webhook tests..." -ForegroundColor Blue
    Write-Host ""
    
    # Check if backend is running
    try {
        Invoke-WebRequest -Uri "http://localhost:8000/api/responders" -TimeoutSec 2 | Out-Null
        Write-Host "Backend is running, testing webhooks..." -ForegroundColor Green
        
        Set-Location backend
        py test_webhook.py
        
    } catch {
        Write-Host "Backend not running on localhost:8000" -ForegroundColor Red
        Write-Host "Start the backend first with: .\dev-local.ps1" -ForegroundColor Yellow
    }
    
} elseif ($Full) {
    Write-Host "Starting Full Stack (Backend + Frontend)..." -ForegroundColor Blue
    Write-Host ""
    Write-Host "This will open two terminals:" -ForegroundColor Yellow
    Write-Host "  1. Backend (FastAPI) on http://localhost:8000" -ForegroundColor Cyan
    Write-Host "  2. Frontend (React) on http://localhost:3100" -ForegroundColor Cyan
    Write-Host ""

    # Ensure Redis for local persistence
    Ensure-Redis | Out-Null
    
    # Start backend in new terminal using venv python if available
    $venvPy = Join-Path $PWD "backend\.venv\Scripts\python.exe"
    $pyCmd = if (Test-Path $venvPy) { $venvPy } else { 'python' }
    Start-Process powershell -ArgumentList "-NoExit", "-Command", "cd '$PWD\backend'; Write-Host 'Starting Backend...' -ForegroundColor Green; `$env:TIMEZONE='America/Los_Angeles'; `$env:ALLOW_LOCAL_AUTH_BYPASS='true'; `$env:REDIS_HOST='localhost'; `$env:REDIS_PORT='6379'; & '$pyCmd' -m uvicorn main:app --reload --host 0.0.0.0 --port 8000"
    
    # Wait a moment for backend to start
    Start-Sleep -Seconds 3
    
    # Start frontend in new terminal
    # - Auto-install dependencies if react-scripts is missing
    # - Escape `$ so env var is set in the child
    Start-Process powershell -ArgumentList "-NoExit", "-Command", "cd '$PWD\frontend'; if (!(Test-Path 'node_modules\\.bin\\react-scripts') -and !(Test-Path 'node_modules\\react-scripts')) { Write-Host 'Installing frontend dependencies (npm ci)…' -ForegroundColor Yellow; npm ci }; Write-Host 'Starting Frontend on :3100...' -ForegroundColor Blue; `$env:PORT=3100; npm start"
    
    Write-Host "Both services starting in separate terminals..." -ForegroundColor Green
    Write-Host ""
    Write-Host "Access URLs:" -ForegroundColor Yellow
    Write-Host "  • Frontend: http://localhost:3100" -ForegroundColor Cyan
    Write-Host "  • Backend: http://localhost:8000" -ForegroundColor Cyan
    Write-Host "  • API Docs: http://localhost:8000/docs" -ForegroundColor Cyan
    
} else {
    Write-Host "Starting Backend Only (FastAPI)..." -ForegroundColor Blue
    Write-Host ""
    Write-Host "Access points:" -ForegroundColor Yellow
    Write-Host "  • API: http://localhost:8000" -ForegroundColor Cyan
    Write-Host "  • Docs: http://localhost:8000/docs" -ForegroundColor Cyan
    Write-Host "  • Webhook: http://localhost:8000/webhook" -ForegroundColor Cyan
    Write-Host ""
    Write-Host "For testing, run in another terminal:" -ForegroundColor Yellow
    Write-Host "  .\dev-local.ps1 -Test" -ForegroundColor White
    Write-Host ""

    # Ensure Redis for local persistence
    Ensure-Redis | Out-Null
    
    Set-Location backend
    $venvPy = Join-Path $PWD "..\backend\.venv\Scripts\python.exe"
    if (-not (Test-Path $venvPy)) { $venvPy = 'python' }
    $env:TIMEZONE='America/Los_Angeles'
    $env:ALLOW_LOCAL_AUTH_BYPASS='true'
    $env:REDIS_HOST='localhost'
    $env:REDIS_PORT='6379'
    & $venvPy -m uvicorn main:app --reload --host 0.0.0.0 --port 8000
}
