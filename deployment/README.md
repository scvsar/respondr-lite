# Respondr Azure Kubernetes Deployment Guide

This directory contains all the necessary files to deploy the Respondr application to Azure Kubernetes Service (AKS) with Application Gateway Ingress Controller (AGIC) and Microsoft Entra authentication.

## Prerequisites

- Azure CLI installed and authenticated (`az login`)
- Docker installed and running
- PowerShell (Windows) or PowerShell Core (Linux/Mac)
- Azure subscription with sufficient quota for AKS and Application Gateway

## Architecture

The deployment includes:
- **Azure Kubernetes Service (AKS)**: Managed Kubernetes cluster with Azure CNI networking
- **Application Gateway**: Azure Application Gateway with WAF and Microsoft Entra authentication
- **Azure Container Registry (ACR)**: Private container registry for Docker images
- **Azure OpenAI**: Cognitive services for AI capabilities
- **Azure Storage**: Blob storage for application data
- **Virtual Network**: Custom VNet with dedicated subnets for AKS and Application Gateway
- **Workload Identity**: Azure AD workload identity for secure pod authentication

## Quick Start

### 1. Pre-Deployment Validation

```powershell
# Navigate to the deployment directory
cd deployment

# Run pre-deployment checks
./pre-deploy-check.ps1 -ResourceGroupName "respondr" -Location "westus"
```

### 2. Deploy Azure Infrastructure

```powershell
# Create resource group if it doesn't exist
az group create --name "respondr" --location "westus"

# Deploy infrastructure using Bicep template
az deployment group create `
  --resource-group "respondr" `
  --template-file "main.bicep" `
  --parameters location="westus"
```

### 3. Post-Deployment Configuration

```powershell
# Configure AKS, ACR, Application Gateway, and authentication
./post-deploy.ps1 -ResourceGroupName "respondr" -Location "westus"
```

**This script will:**
- Configure AKS credentials and workload identity
- Attach ACR to AKS cluster
- Enable Application Gateway Ingress Controller (AGIC)
- Set up Microsoft Entra authentication
- Create federated credentials for secure pod access
- Deploy and test container images

### 4. Deploy Application to Kubernetes

```powershell
# Deploy the respondr application
./deploy-to-k8s.ps1
```

## Detailed Deployment Steps

### Step 1: Prerequisites Check

Before deployment, ensure you have:

```powershell
# Check Azure login
az account show

# Check resource providers (script will register if needed)
./pre-deploy-check.ps1 -ResourceGroupName "respondr"
```

### Step 2: Infrastructure Deployment

The `main.bicep` template creates:
- AKS cluster with Azure CNI networking (NOT overlay mode)
- Virtual Network with subnets for AKS (10.0.1.0/24) and Application Gateway (10.0.2.0/24)  
- Azure Container Registry
- Azure OpenAI account with gpt-4.1-nano model
- Azure Storage account
- User-assigned managed identity for workload identity

```powershell
# Deploy with custom parameters
az deployment group create `
  --resource-group "respondr" `
  --template-file "main.bicep" `
  --parameters `
    location="westus" `
    resourcePrefix="respondr" `
    aksClusterName="respondr-aks-cluster-v2"
```

### Step 3: Post-Deployment Configuration

The `post-deploy.ps1` script handles complex configuration:

```powershell
./post-deploy.ps1 -ResourceGroupName "respondr" -Location "westus"
```

**Key configuration steps:**
1. **AKS Setup**: Get credentials, enable workload identity
2. **ACR Integration**: Attach registry to AKS for seamless image pulls
3. **AGIC Setup**: Enable Application Gateway Ingress Controller addon
4. **Wait for Application Gateway**: Monitor deployment completion (5-10 minutes)
5. **AGIC Health Check**: Ensure ingress controller pod is running
6. **Workload Identity**: Configure service accounts and federated credentials
7. **Microsoft Entra Auth**: Create app registration and authentication settings
8. **Test Deployment**: Validate ACR integration with test pod

### Step 4: Application Deployment

```powershell
# Deploy application with all components
./deploy-to-k8s.ps1

