# Configure Custom Domain with TLS Certificate for Azure Container Apps
# This script configures a custom domain and uploads a PFX certificate

param(
    [Parameter(Mandatory)]
    [string]$ResourceGroup,
    
    [Parameter(Mandatory)] 
    [string]$ContainerAppName,
    
    [Parameter(Mandatory)]
    [string]$DomainName,
    
    [Parameter(Mandatory)]
    [string]$PfxFilePath,
    
    [Parameter(Mandatory)]
    [string]$CertificatePassword,
    
    [string]$CertificateName,
    [switch]$SkipDnsValidation
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

# Validate inputs
if (-not (Test-Path $PfxFilePath)) {
    throw "PFX file not found: $PfxFilePath"
}

if (-not $CertificateName) {
    $CertificateName = $DomainName.Replace(".", "-") + "-cert"
}

Write-Host "🚀 Configuring custom domain for Container Apps" -ForegroundColor Cyan
Write-Host "Resource Group: $ResourceGroup" -ForegroundColor Gray
Write-Host "Container App: $ContainerAppName" -ForegroundColor Gray  
Write-Host "Domain: $DomainName" -ForegroundColor Gray
Write-Host "Certificate: $CertificateName" -ForegroundColor Gray

# Step 1: Get Container App details
Write-Host "`n📋 Getting Container App details..." -ForegroundColor Yellow
$containerApp = az containerapp show -g $ResourceGroup -n $ContainerAppName --query "{fqdn:properties.configuration.ingress.fqdn, resourceId:id}" -o json | ConvertFrom-Json

if (-not $containerApp.fqdn) {
    throw "Container App '$ContainerAppName' not found or doesn't have ingress configured"
}

Write-Host "Container App FQDN: $($containerApp.fqdn)" -ForegroundColor Green

# Step 2: DNS validation (unless skipped)
if (-not $SkipDnsValidation) {
    Write-Host "`n🔍 Validating DNS configuration..." -ForegroundColor Yellow
    
    try {
        $dnsResult = Resolve-DnsName -Name $DomainName -Type CNAME -ErrorAction SilentlyContinue
        if ($dnsResult) {
            $cnameTarget = $dnsResult.NameHost
            Write-Host "DNS CNAME: $DomainName -> $cnameTarget" -ForegroundColor Green
            
            if ($cnameTarget -ne $containerApp.fqdn) {
                Write-Warning "DNS CNAME points to '$cnameTarget' but should point to '$($containerApp.fqdn)'"
                Write-Host "Please update your DNS to point $DomainName to $($containerApp.fqdn)" -ForegroundColor Red
                
                $continue = Read-Host "Continue anyway? (y/N)"
                if ($continue -ne 'y' -and $continue -ne 'Y') {
                    Write-Host "Cancelled by user" -ForegroundColor Yellow
                    exit 0
                }
            } else {
                Write-Host "✅ DNS correctly configured!" -ForegroundColor Green
            }
        } else {
            Write-Warning "No CNAME record found for $DomainName"
            Write-Host "Please create a CNAME record: $DomainName -> $($containerApp.fqdn)" -ForegroundColor Red
            
            $continue = Read-Host "Continue anyway? (y/N)"
            if ($continue -ne 'y' -and $continue -ne 'Y') {
                Write-Host "Cancelled by user" -ForegroundColor Yellow
                exit 0
            }
        }
    } catch {
        Write-Warning "Unable to validate DNS: $($_.Exception.Message)"
    }
}

# Step 3: Upload certificate to Container App environment  
Write-Host "`n📜 Uploading certificate..." -ForegroundColor Yellow

$managedEnvId = az containerapp show -g $ResourceGroup -n $ContainerAppName --query "properties.managedEnvironmentId" -o tsv

if (-not $managedEnvId) {
    throw "Unable to get Container App Environment ID"
}

$managedEnvName = $managedEnvId.Split('/')[-1]
Write-Host "Container App Environment: $managedEnvName" -ForegroundColor Gray

# Upload certificate to the Container App Environment
Write-Host "Uploading certificate to Container App Environment..." -ForegroundColor Gray

$certUploadResult = az containerapp env certificate upload `
    -g $ResourceGroup `
    -n $managedEnvName `
    --certificate-file $PfxFilePath `
    --certificate-name $CertificateName `
    --certificate-password $CertificatePassword `
    -o json 2>$null

if ($LASTEXITCODE -ne 0) {
    Write-Error "Failed to upload certificate. This might be because:"
    Write-Host "• Certificate already exists with this name" -ForegroundColor Yellow
    Write-Host "• Invalid PFX file or password" -ForegroundColor Yellow  
    Write-Host "• Permissions issue" -ForegroundColor Yellow
    throw "Certificate upload failed"
}

$certificateData = $certUploadResult | ConvertFrom-Json
$certificateId = $certificateData.id

Write-Host "✅ Certificate uploaded successfully!" -ForegroundColor Green
Write-Host "Certificate ID: $certificateId" -ForegroundColor Gray

# Step 4: Add custom domain to Container App
Write-Host "`n🌐 Adding custom domain to Container App..." -ForegroundColor Yellow

$domainAddResult = az containerapp hostname add `
    -g $ResourceGroup `
    -n $ContainerAppName `
    --hostname $DomainName `
    -o json 2>$null

if ($LASTEXITCODE -ne 0) {
    Write-Warning "Failed to add hostname. This might be because the domain already exists."
}

# Step 5: Bind certificate to the custom domain
Write-Host "`n🔒 Binding certificate to custom domain..." -ForegroundColor Yellow

$bindResult = az containerapp hostname bind `
    -g $ResourceGroup `
    -n $ContainerAppName `
    --hostname $DomainName `
    --certificate $certificateId `
    -o json 2>$null

if ($LASTEXITCODE -ne 0) {
    throw "Failed to bind certificate to domain"
}

Write-Host "✅ Certificate bound to domain successfully!" -ForegroundColor Green

# Step 6: Verify configuration
Write-Host "`n🔍 Verifying configuration..." -ForegroundColor Yellow

$appConfig = az containerapp show -g $ResourceGroup -n $ContainerAppName --query "properties.configuration.ingress.customDomains" -o json | ConvertFrom-Json

$customDomain = $appConfig | Where-Object { $_.name -eq $DomainName }

if ($customDomain) {
    Write-Host "✅ Custom domain configured successfully!" -ForegroundColor Green
    Write-Host "Domain: $($customDomain.name)" -ForegroundColor White
    Write-Host "Certificate: $($customDomain.certificateId.Split('/')[-1])" -ForegroundColor White
    Write-Host "Binding Type: $($customDomain.bindingType)" -ForegroundColor White
} else {
    Write-Warning "Custom domain not found in Container App configuration"
}

# Summary
Write-Host "`n🎉 Configuration Complete!" -ForegroundColor Green
Write-Host "Custom domain: https://$DomainName" -ForegroundColor Cyan
Write-Host "`n📋 Summary:" -ForegroundColor Cyan
Write-Host "• Certificate '$CertificateName' uploaded to Container App Environment" -ForegroundColor White
Write-Host "• Domain '$DomainName' added to Container App '$ContainerAppName'" -ForegroundColor White
Write-Host "• TLS certificate bound to custom domain" -ForegroundColor White

Write-Host "`n⚠️  Important Notes:" -ForegroundColor Yellow
Write-Host "• DNS propagation may take a few minutes" -ForegroundColor Gray
Write-Host "• Test your custom domain: https://$DomainName" -ForegroundColor Gray
Write-Host "• Certificate expires in $(((Get-PfxCertificate -FilePath $PfxFilePath).NotAfter - (Get-Date)).Days) days" -ForegroundColor Gray

<#
Example usage:

# Configure custom domain with certificate
.\configure-custom-domain.ps1 `
    -ResourceGroup "respondrlite" `
    -ContainerAppName "respondr-lite-container" `
    -DomainName "respondr.scvsar.org" `
    -PfxFilePath ".\certificates\respondr.scvsar.org.pfx" `
    -CertificatePassword "YourSecurePassword123!"

# Skip DNS validation (useful for testing)  
.\configure-custom-domain.ps1 `
    -ResourceGroup "respondrlite" `
    -ContainerAppName "respondr-lite-container" `
    -DomainName "respondr.scvsar.org" `
    -PfxFilePath ".\certificates\respondr.scvsar.org.pfx" `
    -CertificatePassword "YourSecurePassword123!" `
    -SkipDnsValidation
#>