<#
.SYNOPSIS
    Post-deployment configuration for the respondr app.

.DESCRIPTION
    - Fetches deployment outputs (AKS cluster name, ACR name, OpenAI account name)
    - Gets AKS credentials
    - Attaches ACR to AKS (if present)
    - Imports a test image into ACR
    - Deploys a test pod in AKS to verify ACR integration
    - Checks the provisioning state of OpenAI & Storage accounts
#>

param (
    [Parameter(Mandatory)][string]$ResourceGroupName,
    [Parameter()][string]$Location = "westus"
)

Write-Host "Starting post-deployment configuration..." -ForegroundColor Green

# 1) Retrieve deployment outputs
Write-Host "Retrieving deployment outputs..." -ForegroundColor Yellow
$deploy = az deployment group show `
    --resource-group $ResourceGroupName `
    --name main -o json | ConvertFrom-Json

# Assumes your Bicep defines outputs: aksClusterName, acrName, openAiAccountName
$aksClusterName     = $deploy.properties.outputs.aksClusterName.value
$acrName            = $deploy.properties.outputs.acrName.value
$openAiAccountName  = $deploy.properties.outputs.openAiAccountName.value
$podIdentityName    = $deploy.properties.outputs.podIdentityName.value
$podIdentityClientId= $deploy.properties.outputs.podIdentityClientId.value
$podIdentityId      = $deploy.properties.outputs.podIdentityResourceId.value
$vnetName           = $deploy.properties.outputs.vnetName.value
$appGwSubnetName    = $deploy.properties.outputs.appGwSubnetName.value

if (-not $aksClusterName)    { throw "Missing aksClusterName output!" }
if (-not $openAiAccountName) { throw "Missing openAiAccountName output!" }

# 2) Get Storage account name dynamically (if you didn’t output it)
$storageAccountName = az storage account list `
    --resource-group $ResourceGroupName `
    --query "[0].name" -o tsv

Write-Host "  AKS Cluster:  $aksClusterName"
Write-Host "  ACR:          $($acrName  -or '<none found>')"
Write-Host "  OpenAIAcct:   $openAiAccountName"
Write-Host "  StorageAcct:  $storageAccountName"
Write-Host "  PodIdentity:  $podIdentityName"

# 3) AKS credentials
Write-Host "`nGetting AKS credentials..." -ForegroundColor Yellow
az aks get-credentials `
    --resource-group $ResourceGroupName `
    --name $aksClusterName `
    --overwrite-existing

# 3.5) Create dedicated namespace and configure workload identity
Write-Host "`nCreating dedicated namespace for respondr..." -ForegroundColor Yellow
kubectl create namespace respondr --dry-run=client -o yaml | kubectl apply -f -

Write-Host "`nEnsuring user-assigned managed identity and workload identity setup..." -ForegroundColor Yellow
$identity = az identity show --name $podIdentityName --resource-group $ResourceGroupName -o json 2>$null | ConvertFrom-Json
if (-not $identity) {
    Write-Host "Creating user-assigned identity '$podIdentityName'..." -ForegroundColor Yellow
    $identity = az identity create --name $podIdentityName --resource-group $ResourceGroupName -o json | ConvertFrom-Json
    $podIdentityClientId = $identity.clientId
    $podIdentityId       = $identity.id
} else {
    Write-Host "User-assigned identity '$podIdentityName' already exists." -ForegroundColor Green
}

# Assign necessary roles to the managed identity
Write-Host "Assigning roles to user-assigned managed identity..." -ForegroundColor Yellow
$storageAccountId = az storage account show --name $storageAccountName --resource-group $ResourceGroupName --query id -o tsv
$openAiAccountId = az cognitiveservices account show --name $openAiAccountName --resource-group $ResourceGroupName --query id -o tsv

# Storage Blob Data Contributor role for accessing storage
az role assignment create `
    --assignee $podIdentityClientId `
    --role "Storage Blob Data Contributor" `
    --scope $storageAccountId 2>$null

# Cognitive Services OpenAI User role for accessing OpenAI
az role assignment create `
    --assignee $podIdentityClientId `
    --role "Cognitive Services OpenAI User" `
    --scope $openAiAccountId 2>$null