# Check deployment status
kubectl get pods -n respondr
kubectl get ingress -n respondr
```

## Configuration Details

### Network Configuration

The deployment uses Azure CNI (NOT overlay) for proper Application Gateway integration:

```bicep
networkProfile: {
  networkPlugin: 'azure'
  networkPolicy: 'azure'
  serviceCidr: '10.2.0.0/16'
  dnsServiceIP: '10.2.0.10'
}
```

### Application Gateway Configuration

- **Subnet**: Dedicated subnet (10.0.2.0/24)
- **SKU**: Standard_v2 with autoscaling
- **Authentication**: Microsoft Entra (Azure AD) integration
- **WAF**: Web Application Firewall enabled
- **TLS**: SSL termination at gateway

### Workload Identity

Secure authentication without storing credentials:
- User-assigned managed identity
- Federated credentials for Kubernetes service accounts
- RBAC assignments for Azure resources

## Accessing the Application

### DNS Configuration

After deployment, configure DNS or use hosts file:

```
# Get Application Gateway public IP
az network public-ip show --resource-group "MC_respondr_respondr-aks-cluster-v2_westus" --name "respondr-aks-cluster-v2-appgw-appgwpip" --query "ipAddress" -o tsv

# Add to hosts file (Windows: C:\Windows\System32\drivers\etc\hosts)
<APPLICATION_GATEWAY_IP> respondr.example.com
```

### Application Endpoints

- **Frontend**: https://respondr.example.com
- **API**: https://respondr.example.com/api/responders
- **Webhook**: https://respondr.example.com/webhook
- **Health Check**: https://respondr.example.com/health

## Testing the Deployment

### Verify Infrastructure

```powershell
# Check AKS cluster
kubectl get nodes
kubectl get pods --all-namespaces

# Check Application Gateway
az network application-gateway show --name "respondr-aks-cluster-v2-appgw" --resource-group "MC_respondr_respondr-aks-cluster-v2_westus"

# Check AGIC
kubectl get pods -n kube-system -l app=ingress-appgw
```

### Test Application

```powershell
# Test API endpoint
curl https://respondr.example.com/api/responders

# Send test webhook
curl -X POST https://respondr.example.com/webhook `
  -H "Content-Type: application/json" `
  -d '{"name": "Test User", "text": "SAR Response", "created_at": 1234567890}'
```

## Monitoring and Troubleshooting

### Check Deployment Status

```powershell
# Check AKS cluster health
kubectl get nodes
kubectl get pods --all-namespaces

# Check respondr application
kubectl get pods -n respondr
kubectl get services -n respondr
kubectl get ingress -n respondr

# Check AGIC status
kubectl get pods -n kube-system -l app=ingress-appgw
kubectl logs -n kube-system deployment/ingress-appgw-deployment --tail=20
```

### Common Issues and Solutions

#### 1. AGIC Pod CrashLoopBackOff
**Symptoms**: `kubectl get pods -n kube-system` shows AGIC pod crashing
**Cause**: Application Gateway not ready or misconfigured
**Solution**:
```powershell
# Check Application Gateway status
az network application-gateway show --name "respondr-aks-cluster-v2-appgw" --resource-group "MC_respondr_respondr-aks-cluster-v2_westus" --query "provisioningState"

# If not ready, wait or restart AGIC
kubectl rollout restart deployment/ingress-appgw-deployment -n kube-system
```

#### 2. CNI Overlay Issues
**Symptoms**: Application Gateway cannot be created, networking errors
**Cause**: AKS using CNI overlay mode
**Solution**: Use standard Azure CNI (already configured in main.bicep)

#### 3. Application Gateway Takes Too Long
**Symptoms**: AGIC deployment hangs, Application Gateway creation timeout
**Expected**: 5-10 minutes for Application Gateway creation
**Solution**: Wait longer, check Azure portal for deployment progress

#### 4. Workload Identity Issues
**Symptoms**: Pods cannot access Azure resources
**Solution**:
```powershell
# Verify service account annotations
kubectl describe serviceaccount respondr-sa -n respondr

# Check federated credentials
az identity federated-credential list --identity-name "respondr-pod-identity" --resource-group "respondr"
```

#### 5. DNS Resolution Issues
**Symptoms**: Cannot access application via domain name
**Solution**:
```powershell
# Get Application Gateway IP
$appGwIp = az network public-ip show --resource-group "MC_respondr_respondr-aks-cluster-v2_westus" --name "respondr-aks-cluster-v2-appgw-appgwpip" --query "ipAddress" -o tsv

# Update hosts file or DNS records
Write-Host "Add to hosts file: $appGwIp respondr.example.com"
```

