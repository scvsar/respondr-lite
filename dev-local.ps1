param(
    [switch]$Function,
    [switch]$Backend,
    [switch]$Frontend,
    [switch]$Interactive,
    [int]$FunctionPort = 7071,
    [switch]$ForceKillOthers,
    [switch]$Offline
)

# Default behavior if no switches provided: Start everything
if (-not ($Function -or $Backend -or $Frontend -or $Interactive)) {
    $Function = $true
    $Backend  = $true
    $Frontend = $true
}

function Get-PortOwnerPids {
    param([int]$Port)
    try {
        $conns = Get-NetTCPConnection -LocalPort $Port -ErrorAction Stop
        ($conns | Where-Object State -in @('Listen','Established','Bound','SynReceived','SynSent','TimeWait')).
            OwningProcess | Where-Object { $_ -gt 0 } | Sort-Object -Unique
    } catch {
        # Fallback if Get-NetTCPConnection isn't available/privileged
        netstat -ano | Select-String "[: ]$Port\s" | ForEach-Object {
            if ($_ -match '\s+(\d+)$') { [int]$Matches[1] }
        } | Sort-Object -Unique
    }
}

function Get-ProcessNameByPid {
    param([int]$PidToCheck)
    try { (Get-Process -Id $PidToCheck -ErrorAction Stop).ProcessName } catch { $null }
}

function Stop-Pids {
    param([int[]]$Pids)
    foreach ($pidToKill in $Pids) {
        try {
            $name = Get-ProcessNameByPid -PidToCheck $pidToKill
            Write-Host "Stopping PID $pidToKill ($name)..." -ForegroundColor Yellow
            Stop-Process -Id $pidToKill -Force -ErrorAction Stop
        } catch {
            & taskkill /PID $pidToKill /F | Out-Null
        }
    }
}

function Test-PortFree {
    param(
        [int]$Port,
        [switch]$ForceKillOthers
    )
    $pids = Get-PortOwnerPids -Port $Port
    if (-not $pids) { return }

    $procInfo = foreach ($p in $pids) {
        [pscustomobject]@{ 'Pid' = $p; 'Name' = (Get-ProcessNameByPid -PidToCheck $p) }
    }

    $nonFunc = $procInfo | Where-Object { $_.Name -ne 'func' }
    $func    = $procInfo | Where-Object { $_.Name -eq 'func' }

    if ($nonFunc -and -not $ForceKillOthers) {
        Write-Host "Port $Port is in use by:" -ForegroundColor Red
        $procInfo | Format-Table -AutoSize | Out-Host
        throw "Refusing to kill non-func processes on port $Port. Re-run with -ForceKillOthers to override."
    }

    $toKill = if ($ForceKillOthers) { $procInfo } else { $func }
    if ($toKill) {
        $toKill | Format-Table -AutoSize | Out-Host
        Stop-Pids -Pids ($toKill.Pid)
    }

    # Wait briefly for OS to release the port (TIME_WAIT, etc.)
    $deadline = (Get-Date).AddSeconds(10)
    while ((Get-PortOwnerPids -Port $Port) -and (Get-Date) -lt $deadline) {
        Start-Sleep -Milliseconds 200
    }

    if (Get-PortOwnerPids -Port $Port) {
        throw "Port $Port is still in use after attempts to free it."
    }
}

function Start-NewWindow {
    param(
        [string]$Command,
        [string]$WorkingDirectory,
        [string]$Title
    )
    
    if (Get-Command pwsh -ErrorAction SilentlyContinue) {
        $shellExe = "pwsh"
        $arg = "-NoExit -Command cd `"$WorkingDirectory`"; $Command"
    } elseif (Get-Command powershell -ErrorAction SilentlyContinue) {
        $shellExe = "powershell"
        $arg = "-NoExit -Command cd `"$WorkingDirectory`"; $Command"
    } else {
        Write-Error 'PowerShell not found to launch new window.'
        return
    }

    Write-Host "Launching $Title in a new window..." -ForegroundColor Green
    Start-Process -FilePath $shellExe -ArgumentList $arg -WorkingDirectory $WorkingDirectory
}

function Start-FunctionLocal {
    Write-Host "Ensuring port $FunctionPort is free for Azure Functions..." -ForegroundColor Cyan
    Test-PortFree -Port $FunctionPort -ForceKillOthers:$ForceKillOthers

    $funcPath = (Resolve-Path -Path ".\functions").Path
    Start-NewWindow -Command "func start" -WorkingDirectory $funcPath -Title "Azure Functions"
}

function Start-BackendDocker {
    Write-Host "Starting Backend API in Docker..." -ForegroundColor Green
    $cwd = (Get-Location).Path
    
    $cmd = "docker compose -f docker-compose.local.yml up --build"
    if ($Offline) {
        Write-Host "Offline mode enabled: Mocking LLM." -ForegroundColor Yellow
        $cmd = "`$env:ENABLE_LLM_MOCK='true'; " + $cmd
    }
    
    Start-NewWindow -Command $cmd -WorkingDirectory $cwd -Title "Backend API (Docker)"
}

function Start-FrontendLocal {
    Write-Host "Starting Frontend (React)..." -ForegroundColor Green
    $frontendPath = (Resolve-Path -Path ".\frontend").Path
    
    if (-not (Test-Path "$frontendPath\node_modules")) {
        Write-Host "Installing frontend dependencies..." -ForegroundColor Yellow
        Push-Location $frontendPath
        npm install
        Pop-Location
    }

    Start-NewWindow -Command "npm start" -WorkingDirectory $frontendPath -Title "Frontend (React)"
}

if ($Interactive) {
    Write-Host "SCVSAR Respondr Local Development" -ForegroundColor Cyan
    Write-Host "====================================="; Write-Host ""
    Write-Host "Options:" -ForegroundColor Yellow
    Write-Host "  1. Start Azure Functions (Ingest)"
    Write-Host "  2. Start Backend API (Docker)"
    Write-Host "  3. Start Frontend (React)"
    Write-Host "  4. Start All Components"
    
    $choice = Read-Host "Enter option (1-4)"
    switch ($choice) {
        '1' { Start-FunctionLocal }
        '2' { Start-BackendDocker }
        '3' { Start-FrontendLocal }
        '4' { 
            Start-FunctionLocal
            Start-FrontendLocal
            Start-BackendDocker
        }
        default { Write-Host "Invalid option." -ForegroundColor Red }
    }
} else {
    if ($Function) { Start-FunctionLocal }
    if ($Frontend) { Start-FrontendLocal }
    if ($Backend) { Start-BackendDocker }
}
