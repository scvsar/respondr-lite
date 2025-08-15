#!/usr/bin/env pwsh

<#
.SYNOPSIS
    Complete end-to-end deployment script for Respondr application with HTTPS and Entra authentication.

.DESCRIPTION
    This script performs the complete deployment workflow:
    1. Infrastructure deployment (Bicep)
    2. Post-deployment configuration (AGIC, identities, auth setup)
    3. OAuth2 authentication setup (Azure AD app registration and configuration)
    4. HTTPS certificate configuration
    5. Application deployment to Kubernetes with OAuth2 proxy
    6. DNS verification and testing

.PARAMETER ResourceGroupName
    The Azure resource group name to deploy to.

.PARAMETER Location
    The Azure region to deploy to (default: eastus2).

.PARAMETER Domain
    The domain to use for the application (default: rtreit.com).

.PARAMETER SkipInfrastructure
    Skip the infrastructure deployment step.

.PARAMETER SkipImageBuild
    Skip the Docker image build step.

.PARAMETER UseOAuth2
    Disable OAuth2 proxy (default behavior is OAuth2 enabled). When specified, uses Application Gateway auth path.

.EXAMPLE
    .\deploy-complete.ps1 -ResourceGroupName "respondr" -Domain "rtreit.com"
    
.EXAMPLE
    .\deploy-complete.ps1 -ResourceGroupName "respondr" -Domain "rtreit.com" -DisableOAuth2
#>

param(
    [Parameter(Mandatory=$true)]
    [string]$ResourceGroupName,
    
    [Parameter(Mandatory=$false)]
    [string]$Location = "eastus2",
    
    [Parameter(Mandatory=$false)]
    [string]$Domain = "rtreit.com",

    [Parameter(Mandatory=$false)]
    [string]$Namespace = "respondr",

    [Parameter(Mandatory=$false)]
    [string]$HostPrefix = "respondr",

    [Parameter(Mandatory=$false)]
    [string]$ImageTag = "latest",
    
    [Parameter(Mandatory=$false)]
    [string]$AppName,
    
    [Parameter(Mandatory=$false)]
    [switch]$SkipInfrastructure,
    
    [Parameter(Mandatory=$false)]
    [switch]$SkipImageBuild,
    
    [Parameter(Mandatory=$false)]
    [switch]$DisableOAuth2,  # Use -DisableOAuth2 to turn off OAuth2 (default is enabled)
    
    [Parameter(Mandatory=$false)]
    [switch]$DryRun,

    # Optional: Pass Service Tree ID for app registration attribution (SFI tenants)
    [Parameter(Mandatory=$false)]
    [string]$ServiceTreeId,

    [Parameter(Mandatory=$false)]
    [switch]$SetupAcrWebhook,

    [Parameter(Mandatory=$false)]
    [switch]$SetupGithubOidc,
    [Parameter(Mandatory=$false)]
    [string]$GithubRepo,
    [Parameter(Mandatory=$false)]
    [string]$GithubBranch = "main"
    ,
    # Optional: Auth policy inputs for values generation
    [Parameter(Mandatory=$false)]
    [string[]]$AllowedEmailDomains,
    [Parameter(Mandatory=$false)]
    [string[]]$AllowedAdminUsers
)

$hostname = "$HostPrefix.$Domain"

# Resolve app name early for downstream steps
$resolvedAppName = if ($AppName -and $AppName.Trim()) { $AppName } else { $Namespace }

# Derive internal flag (default true unless -DisableOAuth2 provided)
$UseOAuth2 = -not $DisableOAuth2.IsPresent

# Ensure we operate from the script's directory so relative paths resolve
try {
    $ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
    Set-Location $ScriptDir
} catch {
    Write-Warning "Could not change directory to script path: $_"
}

Write-Host "Complete Respondr Deployment" -ForegroundColor Green
Write-Host "======================================" -ForegroundColor Green
Write-Host "Resource Group: $ResourceGroupName" -ForegroundColor Cyan
Write-Host "Location: $Location" -ForegroundColor Cyan
Write-Host "Domain: $hostname" -ForegroundColor Cyan
Write-Host ""

# Function to check if command succeeded
function Test-LastCommand {
    param([string]$ErrorMessage)
    if ($LASTEXITCODE -ne 0) {
        Write-Error $ErrorMessage
        exit 1
    }
}