### Debug Commands

```powershell
# Application logs
kubectl logs -n respondr deployment/respondr-deployment --tail=50

# AGIC logs  
kubectl logs -n kube-system deployment/ingress-appgw-deployment --tail=50

# Application Gateway configuration
az network application-gateway show --name "respondr-aks-cluster-v2-appgw" --resource-group "MC_respondr_respondr-aks-cluster-v2_westus"

# Cluster events
kubectl get events --sort-by='.metadata.creationTimestamp' -n respondr

# Port forward for direct access (bypass ingress)
kubectl port-forward -n respondr service/respondr-service 8080:80
```

## Updates and Maintenance

### Upgrading the Application

```powershell
# Build and deploy new version
./upgrade-k8s.ps1 -Version "v1.1" -ResourceGroupName "respondr"

# Quick restart with same image
kubectl rollout restart deployment/respondr-deployment -n respondr

# Check rollout status
kubectl rollout status deployment/respondr-deployment -n respondr
```

### Scaling

```powershell
# Scale application pods
kubectl scale deployment respondr-deployment --replicas=3 -n respondr

# Check pod distribution
kubectl get pods -n respondr -o wide
```

### Infrastructure Updates

```powershell
# Update Bicep template and redeploy
az deployment group create --resource-group "respondr" --template-file "main.bicep"

# Run post-deploy configuration again
./post-deploy.ps1 -ResourceGroupName "respondr"
```

## Security Considerations

- **Workload Identity**: No credentials stored in pods, uses Azure AD federation
- **Microsoft Entra Authentication**: Users must authenticate via Azure AD
- **Network Security**: Application Gateway provides WAF and DDoS protection
- **Private Registry**: Container images stored in Azure Container Registry
- **RBAC**: Kubernetes and Azure RBAC configured for least privilege access
- **TLS Termination**: SSL/TLS handled by Application Gateway

## Production Recommendations

### 1. DNS Configuration
- Use Azure DNS or your domain provider
- Configure proper SSL certificates (Let's Encrypt or Azure certificates)
- Set up monitoring and health checks

### 2. Backup and Disaster Recovery
- Regular AKS cluster backups
- Azure Storage account geo-replication
- Document recovery procedures

### 3. Monitoring and Logging
- Enable Azure Monitor for containers
- Configure Application Insights
- Set up log aggregation and alerting

### 4. CI/CD Pipeline
- Automate deployments with Azure DevOps or GitHub Actions
- Implement proper testing and staging environments
- Use infrastructure as code for all resources

### 5. Cost Optimization
- Use Azure Spot instances for non-critical workloads
- Configure cluster autoscaling
- Monitor and optimize resource usage

## File Structure

```
deployment/
├── README.md                    # This deployment guide
├── main.bicep                   # Azure infrastructure template
├── pre-deploy-check.ps1         # Pre-deployment validation
├── post-deploy.ps1              # Post-deployment configuration
├── deploy-to-k8s.ps1           # Application deployment script
├── upgrade-k8s.ps1             # Application upgrade script
├── redeploy.ps1                # Quick redeploy utilities
├── cleanup.ps1                 # Resource cleanup script
├── respondr-k8s-template.yaml   # Kubernetes manifests
├── secrets-template.yaml        # Secret template (safe to commit)
├── secrets.yaml                 # Actual secrets (gitignored)
├── test-pod.yaml               # Test pod for validation
└── respondr-k8s.yaml           # Generated deployment file
```

## Cleanup

### Remove Application
```powershell
kubectl delete namespace respondr
```

### Remove Azure Infrastructure
```powershell
./cleanup.ps1 -ResourceGroupName "respondr" -Force
```

Or manually:
```powershell
az group delete --name "respondr" --yes --no-wait
```

## Support and Documentation

- **Azure AKS**: https://docs.microsoft.com/en-us/azure/aks/
- **Application Gateway Ingress Controller**: https://docs.microsoft.com/en-us/azure/application-gateway/ingress-controller-overview
- **Azure Workload Identity**: https://docs.microsoft.com/en-us/azure/aks/workload-identity-overview
- **Microsoft Entra Authentication**: https://docs.microsoft.com/en-us/azure/active-directory/
