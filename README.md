# SCVSAR Response Tracker

A web application that tracks responses to Search and Rescue mission call-outs. The system monitors GroupMe responses and uses Azure OpenAI to extract and aggregate response details into a useful dashboard for command and support staff.

## Project Overview

This application processes incoming webhook notifications from GroupMe messages, extracts responder information (vehicle assignments and ETAs) using Azure OpenAI, and displays the information in a real-time dashboard.

### Key Features

- **Real-time Response Tracking**: Processes GroupMe webhook messages in real-time
- **AI-powered Information Extraction**: Uses Azure OpenAI to parse vehicle assignments and ETAs from natural language messages
- **Live Dashboard**: React-based frontend showing responder status and metrics
- **OAuth2 Authentication**: Seamless Azure AD/Entra integration for secure access
- **Container-ready**: Full Docker containerization with multi-stage builds
- **Kubernetes Deployment**: Production-ready Kubernetes manifests with Azure integration

## Architecture

The application consists of:

- **Frontend**: React application served statically
- **Backend**: FastAPI Python application with Azure OpenAI integration
- **Authentication**: OAuth2 Proxy sidecar for Azure AD/Entra authentication
- **Infrastructure**: Azure Kubernetes Service (AKS), Azure Container Registry (ACR), Azure OpenAI Service, and Azure Storage

## Quick Start - Complete End-to-End Deployment

**Recommended for first-time setup**: Use the automated deployment script for a fully functional deployment with OAuth2 authentication:

```powershell
# Prerequisites: Azure CLI, Docker Desktop, kubectl, PowerShell 7+
# Login to Azure and set subscription
az login
az account set --subscription <your-subscription-id>

# Create resource group
az group create --name respondr --location westus

# Run complete automated deployment
cd deployment
.\deploy-complete.ps1 -ResourceGroupName respondr -Domain "paincave.pro"
```

**This single command handles everything:**
- Deploys all Azure infrastructure (AKS, ACR, OpenAI, Storage, Networking)
- Configures post-deployment settings and AGIC (waits for Application Gateway creation)
- Creates Azure AD app registration and OAuth2 proxy configuration
- Builds and deploys the application with OAuth2 sidecar authentication
- Sets up Let's Encrypt SSL certificates (after you configure DNS)
- Runs comprehensive tests and provides status verification

**⚠️ Important**: You'll need to configure DNS during the deployment process when prompted. The script will pause and show you the Application Gateway IP address that needs to be added to your domain's DNS records.

## Prerequisites

Before starting, ensure you have:

- [Azure CLI](https://docs.microsoft.com/en-us/cli/azure/install-azure-cli) (latest version)
- [Docker Desktop](https://www.docker.com/products/docker-desktop) installed and running
- [kubectl](https://kubernetes.io/docs/tasks/tools/) (latest version)
- [PowerShell](https://docs.microsoft.com/en-us/powershell/scripting/install/installing-powershell) (version 7.0 or higher)
- An active Azure subscription with Contributor role or higher
- A domain name you control for DNS configuration (e.g., `respondr.paincave.pro`)

## Important Deployment Notes

### DNS Configuration Timing
**⚠️ CRITICAL**: DNS must be configured during deployment for Let's Encrypt certificate issuance:
1. The deployment script will pause and display the Application Gateway IP
2. You must immediately update your DNS records: `respondr.paincave.pro` → `<Gateway IP>`
3. DNS propagation takes 5-60 minutes depending on your provider
4. Let's Encrypt certificates are issued automatically after DNS validation

### AGIC and Application Gateway Creation
- Application Gateway Ingress Controller (AGIC) creates the Application Gateway automatically (5-10 minutes)
- AGIC pod may show `CrashLoopBackOff` during this time - **this is normal**
- The deployment scripts handle this timing automatically

### Authentication Architecture
Azure Application Gateway v2 does not support native Azure AD authentication. This deployment includes **OAuth2 Proxy sidecar authentication** for seamless Azure AD/Entra integration.

## Step-by-Step Deployment (Alternative to Quick Start)

If you prefer manual control over each deployment phase:

### Step 1: Environment Setup
```powershell
# Login to Azure and create resource group
az login
az account set --subscription <your-subscription-id>
az group create --name respondr --location westus

# Validate environment
cd deployment
.\pre-deploy-check.ps1 -ResourceGroupName respondr
```

### Step 2: Deploy Azure Infrastructure
```powershell
# Deploy all Azure resources using Bicep template
az deployment group create `
    --resource-group respondr `
    --template-file deployment/main.bicep `
    --parameters resourcePrefix=respondr location=westus
```

Creates: AKS cluster, Azure Container Registry, Azure OpenAI Service, Azure Storage Account, Virtual Network with subnets

### Step 3: Configure Post-Deployment Settings
```powershell
# Configure AKS, ACR integration, AGIC, cert-manager, and workload identity
.\deployment\post-deploy.ps1 -ResourceGroupName respondr
```

This step:
- Configures kubectl with AKS credentials
- Installs cert-manager for Let's Encrypt certificate management
- Sets up workload identity and federated credentials
- Attaches ACR to AKS for seamless image pulling
- Enables Application Gateway Ingress Controller (AGIC)
- Waits for Application Gateway creation (5-10 minutes)

### Step 4: Setup OAuth2 Authentication (Recommended)
```powershell
# Create Azure AD app registration and configure OAuth2 proxy
.\deployment\setup-oauth2.ps1 -ResourceGroupName respondr -Domain "paincave.pro"
```

### Step 5: Deploy Application
```powershell
# Build, push, and deploy application with OAuth2 authentication
.\deployment\deploy-to-k8s.ps1 -ResourceGroupName respondr -UseOAuth2

# Alternative: Deploy without OAuth2 (not recommended for production)
# .\deployment\deploy-to-k8s.ps1 -ResourceGroupName respondr
```

### Step 6: Configure DNS and SSL
The deployment script will display the Application Gateway IP address. You must:

1. **Update DNS Records**: Add A record `respondr.paincave.pro` → `<Gateway IP>` with your domain provider
2. **Wait for DNS Propagation**: 5-60 minutes depending on provider
3. **Verify SSL Certificate**: Let's Encrypt certificate issued automatically after DNS validation

### Step 7: Test and Verify
```powershell
# Run comprehensive end-to-end testing
.\deployment\test-end-to-end.ps1 -Domain "paincave.pro"

# Verify OAuth2 authentication specifically
.\deployment\verify-oauth2-deployment.ps1 -Domain "paincave.pro"
```

## Application Endpoints

Once deployed, the application provides:

- **Frontend Dashboard**: https://respondr.paincave.pro (with OAuth2 authentication)
- **API Endpoint**: https://respondr.paincave.pro/api/responders
- **Webhook Endpoint**: https://respondr.paincave.pro/webhook
- **Health Check**: https://respondr.paincave.pro/health

> **Note**: Replace `paincave.pro` with your actual domain. All endpoints are protected by OAuth2 authentication and served over HTTPS with Let's Encrypt certificates.

## Deployment Management

### Automated Redeployment (Recommended)

For development updates and quick fixes:

```powershell
cd deployment

# Build new image and deploy with rolling update (RECOMMENDED)
.\redeploy.ps1 -Action "build" -ResourceGroupName respondr

# Restart deployment with same image
.\redeploy.ps1 -Action "restart"

# Update configuration and restart
.\redeploy.ps1 -Action "update-config"
```

The `build` action automatically:
- Builds a new container image with timestamp version
- Pushes to Azure Container Registry  
- Updates Kubernetes deployment with zero downtime
- Maintains OAuth2 configuration and session affinity

### Production Upgrades

For production environments with version management:

```powershell
# Full upgrade with new version
.\upgrade-k8s.ps1 -Version "v1.1" -ResourceGroupName respondr

# Upgrade with automatic rollback on failure
.\upgrade-k8s.ps1 -Version "v1.2" -ResourceGroupName respondr -RollbackOnFailure
```

### Manual Deployment Commands

```powershell
# Quick restart without new build
kubectl rollout restart deployment/respondr-deployment

# Rollback to previous version
kubectl rollout undo deployment/respondr-deployment

# Check deployment status
kubectl get pods -l app=respondr
kubectl rollout status deployment/respondr-deployment
```

## Development and Testing

### Local Development

For local development and testing:

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

```powershell
# Run all tests (backend and frontend)
.\run-tests.ps1

# Run just backend tests
cd backend
python run_tests.py

# Run just frontend tests
cd frontend
npm test

# Test webhook functionality
cd backend
python test_webhook.py
```

### Container Management

```powershell
# List all repositories in ACR
$acrName = az acr list -g respondr --query "[0].name" -o tsv
az acr repository list --name $acrName --output table

# List tags for the respondr repository
az acr repository show-tags --name $acrName --repository respondr --output table

# Build and push new versions
docker build -t respondr:v1.1 .
$acrLoginServer = az acr show --name $acrName --query loginServer -o tsv
docker tag respondr:v1.1 "$acrLoginServer/respondr:v1.1"
docker push "$acrLoginServer/respondr:v1.1"

# Update deployment with new image
kubectl set image deployment/respondr-deployment respondr="$acrLoginServer/respondr:v1.1"
kubectl rollout status deployment/respondr-deployment
```

## Monitoring and Troubleshooting

### Quick Status Checks

```powershell
# Check overall deployment status
kubectl get pods,svc,ingress -l app=respondr
kubectl get certificate respondr-tls-letsencrypt -n respondr

# Check application logs
kubectl logs -l app=respondr --tail=50 -f

# Check OAuth2 proxy logs specifically
kubectl logs -l app=respondr -c oauth2-proxy --tail=50

# Run deployment verification
cd deployment
.\verify-oauth2-deployment.ps1 -Domain "paincave.pro"
.\test-end-to-end.ps1 -Domain "paincave.pro"

# Port forward for direct access (bypass ingress)
kubectl port-forward service/respondr-service 8080:80
```

### Common Issues and Solutions

#### AGIC Pod Issues
**Symptoms**: AGIC pod showing `CrashLoopBackOff`
**Cause**: Application Gateway creation in progress (5-10 minutes) or permission issues
**Solution**:
```powershell
# Check if AGIC addon is enabled
az aks addon list --resource-group respondr --name respondr-aks-cluster-v2 --query "[?name=='ingress-appgw'].enabled" -o tsv

# Enable AGIC if needed
$subnetId = az network vnet subnet show --resource-group respondr --vnet-name respondr-vnet --name appgw-subnet --query "id" -o tsv
az aks enable-addons --resource-group respondr --name respondr-aks-cluster-v2 --addons ingress-appgw --appgw-subnet-id $subnetId

# Check AGIC logs
kubectl logs -n kube-system deployment/ingress-appgw-deployment --tail=20
```

#### SSL Certificate Issues
**Symptoms**: "Certificate not trusted" or SSL errors
**Cause**: Let's Encrypt certificate not issued or DNS misconfiguration
**Solution**:
```powershell
# Check certificate status
kubectl get certificate respondr-tls-letsencrypt -n respondr
kubectl describe certificate respondr-tls-letsencrypt -n respondr

# Check cert-manager logs
kubectl logs -n cert-manager deployment/cert-manager

# Verify DNS configuration
nslookup respondr.paincave.pro

# Manual certificate retry
kubectl delete certificate respondr-tls-letsencrypt -n respondr
kubectl apply -f respondr-k8s-deployment.yaml
```

#### OAuth2 Authentication Issues
**Symptoms**: Login loops, "OIDC discovery failed", or authentication errors
**Cause**: Misconfigured Azure AD app or OAuth2 proxy settings
**Solution**:
```powershell
# Check OAuth2 secrets
kubectl get secret oauth2-secrets -n respondr -o yaml

# Check OAuth2 proxy logs
kubectl logs -n respondr -l app=respondr -c oauth2-proxy

# Verify Azure AD app registration
az ad app list --display-name "respondr-oauth2" --query "[].{appId:appId,displayName:displayName}"

# Recreate OAuth2 configuration
.\setup-oauth2.ps1 -ResourceGroupName respondr -Domain "paincave.pro"
kubectl rollout restart deployment/respondr-deployment -n respondr
```

#### DNS and Network Issues
**Symptoms**: Domain not resolving or Application Gateway not accessible
**Solution**:
```powershell
# Get Application Gateway IP
$mcResourceGroup = "MC_respondr_respondr-aks-cluster-v2_westus"
$appGwIp = az network public-ip show --resource-group $mcResourceGroup --name "respondr-aks-cluster-v2-appgw-appgwpip" --query "ipAddress" -o tsv

# Verify DNS resolution
nslookup respondr.paincave.pro

# Check Application Gateway configuration
az network application-gateway list --resource-group $mcResourceGroup --output table
```

#### Container and Image Issues
**Symptoms**: Image pull errors or pod startup failures
**Solution**:
```powershell
# Check ACR attachment
az aks check-acr --resource-group respondr --name respondr-aks-cluster-v2 --acr $acrName

# Manually attach ACR if needed
az aks update --resource-group respondr --name respondr-aks-cluster-v2 --attach-acr $acrName

# Check image availability
az acr repository list --name $acrName
az acr repository show-tags --name $acrName --repository respondr
```

## Resource Management

### Cleanup Resources

To completely clean up the deployment:

```powershell
# Remove Kubernetes resources
kubectl delete -f respondr-k8s-deployment.yaml
kubectl delete -f secrets.yaml

# Clean up Azure resources (WARNING: This deletes everything)
.\deployment\cleanup.ps1 -ResourceGroupName respondr -Force
```

### Resource Naming Convention

All resources follow a consistent naming pattern:

- Resource Group: `respondr`
- AKS Cluster: `respondr-aks-cluster-v2` (uses standard Azure CNI)
- ACR: `respondr<uniqueString>acr`
- OpenAI Account: `respondr-openai-account`
- Storage Account: `resp<uniqueString>store`
- Virtual Network: `respondr-vnet`
- Application Gateway: `respondr-aks-cluster-v2-appgw` (created by AGIC in MC resource group)

The v2 suffix indicates the use of standard Azure CNI networking for compatibility with Application Gateway.

## Production Recommendations

### Security
- All secrets stored in Kubernetes secrets (not configuration files)
- Containers run as non-root users
- ACR integration uses managed identity for secure image pulls
- OAuth2 authentication with Azure AD/Entra integration
- Resource limits prevent resource exhaustion

### Monitoring and Backup
- Enable Azure Monitor for containers and Application Insights
- Configure log aggregation and alerting for critical issues
- Monitor certificate expiration and renewal
- Regular AKS cluster backups using Azure Backup
- Azure Storage account geo-replication for persistent data

### CI/CD Integration
- Automate deployments with Azure DevOps or GitHub Actions
- Include OAuth2 verification using `verify-oauth2-deployment.ps1`
- Add end-to-end testing with `test-end-to-end.ps1` in validation pipelines
- Implement proper testing and staging environments
- Use infrastructure as code (Bicep templates) for environment recreation

### Cost Optimization
- Use Azure Spot instances for non-critical workloads
- Configure cluster autoscaling based on demand
- Monitor and optimize resource usage regularly
- Review and rightsize VM SKUs based on actual usage

## Contributing

1. Fork the repository
2. Create a feature branch
3. Make your changes
4. Test locally and in a development AKS cluster
5. Submit a pull request

## License

This project is licensed under the MIT License - see the LICENSE file for details.