# Step 1: Infrastructure Deployment
if (-not $SkipInfrastructure) {
    Write-Host "📦 Step 1: Deploying Azure Infrastructure..." -ForegroundColor Yellow
    Write-Host "=============================================" -ForegroundColor Yellow
    
    if (-not $DryRun) {
        # check if RG exists and if not create it
        $rgExists = az group exists --name $ResourceGroupName | ConvertFrom-Json
        if (-not $rgExists) {
            Write-Host "Resource group '$ResourceGroupName' does not exist. Creating..." -ForegroundColor Yellow
            az group create --name $ResourceGroupName --location $Location | Out-Null
            Test-LastCommand "Failed to create resource group $ResourceGroupName"
            Write-Host "Resource group '$ResourceGroupName' created successfully." -ForegroundColor Green
        } else {
            Write-Host "Resource group '$ResourceGroupName' already exists." -ForegroundColor Green
        }
    $bicepFile = Join-Path $PSScriptRoot 'main.bicep'
    az deployment group create --resource-group $ResourceGroupName --template-file $bicepFile --parameters resourcePrefix=$ResourceGroupName location=$Location
        Test-LastCommand "Infrastructure deployment failed"
        Write-Host "Infrastructure deployed successfully" -ForegroundColor Green
    } else {
        Write-Host "DRY RUN: Would deploy infrastructure" -ForegroundColor Cyan
    }
} else {
    Write-Host "⏭️  Skipping infrastructure deployment" -ForegroundColor Yellow
}

# Step 2: Post-deployment Configuration
Write-Host "`n🔧 Step 2: Post-deployment Configuration..." -ForegroundColor Yellow
Write-Host "=============================================" -ForegroundColor Yellow

if (-not $DryRun) {
    & (Join-Path $PSScriptRoot 'post-deploy.ps1') -ResourceGroupName $ResourceGroupName -Location $Location -Namespace $Namespace -AppName $resolvedAppName
    Test-LastCommand "Post-deployment configuration failed"
    Write-Host "Post-deployment configuration completed" -ForegroundColor Green
} else {
    Write-Host "DRY RUN: Would run post-deployment configuration" -ForegroundColor Cyan
}

# Step 3: Let's Encrypt Certificate Setup
Write-Host "`n🔒 Step 3: Setting up Let's Encrypt Certificates..." -ForegroundColor Yellow
Write-Host "=================================================" -ForegroundColor Yellow

# Get Application Gateway details
$deploy = az deployment group show --resource-group $ResourceGroupName --name main -o json | ConvertFrom-Json
$aksClusterName = $deploy.properties.outputs.aksClusterName.value
$mcResourceGroup = "MC_$($ResourceGroupName)_$($aksClusterName)_$($Location)"

# Get the actual Application Gateway name from AGIC configuration
Write-Host "Getting Application Gateway name from AGIC configuration..." -ForegroundColor Yellow
$agicConfig = az aks show --resource-group $ResourceGroupName --name $aksClusterName --query "addonProfiles.ingressApplicationGateway.config.effectiveApplicationGatewayId" -o tsv 2>$null

if ($agicConfig) {
    # Extract the Application Gateway name from the resource ID
    $appGwName = $agicConfig.Split('/')[-1]
    Write-Host "Found Application Gateway: $appGwName" -ForegroundColor Green
} else {
    # Fallback to the expected name pattern
    $appGwName = "$aksClusterName-appgw"
    Write-Host "Could not get Application Gateway from AGIC - using fallback name: $appGwName" -ForegroundColor Yellow
}

Write-Host "Application Gateway: $appGwName" -ForegroundColor Cyan
Write-Host "MC Resource Group: $mcResourceGroup" -ForegroundColor Cyan

if (-not $DryRun) {
    # Idempotent HTTPS port handling: skip creation if ANY frontend port already uses 443
    $frontendPortsJson = az network application-gateway frontend-port list --gateway-name $appGwName --resource-group $mcResourceGroup -o json 2>$null
    $existingHttpsPort = $false
    if ($frontendPortsJson) {
        try {
            $frontendPorts = $frontendPortsJson | ConvertFrom-Json
            if ($frontendPorts | Where-Object { $_.port -eq 443 }) { $existingHttpsPort = $true }
        } catch {
            Write-Warning "Could not parse existing frontend ports JSON: $_"
        }
    }

    if ($existingHttpsPort) {
        Write-Host "HTTPS frontend port (443) already exists (name: $((($frontendPorts | Where-Object { $_.port -eq 443 })[0]).name))" -ForegroundColor Green
    } else {
        Write-Host "Adding HTTPS frontend port (443)..." -ForegroundColor Yellow
        az network application-gateway frontend-port create `
            --gateway-name $appGwName `
            --resource-group $mcResourceGroup `
            --name httpsPort `
            --port 443 2>&1 | Out-Null
        if ($LASTEXITCODE -ne 0) {
            # Secondary guard: if failure due to duplicate or already in use, continue; else abort
            $dupCheck = az network application-gateway frontend-port list --gateway-name $appGwName --resource-group $mcResourceGroup -o json 2>$null | ConvertFrom-Json
            if ($dupCheck | Where-Object { $_.port -eq 443 }) {
                Write-Host "Detected existing 443 port after create attempt; proceeding idempotently" -ForegroundColor Yellow
            } else {
                Write-Warning "HTTPS port creation failed and port 443 not found in list; continuing—cert-manager will still provision TLS on ingress."
            }
        } else {
            Write-Host "HTTPS port added" -ForegroundColor Green
        }
    }

    Write-Host "Application Gateway configured for HTTPS - Let's Encrypt certificates will be managed by cert-manager" -ForegroundColor Green
    Write-Host "Note: SSL certificates will be automatically provisioned when the ingress is deployed" -ForegroundColor Yellow
} else {
    Write-Host "DRY RUN: Would configure (or verify existing) Application Gateway HTTPS port (443) and rely on cert-manager" -ForegroundColor Cyan
}

