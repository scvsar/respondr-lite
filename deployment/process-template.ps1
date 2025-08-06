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
    }
}

# Read template file
$templateContent = Get-Content $TemplateFile -Raw

# Replace placeholders
$processedContent = $templateContent

# Replace all known placeholders
$processedContent = $processedContent -replace '{{ACR_IMAGE_PLACEHOLDER}}', "$($values['acrLoginServer'])/$($values['imageName']):$($values['imageTag'])"
$processedContent = $processedContent -replace '{{HOSTNAME_PLACEHOLDER}}', $values['hostname']
$processedContent = $processedContent -replace '{{TENANT_ID_PLACEHOLDER}}', $values['azureTenantId']
$processedContent = $processedContent -replace '{{CLIENT_ID_PLACEHOLDER}}', $values['oauth2ClientId']
$processedContent = $processedContent -replace '{{REDIRECT_URL_PLACEHOLDER}}', $values['oauth2RedirectUrl']
$processedContent = $processedContent -replace '{{NAMESPACE_PLACEHOLDER}}', $values['namespace']
$processedContent = $processedContent -replace '{{DOMAIN_PLACEHOLDER}}', $values['domain']

# Handle OAuth2 conditional sections
$useOAuth2 = $values['useOAuth2'] -eq 'true'
if ($useOAuth2) {
    # Remove OAuth2 conditional markers but keep the content
    $processedContent = $processedContent -replace '\s*{{OAUTH2_CONTAINER_START}}\s*\n?', ''
    $processedContent = $processedContent -replace '\s*{{OAUTH2_CONTAINER_END}}\s*\n?', ''
    $processedContent = $processedContent -replace '\s*{{OAUTH2_INGRESS_START}}\s*\n?', ''
    $processedContent = $processedContent -replace '\s*{{OAUTH2_INGRESS_END}}\s*\n?', ''
    
    # Replace SERVICE_PORT_CONFIG for OAuth2 mode (traffic goes through oauth2-proxy on port 4180)
    $servicePortConfig = @"
- name: http
    port: 80
    targetPort: 4180
    protocol: TCP
"@
    $processedContent = $processedContent -replace '{{SERVICE_PORT_CONFIG}}', $servicePortConfig
} else {
    # Remove entire OAuth2 sections including the markers
    $processedContent = $processedContent -replace '(?s)\s*{{OAUTH2_CONTAINER_START}}.*?{{OAUTH2_CONTAINER_END}}\s*', ''
    $processedContent = $processedContent -replace '(?s)\s*{{OAUTH2_INGRESS_START}}.*?{{OAUTH2_INGRESS_END}}\s*', ''
    
    # Replace SERVICE_PORT_CONFIG for non-OAuth2 mode (traffic goes directly to app on port 8000)
    $servicePortConfig = @"
- name: http
    port: 80
    targetPort: 8000
    protocol: TCP
"@
    $processedContent = $processedContent -replace '{{SERVICE_PORT_CONFIG}}', $servicePortConfig
}

# Write processed content
[System.IO.File]::WriteAllText($OutputFile, $processedContent, [System.Text.Encoding]::UTF8)

Write-Host "✅ Generated $OutputFile from template" -ForegroundColor Green

# Display key replacements made
Write-Host "🔍 Key replacements made:" -ForegroundColor Yellow
Write-Host "   Image: $($values['acrLoginServer'])/$($values['imageName']):$($values['imageTag'])" -ForegroundColor White
Write-Host "   Hostname: $($values['hostname'])" -ForegroundColor White
Write-Host "   Tenant ID: $($values['azureTenantId'])" -ForegroundColor White
