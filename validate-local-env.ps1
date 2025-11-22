$ErrorActionPreference = "Stop"

$backendUrl = "http://localhost:8000"
$functionsUrl = "http://localhost:7071"
$Global:TestResults = @()
$Context = [ordered]@{
    Session = $null
    TestRunId = (Get-Date -Format "yyyyMMddHHmmss")
    CreatedMessages = @()
    DeletedMessages = @()
    GroupmeTestId = $null
}

function Test-Success {
    param(
        [string]$Details = "",
        $Data = $null
    )
    return [pscustomobject]@{
        Success = $true
        Details = $Details
        Data = $Data
    }
}

function Test-Failure {
    param(
        [string]$Details,
        $Data = $null
    )
    return [pscustomobject]@{
        Success = $false
        Details = $Details
        Data = $Data
    }
}

function Add-TestResult {
    param(
        [string]$Category,
        [string]$Name,
        [bool]$Success,
        [string]$Details,
        $Data
    )

    $Global:TestResults += [pscustomobject]@{
        Category = $Category
        Name = $Name
        Success = $Success
        Details = $Details
        Data = $Data
    }

    $statusText = if ($Success) { "PASS" } else { "FAIL" }
    $color = if ($Success) { "Green" } else { "Red" }
    Write-Host "[$statusText] $Category :: $Name - $Details" -ForegroundColor $color
}

function Run-Test {
    param(
        [string]$Category,
        [string]$Name,
        [scriptblock]$Action
    )

    Write-Host "`n[Running] $Category :: $Name" -ForegroundColor Cyan
    try {
        $result = & $Action
        if (-not $result) {
            $result = Test-Success "Completed"
        }

        if ($result.Success) {
            Add-TestResult -Category $Category -Name $Name -Success $true -Details $result.Details -Data $result.Data
        } else {
            Add-TestResult -Category $Category -Name $Name -Success $false -Details $result.Details -Data $result.Data
        }
    } catch {
        Add-TestResult -Category $Category -Name $Name -Success $false -Details $_.Exception.Message -Data $null
    }
}

function Invoke-BackendApi {
    param(
        [string]$Path,
        [string]$Method = "GET",
        $Body = $null,
        [bool]$UseSession = $true
    )

    $uri = "$backendUrl$Path"
    $params = @{
        Uri = $uri
        Method = $Method
        ContentType = "application/json"
    }

    if ($Body) {
        $params.Body = ($Body | ConvertTo-Json -Depth 10)
    }

    if ($UseSession) {
        if (-not $Context.Session) {
            throw "Missing authenticated session"
        }
        $params.WebSession = $Context.Session
    }

    return Invoke-RestMethod @params
}

function Invoke-FunctionsApi {
    param(
        [string]$Path,
        [string]$Method = "GET",
        $Body = $null
    )

    $uri = "$functionsUrl$Path"
    $params = @{
        Uri = $uri
        Method = $Method
        ContentType = "application/json"
    }

    if ($Body) {
        $params.Body = ($Body | ConvertTo-Json -Depth 10)
    }

    return Invoke-RestMethod @params
}

Write-Host "Waiting for backend to be healthy..." -ForegroundColor Cyan
$retries = 0
while ($retries -lt 30) {
    try {
        $health = Invoke-RestMethod -Uri "$backendUrl/health" -ErrorAction Stop
        if ($health.status -eq "healthy") {
            Write-Host "Backend is healthy!" -ForegroundColor Green
            break
        }
    } catch {
        Start-Sleep -Seconds 1
        $retries++
        Write-Host "." -NoNewline
    }
}

if ($retries -ge 30) {
    Write-Error "Backend failed to become healthy."
    exit 1
}

Write-Host "Creating/ensuring test user (via Docker)..." -ForegroundColor Cyan
docker exec respondr-backend python create_local_user.py testuser test@example.com "Test User" --password "TestPass123!" --admin | Out-Host

$global:loginBody = @{
    username = "testuser"
    password = "TestPass123!"
}

