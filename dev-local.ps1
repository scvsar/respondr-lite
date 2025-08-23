# Respondr Local Development Helper Script
# Usage:
#   .\dev-local.ps1                    # Start backend only
#   .\dev-local.ps1 -Full              # Start backend + frontend
#   .\dev-local.ps1 -Docker            # Use Docker
#   .\dev-local.ps1 -Test              # Run tests

param(
    [switch]$Full,
    [switch]$Dev,
    [switch]$Docker,
    [switch]$Test,
    [switch]$Build,
    [switch]$Help
)

if ($Help) {
    Write-Host "Respondr Local Development Helper" -ForegroundColor Green
    Write-Host ""
    Write-Host "Usage:" -ForegroundColor Yellow
    Write-Host "  .\dev-local.ps1              # Backend only (FastAPI). If frontend\\build exists, it's served at / on :8000" -ForegroundColor White
    Write-Host "  .\dev-local.ps1 -Full        # Backend on :8000, production-style SPA if built" -ForegroundColor White
    Write-Host "  .\dev-local.ps1 -Full -Dev   # Backend + CRA dev server (frontend on :3100)" -ForegroundColor White
    Write-Host "  .\dev-local.ps1 -Docker      # Docker Compose" -ForegroundColor White
    Write-Host "  .\dev-local.ps1 -Test        # Run webhook tests" -ForegroundColor White
    Write-Host "  .\dev-local.ps1 -Build       # Build frontend bundle (used by backend static mount on :8000)" -ForegroundColor White
    Write-Host "  .\dev-local.ps1 -Full -Build # Build + start backend on :8000 (no CRA dev server unless -Dev)" -ForegroundColor White
    Write-Host ""
    Write-Host "Access URLs:" -ForegroundColor Yellow
    Write-Host "  Backend API: http://localhost:8000" -ForegroundColor Cyan
    Write-Host "  API Docs: http://localhost:8000/docs" -ForegroundColor Cyan
    Write-Host "  Frontend: http://localhost:8000 (production-style, serves frontend\\build if present)" -ForegroundColor Cyan
    Write-Host "            http://localhost:3100 (only when -Dev is used)" -ForegroundColor Cyan
    exit 0
}

Write-Host "🛠️  Respondr Local Development Setup" -ForegroundColor Green
Write-Host "====================================" -ForegroundColor Green