# Step 4: OAuth2 Authentication Setup
if ($UseOAuth2) {
    Write-Host "`n🔐 Step 4: Setting up OAuth2 Authentication..." -ForegroundColor Yellow
    Write-Host "===============================================" -ForegroundColor Yellow

    if (-not $DryRun) {
        $oauth2Args = @{
            ResourceGroupName = $ResourceGroupName
            Domain            = $Domain
            Namespace         = $Namespace
            HostPrefix        = $HostPrefix
        }
        if ($ServiceTreeId) { $oauth2Args.ServiceTreeId = $ServiceTreeId }
        & (Join-Path $PSScriptRoot 'setup-oauth2.ps1') @oauth2Args
        Test-LastCommand "OAuth2 authentication setup failed"
        Write-Host "OAuth2 authentication configured successfully" -ForegroundColor Green
    } else {
        Write-Host "DRY RUN: Would setup OAuth2 authentication" -ForegroundColor Cyan
    }
} else {
    Write-Host "`n⏭️  Step 4: Skipping OAuth2 Authentication (using Application Gateway auth)" -ForegroundColor Yellow
    Write-Host "============================================================================" -ForegroundColor Yellow
}

# Step 5: DNS Configuration Check and Prompt
Write-Host "`n🌐 Step 5: DNS Configuration Verification..." -ForegroundColor Yellow
Write-Host "=============================================" -ForegroundColor Yellow

if (-not $DryRun) {
    # Get the Application Gateway IP
    $appGwIp = az network public-ip show --resource-group $mcResourceGroup --name "$appGwName-appgwpip" --query "ipAddress" -o tsv 2>$null
    
    if ($appGwIp) {
        Write-Host "Your Application Gateway IP is: $appGwIp" -ForegroundColor Green
        Write-Host ""
        Write-Host "REQUIRED DNS CONFIGURATION:" -ForegroundColor Red
        Write-Host "Before continuing, you MUST configure DNS:" -ForegroundColor Yellow
    Write-Host "  1. Add an A record in your $Domain DNS zone:" -ForegroundColor Cyan
    Write-Host "     Name: $HostPrefix" -ForegroundColor White
        Write-Host "     Type: A" -ForegroundColor White
        Write-Host "     Value: $appGwIp" -ForegroundColor White
        Write-Host "     TTL: 300" -ForegroundColor White
        Write-Host ""
        Write-Host "  2. Wait for DNS propagation (usually 1-5 minutes)" -ForegroundColor Cyan
    Write-Host "  3. Test with: nslookup $hostname" -ForegroundColor Cyan
        Write-Host ""
        
        # Test current DNS resolution
        Write-Host "Testing current DNS resolution..." -ForegroundColor Yellow
        try {
            $dnsResult = Resolve-DnsName -Name $hostname -ErrorAction Stop
            $resolvedIp = $dnsResult.IPAddress
            Write-Host "DNS currently resolves to: $resolvedIp" -ForegroundColor Green
            
            if ($resolvedIp -eq $appGwIp) {
                Write-Host "✅ DNS is correctly configured!" -ForegroundColor Green
            } else {
                Write-Host "❌ DNS mismatch: Expected $appGwIp, got $resolvedIp" -ForegroundColor Red
                Write-Host "Please update your DNS A record and wait for propagation." -ForegroundColor Yellow
            }
        } catch {
            Write-Host "❌ DNS resolution failed - $hostname does not resolve" -ForegroundColor Red
            Write-Host "Please add the DNS A record as shown above." -ForegroundColor Yellow
        }
        
        Write-Host ""
        Write-Host "Press ENTER to continue once DNS is configured, or Ctrl+C to abort..." -ForegroundColor Yellow
        Read-Host
        
        # Verify DNS again after user confirmation
        Write-Host "Verifying DNS configuration..." -ForegroundColor Yellow
        try {
            $dnsResult = Resolve-DnsName -Name $hostname -ErrorAction Stop
            $resolvedIp = $dnsResult.IPAddress
            
            if ($resolvedIp -eq $appGwIp) {
                Write-Host "✅ DNS verification successful!" -ForegroundColor Green
            } else {
                Write-Host "⚠️  DNS still shows mismatch but continuing..." -ForegroundColor Yellow
                Write-Host "Expected: $appGwIp, Got: $resolvedIp" -ForegroundColor Yellow
            }
        } catch {
            Write-Host "⚠️  DNS still not resolving but continuing..." -ForegroundColor Yellow
        }
    } else {
        Write-Host "❌ Could not retrieve Application Gateway IP" -ForegroundColor Red
    }
} else {
    Write-Host "DRY RUN: Would verify DNS configuration" -ForegroundColor Cyan
}

