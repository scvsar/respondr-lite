# Create PFX Certificate for Custom Domain TLS
# This script creates a self-signed certificate for development/testing
# or prepares a CSR for production CA-issued certificates

param(
    [Parameter(Mandatory)]
    [string]$DomainName,
    
    [string]$OutputPath = ".\certificates",
    [string]$CertificatePassword,
    [string]$Country = "US",
    [string]$State = "California", 
    [string]$City = "San Jose",
    [string]$Organization = "SCVSAR",
    [string]$OrganizationalUnit = "IT",
    [int]$ValidityDays = 365,
    [switch]$CreateCSR,
    [switch]$SelfSigned
)

# Ensure output directory exists
if (-not (Test-Path $OutputPath)) {
    New-Item -ItemType Directory -Path $OutputPath -Force | Out-Null
    Write-Host "Created directory: $OutputPath" -ForegroundColor Green
}

# Generate a secure password if not provided
if (-not $CertificatePassword) {
    $CertificatePassword = -join ((65..90) + (97..122) + (48..57) | Get-Random -Count 16 | ForEach-Object {[char]$_})
    Write-Host "Generated certificate password: $CertificatePassword" -ForegroundColor Yellow
    Write-Host "IMPORTANT: Save this password securely!" -ForegroundColor Red
}

$SecurePassword = ConvertTo-SecureString -String $CertificatePassword -Force -AsPlainText

# Certificate subject
$Subject = "CN=$DomainName,O=$Organization,OU=$OrganizationalUnit,L=$City,ST=$State,C=$Country"

# File paths
$CertPath = Join-Path $OutputPath "$DomainName.crt"
$KeyPath = Join-Path $OutputPath "$DomainName.key"
$PfxPath = Join-Path $OutputPath "$DomainName.pfx"
$CsrPath = Join-Path $OutputPath "$DomainName.csr"

Write-Host "Creating certificate for domain: $DomainName" -ForegroundColor Cyan
Write-Host "Subject: $Subject" -ForegroundColor Gray

if ($SelfSigned) {
    Write-Host "Creating self-signed certificate..." -ForegroundColor Yellow
    
    # Create self-signed certificate directly as PFX
    $Cert = New-SelfSignedCertificate `
        -DnsName $DomainName `
        -Subject $Subject `
        -NotAfter (Get-Date).AddDays($ValidityDays) `
        -CertStoreLocation "Cert:\CurrentUser\My" `
        -KeyAlgorithm RSA `
        -KeyLength 2048 `
        -HashAlgorithm SHA256 `
        -KeyUsage DigitalSignature, KeyEncipherment `
        -TextExtension @("2.5.29.37={text}1.3.6.1.5.5.7.3.1") # Server Authentication
    
    # Export to PFX
    Export-PfxCertificate -Cert $Cert -FilePath $PfxPath -Password $SecurePassword | Out-Null
    
    # Export public certificate
    Export-Certificate -Cert $Cert -FilePath $CertPath | Out-Null
    
    # Clean up from certificate store
    Remove-Item -Path "Cert:\CurrentUser\My\$($Cert.Thumbprint)" -Force
    
    Write-Host "✅ Self-signed certificate created successfully!" -ForegroundColor Green
    
} elseif ($CreateCSR) {
    Write-Host "Creating Certificate Signing Request (CSR)..." -ForegroundColor Yellow
    
    # Create private key and CSR using OpenSSL (if available) or .NET
    if (Get-Command openssl -ErrorAction SilentlyContinue) {
        # Using OpenSSL for better compatibility
        $ConfigPath = Join-Path $OutputPath "openssl.conf"
        
        # Create OpenSSL config file
        @"
[req]
default_bits = 2048
prompt = no
distinguished_name = req_distinguished_name
req_extensions = v3_req

[req_distinguished_name]
C = $Country
ST = $State
L = $City
O = $Organization
OU = $OrganizationalUnit
CN = $DomainName

[v3_req]
keyUsage = keyEncipherment, dataEncipherment
extendedKeyUsage = serverAuth
subjectAltName = @alt_names

[alt_names]
DNS.1 = $DomainName
"@ | Out-File -FilePath $ConfigPath -Encoding ascii
        
        # Generate private key
        & openssl genrsa -out $KeyPath 2048
        
        # Generate CSR
        & openssl req -new -key $KeyPath -out $CsrPath -config $ConfigPath
        
        Write-Host "✅ CSR and private key created!" -ForegroundColor Green
        Write-Host "Submit the CSR file to your Certificate Authority: $CsrPath" -ForegroundColor Cyan
        Write-Host "Keep the private key secure: $KeyPath" -ForegroundColor Yellow
        
        # Clean up config file
        Remove-Item $ConfigPath -Force
        
    } else {
        Write-Host "OpenSSL not found. Creating CSR using PowerShell..." -ForegroundColor Yellow
        
        # Create CSR using .NET (more limited but works without OpenSSL)
        $RSA = [System.Security.Cryptography.RSA]::Create(2048)
        $Request = [System.Security.Cryptography.X509Certificates.CertificateRequest]::new(
            $Subject,
            $RSA,
            [System.Security.Cryptography.HashAlgorithmName]::SHA256,
            [System.Security.Cryptography.RSASignaturePadding]::Pkcs1
        )
        
        # Add extensions
        $Request.CertificateExtensions.Add(
            [System.Security.Cryptography.X509Certificates.X509KeyUsageExtension]::new(
                [System.Security.Cryptography.X509Certificates.X509KeyUsageFlags]::DigitalSignature -bor 
                [System.Security.Cryptography.X509Certificates.X509KeyUsageFlags]::KeyEncipherment,
                $false
            )
        )
        
        $SanBuilder = [System.Security.Cryptography.X509Certificates.SubjectAlternativeNameBuilder]::new()
        $SanBuilder.AddDnsName($DomainName)
        $Request.CertificateExtensions.Add($SanBuilder.Build())
        
        # Create CSR
        $CsrBytes = $Request.CreateSigningRequest()
        $CsrPem = "-----BEGIN CERTIFICATE REQUEST-----`n" + 
                  [Convert]::ToBase64String($CsrBytes, [Base64FormattingOptions]::InsertLineBreaks) + 
                  "`n-----END CERTIFICATE REQUEST-----"
        
        [System.IO.File]::WriteAllText($CsrPath, $CsrPem)
        
        # Export private key (this is tricky without OpenSSL, so we'll save as PFX temporarily)
        $TempCert = $Request.CreateSelfSigned([System.DateTimeOffset]::Now, [System.DateTimeOffset]::Now.AddDays(1))
        $TempPfxPath = Join-Path $OutputPath "temp.pfx"
        [System.IO.File]::WriteAllBytes($TempPfxPath, $TempCert.Export([System.Security.Cryptography.X509Certificates.X509ContentType]::Pfx, $CertificatePassword))
        
        Write-Host "✅ CSR created: $CsrPath" -ForegroundColor Green
        Write-Host "⚠️  Private key stored in temporary PFX: $TempPfxPath" -ForegroundColor Yellow
        Write-Host "Submit the CSR to your Certificate Authority and use the temp PFX to create final PFX" -ForegroundColor Cyan
    }
    
} else {
    Write-Host "Please specify either -SelfSigned or -CreateCSR" -ForegroundColor Red
    exit 1
}

