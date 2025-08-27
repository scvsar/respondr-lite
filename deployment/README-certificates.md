# Custom Domain TLS Certificates for Azure Container Apps

This directory contains scripts to create and configure TLS certificates for custom domains with Azure Container Apps.

## Overview

Azure Container Apps supports "Bring Your Own Certificate" (BYOC) for custom domains. You can use either:

1. **Self-signed certificates** (for development/testing)
2. **CA-issued certificates** (for production)

## Scripts

### `create-pfx-certificate.ps1`
Creates PFX certificates for custom domain TLS configuration.

**Features:**
- Generate self-signed certificates for testing
- Create Certificate Signing Requests (CSR) for CA-issued certificates  
- Automatic password generation
- OpenSSL integration (when available)
- PowerShell fallback for systems without OpenSSL

### `configure-custom-domain.ps1` 
Configures custom domains with TLS certificates in Azure Container Apps.

**Features:**
- Uploads PFX certificates to Container App Environment
- Adds custom domains to Container Apps
- Binds certificates to domains
- DNS validation
- Configuration verification

## Quick Start

### 1. Create a Self-Signed Certificate (Development)

```powershell
# Create self-signed certificate for testing
.\create-pfx-certificate.ps1 -DomainName "respondr.scvsar.org" -SelfSigned

# With custom settings
.\create-pfx-certificate.ps1 `
    -DomainName "respondr.scvsar.org" `
    -SelfSigned `
    -Organization "SCVSAR" `
    -ValidityDays 730 `
    -CertificatePassword "MySecurePassword123!"
```

### 2. Create CSR for CA-Issued Certificate (Production)

```powershell
# Generate CSR and private key
.\create-pfx-certificate.ps1 -DomainName "respondr.scvsar.org" -CreateCSR

# Submit the CSR to your Certificate Authority
# After receiving the signed certificate, combine with private key:
openssl pkcs12 -export -out respondr.scvsar.org.pfx -inkey respondr.scvsar.org.key -in certificate.crt
```

### 3. Configure Custom Domain in Azure

```powershell
# Configure custom domain with certificate
.\configure-custom-domain.ps1 `
    -ResourceGroup "respondrlite" `
    -ContainerAppName "respondr-lite-container" `
    -DomainName "respondr.scvsar.org" `
    -PfxFilePath ".\certificates\respondr.scvsar.org.pfx" `
    -CertificatePassword "YourSecurePassword123!"
```

## DNS Configuration

Before configuring the custom domain, ensure your DNS is properly configured:

1. **CNAME Record**: Point your custom domain to your Container App FQDN
   ```
   respondr.scvsar.org    CNAME    your-container-app.domain.region.azurecontainerapps.io
   ```

2. **Verification**: The script will validate DNS configuration automatically

## Certificate Management

### Security Best Practices

- **Password Storage**: Store PFX passwords securely (Azure Key Vault recommended)
- **Certificate Rotation**: Monitor certificate expiration dates
- **Production Certificates**: Always use CA-issued certificates for production

### Certificate Expiration

Self-signed certificates created by this script are valid for 365 days by default. Monitor expiration and renew certificates before they expire.

### Troubleshooting

**Common Issues:**

1. **DNS not propagated**: Wait a few minutes for DNS changes to propagate
2. **Certificate upload fails**: Check PFX file format and password
3. **Domain validation fails**: Ensure CNAME record is correctly configured
4. **Browser warnings**: Self-signed certificates will show security warnings

**Certificate Validation:**
```powershell
# Check certificate details
Get-PfxCertificate -FilePath ".\certificates\respondr.scvsar.org.pfx"

# Test certificate binding
Test-NetConnection respondr.scvsar.org -Port 443
```

## File Structure

After running the scripts, you'll have:

```
certificates/
├── respondr.scvsar.org.crt     # Public certificate (self-signed)
├── respondr.scvsar.org.key     # Private key (CSR workflow)  
├── respondr.scvsar.org.pfx     # Combined certificate + key
└── respondr.scvsar.org.csr     # Certificate signing request
```

## Examples

### Development Environment
```powershell
# Create self-signed certificate
.\create-pfx-certificate.ps1 -DomainName "respondr-dev.scvsar.org" -SelfSigned

# Configure in Azure (skip DNS validation for testing)
.\configure-custom-domain.ps1 `
    -ResourceGroup "respondrlite-dev" `
    -ContainerAppName "respondr-lite-dev" `
    -DomainName "respondr-dev.scvsar.org" `
    -PfxFilePath ".\certificates\respondr-dev.scvsar.org.pfx" `
    -CertificatePassword "GeneratedPassword123" `
    -SkipDnsValidation
```

### Production Environment
```powershell
# 1. Create CSR
.\create-pfx-certificate.ps1 -DomainName "respondr.scvsar.org" -CreateCSR

# 2. Submit CSR to Certificate Authority and receive signed certificate

# 3. Create PFX from signed certificate and private key
openssl pkcs12 -export -out respondr.scvsar.org.pfx -inkey respondr.scvsar.org.key -in signed-certificate.crt -password pass:YourSecurePassword

# 4. Configure in Azure
.\configure-custom-domain.ps1 `
    -ResourceGroup "respondrlite" `
    -ContainerAppName "respondr-lite-prod" `
    -DomainName "respondr.scvsar.org" `
    -PfxFilePath ".\certificates\respondr.scvsar.org.pfx" `
    -CertificatePassword "YourSecurePassword"
```

## Integration with Deployment

Add certificate configuration to your deployment process:

```powershell
# In your deployment script
if ($CustomDomain) {
    Write-Host "Configuring custom domain: $CustomDomain"
    .\configure-custom-domain.ps1 `
        -ResourceGroup $ResourceGroup `
        -ContainerAppName $ContainerAppName `
        -DomainName $CustomDomain `
        -PfxFilePath $PfxFilePath `
        -CertificatePassword $CertificatePassword
}
```

## Support

For issues with certificate creation or configuration:

1. Check Azure Container Apps documentation
2. Verify DNS configuration
3. Validate certificate format and password
4. Review Azure resource logs

## References

- [Azure Container Apps Custom Domains](https://docs.microsoft.com/en-us/azure/container-apps/custom-domains-certificates)
- [OpenSSL Certificate Creation](https://www.openssl.org/docs/)
- [PowerShell Certificate Management](https://docs.microsoft.com/en-us/powershell/module/pki/)