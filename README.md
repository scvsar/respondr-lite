# SCVSAR Response Tracker

A web application that tracks responses to Search and Rescue mission call-outs. The system monitors GroupMe responses and uses Azure OpenAI to extract and aggregate response details into a useful dashboard for command and support staff.

## Project Overview

This application processes incoming webhook notifications from GroupMe messages, extracts responder information (vehicle assignments and ETAs) using Azure OpenAI, and displays the information in a real-time dashboard.

### Key Features

- **Real-time Response Tracking**: Processes GroupMe webhook messages in real-time
- **AI-powered Information Extraction**: Uses Azure OpenAI to parse vehicle assignments and ETAs from natural language messages
- **Live Dashboard**: React-based frontend showing responder status and metrics
- **Container-ready**: Full Docker containerization with multi-stage builds
- **Kubernetes Deployment**: Production-ready Kubernetes manifests with Azure integration

## Architecture

The application consists of:

- **Frontend**: React application served statically
- **Backend**: FastAPI Python application with Azure OpenAI integration
- **Infrastructure**: Azure Kubernetes Service (AKS), Azure Container Registry (ACR), Azure OpenAI Service, and Azure Storage

## Complete End-to-End Deployment Guide

### Prerequisites

- [Azure CLI](https://docs.microsoft.com/en-us/cli/azure/install-azure-cli) (latest version)
- [Docker Desktop](https://www.docker.com/products/docker-desktop) installed and running
- [kubectl](https://kubernetes.io/docs/tasks/tools/) (latest version)
- [PowerShell](https://docs.microsoft.com/en-us/powershell/scripting/install/installing-powershell) (version 7.0 or higher)
- An active Azure subscription with Contributor role or higher

### Step 1: Prepare Your Environment

```powershell
# Login to Azure
az login

# Set the active subscription (if you have multiple subscriptions)
az account set --subscription <your-subscription-id>

# Create resource group
az group create --name respondr --location westus

# Clone the repository (if not already done)
git clone <repository-url>
cd respondr
```

### Step 2: Deploy Azure Infrastructure

Deploy all required Azure resources using the Bicep template:

```powershell
# Deploy the infrastructure
az deployment group create `
    --resource-group respondr `
    --template-file deployment/main.bicep `
    --parameters resourcePrefix=respondr location=westus
```

This creates:
- Azure Kubernetes Service (AKS) cluster: `respondr-aks-cluster`
- Azure Container Registry (ACR): `respondracr`
- Azure OpenAI Service: `respondr-openai-account`
- Azure Storage Account: `resp<uniqueid>store`

### Step 3: Configure Post-Deployment Settings

Run the post-deployment script to configure the infrastructure:

```powershell
# Configure AKS and ACR integration
.\deployment\post-deploy.ps1 -ResourceGroupName respondr
```

This script:
- Configures kubectl with AKS credentials
- Attaches ACR to AKS for seamless image pulling
- Imports a test image and validates the setup
- Verifies all service provisioning states

### Step 4: Build and Push Container Image

Build the application container and push it to your Azure Container Registry:

```powershell
# Get ACR login server name
$acrName = "respondracr"  # or use: az acr list -g respondr --query "[0].name" -o tsv
$acrLoginServer = az acr show --name $acrName --query loginServer -o tsv

# Login to ACR
az acr login --name $acrName

# Build the container image
docker build -t respondr:latest .

# Tag for ACR
docker tag respondr:latest "$acrLoginServer/respondr:latest"
docker tag respondr:latest "$acrLoginServer/respondr:v1.0"

# Push to ACR
docker push "$acrLoginServer/respondr:latest"
docker push "$acrLoginServer/respondr:v1.0"

# Verify the image was pushed
az acr repository list --name $acrName --output table
```

### Step 5: Configure Application Secrets

You'll need Azure OpenAI credentials for the application to function:

```powershell
# Get Azure OpenAI details from the deployment
$resourceGroup = "respondr"
$openAIName = az cognitiveservices account list -g $resourceGroup --query "[?kind=='OpenAI'].name" -o tsv
$openAIEndpoint = az cognitiveservices account show -n $openAIName -g $resourceGroup --query "properties.endpoint" -o tsv
$openAIKey = az cognitiveservices account keys list -n $openAIName -g $resourceGroup --query "key1" -o tsv

# Display the values you'll need
Write-Host "Azure OpenAI Endpoint: $openAIEndpoint"
Write-Host "Azure OpenAI Key: $openAIKey"
Write-Host "Azure OpenAI Deployment: gpt-4o-mini"  # Default from template
Write-Host "Azure OpenAI API Version: 2025-01-01-preview"  # Default from template
```

### Step 6: Deploy Application to Kubernetes

Navigate to the deployment directory and deploy the application:

```powershell
cd deployment

# Update the Kubernetes manifest with your ACR image
$acrLoginServer = az acr show --name respondracr --query loginServer -o tsv
(Get-Content respondr-k8s-template.yaml) -replace 'respondr:latest', "$acrLoginServer/respondr:latest" | Set-Content respondr-k8s-deployment.yaml

# Deploy using the PowerShell script with your Azure OpenAI key
.\deploy-to-k8s.ps1 -AzureOpenAIApiKey $openAIKey
```

Alternatively, deploy manually:

```powershell
# Create secrets file
cp secrets-template.yaml secrets.yaml
# Edit secrets.yaml with your actual Azure OpenAI credentials

# Deploy to Kubernetes
kubectl apply -f secrets.yaml
kubectl apply -f respondr-k8s-deployment.yaml

# Wait for deployment
kubectl wait --for=condition=available --timeout=300s deployment/respondr-deployment

# Check status
kubectl get pods -l app=respondr
kubectl get services -l app=respondr
kubectl get ingress respondr-ingress
```

### Step 7: Configure Access

Add an entry to your hosts file for local access:

```powershell
# Windows (run as Administrator)
Add-Content -Path C:\Windows\System32\drivers\etc\hosts -Value "127.0.0.1 respondr.local"

# Or manually add this line to your hosts file:
# 127.0.0.1 respondr.local
```

### Step 8: Test the Deployment

Test that everything is working:

```powershell
# Test the API endpoint
curl http://respondr.local/api/responders

# Send a test webhook
$testPayload = @{
    name = "Test User"
    text = "I am responding with SAR78, ETA 15 minutes"
    created_at = [int][double]::Parse((Get-Date -UFormat %s))
} | ConvertTo-Json

Invoke-RestMethod -Uri "http://respondr.local/webhook" -Method POST -Body $testPayload -ContentType "application/json"

# Check the results
curl http://respondr.local/api/responders
```

Visit http://respondr.local in your browser to see the dashboard.

### Step 9: Run Comprehensive Tests

```powershell
# Run the test suite from the backend directory
cd ../backend
python test_webhook.py

# This will send multiple test messages and verify the system is working
```

## Upgrading and Redeployment

### Production Upgrades

For production environments, use the upgrade script that handles versioning, container builds, and rollback capabilities:

```powershell
cd deployment

# Full upgrade with new version
.\upgrade-k8s.ps1 -Version "v1.1" -ResourceGroupName respondr

# Upgrade with automatic rollback on failure
.\upgrade-k8s.ps1 -Version "v1.2" -ResourceGroupName respondr -RollbackOnFailure

# Use existing container image (skip build)
.\upgrade-k8s.ps1 -Version "v1.1" -ResourceGroupName respondr -SkipBuild
```

### Quick Redeployment

For development or quick fixes:

```powershell
cd deployment

# Build and deploy with timestamp version
.\redeploy.ps1 -Action "build" -ResourceGroupName respondr

# Restart deployment (same image, fresh pods)
.\redeploy.ps1 -Action "restart"

# Update configuration and restart
.\redeploy.ps1 -Action "update-config"
```

### Manual Commands

```powershell
# Quick restart without new build
kubectl rollout restart deployment/respondr-deployment

# Rollback to previous version
kubectl rollout undo deployment/respondr-deployment

# Check deployment status
kubectl get pods -l app=respondr
kubectl rollout status deployment/respondr-deployment
```

## Application Endpoints

Once deployed, the application provides:

- **Frontend Dashboard**: http://respondr.local
- **API Endpoint**: http://respondr.local/api/responders
- **Webhook Endpoint**: http://respondr.local/webhook
- **Simple Dashboard**: http://respondr.local/dashboard

## Development and Local Testing

For local development:

```powershell
# Backend development
cd backend
# Create .env file with Azure OpenAI credentials
python -m uvicorn main:app --reload

# Frontend development (separate terminal)
cd frontend
npm install
npm start
```

## Cleanup and Resource Management

To completely clean up the deployment:

```powershell
# Remove Kubernetes resources
kubectl delete -f respondr-k8s-deployment.yaml
kubectl delete -f secrets.yaml

# Clean up Azure resources (WARNING: This deletes everything)
.\deployment\cleanup.ps1 -ResourceGroupName respondr -Force
```

## Container Registry Management

Useful commands for managing your container images:

```powershell
# List all repositories in ACR
az acr repository list --name respondracr --output table

# List tags for the respondr repository
az acr repository show-tags --name respondracr --repository respondr --output table

# Delete old image versions
az acr repository delete --name respondracr --image respondr:v1.0 --yes

# Build and push new versions
docker build -t respondr:v1.1 .
docker tag respondr:v1.1 "$acrLoginServer/respondr:v1.1"
docker push "$acrLoginServer/respondr:v1.1"

# Update deployment with new image
kubectl set image deployment/respondr-deployment respondr="$acrLoginServer/respondr:v1.1"
kubectl rollout status deployment/respondr-deployment
```

## Monitoring and Troubleshooting

### Common Commands

```powershell
# Check pod status and logs
kubectl get pods -l app=respondr
kubectl logs -l app=respondr --tail=100 -f

# Check service and ingress
kubectl get svc,ingress
kubectl describe ingress respondr-ingress

# Port forward for direct access (bypass ingress)
kubectl port-forward service/respondr-service 8080:80
```

### Common Issues

1. **Image Pull Errors**: Ensure ACR is properly attached to AKS
2. **DNS Resolution**: Verify hosts file or configure proper DNS
3. **Azure OpenAI Errors**: Check credentials and deployment name
4. **Pod Startup Issues**: Check resource limits and quotas

## Resource Naming Convention

All resources follow a consistent naming pattern:

- Resource Group: `respondr`
- AKS Cluster: `respondr-aks-cluster`
- ACR: `respondracr`
- OpenAI Account: `respondr-openai-account`
- Storage Account: `resp<uniqueString>store`

You can customize the prefix by modifying the `resourcePrefix` parameter in the Bicep deployment.

## Security Considerations

- All secrets are stored in Kubernetes secrets, not in configuration files
- The application runs as a non-root user in containers
- ACR integration uses managed identity for secure image pulls
- Resource limits prevent resource exhaustion
- Network policies can be applied for additional security

## Contributing

1. Fork the repository
2. Create a feature branch
3. Make your changes
4. Test locally and in a development AKS cluster
5. Submit a pull request

## License

This project is licensed under the MIT License - see the LICENSE file for details.