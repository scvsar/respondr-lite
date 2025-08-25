param(
    [switch]$Function,
    [switch]$Docker,
    [switch]$Interactive,
    [int]$FunctionPort = 7071,
    [switch]$ForceKillOthers
)

if (-not ($Function -or $Docker -or $Interactive)) {
    $Function = $true
    $Docker   = $true
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


function Start-FunctionLocal {
    Write-Host "Ensuring port $FunctionPort is free for Azure Functions..." -ForegroundColor Cyan
    Test-PortFree -Port $FunctionPort -ForceKillOthers:$ForceKillOthers

    Write-Host "Starting Azure function locally..." -ForegroundColor Green
    Push-Location functions
    try { & func start } finally { Pop-Location }
}

function Start-FunctionNewWindow {
    Write-Host "Ensuring port $FunctionPort is free for Azure Functions..." -ForegroundColor Cyan
    Test-PortFree -Port $FunctionPort -ForceKillOthers:$ForceKillOthers

    Write-Host "Launching Azure function in a new shell window..." -ForegroundColor Green
    $funcPath = (Resolve-Path -Path ".\functions").Path

    if (Get-Command pwsh -ErrorAction SilentlyContinue) {
        $shellExe = "pwsh"
        $arg = "-NoExit -Command cd `"$funcPath`"; func start"
    } elseif (Get-Command powershell -ErrorAction SilentlyContinue) {
        $shellExe = "powershell"
        $arg = "-NoExit -Command cd `"$funcPath`"; func start"
    } else {
        Write-Host "No PowerShell found; starting in current session." -ForegroundColor Yellow
        Start-FunctionLocal
        return
    }

    Start-Process -FilePath $shellExe -ArgumentList $arg -WorkingDirectory $funcPath
}

function Start-DockerCompose {
    Write-Host "Starting backend/frontend stack in Docker Desktop (docker-compose.local.yml)..." -ForegroundColor Green
    & docker compose -f docker-compose.local.yml up --build
}

if ($Interactive) {
    Write-Host "SCVSAR Respondr Local Development" -ForegroundColor Cyan
    Write-Host "====================================="; Write-Host ""
    Write-Host "Options:" -ForegroundColor Yellow
    Write-Host "  1. Start Azure function locally"
    Write-Host "  2. Start backend/frontend stack (docker-compose.local.yml)"
    Write-Host "  3. Start both (function + docker)"
    $choice = Read-Host "Enter option (1, 2 or 3)"
    switch ($choice) {
        '1' { Start-FunctionLocal }
        '2' { Start-DockerCompose }
        '3' { Start-FunctionNewWindow; Start-DockerCompose }
        default { Write-Host "Invalid option. Enter 1, 2 or 3." -ForegroundColor Red }
    }
} else {
    if ($Function -and $Docker) {
        Start-FunctionNewWindow
        Start-DockerCompose
    } elseif ($Function) {
        Start-FunctionLocal
    } elseif ($Docker) {
        Start-DockerCompose
    } else {
        Write-Host "Nothing to do. Use -Function, -Docker, or -Interactive." -ForegroundColor Yellow
    }
}
