param(
    [Parameter(Mandatory = $true)]
    [string]$TemplateFile,
    
    [Parameter(Mandatory = $true)]
    [string]$OutputFile,
    
    [string]$ValuesFile = "values.yaml"
)

if (-not (Test-Path $ValuesFile)) {
    Write-Error "Values file '$ValuesFile' not found. Run generate-values.ps1 first."
    exit 1
}

if (-not (Test-Path $TemplateFile)) {
    Write-Error "Template file '$TemplateFile' not found."
    exit 1
}

Write-Host "🔄 Processing template: $TemplateFile -> $OutputFile" -ForegroundColor Cyan

# Read values file and parse simple key: value pairs
$values = @{}
Get-Content $ValuesFile | ForEach-Object {
    if ($_ -match '^\s*([^#:]+):\s*"?([^"]*)"?\s*$') {
        $key = $matches[1].Trim()
        $value = $matches[2].Trim()
        $values[$key] = $value
        Write-Verbose "Loaded: $key = $value"
    }
}

Write-Host "📋 Loaded $($values.Count) configuration values" -ForegroundColor Cyan

# Read template file
$templateContent = Get-Content $TemplateFile -Raw

# Replace placeholders
$processedContent = $templateContent

# Replace all known placeholders with comprehensive mapping
$placeholderMap = @{
    '{{ACR_IMAGE_PLACEHOLDER}}' = "$($values['acrLoginServer'])/$($values['imageName']):$($values['imageTag'])"
    '{{HOSTNAME_PLACEHOLDER}}' = $values['hostname']
    '{{TENANT_ID_PLACEHOLDER}}' = $values['azureTenantId']
    '{{CLIENT_ID_PLACEHOLDER}}' = $values['oauth2ClientId']
    '{{REDIRECT_URL_PLACEHOLDER}}' = $values['oauth2RedirectUrl']
    '{{NAMESPACE_PLACEHOLDER}}' = $values['namespace']
    '{{DOMAIN_PLACEHOLDER}}' = $values['domain']
}

# Apply all basic placeholder replacements
foreach ($placeholder in $placeholderMap.Keys) {
    $value = $placeholderMap[$placeholder]
    if ($value) {
        $processedContent = $processedContent -replace [regex]::Escape($placeholder), $value
        Write-Verbose "Replaced: $placeholder -> $value"
    } else {
        Write-Warning "No value found for placeholder: $placeholder"
    }
}

# Handle OAuth2 conditional sections
$useOAuth2 = $values['useOAuth2'] -eq 'true'
Write-Host "🔧 Processing OAuth2 conditional sections (useOAuth2: $useOAuth2)" -ForegroundColor Cyan

if ($useOAuth2) {
    # Remove OAuth2 conditional markers but keep the content and preserve formatting
    $processedContent = $processedContent -replace '\{\{OAUTH2_CONTAINER_START\}\}', ""
    $processedContent = $processedContent -replace '\{\{OAUTH2_CONTAINER_END\}\}', ""
    $processedContent = $processedContent -replace '\{\{OAUTH2_INGRESS_START\}\}', ""
    $processedContent = $processedContent -replace '\{\{OAUTH2_INGRESS_END\}\}', ""
    
    # Replace SERVICE_PORT_CONFIG for OAuth2 mode (traffic goes through oauth2-proxy on port 4180)
    $servicePortConfig = @"
- name: http
    port: 80
    targetPort: 4180
    protocol: TCP
"@
    $processedContent = $processedContent -replace '\{\{SERVICE_PORT_CONFIG\}\}', $servicePortConfig
    Write-Verbose "Applied OAuth2 service port configuration"
} else {
    # Remove entire OAuth2 sections including the markers and preserve document structure
    $processedContent = $processedContent -replace '(?s)      # OAuth2 Proxy sidecar container \(conditional - will be removed if ENABLE_OAUTH2=false\)\r?\n      \{\{OAUTH2_CONTAINER_START\}\}.*?\{\{OAUTH2_CONTAINER_END\}\}\r?\n', ''
    $processedContent = $processedContent -replace '(?s)\s*\{\{OAUTH2_INGRESS_START\}\}.*?\{\{OAUTH2_INGRESS_END\}\}\s*', ''
    
    # Replace SERVICE_PORT_CONFIG for non-OAuth2 mode (traffic goes directly to app on port 8000)
    $servicePortConfig = @"
- name: http
    port: 80
    targetPort: 8000
    protocol: TCP
"@
    $processedContent = $processedContent -replace '\{\{SERVICE_PORT_CONFIG\}\}', $servicePortConfig
    Write-Verbose "Applied non-OAuth2 service port configuration"
}

# Write processed content
try {
    $processedContent | Out-File -FilePath $OutputFile -Encoding UTF8 -NoNewline
    Write-Host "✅ Generated $OutputFile from template" -ForegroundColor Green
} catch {
    Write-Error "Failed to write output file '$OutputFile': $_"
    exit 1
}

# Verify no placeholders remain
$remainingPlaceholders = [regex]::Matches($processedContent, '\{\{[^}]+\}\}')
if ($remainingPlaceholders.Count -gt 0) {
    Write-Warning "⚠️  Found $($remainingPlaceholders.Count) unresolved placeholders:"
    foreach ($match in $remainingPlaceholders) {
        Write-Warning "   - $($match.Value)"
    }
    Write-Host "Consider updating the placeholderMap in process-template.ps1" -ForegroundColor Yellow
} else {
    Write-Host "✅ All placeholders successfully resolved" -ForegroundColor Green
}

# Display key replacements made
Write-Host "🔍 Key replacements made:" -ForegroundColor Cyan
Write-Host "   Image: $($values['acrLoginServer'])/$($values['imageName']):$($values['imageTag'])" -ForegroundColor White
Write-Host "   Hostname: $($values['hostname'])" -ForegroundColor White
Write-Host "   Tenant ID: $($values['azureTenantId'])" -ForegroundColor White
Write-Host "   Client ID: $($values['oauth2ClientId'])" -ForegroundColor White
Write-Host "   Use OAuth2: $($values['useOAuth2'])" -ForegroundColor White