Run-Test -Category "Environment" -Name "Backend Health" -Action {
    $resp = Invoke-RestMethod -Uri "$backendUrl/health"
    if ($resp.status -ne "healthy") {
        return Test-Failure "Health endpoint returned '$($resp.status)'"
    }
    Test-Success "Status: healthy"
}

Run-Test -Category "Auth" -Name "Backend Local Login" -Action {
    $loginParams = @{
        Uri = "$backendUrl/api/auth/local/login"
        Method = "POST"
        ContentType = "application/json"
        Body = ($global:loginBody | ConvertTo-Json)
        SessionVariable = "session"
    }

    $loginRes = Invoke-WebRequest @loginParams
    $Context.Session = $session
    $setCookie = $loginRes.Headers["Set-Cookie"]
    Test-Success "Session cookie acquired" $setCookie
}

Run-Test -Category "Auth" -Name "Current Session User" -Action {
    $resp = Invoke-BackendApi -Path "/api/auth/local/me"
    if (-not $resp.authenticated) {
        return Test-Failure "Server reports not authenticated"
    }
    Test-Success "Authenticated as $($resp.username)"
}

Run-Test -Category "Auth" -Name "Local Auth Enabled" -Action {
    $resp = Invoke-BackendApi -Path "/api/auth/local/enabled"
    if (-not $resp.enabled) {
        return Test-Failure "Endpoint returned disabled"
    }
    Test-Success "Local auth enabled"
}

Run-Test -Category "Azure Functions" -Name "Local Login Function" -Action {
    $body = @{
        email = "test@example.com"
        password = "TestPass123!"
    }
    $resp = Invoke-FunctionsApi -Path "/api/local_login" -Method "POST" -Body $body
    if (-not $resp.token) {
        return Test-Failure "No JWT returned"
    }
    Test-Success "Token issued" ($resp.token.Substring(0, 16) + "...")
}

Run-Test -Category "Azure Functions" -Name "GroupMe Ingest Function" -Action {
    $Context.GroupmeTestId = "gm-$($Context.TestRunId)-$([Guid]::NewGuid().ToString('N').Substring(0,6))"
    $payload = @{
        id = $Context.GroupmeTestId
        source_guid = [Guid]::NewGuid().ToString()
        created_at = [int][double]::Parse((Get-Date -UFormat %s))
        user_id = "test-user-1"
        sender_id = "test-user-1"
        sender_type = "user"
        group_id = "109174633"
        name = "Test Responder"
        text = "Responding to base ETA 10m ($($Context.GroupmeTestId))"
        system = $false
        favorited_by = @()
        attachments = @()
    }

    $resp = Invoke-FunctionsApi -Path "/api/groupme_ingest" -Method "POST" -Body $payload
    Test-Success "Accepted message $($Context.GroupmeTestId)" $resp
}

Run-Test -Category "Azure Functions" -Name "Ingest Propagation" -Action {
    Start-Sleep -Seconds 5
    $status = Invoke-BackendApi -Path "/api/current-status"
    $match = $status | Where-Object { $_.text -match $Context.GroupmeTestId }
    if (-not $match) {
        return Test-Failure "Current status missing $($Context.GroupmeTestId)"
    }
    Test-Success "Current status contains ingest message"
}

Run-Test -Category "Responders" -Name "Create responder" -Action {
    $payload = @{
        name = "Live Tester"
        text = "Manual entry from live suite $($Context.TestRunId)"
        vehicle = "Unit 42"
        eta = "30 min"
        eta_timestamp = (Get-Date).AddMinutes(30).ToString("o")
        status = "Responding"
        group_id = "manual"
    }
    $resp = Invoke-BackendApi -Path "/api/responders" -Method "POST" -Body $payload
    $msgId = $resp.message.id
    $Context.CreatedMessages += $msgId
    Test-Success "Created responder $msgId" $msgId
}