Write-Host "Enabling OIDC and workload identity on AKS cluster..." -ForegroundColor Yellow
az aks update --name $aksClusterName --resource-group $ResourceGroupName --enable-oidc-issuer --enable-workload-identity

# Check if workload identity webhook is deployed
Write-Host "Checking workload identity webhook deployment..." -ForegroundColor Yellow
$webhookPods = kubectl get pods -n kube-system -l app=azure-workload-identity-webhook-mutator -o json | ConvertFrom-Json
if ($webhookPods.items.Count -gt 0) {
    Write-Host "Workload identity webhook is deployed" -ForegroundColor Green
} else {
    Write-Host "Warning: Workload identity webhook not found. May need manual installation on older AKS versions." -ForegroundColor Yellow
}

$issuer = az aks show --name $aksClusterName --resource-group $ResourceGroupName --query "oidcIssuerProfile.issuerUrl" -o tsv
$ficName = "respondr-fic"

# Create federated credential with templated namespace
az identity federated-credential create `
    --name $ficName `
    --identity-name $podIdentityName `
    --resource-group $ResourceGroupName `
    --issuer $issuer `
    --subject "system:serviceaccount:respondr:respondr-sa" `
    --audience "api://AzureADTokenExchange" 2>$null

# Create service account in the respondr namespace
kubectl create serviceaccount respondr-sa -n respondr --dry-run=client -o yaml | kubectl apply -f -
kubectl annotate serviceaccount respondr-sa -n respondr azure.workload.identity/client-id=$podIdentityClientId --overwrite

# Get tenant ID for optional annotation
$tenantId = az account show --query tenantId -o tsv
kubectl annotate serviceaccount respondr-sa -n respondr azure.workload.identity/tenant-id=$tenantId --overwrite

# 4) Attach ACR (if one exists)
if ($acrName) {
    Write-Host "`nAttaching ACR '$acrName' to AKS cluster..." -ForegroundColor Yellow
    az aks update `
        --name $aksClusterName `
        --resource-group $ResourceGroupName `
        --attach-acr $acrName
} else {
    Write-Host "`nNo ACR name found—skipping attach step." -ForegroundColor Cyan
}

# 5) Enable AGIC with Microsoft Entra authentication and cert-manager for Let's Encrypt
Write-Host "`nInstalling cert-manager for Let's Encrypt certificates..." -ForegroundColor Yellow

# Check if cert-manager is already installed
$certManagerInstalled = kubectl get pods -n cert-manager 2>$null
if (-not $certManagerInstalled) {
    Write-Host "Installing cert-manager..." -ForegroundColor Yellow
    kubectl apply -f https://github.com/cert-manager/cert-manager/releases/download/v1.14.4/cert-manager.yaml
    
    # Wait for cert-manager to be ready
    Write-Host "Waiting for cert-manager pods to be ready..." -ForegroundColor Yellow
    kubectl wait --for=condition=Ready pod -l app.kubernetes.io/instance=cert-manager -n cert-manager --timeout=300s
    Write-Host "cert-manager installed successfully!" -ForegroundColor Green
} else {
    Write-Host "cert-manager is already installed" -ForegroundColor Green
}

# Apply Let's Encrypt ClusterIssuer
Write-Host "Creating Let's Encrypt ClusterIssuer..." -ForegroundColor Yellow
$letsencryptIssuerPath = Join-Path $PSScriptRoot "letsencrypt-issuer.yaml"
if (Test-Path $letsencryptIssuerPath) {
    kubectl apply -f $letsencryptIssuerPath
    Write-Host "Let's Encrypt ClusterIssuer created successfully!" -ForegroundColor Green
} else {
    Write-Host "Warning: letsencrypt-issuer.yaml not found at $letsencryptIssuerPath" -ForegroundColor Yellow
}

Write-Host "`nEnabling Application Gateway Ingress Controller with Microsoft Entra auth..." -ForegroundColor Yellow

# Install application-gateway-preview extension
Write-Host "Installing/updating Azure CLI application-gateway-preview extension..." -ForegroundColor Yellow
az extension add --name application-gateway-preview -y --upgrade 2>$null

$appGwName = "$aksClusterName-appgw"