# Build the React frontend production bundle
function Build-Frontend {
    Write-Host "🏗️  Building frontend production bundle..." -ForegroundColor Yellow
    $frontendPath = Join-Path $PWD "frontend"
    if (-not (Test-Path $frontendPath)) {
        Write-Host "❌ Frontend directory not found at $frontendPath" -ForegroundColor Red
        return $false
    }
    Push-Location $frontendPath
    try {
        if (!(Test-Path 'node_modules')) {
            Write-Host "Installing frontend dependencies (npm ci)…" -ForegroundColor Yellow
            npm ci
            if ($LASTEXITCODE -ne 0) { throw "npm ci failed" }
        }
        Write-Host "Running 'npm run build'…" -ForegroundColor Yellow
        npm run build
        if ($LASTEXITCODE -ne 0) { throw "npm run build failed" }
        Write-Host "✅ Frontend build complete: frontend\\build" -ForegroundColor Green
        return $true
    } catch {
        Write-Host "❌ Frontend build failed: $($_.Exception.Message)" -ForegroundColor Red
        return $false
    } finally {
        Pop-Location
    }
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
        py tests/test_webhook.py
        
    } catch {
        Write-Host "Backend not running on localhost:8000" -ForegroundColor Red
        Write-Host "Start the backend first with: .\dev-local.ps1" -ForegroundColor Yellow
    }
    
} elseif ($Full) {
    Write-Host "Starting Full Stack..." -ForegroundColor Blue
    Write-Host ""
    if ($Build) {
        Write-Host "Mode: Build + Serve via Backend on :8000" -ForegroundColor Yellow
        Write-Host "  • Backend (FastAPI) will serve the built SPA on http://localhost:8000" -ForegroundColor Cyan
    }
    if ($Dev) {
        Write-Host "Mode: Dev UI enabled — CRA dev server will run on :3100" -ForegroundColor Yellow
    } else {
        Write-Host "Mode: Production-style UI on :8000 (serves existing frontend\\build if present)" -ForegroundColor Yellow
    }
    Write-Host ""

    taskkill /F /IM python.exe 2>$null | Out-Null
    taskkill /F /IM node.exe 2>$null | Out-Null
    
    # If building, do it before starting the backend so static files are mounted
    if ($Build) {
        if (-not (Build-Frontend)) {
            Write-Host "⚠️  Proceeding without built frontend due to build failure" -ForegroundColor Yellow
        }
    }

    # Clear conflicting Azure OpenAI environment variables to ensure .env file is used
    Write-Host "Clearing conflicting Azure OpenAI environment variables..." -ForegroundColor Yellow
    Remove-Item Env:AZURE_OPENAI_ENDPOINT -ErrorAction SilentlyContinue
    Remove-Item Env:AZURE_OPENAI_API_VERSION -ErrorAction SilentlyContinue
    Remove-Item Env:AZURE_OPENAI_DEPLOYMENT -ErrorAction SilentlyContinue
    Write-Host "✅ Environment cleared for .env file usage" -ForegroundColor Green
    
    # Start backend in new terminal using venv python if available
    $venvPy = Join-Path $PWD "backend\.venv\Scripts\python.exe"
    $pyCmd = if (Test-Path $venvPy) { $venvPy } else { 'python' }
    Start-Process powershell -ArgumentList "-NoExit", "-Command", "cd '$PWD\backend'; Write-Host 'Starting Backend...' -ForegroundColor Green; `$env:TIMEZONE='America/Los_Angeles'; `$env:ALLOW_LOCAL_AUTH_BYPASS='true'; `$env:LOCAL_BYPASS_IS_ADMIN='true'; `$env:DISABLE_API_KEY_CHECK='true'; `$env:ALLOW_CLEAR_ALL='true'; & '$pyCmd' -m uvicorn main:app --reload --host 0.0.0.0 --port 8000"
    
    # Wait a moment for backend to start
    Start-Sleep -Seconds 3
    
    if ($Dev) {
        # Start frontend in new terminal (CRA dev server)
        # - Auto-install dependencies if react-scripts is missing
        # - Escape `$ so env var is set in the child
        Start-Process powershell -ArgumentList "-NoExit", "-Command", "cd '$PWD\frontend'; if (!(Test-Path 'node_modules\\.bin\\react-scripts') -and !(Test-Path 'node_modules\\react-scripts')) { Write-Host 'Installing frontend dependencies (npm ci)…' -ForegroundColor Yellow; npm ci }; Write-Host 'Starting Frontend on :3100...' -ForegroundColor Blue; `$env:PORT=3100; npm start"
        
        Write-Host "Backend and Frontend dev server starting in separate terminals..." -ForegroundColor Green
        Write-Host ""
        Write-Host "Access URLs:" -ForegroundColor Yellow
        Write-Host "  • Frontend (Dev): http://localhost:3100" -ForegroundColor Cyan
        Write-Host "  • Backend: http://localhost:8000" -ForegroundColor Cyan
        Write-Host "  • API Docs: http://localhost:8000/docs" -ForegroundColor Cyan
    } else {
        Write-Host "Backend starting; open the app at http://localhost:8000 (serves frontend\\build if present)" -ForegroundColor Green
        Write-Host ""
        Write-Host "Access URLs:" -ForegroundColor Yellow
        Write-Host "  • App + API: http://localhost:8000" -ForegroundColor Cyan
        Write-Host "  • API Docs: http://localhost:8000/docs" -ForegroundColor Cyan
    # Open the app in the default browser for convenience
    try { Start-Process "http://localhost:8000" } catch {}
    }
    
} else {
    Write-Host "Starting Backend Only (FastAPI)..." -ForegroundColor Blue
    Write-Host ""
    Write-Host "Access points:" -ForegroundColor Yellow
    Write-Host "  • API: http://localhost:8000" -ForegroundColor Cyan
    Write-Host "  • Docs: http://localhost:8000/docs" -ForegroundColor Cyan
    Write-Host "  • Webhook: http://localhost:8000/webhook" -ForegroundColor Cyan
    Write-Host "  • UI: http://localhost:8000 (if frontend\\build exists; use -Build to create it)" -ForegroundColor Cyan
    Write-Host ""
    Write-Host "For testing, run in another terminal:" -ForegroundColor Yellow
    Write-Host "  .\dev-local.ps1 -Test" -ForegroundColor White
    Write-Host ""

    
    # Clear conflicting Azure OpenAI environment variables to ensure .env file is used
    Write-Host "Clearing conflicting Azure OpenAI environment variables..." -ForegroundColor Yellow
    Remove-Item Env:AZURE_OPENAI_ENDPOINT -ErrorAction SilentlyContinue
    Remove-Item Env:AZURE_OPENAI_API_VERSION -ErrorAction SilentlyContinue
    Remove-Item Env:AZURE_OPENAI_DEPLOYMENT -ErrorAction SilentlyContinue
    Write-Host "✅ Environment cleared for .env file usage" -ForegroundColor Green
    
    # If building, do it before starting the backend so static files are mounted
    if ($Build) {
        if (-not (Build-Frontend)) {
            Write-Host "⚠️  Proceeding without built frontend due to build failure" -ForegroundColor Yellow
        }
    }

    Set-Location backend
    $venvPy = Join-Path $PWD "..\backend\.venv\Scripts\python.exe"
    if (-not (Test-Path $venvPy)) { $venvPy = 'python' }
    $env:TIMEZONE='America/Los_Angeles'
    $env:ALLOW_LOCAL_AUTH_BYPASS='true'
    $env:LOCAL_BYPASS_IS_ADMIN='true'
    $env:DISABLE_API_KEY_CHECK='true'
    $env:ALLOW_CLEAR_ALL='true'
    & $venvPy -m uvicorn main:app --reload --host 0.0.0.0 --port 8000
}
