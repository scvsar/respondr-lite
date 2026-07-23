#!/usr/bin/env pwsh

$ErrorActionPreference = "Stop"

$repoRoot = Split-Path -Parent $PSScriptRoot

function Get-RepoPath {
    param([string]$RelativePath)

    Join-Path $repoRoot $RelativePath
}

function Assert-True {
    param(
        [bool]$Condition,
        [string]$Message
    )

    if (-not $Condition) {
        throw $Message
    }
}

function Get-RelativeFileMap {
    param([string]$Root)

    $resolvedRoot = (Resolve-Path -LiteralPath $Root).Path
    $map = @{}
    Get-ChildItem -LiteralPath $resolvedRoot -Recurse -File | ForEach-Object {
        $relativePath = $_.FullName.Substring($resolvedRoot.Length + 1)
        $map[$relativePath] = $_.FullName
    }
    $map
}

function Assert-SameSet {
    param(
        [string[]]$Expected,
        [string[]]$Actual,
        [string]$Label
    )

    $difference = Compare-Object ($Expected | Sort-Object) ($Actual | Sort-Object)
    if ($difference) {
        $details = $difference | ForEach-Object {
            "$($_.SideIndicator) $($_.InputObject)"
        }
        throw "$Label differs:`n$($details -join "`n")"
    }
}

$requiredFiles = @(
    "AGENTS.md",
    "CLAUDE.md",
    ".mcp.json",
    ".codex/config.toml",
    ".codex/hooks.json",
    ".claude/settings.json",
    ".github/copilot-instructions.md",
    ".github/hooks/copilot-policy.json"
)

foreach ($relativePath in $requiredFiles) {
    Assert-True (Test-Path -LiteralPath (Get-RepoPath $relativePath) -PathType Leaf) `
        "Missing required agent artifact: $relativePath"
}

$claudeInstructions = Get-Content -LiteralPath (Get-RepoPath "CLAUDE.md") -Raw
Assert-True ($claudeInstructions -match '(?m)^@AGENTS\.md\s*$') `
    "CLAUDE.md must import AGENTS.md."

$copilotInstructions = Get-Content `
    -LiteralPath (Get-RepoPath ".github/copilot-instructions.md") -Raw
Assert-True ($copilotInstructions -match '(?m)^@\.\./AGENTS\.md\s*$') `
    "Copilot instructions must import AGENTS.md."

$jsonFiles = @(
    ".mcp.json",
    ".codex/hooks.json",
    ".claude/settings.json",
    ".github/hooks/copilot-policy.json"
)

foreach ($relativePath in $jsonFiles) {
    Get-Content -LiteralPath (Get-RepoPath $relativePath) -Raw |
        ConvertFrom-Json -Depth 100 |
        Out-Null
}

$mcpConfig = Get-Content -LiteralPath (Get-RepoPath ".mcp.json") -Raw |
    ConvertFrom-Json -Depth 100
Assert-True ($null -ne $mcpConfig.mcpServers) `
    ".mcp.json must use the shared mcpServers schema."
Assert-True ($null -ne $mcpConfig.mcpServers."microsoft-learn") `
    ".mcp.json must configure microsoft-learn."
Assert-True ($null -ne $mcpConfig.mcpServers.playwright) `
    ".mcp.json must configure playwright."

$canonicalSkillRoot = Get-RepoPath ".agents/skills"
$claudeSkillRoot = Get-RepoPath ".claude/skills"
$canonicalFiles = Get-RelativeFileMap $canonicalSkillRoot
$claudeFiles = Get-RelativeFileMap $claudeSkillRoot

Assert-SameSet @($canonicalFiles.Keys) @($claudeFiles.Keys) "Claude skill mirror"

foreach ($relativePath in $canonicalFiles.Keys) {
    $sourceHash = (Get-FileHash -LiteralPath $canonicalFiles[$relativePath]).Hash
    $mirrorHash = (Get-FileHash -LiteralPath $claudeFiles[$relativePath]).Hash
    Assert-True ($sourceHash -eq $mirrorHash) `
        "Claude skill mirror differs: $relativePath"
}

$skillDirectories = Get-ChildItem -LiteralPath $canonicalSkillRoot -Directory
foreach ($skillDirectory in $skillDirectories) {
    $skillFile = Join-Path $skillDirectory.FullName "SKILL.md"
    Assert-True (Test-Path -LiteralPath $skillFile -PathType Leaf) `
        "Missing SKILL.md: $($skillDirectory.Name)"

    $nameLine = Get-Content -LiteralPath $skillFile |
        Select-String -Pattern '^name:\s*(.+?)\s*$' |
        Select-Object -First 1
    Assert-True ($null -ne $nameLine) `
        "Missing skill name: $($skillDirectory.Name)"
    Assert-True ($nameLine.Matches[0].Groups[1].Value -eq $skillDirectory.Name) `
        "Skill name does not match its folder: $($skillDirectory.Name)"
}

$githubSkillFiles = @()
$githubSkillRoot = Get-RepoPath ".github/skills"
if (Test-Path -LiteralPath $githubSkillRoot) {
    $githubSkillFiles = @(
        Get-ChildItem -LiteralPath $githubSkillRoot -Recurse -File
    )
}
Assert-True ($githubSkillFiles.Count -eq 0) `
    "Do not duplicate shared skills under .github/skills."

$codexAgents = Get-ChildItem -LiteralPath (Get-RepoPath ".codex/agents") `
    -Filter "*.toml" -File |
    ForEach-Object { $_.BaseName }
$claudeAgents = Get-ChildItem -LiteralPath (Get-RepoPath ".claude/agents") `
    -Filter "*.md" -File |
    ForEach-Object { $_.BaseName }
$copilotAgents = Get-ChildItem -LiteralPath (Get-RepoPath ".github/agents") `
    -Filter "*.agent.md" -File |
    ForEach-Object { $_.Name -replace '\.agent\.md$', '' }

Assert-SameSet @($codexAgents) @($claudeAgents) "Claude agent set"
Assert-SameSet @($codexAgents) @($copilotAgents) "Copilot agent set"

Write-Host "Agent artifact validation passed."
Write-Host "Shared skills: $($skillDirectories.Count)"
Write-Host "Specialist agents: $($codexAgents.Count)"