# Step 6: Secrets Creation
Write-Host "`n🔑 Step 6: Creating Application Secrets..." -ForegroundColor Yellow
Write-Host "===========================================" -ForegroundColor Yellow

if (-not $DryRun) {
    # Create secrets using the dedicated script
    Write-Host "Generating application secrets..." -ForegroundColor Yellow
    # Determine app name early (prefer explicit; else from values; else fallback to namespace)
    $resolvedAppName = if ($AppName) { $AppName } else { $null }
    $valuesPathEarly = Join-Path $PSScriptRoot 'values.yaml'
    if (-not $resolvedAppName -and (Test-Path $valuesPathEarly)) {
        try {
            $valuesRawEarly = Get-Content $valuesPathEarly -Raw
            $appNameMatch = $valuesRawEarly | Select-String 'appName: "([^"]+)"'
            if ($appNameMatch -and $appNameMatch.Matches -and $appNameMatch.Matches.Count -gt 0) {
                $resolvedAppName = $appNameMatch.Matches[0].Groups[1].Value
            }
        } catch {}
    }
    if (-not $resolvedAppName) { $resolvedAppName = $Namespace }

    # If a secrets.yaml exists and contains a distinct name, align to it to avoid mismatch
    $secretsPathPeek = Join-Path $PSScriptRoot 'secrets.yaml'
    if (Test-Path $secretsPathPeek) {
        try {
            $secretsRaw = Get-Content $secretsPathPeek -Raw
            $nameMatch = $secretsRaw | Select-String '(?m)^\s*name:\s*([A-Za-z0-9-]+)-secrets\s*$'
            if ($nameMatch -and $nameMatch.Matches.Count -gt 0) {
                $secretBase = $nameMatch.Matches[0].Groups[1].Value
                if ($secretBase -and ($secretBase -ne $resolvedAppName)) {
                    Write-Host "Aligning app name to secrets file base '$secretBase'" -ForegroundColor Yellow
                    $resolvedAppName = $secretBase
                }
            }
        } catch {}
    }

    & (Join-Path $PSScriptRoot 'create-secrets.ps1') -ResourceGroupName $ResourceGroupName -Namespace $Namespace -AppName $resolvedAppName
    Test-LastCommand "Secrets creation failed"
    Write-Host "Application secrets created successfully" -ForegroundColor Green

    # NEW: Immediately apply secrets to cluster (idempotent) before any app deployment
    $secretsPath = Join-Path $PSScriptRoot 'secrets.yaml'
    if (Test-Path $secretsPath) {
        Write-Host "Applying Kubernetes secrets file to namespace '$Namespace'..." -ForegroundColor Yellow
        kubectl apply -f $secretsPath -n $Namespace | Out-Null
        Test-LastCommand "Failed to apply secrets.yaml to cluster"
        # Verify secret exists
        $primarySecretName = "$resolvedAppName-secrets"
        $null = kubectl get secret $primarySecretName -n $Namespace -o name
        if ($LASTEXITCODE -ne 0) {
            Write-Error "Secret $primarySecretName not found in namespace '$Namespace' after apply"
            exit 1
        }
        Write-Host "✅ Kubernetes secret '$primarySecretName' present in namespace '$Namespace'" -ForegroundColor Green

        # Compatibility: if some manifests expect 'respondr-secrets', ensure an alias exists
        $compatSecretName = 'respondr-secrets'
        $null = kubectl get secret $compatSecretName -n $Namespace -o name
        if ($LASTEXITCODE -ne 0) {
            Write-Host "Creating compatibility secret '$compatSecretName' from '$primarySecretName'..." -ForegroundColor Yellow
            $srcSecretYaml = kubectl get secret $primarySecretName -n $Namespace -o yaml
            if ($LASTEXITCODE -eq 0 -and $srcSecretYaml) {
                $dupYaml = $srcSecretYaml -replace '(?m)^  name:\s*.+-secrets\s*$', "  name: $compatSecretName"
                $dupYaml | kubectl apply -f - -n $Namespace | Out-Null
                if ($LASTEXITCODE -eq 0) {
                    Write-Host "✅ Created '$compatSecretName' for compatibility" -ForegroundColor Green
                } else {
                    Write-Warning "Failed to create compatibility secret '$compatSecretName'"
                }
            }
        }
    } else {
        Write-Warning "secrets.yaml not found at $secretsPath"
        
        # For non-main namespaces (e.g., preprod), try copying secrets from primary namespace
        if ($Namespace -ne "respondr") {
            Write-Host "Attempting to copy secrets from main namespace 'respondr' to '$Namespace'..." -ForegroundColor Yellow
            $resolvedAppName = if ($AppName) { $AppName } else { $Namespace }
            $mainSecret = kubectl get secret "$resolvedAppName-secrets" -n respondr -o yaml 2>$null
            if ($mainSecret) {
                # Replace namespace and apply to target namespace
                $preprodSecret = $mainSecret -replace 'namespace: respondr', "namespace: $Namespace"
                $preprodSecret | kubectl apply -f - | Out-Null
                Test-LastCommand "Failed to copy secret from main namespace"
                Write-Host "✅ Secret copied from main namespace to '$Namespace'" -ForegroundColor Green
            } else {
                Write-Error "No secrets found in main namespace 'respondr' to copy from"
                exit 1
            }
        } else {
            Write-Error "Expected secrets.yaml at $secretsPath but file not found"
            exit 1
        }
    }
} else {
    Write-Host "DRY RUN: Would create application secrets" -ForegroundColor Cyan
}

