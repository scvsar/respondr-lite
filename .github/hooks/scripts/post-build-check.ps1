# Post-tool hook scaffold for optional diagnostics.

param(
    [string]$Command = $env:COPILOT_TOOL_INPUT
)

if (-not $Command) {
    exit 0
}

if ($env:RESPONDR_HOOK_VERBOSE -eq "1") {
    Write-Host "post-build-check observed command: $Command"
}

exit 0
