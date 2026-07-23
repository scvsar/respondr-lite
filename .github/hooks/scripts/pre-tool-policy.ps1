# Shared pre-tool policy hook for Claude Code, Codex, and Copilot.

param(
    [string]$File = $env:COPILOT_FILE
)

function Stop-PolicyViolation {
    param([string]$Message)

    Write-Error "POLICY VIOLATION: $Message"
    if ($env:CLAUDE_PROJECT_DIR) {
        exit 2
    }
    exit 1
}

$hookInput = $null
if ([string]::IsNullOrWhiteSpace($File) -and [Console]::IsInputRedirected) {
    $rawInput = [Console]::In.ReadToEnd()
    if (-not [string]::IsNullOrWhiteSpace($rawInput)) {
        try {
            $hookInput = $rawInput | ConvertFrom-Json -Depth 100
            $File = $hookInput.tool_input.file_path
            if ([string]::IsNullOrWhiteSpace($File)) {
                $File = $hookInput.tool_input.path
            }
        }
        catch {
            exit 0
        }
    }
}

$resolved = $null
if (-not [string]::IsNullOrWhiteSpace($File)) {
    if (Test-Path -LiteralPath $File) {
        $resolved = (Resolve-Path -LiteralPath $File).Path
    }
    else {
        $basePath = if ($env:CLAUDE_PROJECT_DIR) {
            $env:CLAUDE_PROJECT_DIR
        }
        else {
            (Get-Location).Path
        }
        $resolved = [System.IO.Path]::GetFullPath($File, $basePath)
    }
}

if ($resolved) {
    $leaf = Split-Path -Leaf $resolved
    if ($leaf -match '^\.env(\.|$)' -and $leaf -notmatch '(?i)(sample|example|template)') {
        Stop-PolicyViolation "Do not edit a local secret file through an agent workflow: $File"
    }
}

$contentParts = [System.Collections.Generic.List[string]]::new()
if ($resolved -and (Test-Path -LiteralPath $resolved -PathType Leaf)) {
    $existingContent = Get-Content -LiteralPath $resolved -Raw -ErrorAction SilentlyContinue
    if ($existingContent) {
        $contentParts.Add($existingContent)
    }
}

if ($hookInput) {
    foreach ($property in @("content", "new_string", "patch", "input")) {
        $value = $hookInput.tool_input.$property
        if ($value -is [string] -and -not [string]::IsNullOrWhiteSpace($value)) {
            $contentParts.Add($value)
        }
    }
}

$content = $contentParts -join "`n"
$strongSecretPatterns = @(
    '-----BEGIN (RSA |EC |OPENSSH )?PRIVATE KEY-----',
    '(?i)AccountKey=[A-Za-z0-9+/]{20,}={0,2}',
    '(?i)(client_secret|jwt_secret_key|local_auth_secret_key)\s*[:=]\s*["''][^"'']{12,}["'']',
    '(?i)(api[_-]?key|access[_-]?token)\s*[:=]\s*["''][A-Za-z0-9_\-+/]{24,}={0,2}["'']'
)

foreach ($pattern in $strongSecretPatterns) {
    if ($content -match $pattern) {
        Stop-PolicyViolation "Potential hardcoded secret detected. Use a managed secret source."
    }
}

exit 0
