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
    Write-Host "  Frontend: http://localhost:3000 (if -Full)" -ForegroundColor Cyan
    exit 0
}

Write-Host "🛠️  Respondr Local Development Setup" -ForegroundColor Green
Write-Host "====================================" -ForegroundColor Green

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
    Write-Host "  2. Frontend (React) on http://localhost:3000" -ForegroundColor Cyan
    Write-Host ""
    
    # Start backend in new terminal
    Start-Process powershell -ArgumentList "-NoExit", "-Command", "cd '$PWD\backend'; Write-Host 'Starting Backend...' -ForegroundColor Green; python -m uvicorn main:app --reload --host 0.0.0.0 --port 8000"
    
    # Wait a moment for backend to start
    Start-Sleep -Seconds 3
    
    # Start frontend in new terminal
    Start-Process powershell -ArgumentList "-NoExit", "-Command", "cd '$PWD\frontend'; Write-Host 'Starting Frontend...' -ForegroundColor Blue; npm start"
    
    Write-Host "Both services starting in separate terminals..." -ForegroundColor Green
    Write-Host ""
    Write-Host "Access URLs:" -ForegroundColor Yellow
    Write-Host "  • Frontend: http://localhost:3000" -ForegroundColor Cyan
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
    
    Set-Location backend
    python -m uvicorn main:app --reload --host 0.0.0.0 --port 8000
}
