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

### Deployment Options

You have two main deployment approaches:

#### Option 1: Complete Automated Deployment (Recommended for first-time setup)
Use the `deploy-complete.ps1` script for a fully automated end-to-end deployment:

```powershell
cd deployment
.\deploy-complete.ps1 -ResourceGroupName respondr -Domain "paincave.pro"
```

This single command:
- Deploys all Azure infrastructure via Bicep
- Configures AKS, AGIC, cert-manager, and authentication
- Builds and deploys the application
- Sets up Let's Encrypt SSL certificates
- Tests connectivity and provides comprehensive status

#### Option 2: Step-by-Step Deployment (Recommended for customization or troubleshooting)
Use individual scripts for more control over each step:

```powershell
# Step 1: Deploy infrastructure
az deployment group create --resource-group respondr --template-file main.bicep

# Step 2: Configure post-deployment settings
.\post-deploy.ps1 -ResourceGroupName respondr

# Step 3: Deploy application
.\deploy-to-k8s.ps1 -ResourceGroupName respondr
```

### Prerequisites

- [Azure CLI](https://docs.microsoft.com/en-us/cli/azure/install-azure-cli) (latest version)
- [Docker Desktop](https://www.docker.com/products/docker-desktop) installed and running
- [kubectl](https://kubernetes.io/docs/tasks/tools/) (latest version)
- [PowerShell](https://docs.microsoft.com/en-us/powershell/scripting/install/installing-powershell) (version 7.0 or higher)
- An active Azure subscription with Contributor role or higher

### Important: AGIC and Application Gateway Timing

**Key Learning**: The Application Gateway Ingress Controller (AGIC) automatically creates the Application Gateway, but this process takes 5-10 minutes. During this time:

1. AGIC pod will show `CrashLoopBackOff` status - **this is normal**
2. The Application Gateway is created in the MC resource group (e.g., `MC_respondr_respondr-aks-cluster-v2_westus`)
3. The post-deploy script now waits for this process and monitors AGIC health
4. Once the Application Gateway is ready, AGIC pod becomes healthy automatically

**Do not restart AGIC pods during the initial 10-minute creation window.**

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

# Run pre-deployment validation
.\deployment\pre-deploy-check.ps1 -ResourceGroupName respondr
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

> **Note:** If you encounter an error about the Azure Container Registry name being already in use, this is expected behavior. The template automatically generates unique names for globally unique resources like ACR and Storage Accounts. Simply retry the deployment command.

This creates:
- Azure Kubernetes Service (AKS) cluster: `respondr-aks-cluster-v2` (with Azure CNI networking)
- Azure Container Registry (ACR): `respondr<uniqueid>acr`
- Azure OpenAI Service: `respondr-openai-account`
- Azure Storage Account: `resp<uniqueid>store`
- Virtual Network: `respondr-vnet` with dedicated subnets for AKS and Application Gateway

### Step 3: Configure Post-Deployment Settings

Run the post-deployment script to configure the infrastructure:

```powershell
# Configure AKS, ACR integration, Application Gateway Ingress Controller (AGIC), and cert-manager
.\deployment\post-deploy.ps1 -ResourceGroupName respondr
```

This script:
- Configures kubectl with AKS credentials
- **Installs cert-manager for Let's Encrypt certificate management**
- **Creates Let's Encrypt ClusterIssuer for automatic SSL certificates**
- Sets up workload identity and federated credentials
- Attaches ACR to AKS for seamless image pulling
- **Enables Application Gateway Ingress Controller (AGIC)**
- **Waits for Application Gateway to be created by AGIC (takes 5-10 minutes)**
- **Monitors AGIC pod health and readiness**
- Configures Microsoft Entra (Azure AD) authentication
- Imports a test image and validates the setup
- Deploys and verifies gpt-4.1-nano model in Azure OpenAI

> **Important:** The script now properly handles AGIC timing and installs cert-manager for automatic Let's Encrypt SSL certificate management. The Application Gateway is created in the MC resource group (e.g., `MC_respondr_respondr-aks-cluster-v2_westus`) and the script monitors this automatically.

### Step 4: Build and Push Container Image

Build the application container and push it to your Azure Container Registry:

```powershell
# Get ACR login server name
$acrName = az acr list -g respondr --query "[0].name" -o tsv
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

You'll need Azure OpenAI credentials for the application to function. Use the `create-secrets.ps1` script to automatically generate your Kubernetes secrets file:

```powershell
# Create the secrets.yaml file with your Azure OpenAI credentials
cd deployment
.\create-secrets.ps1 -ResourceGroupName respondr

# Verify the secrets were created correctly
# The script will show you the endpoint and deployment settings (but not the key value)
```

Alternatively, you can manually retrieve the credentials and create the file:

```powershell
# Get Azure OpenAI details from the deployment
$resourceGroup = "respondr"
$openAIName = az cognitiveservices account list -g $resourceGroup --query "[?kind=='OpenAI'].name" -o tsv
$openAIEndpoint = az cognitiveservices account show -n $openAIName -g $resourceGroup --query "properties.endpoint" -o tsv
$openAIKey = az cognitiveservices account keys list -n $openAIName -g $resourceGroup --query "key1" -o tsv

# Display the values you'll need
Write-Host "Azure OpenAI Endpoint: $openAIEndpoint"
Write-Host "Azure OpenAI Key: $openAIKey"
Write-Host "Azure OpenAI Deployment: gpt-4-1-nano"  # Default from template
Write-Host "Azure OpenAI API Version: 2025-01-01-preview"  # Default from template
```

### Step 6: Deploy Application to Kubernetes

Navigate to the deployment directory and deploy the application:

```powershell
cd deployment

# Deploy the application (automatically creates secrets.yaml from Azure and configures Let's Encrypt)
.\deploy-to-k8s.ps1 -ResourceGroupName respondr -ImageTag "latest"

# If you want to use an existing secrets file, you can skip secrets creation:
# .\deploy-to-k8s.ps1 -ResourceGroupName respondr -ImageTag "latest" -SkipSecretsCreation
```

This will:
- Build and push the container image to ACR
- Create Kubernetes secrets from Azure OpenAI credentials
- Deploy the application with Let's Encrypt certificate configuration
- Wait for the Let's Encrypt certificate to be issued (may take 2-10 minutes)

Alternatively, deploy manually:

```powershell
# Create secrets file (now built into deploy-to-k8s.ps1)
# This step is now optional as deploy-to-k8s.ps1 will handle it automatically
.\create-secrets.ps1 -ResourceGroupName respondr

# Deploy to Kubernetes
kubectl apply -f secrets.yaml
kubectl apply -f respondr-k8s-deployment.yaml

# Wait for deployment
kubectl wait --for=condition=available --timeout=300s deployment/respondr-deployment

# Wait for Let's Encrypt certificate (this may take a few minutes)
kubectl wait --for=condition=Ready certificate/respondr-tls-letsencrypt --timeout=600s

# Check status
kubectl get pods -l app=respondr
kubectl get services -l app=respondr
kubectl get ingress respondr-ingress
kubectl get certificate respondr-tls-letsencrypt
```

### Step 7: Configure DNS and Wait for SSL Certificate

Get the Application Gateway's public IP and configure DNS:

```powershell
# Get Application Gateway public IP
$mcResourceGroup = "MC_respondr_respondr-aks-cluster-v2_westus"
$appGwIp = az network public-ip show `
    --resource-group $mcResourceGroup `
    --name "respondr-aks-cluster-v2-appgw-appgwpip" `
    --query "ipAddress" -o tsv

Write-Host "Application Gateway IP: $appGwIp"

# For testing, add to hosts file (Windows - run as Administrator)
Add-Content -Path C:\Windows\System32\drivers\etc\hosts -Value "$appGwIp respondr.paincave.pro"

# Or manually add this line to your hosts file:
# <IP_ADDRESS> respondr.paincave.pro
```

**For production, configure proper DNS records:**
- Add an A record with your domain provider: `respondr.paincave.pro` → `<Application Gateway IP>`
- Or use Azure DNS if managing the domain through Azure

**Wait for Let's Encrypt certificate:**
```powershell
# Check certificate status
kubectl get certificate respondr-tls-letsencrypt -n respondr

# Monitor certificate issuance
kubectl describe certificate respondr-tls-letsencrypt -n respondr

# Check certificaterequest progress
kubectl get certificaterequests -n respondr
```

The Let's Encrypt certificate issuance process:
1. cert-manager detects the ingress with Let's Encrypt annotations
2. Creates a certificate request and temporary challenge pods
3. Let's Encrypt validates domain ownership via HTTP-01 challenge
4. Issues the certificate (usually takes 2-10 minutes)
5. cert-manager stores the certificate in the Kubernetes secret

### Step 8: Test the Deployment

Test that everything is working:

```powershell
# Test the API endpoint (after certificate is ready)
curl https://respondr.paincave.pro/api/responders

# Send a test webhook
$testPayload = @{
    name = "Test User"
    text = "I am responding with SAR78, ETA 15 minutes"
    created_at = [int][double]::Parse((Get-Date -UFormat %s))
} | ConvertTo-Json

Invoke-RestMethod -Uri "https://respondr.paincave.pro/webhook" -Method POST -Body $testPayload -ContentType "application/json"

# Check the results
curl https://respondr.paincave.pro/api/responders
```

Visit https://respondr.paincave.pro in your browser to see the dashboard. You'll be prompted to authenticate with Microsoft Entra (Azure AD).

**If you get SSL certificate errors:**
1. Check certificate status: `kubectl get certificate respondr-tls-letsencrypt -n respondr`
2. Wait for certificate to be Ready (may take up to 10 minutes)
3. Verify DNS is pointing to the correct IP address
4. Check cert-manager logs: `kubectl logs -n cert-manager deployment/cert-manager`

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

- **Frontend Dashboard**: https://respondr.paincave.pro (via Application Gateway with Entra auth)
- **API Endpoint**: https://respondr.paincave.pro/api/responders
- **Webhook Endpoint**: https://respondr.paincave.pro/webhook
- **Health Check**: https://respondr.paincave.pro/health

> **Note**: The actual domain depends on your DNS configuration. For testing, you can use the Application Gateway's public IP and add an entry to your hosts file.

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

### Running Tests

The project includes both backend (pytest) and frontend (Jest) tests.

```powershell
# Run all tests (backend and frontend)
.\run-tests.ps1

# Run just backend tests
cd backend
python run_tests.py

# Run just frontend tests
cd frontend
npm test
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
$acrName = az acr list -g respondr --query "[0].name" -o tsv
az acr repository list --name $acrName --output table

# List tags for the respondr repository
az acr repository show-tags --name $acrName --repository respondr --output table

# Delete old image versions
az acr repository delete --name $acrName --image respondr:v1.0 --yes

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
5. **AGIC Pod CrashLoopBackOff**: This is normal during Application Gateway creation (5-10 minutes)
6. **Azure CLI Extension Conflicts**: Remove conflicting extensions with `az extension remove --name aks-preview`
7. **CNI Overlay Issues**: The template uses standard Azure CNI to avoid preview feature requirements
8. **Let's Encrypt Certificate Issues**: Check DNS configuration and certificate status

### Let's Encrypt Certificate Troubleshooting

**Issue**: SSL certificate not working or site shows "certificate not trusted"
**Cause**: Let's Encrypt certificate not yet issued or DNS misconfiguration
**Solution**:

```powershell
# Check certificate status
kubectl get certificate respondr-tls-letsencrypt -n respondr
kubectl describe certificate respondr-tls-letsencrypt -n respondr

# Check certificaterequest status
kubectl get certificaterequests -n respondr
kubectl describe certificaterequest <request-name> -n respondr

# Check cert-manager logs
kubectl logs -n cert-manager deployment/cert-manager
kubectl logs -n cert-manager deployment/cert-manager-webhook

# Check ACME challenge pods
kubectl get pods -n respondr -l acme.cert-manager.io/http01-solver=true

# Manual certificate retry (if needed)
kubectl delete certificate respondr-tls-letsencrypt -n respondr
kubectl apply -f respondr-k8s-deployment.yaml
```

**Issue**: ACME challenge fails
**Cause**: DNS not pointing to Application Gateway or domain not accessible
**Solution**:
1. Verify DNS A record: `respondr.paincave.pro` → Application Gateway IP
2. Test domain accessibility: `curl http://respondr.paincave.pro/.well-known/acme-challenge/test`
3. Check Application Gateway HTTP listener configuration
4. Ensure Application Gateway allows HTTP traffic for ACME challenges

### AGIC and Application Gateway Troubleshooting

**Issue**: AGIC pod showing CrashLoopBackOff or failing to start
**Cause**: Application Gateway doesn't exist yet (AGIC creates it automatically)
**Solution**: Wait 5-10 minutes for AGIC to create the Application Gateway, or check deployment status:

```powershell
# Check AGIC deployment progress
$aksCluster = "respondr-aks-cluster-v2"
$mcResourceGroup = "MC_respondr_$aksCluster_westus"
az deployment group list --resource-group $mcResourceGroup --output table

# Check AGIC pod status
kubectl get pods -n kube-system -l app=ingress-appgw
kubectl logs -n kube-system deployment/ingress-appgw-deployment --tail=20

# Restart AGIC if needed (after Application Gateway is ready)
kubectl rollout restart deployment/ingress-appgw-deployment -n kube-system
```

**Issue**: Application Gateway not accessible
**Cause**: Application Gateway is created in MC resource group, not main resource group
**Solution**: Check the correct resource group:

```powershell
# Correct resource group for Application Gateway
$mcResourceGroup = "MC_respondr_respondr-aks-cluster-v2_westus"
az network application-gateway list --resource-group $mcResourceGroup --output table
```

## Resource Naming Convention

All resources follow a consistent naming pattern:

- Resource Group: `respondr`
- AKS Cluster: `respondr-aks-cluster-v2` (uses standard Azure CNI)
- ACR: `respondr<uniqueString>acr`
- OpenAI Account: `respondr-openai-account`
- Storage Account: `resp<uniqueString>store`
- Virtual Network: `respondr-vnet`
- Application Gateway: `respondr-aks-cluster-v2-appgw` (created by AGIC in MC resource group)

The v2 suffix indicates the use of standard Azure CNI networking instead of CNI overlay to ensure compatibility with Application Gateway.

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