# Output summary
Write-Host "`n📋 Certificate Summary:" -ForegroundColor Cyan
Write-Host "Domain: $DomainName" -ForegroundColor White
Write-Host "Output Directory: $OutputPath" -ForegroundColor White

if ($SelfSigned) {
    Write-Host "Certificate: $CertPath" -ForegroundColor White
    Write-Host "PFX File: $PfxPath" -ForegroundColor White
    Write-Host "Password: $CertificatePassword" -ForegroundColor Yellow
    
    Write-Host "`n🚀 Next Steps for Azure Container Apps:" -ForegroundColor Green
    Write-Host "1. Upload the PFX file to Azure Key Vault or directly to Container Apps" -ForegroundColor Gray
    Write-Host "2. Configure custom domain in Container Apps with the certificate" -ForegroundColor Gray
    Write-Host "3. Update DNS to point to your Container App FQDN" -ForegroundColor Gray
    
} elseif ($CreateCSR) {
    Write-Host "CSR File: $CsrPath" -ForegroundColor White
    if (Test-Path $KeyPath) {
        Write-Host "Private Key: $KeyPath" -ForegroundColor White
    }
    
    Write-Host "`n🚀 Next Steps:" -ForegroundColor Green
    Write-Host "1. Submit CSR to your Certificate Authority" -ForegroundColor Gray
    Write-Host "2. Receive signed certificate from CA" -ForegroundColor Gray
    Write-Host "3. Combine with private key to create PFX:" -ForegroundColor Gray
    Write-Host "   openssl pkcs12 -export -out $DomainName.pfx -inkey $KeyPath -in certificate.crt" -ForegroundColor DarkGray
}

Write-Host "`n⚠️  Security Notes:" -ForegroundColor Red
Write-Host "• Store the PFX password securely (e.g., Azure Key Vault)" -ForegroundColor Gray
Write-Host "• For production, use CA-issued certificates" -ForegroundColor Gray
Write-Host "• Self-signed certificates will show browser warnings" -ForegroundColor Gray

<# 
Example usage:

# Create self-signed certificate
.\create-pfx-certificate.ps1 -DomainName "respondr.scvsar.org" -SelfSigned

# Create CSR for CA-issued certificate  
.\create-pfx-certificate.ps1 -DomainName "respondr.scvsar.org" -CreateCSR

# With custom settings
.\create-pfx-certificate.ps1 -DomainName "respondr.scvsar.org" -SelfSigned -Organization "SCVSAR" -ValidityDays 730 -CertificatePassword "MySecurePassword123!"
#>