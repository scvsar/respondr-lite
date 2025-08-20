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
    '{{REPLICAS_PLACEHOLDER}}' = $values['replicas']
    # Computed placeholders handled later; do NOT include them in the first pass
}

# Apply all basic placeholder replacements (always replace, even if empty)
foreach ($placeholder in $placeholderMap.Keys) {
    $value = $placeholderMap[$placeholder]
    $processedContent = $processedContent -replace [regex]::Escape($placeholder), ($value -ne $null ? $value : '')
    if ($value -ne $null -and $value -ne '') {
        Write-Verbose "Replaced: $placeholder -> $value"
    } else {
        Write-Verbose "No value for placeholder: $placeholder (left empty)"
    }
}

# Compute multi-tenant issuer segment and email domain args
$multiTenant = ($values['multiTenantAuth'] -eq 'true' -or $values['multiTenantAuth'] -eq 'True' -or $values['multiTenantAuth'] -eq '1')
$oidcTenantSegment = if ($multiTenant) { 'common' } else { $values['azureTenantId'] }

# Build allowed email domains args for oauth2-proxy
$emailArgs = ''
if ($multiTenant) {
    # For multi-tenant apps, let the application handle domain validation
    $emailArgs = "        - --email-domain=*"
} else {
    # For single-tenant apps, use configured domains
    try {
        $domainLines = @()
        $inDomains = $false
        foreach ($line in (Get-Content $ValuesFile)) {
            if ($line -match '^allowedEmailDomains\s*:') { $inDomains = $true; continue }
            if ($inDomains) {
                if ($line -match '^\s*-\s*(.+)') {
                    $v = $matches[1].Trim()
                    if ($v.StartsWith('"') -and $v.EndsWith('"')) { $v = $v.Substring(1, $v.Length - 2) }
                    if ($v.StartsWith("'") -and $v.EndsWith("'")) { $v = $v.Substring(1, $v.Length - 2) }
                    $domainLines += $v
                } else { break }
            }
        }
        if ($domainLines.Count -gt 0) {
            foreach ($d in $domainLines) { $emailArgs += "        - --email-domain=`"$d`"`n" }
        } else {
            $emailArgs = "        - --email-domain=*"
        }
    $emailArgs = $emailArgs.TrimEnd("`n")
    } catch { $emailArgs = "        - --email-domain=*" }
}


# Build allowed email domains string for application environment variable
try {
    $domainList = @()
    $inDomains = $false
    foreach ($line in (Get-Content $ValuesFile)) {
        if ($line -match '^allowedEmailDomains\s*:') { $inDomains = $true; continue }
        if ($inDomains) {
            if ($line -match '^\s*-\s*(.+)') {
                $v = $matches[1].Trim()
                if ($v.StartsWith('"') -and $v.EndsWith('"')) { $v = $v.Substring(1, $v.Length - 2) }
                if ($v.StartsWith("'") -and $v.EndsWith("'")) { $v = $v.Substring(1, $v.Length - 2) }
                $domainList += $v
            } else { break }
        }
    }
    $allowedDomains = $domainList -join ","
} catch { 
    $allowedDomains = "scvsar.org,rtreit.com" 
}


# Build allowed admin users string for application environment variable
try {
    $adminList = @()
    $inAdmins = $false
    foreach ($line in (Get-Content $ValuesFile)) {
        if ($line -match '^allowedAdminUsers\s*:') { $inAdmins = $true; continue }
        if ($inAdmins) {
            if ($line -match '^\s*-\s*(.+)') {
                $v = $matches[1].Trim()
                if ($v.StartsWith('"') -and $v.EndsWith('"')) { $v = $v.Substring(1, $v.Length - 2) }
                if ($v.StartsWith("'") -and $v.EndsWith("'")) { $v = $v.Substring(1, $v.Length - 2) }
                $adminList += $v
            } else { break }
        }
    }
    $allowedAdmins = ($adminList | ForEach-Object { $_.ToLower() }) -join ","
} catch { $allowedAdmins = "" }


# Ensure env var placeholders render as valid YAML even when empty
$ALLOWED_EMAIL_DOMAINS_PLACEHOLDER = if ($allowedDomains -and $allowedDomains.Trim()) { $allowedDomains } else { '""' }
$ALLOWED_ADMIN_USERS_PLACEHOLDER   = if ($allowedAdmins -and $allowedAdmins.Trim()) { $allowedAdmins } else { '""' }
$LEGACY_HOSTNAMES_PLACEHOLDER      = if ($values.ContainsKey('legacyHostnames') -and $values['legacyHostnames']) { $values['legacyHostnames'] } else { '""' }

# Apply replacements for computed placeholders (always replace)
# Now replace computed placeholders
$processedContent = $processedContent -replace [regex]::Escape('{{OIDC_TENANT_SEGMENT}}'), ($null -ne $oidcTenantSegment ? $oidcTenantSegment : '')
$processedContent = $processedContent -replace [regex]::Escape('{{EMAIL_DOMAIN_ARGS}}'),   ($null -ne $emailArgs ? $emailArgs : '')
$processedContent = $processedContent -replace [regex]::Escape('{{ALLOWED_EMAIL_DOMAINS_PLACEHOLDER}}'), ($null -ne $ALLOWED_EMAIL_DOMAINS_PLACEHOLDER ? $ALLOWED_EMAIL_DOMAINS_PLACEHOLDER : '')
$processedContent = $processedContent -replace [regex]::Escape('{{ALLOWED_ADMIN_USERS_PLACEHOLDER}}'),   ($null -ne $ALLOWED_ADMIN_USERS_PLACEHOLDER ? $ALLOWED_ADMIN_USERS_PLACEHOLDER : '')
$processedContent = $processedContent -replace [regex]::Escape('{{LEGACY_HOSTNAMES_PLACEHOLDER}}'),      ($null -ne $LEGACY_HOSTNAMES_PLACEHOLDER ? $LEGACY_HOSTNAMES_PLACEHOLDER : '')

# Handle legacy redirect hostnames
$redirectIngressBlock = ''
$redirectDeploymentBlock = ''
if ($values.ContainsKey('legacyHostnames') -and $values['legacyHostnames']) {
    $legacyHosts = ($values['legacyHostnames'] -split ',') | ForEach-Object { $_.Trim() } | Where-Object { $_ -ne '' }
    
    if ($legacyHosts.Count -gt 0) {
        # Generate redirect Ingress that routes to existing respondr-service
        # The application will handle redirect detection based on hostname
        $hostsList = ($legacyHosts | ForEach-Object { "    - $_" }) -join "`n"
        $rulesList = ''
        foreach ($h in $legacyHosts) {
            $rulesList += @"
  - host: $h
    http:
      paths:
      - path: /
        pathType: Prefix
        backend:
          service:
            name: respondr-service
            port:
              number: 80
"@
        }
        
        $redirectIngressBlock = @"
---
apiVersion: networking.k8s.io/v1
kind: Ingress
metadata:
  name: respondr-redirect-ingress
  namespace: $($values['namespace'])
  annotations:
    kubernetes.io/ingress.class: azure/application-gateway
    appgw.ingress.kubernetes.io/ssl-redirect: "true"
    appgw.ingress.kubernetes.io/use-private-ip: "false"
    cert-manager.io/cluster-issuer: "letsencrypt-prod"
    appgw.ingress.kubernetes.io/backend-protocol: "http"
spec:
  tls:
  - hosts:
$hostsList
    secretName: respondr-redirect-tls-letsencrypt
  rules:
$rulesList
"@

        # No separate deployment needed - application handles redirects
        $redirectDeploymentBlock = ''
    }
}

$processedContent = $processedContent -replace [regex]::Escape('{{REDIRECT_INGRESS_BLOCK}}'), $redirectIngressBlock
$processedContent = $processedContent -replace [regex]::Escape('{{REDIRECT_DEPLOYMENT_BLOCK}}'), $redirectDeploymentBlock

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
    # Defensive fix: ensure probes use /health (avoid accidental /api/responders in generated files)
    $processedContent = $processedContent -replace 'livenessProbe:(?s).*?httpGet:\s*\n\s*path:\s*/api/responders', 'livenessProbe:`n          httpGet:`n            path: /health'
    $processedContent = $processedContent -replace 'readinessProbe:(?s).*?httpGet:\s*\n\s*path:\s*/api/responders', 'readinessProbe:`n          httpGet:`n            path: /health'

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