# Step 7: Generate Values and Process Templates
Write-Host "`n📋 Step 7: Generating deployment configuration from environment..." -ForegroundColor Yellow
Write-Host "=================================================================" -ForegroundColor Yellow

if (-not $DryRun) {
    # Generate values.yaml from current Azure environment
    Write-Host "Generating values.yaml from current Azure environment..." -ForegroundColor Yellow
    $genArgs = @{
        ResourceGroupName = $ResourceGroupName
        Domain            = $Domain
        Namespace         = $Namespace
        HostPrefix        = $HostPrefix
        ImageTag          = $ImageTag
    }
    # Always pass the resolved app name so values.yaml stays aligned with secrets/app resources
    $genArgs.AppName = $resolvedAppName
    if ($AllowedEmailDomains) { $genArgs.AllowedEmailDomains = $AllowedEmailDomains }
    if ($AllowedAdminUsers)   { $genArgs.AllowedAdminUsers   = $AllowedAdminUsers }
    & (Join-Path $PSScriptRoot 'generate-values.ps1') @genArgs
    Test-LastCommand "Failed to generate values from environment"
    Write-Host "Values generated successfully" -ForegroundColor Green
    
    # If OAuth2 is disabled, force useOAuth2: "false" in values.yaml so template removes oauth2-proxy
    if (-not $UseOAuth2) {
        try {
            $valuesPath = Join-Path $PSScriptRoot 'values.yaml'
            if (Test-Path $valuesPath) {
                $raw = Get-Content $valuesPath -Raw
                if ($raw -match '(?m)^\s*useOAuth2\s*:') {
                    $raw = [regex]::Replace($raw, '(?m)^\s*useOAuth2\s*:\s*"?[^"\r\n]*"?', 'useOAuth2: "false"')
                } else {
                    $raw += "`nuseOAuth2: `"false`"`n"
                }
                $raw | Out-File -FilePath $valuesPath -Encoding UTF8
                Write-Host "Set useOAuth2=false in values.yaml (DisableOAuth2 requested)" -ForegroundColor Yellow
            }
        } catch {
            Write-Warning "Could not update useOAuth2 in values.yaml: $_"
        }
    }

    # Process template to generate deployment file
    Write-Host "Processing deployment template..." -ForegroundColor Yellow
    $templateFile = Join-Path $PSScriptRoot "respondr-k8s-unified-template.yaml"
    $outputFile = Join-Path $PSScriptRoot "respondr-k8s-generated.yaml"
    
    & (Join-Path $PSScriptRoot 'process-template.ps1') -TemplateFile $templateFile -OutputFile $outputFile
    Test-LastCommand "Failed to process deployment template"
    Write-Host "Deployment file generated from template" -ForegroundColor Green
} else {
    Write-Host "DRY RUN: Would generate values and process templates" -ForegroundColor Cyan
}

# Step 8: Application Deployment
Write-Host "`n📦 Step 8: Deploying Application with Authentication..." -ForegroundColor Yellow
Write-Host "======================================================" -ForegroundColor Yellow

