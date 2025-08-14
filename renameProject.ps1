# Requires: PowerShell 7+
[CmdletBinding(SupportsShouldProcess)]
param(
    [Parameter(Mandatory = $true)]
    [string]$NewName,
    
    [Parameter()]
    [string]$OldName,
    
    [Parameter()]
    [string[]]$IncludePaths,
    
    [Parameter()]
    [string[]]$AdditionalTokens,
    
    [Parameter()]
    [string[]]$ExcludePaths,
    
    [Parameter()]
    [string[]]$ExcludeExtensions,
    
    [Parameter()]
    [string[]]$IncludeExtensions,
    
    [Parameter()]
    [switch]$DryRun,
    
    [Parameter()]
    [switch]$UseGit,
    
    [Parameter()]
    [switch]$RenameRootDirectory
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

# Initialize default values for optional parameters
if (-not $OldName) { $OldName = "" }
if (-not $IncludePaths) { $IncludePaths = @() }
if (-not $AdditionalTokens) { $AdditionalTokens = @() }
if (-not $ExcludePaths) { $ExcludePaths = @() }
if (-not $ExcludeExtensions) { $ExcludeExtensions = @() }
if (-not $IncludeExtensions) { $IncludeExtensions = @() }

# Validate required parameter
if ([string]::IsNullOrWhiteSpace($NewName)) {
    throw "NewName parameter cannot be null or empty."
}

function Write-Info {
    param([string]$Message)
    Write-Host "[INFO] $Message" -ForegroundColor Cyan
}

function Write-Change {
    param([string]$Message)
    Write-Host "[CHANGE] $Message" -ForegroundColor Green
}

function Write-Skip {
    param([string]$Message)
    Write-Host "[SKIP] $Message" -ForegroundColor DarkYellow
}

function Write-Warn {
    param([string]$Message)
    Write-Warning $Message
}

function Resolve-Root {
    # Resolve repo root to the directory containing this script
    try {
        $scriptRoot = Split-Path -LiteralPath $PSCommandPath -Parent
    } catch {
        $scriptRoot = Get-Location
    }
    return (Resolve-Path -LiteralPath $scriptRoot).Path
}

function Test-GitAvailable {
    try {
        $null = git --version 2>$null
        return $LASTEXITCODE -eq 0
    } catch { return $false }
}

function Get-CaseMap {
    param([string]$Old,[string]$New,[string[]]$AlsoTokens)

    $map = [ordered]@{}
    function title([string]$s){ if([string]::IsNullOrWhiteSpace($s)){return $s}; return $s.Substring(0,1).ToUpper() + $s.Substring(1).ToLower() }

    # core name variants
    $variants = @($Old)
    if ($AlsoTokens) { $variants += $AlsoTokens }

    foreach ($token in $variants | Sort-Object -Unique) {
        $lower = $token.ToLower()
        $upper = $token.ToUpper()
        $title = title $token

        $newLower = $New.ToLower()
        $newUpper = $New.ToUpper()
        $newTitle = title $New

        if (-not $map.Contains($lower)) { $map[$lower] = $newLower }
        if (-not $map.Contains($upper)) { $map[$upper] = $newUpper }
        if (-not $map.Contains($title)) { $map[$title] = $newTitle }
    }
    return $map
}

function Test-BinaryFile {
    param([string]$Path,[string[]]$BinaryExtensions)
    $ext = [IO.Path]::GetExtension($Path)
    if ($BinaryExtensions -contains $ext.ToLower()) { return $true }
    try {
        $fs = [System.IO.File]::Open($Path, [System.IO.FileMode]::Open, [System.IO.FileAccess]::Read, [System.IO.FileShare]::ReadWrite)
        try {
            $len = [Math]::Min(8192, $fs.Length)
            $bytes = New-Object byte[] $len
            $null = $fs.Read($bytes, 0, $len)
            # Heuristic: null byte indicates likely binary
            if ($bytes -contains 0) { return $true }
            return $false
        } finally { $fs.Dispose() }
    } catch { return $true }
}

function Replace-In-Content {
    param([string]$File,[hashtable]$CaseMap)
    try {
        $original = Get-Content -LiteralPath $File -Raw -ErrorAction Stop
    } catch {
        Write-Skip "Unable to read file (skipping): $File ($_)."
        return $false
    }

    $updated = $original
    $order = $CaseMap.Keys | Sort-Object { $_.Length } -Descending
    foreach ($old in $order) {
        $new = $CaseMap[$old]
        # case-sensitive replacement for explicit variants
        $updated = $updated.Replace($old, $new)
    }

    if ($updated -ne $original) {
        if ($DryRun) {
            Write-Change "Would update contents: $File"
            return $true
        }
    Set-Content -LiteralPath $File -Value $updated -Encoding utf8NoBOM
        Write-Change "Updated contents: $File"
        return $true
    }
    return $false
}

function Apply-Name-Replacements {
    param([string]$Name,[hashtable]$CaseMap)
    $result = $Name
    $order = $CaseMap.Keys | Sort-Object { $_.Length } -Descending
    foreach ($old in $order) {
        $new = $CaseMap[$old]
        $result = $result.Replace($old, $new)
    }
    return $result
}

function Rename-PathIfNeeded {
    param([string]$Path,[hashtable]$CaseMap,[bool]$PreferGit,$Root)
    $parent = [System.IO.Path]::GetDirectoryName($Path)
    $leaf   = [System.IO.Path]::GetFileName($Path)
    $newLeaf = Apply-Name-Replacements -Name $leaf -CaseMap $CaseMap
    if ($newLeaf -eq $leaf) { return $Path }
    $newPath = Join-Path -Path $parent -ChildPath $newLeaf
    if ($DryRun) {
        Write-Change "Would rename: $Path -> $newPath"
        return $newPath
    }
    if ($PSCmdlet.ShouldProcess($Path, "Rename to $newPath")) {
        if ($PreferGit -and (Test-Path -LiteralPath (Join-Path $Root '.git'))) {
            if (Test-GitAvailable) {
                & git mv -- "$Path" "$newPath" | Out-Null
            } else {
                Rename-Item -LiteralPath $Path -NewName $newLeaf -Force
            }
        } else {
            Rename-Item -LiteralPath $Path -NewName $newLeaf -Force
        }
        Write-Change "Renamed: $Path -> $newPath"
    }
    return $newPath
}

function Should-ExcludePath {
    param([string]$FullPath,[regex[]]$ExcludeRegexes)
    foreach ($rx in $ExcludeRegexes) {
        if ($rx.IsMatch($FullPath)) { return $true }
    }
    return $false
}

# --- Main ---
try {
    $root = Resolve-Root
    Set-Location -LiteralPath $root

    if (-not $OldName -or [string]::IsNullOrWhiteSpace($OldName)) {
        $OldName = Split-Path -Leaf $root
    }

    if ($OldName -ieq $NewName) {
        throw "OldName and NewName are the same. Nothing to do."
    }

    Write-Info "Root: $root"
    Write-Info "OldName: $OldName"
    Write-Info "NewName: $NewName"
    Write-Info "DryRun: $($DryRun.IsPresent)"

# Default excludes
$defaultExcludeDirs = @(
    '.git', '.svn', '.hg', '.idea', '.vscode',
    'node_modules', 'dist', 'build', 'out', 'coverage',
    '.venv', 'venv', '__pycache__', '.pytest_cache', '.mypy_cache', '.ruff_cache', '.tox', '.eggs',
    '.parcel-cache', '.turbo', '.next', '.pnpm-store', '.azure', '.terraform'
)

# Merge user excludes (dir or substring). Convert to regex that matches any segment.
$excludePatterns = @()
foreach ($d in $defaultExcludeDirs + $ExcludePaths) {
    if ([string]::IsNullOrWhiteSpace($d)) { continue }
    $escaped = [regex]::Escape($d.Trim())
    # match /d/ or \d\ at any depth
    $excludePatterns += "(^|[\\/])$escaped([\\/]|$)"
}
$excludeRegexes = $excludePatterns | ForEach-Object { [regex]$_ }

# Binary extensions
$binaryExtDefault = @(
    '.png','.jpg','.jpeg','.gif','.bmp','.ico','.webp','.svgz',
    '.pdf','.zip','.gz','.7z','.rar','.tar','.tgz','.xz','.lz',
    '.mp3','.mp4','.mov','.avi','.wav','.flac','.ogg','.webm',
    '.pyd','.pyc','.pyo','.so','.dll','.dylib','.exe','.bin','.class','.jar',
    '.ttf','.otf','.woff','.woff2','.eot',
    '.sln','.snk'
)

if ($ExcludeExtensions) {
    $ExcludeExtensions = $ExcludeExtensions | ForEach-Object { if($_ -and $_[0] -ne '.') {'.'+$_} else {$_} } | Select-Object -Unique
}

$BinaryExtensions = ($binaryExtDefault + $ExcludeExtensions) | Select-Object -Unique

# Case map for replacements
$caseMap = Get-CaseMap -Old $OldName -New $NewName -AlsoTokens $AdditionalTokens

# Resolve include roots
$includeRoots = @()
if (-not $IncludePaths -or $IncludePaths.Count -eq 0) {
    $IncludePaths = @(".")
}
foreach ($p in $IncludePaths) {
    $rp = Resolve-Path -LiteralPath $p -ErrorAction SilentlyContinue
    if ($rp) { $includeRoots += $rp.Path } else { Write-Warn "Include path not found: $p" }
}
if (-not $includeRoots) { $includeRoots = @($root) }

$preferGit = $UseGit.IsPresent
if (-not $UseGit.IsPresent) { $preferGit = Test-Path -LiteralPath (Join-Path $root '.git') }

# 1) Rename directories/files whose names contain tokens (deepest-first)
$renameTargets = @()
foreach ($r in $includeRoots) {
    $dirs = Get-ChildItem -LiteralPath $r -Recurse -Force -Directory | Where-Object { -not (Should-ExcludePath -FullPath $_.FullName -ExcludeRegexes $excludeRegexes) }
    $files = Get-ChildItem -LiteralPath $r -Recurse -Force -File | Where-Object { -not (Should-ExcludePath -FullPath $_.FullName -ExcludeRegexes $excludeRegexes) }
    $renameTargets += @($dirs) + @($files)
}

function Contains-AnyToken {
    param([string]$Name,[hashtable]$CaseMap)
    foreach ($k in $CaseMap.Keys) { if ($Name -like "*${k}*") { return $true } }
    return $false
}

# sort by depth (deepest first) to avoid path conflicts
$renameTargets = $renameTargets | Where-Object { Contains-AnyToken -Name $_.Name -CaseMap $caseMap } |
    Sort-Object { ($_.FullName -split '[\\/]').Count } -Descending

$renamedCount = 0
foreach ($it in $renameTargets) {
    $newPath = Rename-PathIfNeeded -Path $it.FullName -CaseMap $caseMap -PreferGit:$preferGit -Root $root
    if ($newPath -ne $it.FullName) { $renamedCount++ }
}

# Optionally rename root folder last
if ($RenameRootDirectory) {
    $rootLeaf = Split-Path -Leaf $root
    $newRootLeaf = Apply-Name-Replacements -Name $rootLeaf -CaseMap $caseMap
    if ($newRootLeaf -ne $rootLeaf) {
        $parent = Split-Path -LiteralPath $root
        $newRootPath = Join-Path $parent $newRootLeaf
        if ($DryRun) {
            Write-Change "Would rename root directory: $root -> $newRootPath"
        } else {
            if ($preferGit -and (Test-Path -LiteralPath (Join-Path $root '.git'))) {
                Write-Warn "Skipping git-based root rename automatically. Rename the repository folder manually: '$root' -> '$newRootPath'"
            } else {
                Rename-Item -LiteralPath $root -NewName $newRootLeaf -Force
                Write-Change "Renamed root directory: $root -> $newRootPath"
            }
        }
    }
}

# 2) Replace text in files
$contentChanged = 0
$filesProcessed = 0
foreach ($r in $includeRoots) {
    $files = Get-ChildItem -LiteralPath $r -Recurse -File -Force | Where-Object { -not (Should-ExcludePath -FullPath $_.FullName -ExcludeRegexes $excludeRegexes) }
    foreach ($f in $files) {
        # filter extensions
        $ext = [IO.Path]::GetExtension($f.Name).ToLower()
        if ($IncludeExtensions -and ($IncludeExtensions | ForEach-Object { if($_ -and $_[0] -ne '.') {'.'+$_} else {$_} } | Where-Object { $_ -eq $ext } | Measure-Object).Count -eq 0) { continue }
        if (Test-BinaryFile -Path $f.FullName -BinaryExtensions $BinaryExtensions) { continue }
        $filesProcessed++
        if (Replace-In-Content -File $f.FullName -CaseMap $caseMap) { $contentChanged++ }
    }
}

Write-Host "" 
Write-Info "Summary:"
Write-Host "  Renamed items: $renamedCount"
Write-Host "  Files processed for content: $filesProcessed"
Write-Host "  Files changed for content: $contentChanged"

    if ($DryRun) {
        Write-Info "Dry run complete. Re-run without -DryRun to apply changes."
    } else {
        Write-Info "Done. Review changes and run your deployment scripts."
    }
} catch {
    Write-Host "ERROR: $($_.Exception.Message)" -ForegroundColor Red
    Write-Host "At line $($_.InvocationInfo.ScriptLineNumber): $($_.InvocationInfo.Line.Trim())" -ForegroundColor Yellow
    exit 1
}

# Usage examples:
#   pwsh ./renameProject.ps1 -NewName excalibur             # OldName inferred from repo folder
#   pwsh ./renameProject.ps1 -OldName respondr -NewName excalibur -DryRun
#   pwsh ./renameProject.ps1 -NewName excalibur -UseGit      # use git mv if available
#   pwsh ./renameProject.ps1 -NewName excalibur -IncludePaths ./deployment,./backend -ExcludePaths node_modules,.venv