# Enable AGIC addon with proper subnet configuration using existing VNet
Write-Host "Enabling AGIC addon..." -ForegroundColor Yellow
az aks enable-addons `
    --resource-group $ResourceGroupName `
    --name $aksClusterName `
    --addons ingress-appgw `
    --appgw-name $appGwName `
    --appgw-subnet-id "/subscriptions/$(az account show --query id -o tsv)/resourceGroups/$ResourceGroupName/providers/Microsoft.Network/virtualNetworks/$vnetName/subnets/$appGwSubnetName" `
    --enable-azure-rbac 2>$null

# Wait for Application Gateway to be created by AGIC
Write-Host "Waiting for Application Gateway to be ready..." -ForegroundColor Yellow

# IMPORTANT: AGIC creates Application Gateway in the MC resource group, not the main resource group!
$mcResourceGroup = "MC_$($ResourceGroupName)_$($aksClusterName)_$($Location)"
Write-Host "Monitoring Application Gateway in MC resource group: $mcResourceGroup" -ForegroundColor Cyan

# First, wait for AGIC deployment to start
Write-Host "Waiting for AGIC to start Application Gateway deployment..." -ForegroundColor Yellow
$deploymentStartTimeout = (Get-Date).AddMinutes(5)
$deploymentStarted = $false

do {
    Start-Sleep -Seconds 30
    $deploymentStatus = az deployment group show --resource-group $mcResourceGroup --name $appGwName --query "properties.provisioningState" -o tsv 2>$null
    if ($deploymentStatus) {
        Write-Host "AGIC started Application Gateway deployment: $deploymentStatus" -ForegroundColor Green
        $deploymentStarted = $true
        break
    }
    Write-Host "Waiting for AGIC to start Application Gateway deployment..." -ForegroundColor Yellow
} while ((Get-Date) -lt $deploymentStartTimeout)

if (-not $deploymentStarted) {
    Write-Host "Warning: AGIC has not started Application Gateway deployment within timeout" -ForegroundColor Yellow
    Write-Host "Check AGIC pod logs: kubectl logs -n kube-system deployment/ingress-appgw-deployment" -ForegroundColor Yellow
}

# Wait for deployment to complete
$deploymentTimeout = (Get-Date).AddMinutes(10)
do {
    Start-Sleep -Seconds 30
    $deploymentStatus = az deployment group show --resource-group $mcResourceGroup --name $appGwName --query "properties.provisioningState" -o tsv 2>$null
    Write-Host "Application Gateway deployment status: $deploymentStatus" -ForegroundColor Cyan
    
    if ($deploymentStatus -eq "Succeeded") {
        Write-Host "Application Gateway deployment completed successfully!" -ForegroundColor Green
        break
    } elseif ($deploymentStatus -eq "Failed") {
        Write-Host "Application Gateway deployment failed!" -ForegroundColor Red
        $deploymentError = az deployment group show --resource-group $mcResourceGroup --name $appGwName --query "properties.error" -o json 2>$null
        if ($deploymentError -and $deploymentError -ne "null") {
            Write-Host "Deployment error: $deploymentError" -ForegroundColor Red
        }
        break
    }
} while ((Get-Date) -lt $deploymentTimeout)

# Wait for Application Gateway resource to be fully provisioned
Write-Host "Waiting for Application Gateway resource to be ready..." -ForegroundColor Yellow
$resourceTimeout = (Get-Date).AddMinutes(5)
do {
    Start-Sleep -Seconds 15
    $appGwState = az network application-gateway show --name $appGwName --resource-group $mcResourceGroup --query "provisioningState" -o tsv 2>$null
    Write-Host "Application Gateway resource state: $appGwState" -ForegroundColor Cyan
} while ($appGwState -ne "Succeeded" -and (Get-Date) -lt $resourceTimeout)

if ($appGwState -ne "Succeeded") {
    Write-Host "Warning: Application Gateway not ready within timeout" -ForegroundColor Yellow
} else {
    Write-Host "Application Gateway is ready!" -ForegroundColor Green
}

