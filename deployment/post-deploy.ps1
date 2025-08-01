<#
.SYNOPSIS
    Post-deployment configuration for the response-tracking-render app.

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

# 3) AKS credentials
Write-Host "`nGetting AKS credentials..." -ForegroundColor Yellow
az aks get-credentials `
    --resource-group $ResourceGroupName `
    --name $aksClusterName `
    --overwrite-existing

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

# 5) Import test image into ACR
if ($acrName) {
    Write-Host "`nImporting test image to ACR..." -ForegroundColor Yellow
    $importResult = az acr import `
        --name $acrName `
        --source docker.io/library/nginx:latest `
        --image nginx:test 2>&1    if ($LASTEXITCODE -ne 0) {
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
                    $containerStatus = $podStatus.status.containerStatuses                    if ($containerStatus.state.waiting.reason -in @("ImagePullBackOff", "ErrImagePull", "InvalidImageName")) {
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
                
                # Test HTTP connection                try {
                    $response = Invoke-WebRequest -Uri http://localhost:8080 -TimeoutSec 5
                    Write-Host "Successfully connected to pod - HTTP Status: $($response.StatusCode)" -ForegroundColor Green
                } catch {
                    Write-Host "Could not connect to pod: $_" -ForegroundColor Yellow
                } finally {
                    # Clean up
                    Stop-Job -Job $job
                    Remove-Job -Job $job
                }            } else {
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
            Remove-Item -Path $tempYamlPath -Force        } else {
            Write-Host "Cannot deploy test pod - ACR name is missing." -ForegroundColor Red
        }
    } else {
        Write-Host "kubectl not installed—skip pod deployment." -ForegroundColor Yellow
        Write-Host "   To test manually, install kubectl and run:" -ForegroundColor Cyan
        Write-Host "     kubectl apply -f $testPodYaml"
    }
} else {    Write-Host "test-pod.yaml not found at $testPodYaml" -ForegroundColor Red
}

# 7) Check OpenAI account provisioning state
Write-Host "`nChecking OpenAI account status..." -ForegroundColor Yellow
$openAiState = az cognitiveservices account show `
    --name $openAiAccountName `
    --resource-group $ResourceGroupName `
    --query "properties.provisioningState" -o tsv
Write-Host "OpenAI provisioningState: $openAiState" -ForegroundColor Cyan

# 8) Check Storage account provisioning state
if ($storageAccountName) {
    Write-Host "`nChecking Storage account status..." -ForegroundColor Yellow
    $storageState = az storage account show `
        --name $storageAccountName `
        --resource-group $ResourceGroupName `
        --query "provisioningState" -o tsv
    Write-Host "Storage provisioningState: $storageState" -ForegroundColor Cyan
}

Write-Host "`nPost-deployment configuration completed successfully!" -ForegroundColor Green