Run-Test -Category "Responders" -Name "Update responder" -Action {
    $msgId = $Context.CreatedMessages[-1]
    $payload = @{ arrival_status = "Available"; vehicle = "SUV 7" }
    $resp = Invoke-BackendApi -Path "/api/responders/$msgId" -Method "PUT" -Body $payload
    if ($resp.status -ne "updated") {
        return Test-Failure "Unexpected response"
    }
    Test-Success "Updated $msgId"
}

Run-Test -Category "Responders" -Name "List responders" -Action {
    $resp = Invoke-BackendApi -Path "/api/responders"
    $msgId = $Context.CreatedMessages[-1]
    $match = $resp | Where-Object { $_.id -eq $msgId }
    if (-not $match) {
        return Test-Failure "Manual responder missing from list"
    }
    Test-Success "Responder present"
}

Run-Test -Category "Responders" -Name "Delete responder" -Action {
    $msgId = $Context.CreatedMessages[-1]
    Invoke-BackendApi -Path "/api/responders/$msgId" -Method "DELETE" | Out-Null
    $Context.DeletedMessages += $msgId
    Test-Success "Deleted $msgId"
}

Run-Test -Category "Responders" -Name "Deleted responders list" -Action {
    $resp = Invoke-BackendApi -Path "/api/deleted-responders"
    $msgId = $Context.DeletedMessages[-1]
    $match = $resp | Where-Object { $_.id -eq $msgId }
    if (-not $match) {
        return Test-Failure "Deleted list missing $msgId"
    }
    Test-Success "Deleted responder visible"
}

Run-Test -Category "Responders" -Name "Undelete responder" -Action {
    $msgId = $Context.DeletedMessages[-1]
    $payload = @{ message_id = $msgId }
    $resp = Invoke-BackendApi -Path "/api/deleted-responders/undelete" -Method "POST" -Body $payload
    if ($resp.status -ne "restored") {
        return Test-Failure "Undelete failed"
    }
    Test-Success "Restored $msgId"
}

Run-Test -Category "Responders" -Name "Bulk delete responders" -Action {
    $ids = @()
    for ($i = 0; $i -lt 2; $i++) {
        $payload = @{
            name = "Bulk Tester $i"
            text = "Bulk delete entry $i ($($Context.TestRunId))"
            vehicle = "Rig $i"
            eta = "15 min"
            eta_timestamp = (Get-Date).AddMinutes(15).ToString("o")
            status = "Responding"
            group_id = "manual"
        }
        $resp = Invoke-BackendApi -Path "/api/responders" -Method "POST" -Body $payload
        $ids += $resp.message.id
    }

    $body = @{ ids = $ids }
    $respDelete = Invoke-BackendApi -Path "/api/responders/bulk-delete" -Method "POST" -Body $body
    if ($respDelete.count -lt $ids.Count) {
        return Test-Failure "Bulk delete removed $($respDelete.count) of $($ids.Count)"
    }
    $Context.DeletedMessages += $ids
    Test-Success "Bulk deleted $($ids.Count) responders"
}

Run-Test -Category "Admin" -Name "Group config" -Action {
    $resp = Invoke-BackendApi -Path "/api/config/groups"
    if (-not $resp.groups) {
        return Test-Failure "No groups returned"
    }
    Test-Success "$($resp.groups.Count) groups returned"
}

Run-Test -Category "Admin" -Name "Default prompts" -Action {
    $sample = [uri]::EscapeDataString("Testing live prompts")
    $resp = Invoke-BackendApi -Path "/api/debug/default-prompts?text=$sample"
    if (-not $resp.sys_prompt) {
        return Test-Failure "No prompts returned"
    }
    Test-Success "Prompts generated"
}

Write-Host "`n===== Live Test Summary =====" -ForegroundColor Cyan
$TestResults | Sort-Object Category, Name | Format-Table Category, Name, Success, Details | Out-String | Write-Host

$failed = $TestResults | Where-Object { -not $_.Success }
if ($failed) {
    Write-Host "`nOne or more tests failed." -ForegroundColor Red
    exit 1
} else {
    Write-Host "`nAll live tests passed." -ForegroundColor Green
    exit 0
}