# Wait for AGIC pod to become healthy
Write-Host "Waiting for AGIC pod to be ready..." -ForegroundColor Yellow
$agicTimeout = (Get-Date).AddMinutes(5)
do {
    Start-Sleep -Seconds 15
    $agicPod = kubectl get pods -n kube-system -l app=ingress-appgw -o json 2>$null | ConvertFrom-Json
    if ($agicPod.items.Count -gt 0) {
        $podStatus = $agicPod.items[0].status
        if ($podStatus.phase -eq "Running" -and $podStatus.containerStatuses[0].ready -eq $true) {
            Write-Host "AGIC pod is running and ready!" -ForegroundColor Green
            break
        } else {
            $readyStatus = if ($podStatus.containerStatuses.Count -gt 0) { $podStatus.containerStatuses[0].ready } else { "unknown" }
            Write-Host "AGIC pod status: $($podStatus.phase), Ready: $readyStatus" -ForegroundColor Cyan
        }
    } else {
        Write-Host "AGIC pod not found" -ForegroundColor Yellow
    }
} while ((Get-Date) -lt $agicTimeout)

# Show final AGIC status
$finalAgicPod = kubectl get pods -n kube-system -l app=ingress-appgw -o json 2>$null | ConvertFrom-Json
if ($finalAgicPod.items.Count -gt 0) {
    $finalPodStatus = $finalAgicPod.items[0]
    $finalReadyStatus = if ($finalPodStatus.status.containerStatuses.Count -gt 0) { $finalPodStatus.status.containerStatuses[0].ready } else { "unknown" }
    Write-Host "Final AGIC pod status: $($finalPodStatus.status.phase), Ready: $finalReadyStatus" -ForegroundColor Cyan
    if ($finalPodStatus.status.phase -ne "Running" -or $finalReadyStatus -ne $true) {
        Write-Host "Warning: AGIC pod may not be fully ready. Check logs with: kubectl logs -n kube-system deployment/ingress-appgw-deployment" -ForegroundColor Yellow
    }
}

# Create and assign user-assigned managed identity for Application Gateway
$appGwIdentityName = "$appGwName-identity"
Write-Host "Creating user-assigned managed identity for Application Gateway..." -ForegroundColor Yellow

# Note: Application Gateway identity should be created in the MC resource group where the gateway exists
$existingAppGwIdentity = az identity show --name $appGwIdentityName --resource-group $mcResourceGroup -o json 2>$null | ConvertFrom-Json
if (-not $existingAppGwIdentity) {
    $appGwIdentity = az identity create --name $appGwIdentityName --resource-group $mcResourceGroup -o json | ConvertFrom-Json
} else {
    $appGwIdentity = $existingAppGwIdentity
    Write-Host "Using existing Application Gateway identity" -ForegroundColor Green
}
$appGwIdentityId = $appGwIdentity.id

# Assign the identity to the Application Gateway
Write-Host "Assigning identity to Application Gateway..." -ForegroundColor Yellow
az network application-gateway identity assign `
    --resource-group $mcResourceGroup `
    --gateway-name $appGwName `
    --identity $appGwIdentityId 2>$null

# Assign Network Contributor role to the identity on the MC resource group (where App Gateway exists)
Write-Host "Assigning Network Contributor role to Application Gateway identity..." -ForegroundColor Yellow
$mcResourceGroupId = az group show --name $mcResourceGroup --query id -o tsv
az role assignment create `
    --assignee $appGwIdentity.principalId `
    --role "Network Contributor" `
    --scope $mcResourceGroupId 2>$null