if (-not $DryRun) {
    # Build and push Docker image if not skipped
    if (-not $SkipImageBuild) {
        Write-Host "Building and pushing Docker image..." -ForegroundColor Yellow
        
        # Get ACR details from values
        $valuesContent = Get-Content "values.yaml" -Raw
        $acrName = ($valuesContent | Select-String "acrName: `"([^`"]+)`"").Matches[0].Groups[1].Value
        $acrLoginServer = ($valuesContent | Select-String "acrLoginServer: `"([^`"]+)`"").Matches[0].Groups[1].Value
        $imageTag = ($valuesContent | Select-String "imageTag: `"([^`"]+)`"").Matches[0].Groups[1].Value
    # Determine app name from values.yaml for tagging
    $appNameFromValues = ($valuesContent | Select-String 'appName: "([^"]+)"').Matches[0].Groups[1].Value
    if (-not $appNameFromValues) { $appNameFromValues = 'respondr' }
    $fullImageName = "$acrLoginServer/${appNameFromValues}:$imageTag"
        
        # Navigate to project root
        $projectRoot = Split-Path $PSScriptRoot -Parent
        $originalLocation = Get-Location
        
        try {
            Set-Location $projectRoot
            Write-Host "Building from: $projectRoot" -ForegroundColor Cyan
            
            # Login to ACR
            az acr login --name $acrName | Out-Null
            Test-LastCommand "Failed to login to ACR"
            
            # Ensure AKS can pull from ACR (safe to run multiple times)
            Write-Host "Ensuring AKS cluster can pull from ACR..." -ForegroundColor Yellow
            $aksCluster = az aks list -g $ResourceGroupName --query "[0].name" -o tsv
            if ($aksCluster) {
                az aks update -g $ResourceGroupName -n $aksCluster --attach-acr $acrName | Out-Null
                if ($LASTEXITCODE -eq 0) {
                    Write-Host "✅ ACR attached to AKS cluster" -ForegroundColor Green
                } else {
                    Write-Warning "Failed to attach ACR to AKS (may already be attached)"
                }
            }
            
            # Build and push Docker image with correct tag
            docker build -t "${appNameFromValues}:$imageTag" -t $fullImageName .
            Test-LastCommand "Docker build failed"
            
            docker push $fullImageName
            Test-LastCommand "Docker push failed"
            
            Write-Host "Docker image built and pushed successfully" -ForegroundColor Green
        } finally {
            Set-Location $originalLocation
        }
    }
    else {
        # Even if skipping build, ensure AKS has pull permissions to ACR
        try {
            $valuesContent = Get-Content "values.yaml" -Raw
            $acrName = ($valuesContent | Select-String 'acrName: "([^"]+)"').Matches[0].Groups[1].Value
            Write-Host "Ensuring AKS cluster can pull from ACR (skip build path)..." -ForegroundColor Yellow
            $aksCluster = az aks list -g $ResourceGroupName --query "[0].name" -o tsv
            if ($aksCluster) {
                az aks update -g $ResourceGroupName -n $aksCluster --attach-acr $acrName | Out-Null
                if ($LASTEXITCODE -eq 0) {
                    Write-Host "✅ ACR attached to AKS cluster" -ForegroundColor Green
                } else {
                    Write-Warning "Failed to attach ACR to AKS (may already be attached)"
                }
            }
        } catch {
            Write-Warning "Could not ensure AKS has pull permission to ACR: $_"
        }
    }
    
    # Deploy Redis first
    Write-Host "Deploying Redis for shared storage..." -ForegroundColor Yellow
    kubectl apply -f (Join-Path $PSScriptRoot 'redis-deployment.yaml') -n $Namespace
    Test-LastCommand "Failed to deploy Redis"
    
    # Wait for Redis to be ready
    kubectl wait --for=condition=available --timeout=120s deployment/redis -n $Namespace
    if ($LASTEXITCODE -ne 0) {
        Write-Warning "Redis deployment may not be fully ready, continuing..."
    } else {
        Write-Host "Redis deployment is ready" -ForegroundColor Green
    }
    
    # Deploy the generated application configuration
    Write-Host "Deploying application..." -ForegroundColor Yellow
    # Preflight: ensure required secret exists (defensive check)
    # Re-evaluate app name late to align with processed template
    $resolvedAppName = $null
    try {
        $valuesRawLate = Get-Content (Join-Path $PSScriptRoot 'values.yaml') -Raw
        $m = ($valuesRawLate | Select-String 'appName: "([^"]+)"').Matches
        if ($m.Count -gt 0) { $resolvedAppName = $m[0].Groups[1].Value }
    } catch {}
    if (-not $resolvedAppName) { $resolvedAppName = $Namespace }

    # Ensure the "$resolvedAppName-secrets" exists; if missing, attempt a safe alignment ONLY if a single non-oauth2 candidate exists
    $null = kubectl get secret "$resolvedAppName-secrets" -n $Namespace -o name 2>$null
    if ($LASTEXITCODE -ne 0) {
        # Gather candidate app secrets (exclude oauth2 and TLS/helm/etc.)
        $secretNames = kubectl get secret -n $Namespace -o jsonpath="{range .items[*]}{.metadata.name}{'\n'}{end}" 2>$null
        $candidates = @()
        if ($secretNames) {
            foreach ($sn in ($secretNames -split "`n")) {
                if ($sn -match '^[a-z0-9-]+-secrets$' -and $sn -ne 'oauth2-secrets' -and $sn -notmatch '^sh\.helm\.' -and $sn -notmatch 'tls' -and $sn.Trim()) {
                    $candidates += $sn
                }
            }
        }
        if ($candidates.Count -eq 1) {
            $candidateBase = $candidates[0].Substring(0, $candidates[0].Length - '-secrets'.Length)
            Write-Host "Aligning to existing app secret '$($candidates[0])' for deployment (appName='$candidateBase')" -ForegroundColor Yellow
            $resolvedAppName = $candidateBase
        } elseif ($candidates.Count -gt 1) {
            Write-Warning "Multiple app secrets found: $($candidates -join ', '). Not auto-aligning."
        }
    }
    # Final check
    $null = kubectl get secret "$resolvedAppName-secrets" -n $Namespace -o name
    if ($LASTEXITCODE -ne 0) {
        Write-Error "Blocking deployment: required secret '$resolvedAppName-secrets' missing in namespace '$Namespace'"
        exit 1
    }
    kubectl apply -f (Join-Path $PSScriptRoot 'respondr-k8s-generated.yaml') -n $Namespace
    Test-LastCommand "Application deployment failed"
    
    # Wait for deployment to be ready
    kubectl wait --for=condition=available --timeout=300s deployment/$resolvedAppName-deployment -n $Namespace
    Test-LastCommand "Deployment did not become ready in time"
    
    Write-Host "Application deployed successfully" -ForegroundColor Green
    
    # Sync local .env file with Kubernetes secrets for development
    Write-Host "Syncing local .env file with deployed secrets..." -ForegroundColor Yellow
    & (Join-Path $PSScriptRoot 'sync-env.ps1') -Namespace $Namespace -SecretName "$resolvedAppName-secrets"
    Write-Host "Local .env file updated for development use" -ForegroundColor Green
} else {
    Write-Host "DRY RUN: Would deploy application with OAuth2 authentication" -ForegroundColor Cyan
}

# Step 9: DNS and Connectivity Verification
Write-Host "`n🌐 Step 9: DNS and Connectivity Verification..." -ForegroundColor Yellow
Write-Host "=================================================" -ForegroundColor Yellow

if (-not $DryRun) {
    # Get ingress IP
    Start-Sleep -Seconds 10  # Wait for ingress to be ready
    $ingressName = "$resolvedAppName-ingress"
    $ingressIp = kubectl get ingress $ingressName -n $Namespace -o jsonpath="{.status.loadBalancer.ingress[0].ip}" 2>$null
    
    if ($ingressIp) {
        Write-Host "Application Gateway IP: $ingressIp" -ForegroundColor Green
        
        # Test DNS resolution
        Write-Host "Testing DNS resolution..." -ForegroundColor Yellow
        try {
            $dnsResult = Resolve-DnsName -Name $hostname -ErrorAction Stop
            $resolvedIp = $dnsResult.IPAddress
            Write-Host "DNS resolves to: $resolvedIp" -ForegroundColor Green
            
            if ($resolvedIp -eq $ingressIp) {
                Write-Host "DNS is correctly configured" -ForegroundColor Green
            } else {
                Write-Host "⚠️  DNS mismatch: Expected $ingressIp, got $resolvedIp" -ForegroundColor Yellow
                Write-Host "Please update your DNS A record:" -ForegroundColor Yellow
                Write-Host "  Type: A" -ForegroundColor Cyan
                Write-Host "  Name: $HostPrefix" -ForegroundColor Cyan
                Write-Host "  Value: $ingressIp" -ForegroundColor Cyan
            }
        } catch {
            Write-Host "❌ DNS resolution failed" -ForegroundColor Red
            Write-Host "Please add DNS A record:" -ForegroundColor Yellow
            Write-Host "  Type: A" -ForegroundColor Cyan
            Write-Host "  Name: $HostPrefix" -ForegroundColor Cyan
            Write-Host "  Value: $ingressIp" -ForegroundColor Cyan
        }
        
        # Test HTTP connectivity (unauthenticated health endpoint)
        Write-Host "Testing HTTP connectivity (health endpoint)..." -ForegroundColor Yellow
        try {
            $response = Invoke-WebRequest -Uri "http://$hostname/health" -UseBasicParsing -TimeoutSec 10
            Write-Host "HTTP /health successful (Status: $($response.StatusCode))" -ForegroundColor Green
        } catch {
            Write-Host "❌ HTTP /health failed: $($_.Exception.Message)" -ForegroundColor Red
        }
        
        # Test HTTPS connectivity (unauthenticated health endpoint)
        Write-Host "Testing HTTPS connectivity (health endpoint)..." -ForegroundColor Yellow
        try {
            $response = Invoke-WebRequest -Uri "https://$hostname/health" -UseBasicParsing -TimeoutSec 10 -SkipCertificateCheck
            Write-Host "HTTPS /health successful (Status: $($response.StatusCode))" -ForegroundColor Green
        } catch {
            Write-Host "❌ HTTPS /health failed: $($_.Exception.Message)" -ForegroundColor Red
            Write-Host "Note: HTTPS may take a few minutes to become available after certificate setup" -ForegroundColor Yellow
        }
    } else {
        Write-Host "❌ Could not get ingress IP address" -ForegroundColor Red
    }
} else {
    Write-Host "DRY RUN: Would verify DNS and connectivity" -ForegroundColor Cyan
}

# Summary
Write-Host "`nDeployment Summary" -ForegroundColor Green
Write-Host "=====================" -ForegroundColor Green

if (-not $DryRun) {
    Write-Host "Infrastructure: Deployed" -ForegroundColor Green
    Write-Host "AGIC: Configured" -ForegroundColor Green
    Write-Host "Let's Encrypt Setup: Configured via cert-manager" -ForegroundColor Green
    if ($UseOAuth2) {
        Write-Host "OAuth2 Authentication: Configured with Azure AD" -ForegroundColor Green
        Write-Host "Application: Deployed with oauth2-proxy" -ForegroundColor Green
    } else {
        Write-Host "OAuth2 Authentication: Disabled (using direct backend access)" -ForegroundColor Yellow
        Write-Host "Application: Deployed without oauth2-proxy (service targets port 8000)" -ForegroundColor Green
    }
    Write-Host ""
    Write-Host "🌐 Access Information:" -ForegroundColor Cyan
    Write-Host "  HTTP:  http://$hostname (redirects to HTTPS)" -ForegroundColor White
    Write-Host "  HTTPS: https://$hostname" -ForegroundColor White
    Write-Host "  Health: https://$hostname/health" -ForegroundColor White
    Write-Host "  API:   https://$hostname/api/responders" -ForegroundColor White
    Write-Host ""
    Write-Host "🪝 ACR Webhook: Configure ACR to POST to https://$hostname/internal/acr-webhook on push" -ForegroundColor Cyan
    Write-Host "  Header: X-ACR-Token with the value from deployment/secrets.yaml (ACR_WEBHOOK_TOKEN)" -ForegroundColor White
    Write-Host "  Action: Push; Repo: $resolvedAppName" -ForegroundColor White
    Write-Host "" 
    if ($UseOAuth2) {
        Write-Host "🔐 Authentication:" -ForegroundColor Cyan
        Write-Host "  - OAuth2 Proxy with Azure AD authentication is ENABLED" -ForegroundColor White
        Write-Host "  - Users WILL be challenged to sign in with Entra/Azure AD" -ForegroundColor White
        Write-Host "  - Authentication is handled by oauth2-proxy sidecar container" -ForegroundColor White
        Write-Host "  - No application code changes required" -ForegroundColor White
    } else {
        Write-Host "🔐 Authentication: DISABLED (direct access)" -ForegroundColor Yellow
    }
    Write-Host ""
    Write-Host "🔒 SSL Certificates:" -ForegroundColor Cyan
    Write-Host "  - Let's Encrypt certificates will be automatically provisioned" -ForegroundColor White
    Write-Host "  - Initial certificate request may take a few minutes" -ForegroundColor White
    Write-Host "  - Check certificate status: kubectl get certificate -n $Namespace" -ForegroundColor White
    Write-Host ""
    Write-Host "📝 Next Steps:" -ForegroundColor Cyan
    Write-Host "  1. Ensure DNS A record: $hostname → $ingressIp" -ForegroundColor White
    Write-Host "  2. Wait for Let's Encrypt certificate to be issued (2-10 minutes)" -ForegroundColor White
    Write-Host "  3. Test in browser: https://$hostname" -ForegroundColor White
    Write-Host "  4. Verify OAuth2 authentication redirects to Microsoft sign-in" -ForegroundColor White
    Write-Host "  5. Test API access after authentication: https://$hostname/api/responders" -ForegroundColor White
    Write-Host ""
    Write-Host "Certificate Status Commands:" -ForegroundColor Cyan
    Write-Host "  kubectl get certificate -n $Namespace" -ForegroundColor White
    Write-Host "  kubectl describe certificate $resolvedAppName-tls-letsencrypt -n $Namespace" -ForegroundColor White
    Write-Host "  kubectl get certificaterequests -n $Namespace" -ForegroundColor White
} else {
    Write-Host "DRY RUN completed - no changes made" -ForegroundColor Cyan
}

Write-Host ""
Write-Host "Deployment completed!" -ForegroundColor Green

if ($SetupAcrWebhook -and -not $DryRun) {
    Write-Host "\n🪝 Configuring ACR webhook..." -ForegroundColor Yellow
    
    # Determine environment from HostPrefix
    $Environment = if ($HostPrefix -eq "respondr-preprod") { "preprod" } else { "main" }
    
    & (Join-Path $PSScriptRoot 'configure-acr-webhook.ps1') -ResourceGroupName $ResourceGroupName -Domain $Domain -Environment $Environment -HostPrefix $HostPrefix
}

# Optional: Configure GitHub OIDC and repo secrets
if ($SetupGithubOidc -and -not $DryRun) {
    if (-not $GithubRepo) {
        Write-Warning "SetupGithubOidc requested but GithubRepo not provided (expected format owner/repo). Skipping."
    } else {
        Write-Host "\n🔐 Configuring GitHub OIDC + secrets for $GithubRepo ..." -ForegroundColor Yellow
        # Try to pass ACR name if we can resolve it from values.yaml
        $acrNameForOidc = $null
        $valuesPath = Join-Path $PSScriptRoot 'values.yaml'
        if (Test-Path $valuesPath) {
            try {
                $valuesRaw = Get-Content $valuesPath -Raw
                $acrNameForOidc = ($valuesRaw | Select-String 'acrName: "([^"]+)"').Matches[0].Groups[1].Value
            } catch {}
        }
        if ($acrNameForOidc) {
            & (Join-Path $PSScriptRoot 'setup-github-oidc.ps1') -ResourceGroupName $ResourceGroupName -Repo $GithubRepo -AcrName $acrNameForOidc -Branch "main,preprod"
        } else {
            & (Join-Path $PSScriptRoot 'setup-github-oidc.ps1') -ResourceGroupName $ResourceGroupName -Repo $GithubRepo -Branch "main,preprod"
        }
    }
}