# Assign Managed Identity Operator role for AGIC to impersonate other identities
Write-Host "Assigning Managed Identity Operator role to AGIC..." -ForegroundColor Yellow
$agicIdentity = az aks show --name $aksClusterName --resource-group $ResourceGroupName --query "addonProfiles.ingressApplicationGateway.identity.objectId" -o tsv
if ($agicIdentity) {
    az role assignment create `
        --assignee $agicIdentity `
        --role "Managed Identity Operator" `
        --scope $appGwIdentityId 2>$null
}

# Note: Azure Application Gateway v2 (Standard_v2) does not support native Azure AD authentication
# Authentication should be implemented at the application level instead
Write-Host "Note: Azure Application Gateway v2 (Standard_v2) does not support native Azure AD authentication" -ForegroundColor Yellow
Write-Host "For authentication, consider implementing application-level auth or upgrading to Azure Front Door Premium" -ForegroundColor Yellow

# Authentication can be added at the application level using libraries like:
# - MSAL (Microsoft Authentication Library)
# - FastAPI OAuth2/OpenID Connect
# - Azure Easy Auth (if moving to App Service)

# For now, the application will be accessible without gateway-level authentication
# Implement authentication in the FastAPI backend as needed for your security requirements

# 6) Import test image into ACR
if ($acrName) {
    Write-Host "`nImporting test image to ACR..." -ForegroundColor Yellow
    $importResult = az acr import `
        --name $acrName `
        --source mcr.microsoft.com/oss/nginx/nginx:1.21.6 `
        --image nginx:test 2>&1
    
    if ($LASTEXITCODE -ne 0) {
        if ($importResult -match 'already exists') {
            Write-Host "nginx:test already exists in ACR." -ForegroundColor Green
        } else {
            Write-Host "Import failed: $importResult" -ForegroundColor Yellow
        }
    } else {
        Write-Host "Successfully imported nginx:test" -ForegroundColor Green
    }
}

# 6) Deploy and validate a test pod
Write-Host "`nDeploying test pod to verify AKS & ACR integration..." -ForegroundColor Yellow
$testPodYaml = Join-Path $PSScriptRoot "test-pod.yaml"

if (Test-Path $testPodYaml) {
    if (Get-Command kubectl -ErrorAction SilentlyContinue) {
        # Create a temporary file with the correct ACR name
        $tempYamlPath = Join-Path $env:TEMP "test-pod-temp.yaml"
        $yamlContent = Get-Content $testPodYaml -Raw
        
        if ($acrName) {
            $acrLoginServer = "$acrName.azurecr.io"
            # Replace the placeholder with the actual ACR login server
            $yamlContent = $yamlContent -replace 'ACR_PLACEHOLDER', $acrLoginServer
            Set-Content -Path $tempYamlPath -Value $yamlContent
            Write-Host "Created test pod manifest with ACR: $acrLoginServer" -ForegroundColor Green
            
            # Ensure AKS has proper access to ACR (re-verify)
            Write-Host "`nVerifying ACR access for AKS..." -ForegroundColor Yellow
            az aks update `
                --name $aksClusterName `
                --resource-group $ResourceGroupName `
                --attach-acr $acrName
            
            # Delete the pod if it already exists
            kubectl delete pod nginx-test --ignore-not-found
            
            # Dump the actual YAML that will be applied (for debugging)
            Write-Host "`nApplying pod manifest:" -ForegroundColor Yellow
            Get-Content $tempYamlPath | ForEach-Object { Write-Host "  $_" }
            
            # Deploy the test pod
            kubectl apply -f $tempYamlPath
            Write-Host "Waiting for nginx-test pod to be ready..." -ForegroundColor Yellow
            
            # Wait for the pod with more detailed status checking
            $podReady = $false
            $timeout = (Get-Date).AddSeconds(120)
            
            while (-not $podReady -and (Get-Date) -lt $timeout) {
                Start-Sleep -Seconds 5
                $podStatus = kubectl get pod nginx-test -o json | ConvertFrom-Json
                
                if ($podStatus.status.phase -eq "Running" -and 
                    $podStatus.status.containerStatuses.ready -contains $true) {
                    $podReady = $true
                    Write-Host "Test pod is running successfully." -ForegroundColor Green
                } elseif ($podStatus.status.phase -eq "Pending") {
                    # Check for image pull issues
                    $events = kubectl get events --field-selector involvedObject.name=nginx-test --sort-by='.lastTimestamp' -o json | 
                              ConvertFrom-Json
                      foreach ($event in $events.items | Where-Object { $_.type -eq "Warning" }) {
                        Write-Host "Pod warning: $($event.message)" -ForegroundColor Yellow
                    }
                    
                    # Check if we're having image pull issues
                    $containerStatus = $podStatus.status.containerStatuses
                    
                    if ($containerStatus.state.waiting.reason -in @("ImagePullBackOff", "ErrImagePull", "InvalidImageName")) {
                        Write-Host "Image pull issue detected: $($containerStatus.state.waiting.reason)" -ForegroundColor Red
                        Write-Host "    - Verifying ACR authentication..." -ForegroundColor Yellow
                        
                        # Verify we can access the ACR
                        $acrLoginCheck = az acr login --name $acrName 2>&1
                        if ($LASTEXITCODE -ne 0) {
                            Write-Host "ACR login failed: $acrLoginCheck" -ForegroundColor Red
                        } else {
                            Write-Host "ACR login successful" -ForegroundColor Green
                        }
                        
                        # List repositories in ACR to verify access and content
                        Write-Host "    - Checking ACR repositories..." -ForegroundColor Yellow
                        $repos = az acr repository list --name $acrName -o json | ConvertFrom-Json
                        Write-Host "      Repositories in ACR: $($repos -join ', ')" -ForegroundColor Cyan
                          # Check if our image exists
                        $imageExists = az acr repository show --name $acrName --image nginx:test 2>&1
                        if ($LASTEXITCODE -ne 0) {
                            Write-Host "Image 'nginx:test' not found in ACR - reimporting..." -ForegroundColor Red
                            az acr import --name $acrName --source docker.io/library/nginx:latest --image nginx:test
                        } else {
                            Write-Host "Image 'nginx:test' exists in ACR" -ForegroundColor Green
                        }
                    }
                }
                
                # Show pod status
                Write-Host "Current pod status: $($podStatus.status.phase)" -ForegroundColor Cyan
            }
            
            if ($podReady) {
                # Additional validation - check pod details
                Write-Host "`nVerifying pod details:" -ForegroundColor Yellow
                kubectl describe pod nginx-test | Select-String -Pattern "Image:|Status:|Ready:|Container ID:"
                
                # Port forward to test accessibility (in background)
                Write-Host "`nTesting pod accessibility..." -ForegroundColor Yellow
                $job = Start-Job -ScriptBlock {
                    kubectl port-forward pod/nginx-test 8080:80
                }
                
                # Wait a moment for port-forwarding to establish
                Start-Sleep -Seconds 3
                
                # Test HTTP connection
                try {
                    $response = Invoke-WebRequest -Uri http://localhost:8080 -TimeoutSec 5
                    Write-Host "Successfully connected to pod - HTTP Status: $($response.StatusCode)" -ForegroundColor Green
                } catch {
                    Write-Host "Could not connect to pod: $_" -ForegroundColor Yellow
                } finally {
                    # Clean up
                    Stop-Job -Job $job
                    Remove-Job -Job $job
                }
            } else {
                # If pod not ready, provide detailed diagnostics
                Write-Host "`nTest pod failed to start within timeout period." -ForegroundColor Red
                Write-Host "Pod status:" -ForegroundColor Yellow
                kubectl get pod nginx-test -o wide
                kubectl describe pod nginx-test
                
                # Show recent events for the pod
                Write-Host "`nPod events:" -ForegroundColor Yellow
                kubectl get events --field-selector involvedObject.name=nginx-test --sort-by='.lastTimestamp'
            }
            
            # Clean up test pod
            Write-Host "`nCleaning up test pod..." -ForegroundColor Yellow
            kubectl delete pod nginx-test --ignore-not-found
            
            # Clean up temp file
            Remove-Item -Path $tempYamlPath -Force
        } else {
            Write-Host "Cannot deploy test pod - ACR name is missing." -ForegroundColor Red
        }
    } else {
        Write-Host "kubectl not installed—skip pod deployment." -ForegroundColor Yellow
        Write-Host "   To test manually, install kubectl and run:" -ForegroundColor Cyan
        Write-Host "     kubectl apply -f $testPodYaml"
    }
} else {    Write-Host "test-pod.yaml not found at $testPodYaml" -ForegroundColor Red }

# 7) Validate AGIC ingress and Azure DNS
Write-Host "`nValidating Application Gateway ingress and DNS..." -ForegroundColor Yellow
$ingressIp = kubectl get ingress respondr-ingress -o jsonpath="{.status.loadBalancer.ingress[0].ip}" 2>$null
if ($ingressIp) {
    Write-Host "Ingress IP: $ingressIp" -ForegroundColor Green
    try {
        $resp = Invoke-WebRequest -Uri "http://$ingressIp" -UseBasicParsing -TimeoutSec 5
        Write-Host "Application responded with status $($resp.StatusCode)" -ForegroundColor Green
    } catch {
        Write-Host "Ingress test failed: $_" -ForegroundColor Yellow
    }
} else {
    Write-Host "Ingress IP not available" -ForegroundColor Yellow
}

$dnsZone = az network dns zone list --resource-group $ResourceGroupName --query "[0].name" -o tsv
if ($dnsZone) {
    $fqdn = "respondr.$dnsZone"
    $dnsIp = az network dns record-set a show --resource-group $ResourceGroupName --zone-name $dnsZone --name respondr --query "arecords[0].ipv4Address" -o tsv 2>$null
    if ($dnsIp) { Write-Host "DNS A record for $fqdn -> $dnsIp" -ForegroundColor Green }
    try {
        Invoke-WebRequest -Uri "https://$fqdn" -UseBasicParsing -TimeoutSec 5 | Out-Null
        Write-Host "DNS endpoint reachable" -ForegroundColor Green
    } catch {
        Write-Host "DNS endpoint unreachable: $_" -ForegroundColor Yellow
    }
}

# 8) Check OpenAI account provisioning state
Write-Host "`nChecking OpenAI account status..." -ForegroundColor Yellow
$openAiState = az cognitiveservices account show `
    --name $openAiAccountName `
    --resource-group $ResourceGroupName `
    --query "properties.provisioningState" -o tsv
Write-Host "OpenAI provisioningState: $openAiState" -ForegroundColor Cyan

# 8.5) Deploy gpt-4.1-nano model if OpenAI account is ready
if ($openAiState -eq "Succeeded") {
    Write-Host "`nDeploying gpt-4.1-nano model..." -ForegroundColor Yellow
    
    # Check if deployment already exists
    $existingDeployment = az cognitiveservices account deployment list `
        --name $openAiAccountName `
        --resource-group $ResourceGroupName `
        --query "[?name=='gpt-4-1-nano']" -o json | ConvertFrom-Json
    
    if ($existingDeployment.Count -eq 0) {
        # Create the model deployment using new SKU-based approach
        # GPT-4.1-nano uses GlobalStandard SKU (serverless/pay-per-token)
        # Set capacity to 250 to get 250K TPM (tokens per minute) and 250 RPM (requests per minute)
        $deploymentResult = az cognitiveservices account deployment create `
            --name $openAiAccountName `
            --resource-group $ResourceGroupName `
            --deployment-name "gpt-4-1-nano" `
            --model-name "gpt-4.1-nano" `
            --model-version "2025-04-14" `
            --model-format "OpenAI" `
            --sku-name "GlobalStandard" `
            --sku-capacity 200 2>&1
        
        if ($LASTEXITCODE -eq 0) {
            Write-Host "Successfully deployed gpt-4.1-nano model" -ForegroundColor Green
        } else {
            Write-Host "Failed to deploy gpt-4.1-nano model: $deploymentResult" -ForegroundColor Red
        }
    } else {
        Write-Host "gpt-4.1-nano model deployment already exists" -ForegroundColor Green
    }
    
    # List all deployments for verification
    Write-Host "`nCurrent model deployments:" -ForegroundColor Yellow
    az cognitiveservices account deployment list `
        --name $openAiAccountName `
        --resource-group $ResourceGroupName `
        --query "[].{Name:name, Model:properties.model.name, Version:properties.model.version, Status:properties.provisioningState}" `
        --output table
} else {
    Write-Host "`nSkipping model deployment - OpenAI account not ready (state: $openAiState)" -ForegroundColor Yellow
}

# 9) Check Storage account provisioning state
if ($storageAccountName) {
    Write-Host "`nChecking Storage account status..." -ForegroundColor Yellow
    $storageState = az storage account show `
        --name $storageAccountName `
        --resource-group $ResourceGroupName `
        --query "provisioningState" -o tsv
    Write-Host "Storage provisioningState: $storageState" -ForegroundColor Cyan
}

Write-Host "`nPost-deployment configuration completed successfully!" -ForegroundColor Green
