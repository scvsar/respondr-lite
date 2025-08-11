# Pre-production Deployment Guide

This repo supports deploying a separate pre-production environment into its own Kubernetes namespace and DNS host on the same Application Gateway/Public IP.

## Overview

**Key Features:**
- **Namespace isolation**: `respondr-preprod` (configurable)
- **DNS routing**: `preprod.rtreit.com` (or custom HostPrefix.Domain)
- **Image tagging**: Uses `preprod` and `preprod-<sha>` tags (never latest)
- **TLS certificates**: cert-manager issues separate certificates per hostname
- **Secret management**: Automatically copies secrets from main namespace if needed
- **ACR integration**: Ensures AKS can pull preprod images from ACR

## Prerequisites

1. **Main deployment working**: Ensure the main production deployment is functional
2. **DNS setup**: Create an A record for your preprod hostname pointing to the same Application Gateway IP
3. **Azure CLI logged in**: `az login` with appropriate permissions
4. **kubectl configured**: Access to your AKS cluster

## Deployment Methods

### Method 1: Automated End-to-End (Recommended)

Run the complete deployment script with preprod parameters:

```powershell
# From deployment/ directory
.\deploy-complete.ps1 `
  -ResourceGroupName respondr `
  -Domain rtreit.com `
  -Namespace respondr-preprod `
  -HostPrefix preprod `
  -ImageTag preprod `
  -SkipInfrastructure
```

**What this does:**
- ✅ Generates values.yaml for preprod configuration
- ✅ Builds and pushes `respondr:preprod` image to ACR
- ✅ Ensures AKS can pull from ACR (attaches if needed)
- ✅ Copies secrets from main namespace if secrets.yaml not found
- ✅ Creates namespace if it doesn't exist
- ✅ Deploys Redis and application with OAuth2
- ✅ Waits for rollout to complete

### Method 2: Step-by-Step (for debugging)

If you need to debug or customize:

```powershell
# 1. Generate configuration
.\generate-values.ps1 -ResourceGroupName respondr -Domain rtreit.com -Namespace respondr-preprod -HostPrefix preprod -ImageTag preprod

# 2. Process template
.\process-template.ps1 -TemplateFile respondr-k8s-unified-template.yaml -OutputFile respondr-k8s-generated.yaml

# 3. Create namespace and copy secrets
kubectl create namespace respondr-preprod --dry-run=client -o yaml | kubectl apply -f -
kubectl get secret respondr-secrets -n respondr -o yaml | sed 's/namespace: respondr/namespace: respondr-preprod/' | kubectl apply -f -

# 4. Build and push image
$acrName = (Select-String 'acrName: "([^"]+)"' values.yaml).Matches[0].Groups[1].Value
$loginServer = (Select-String 'acrLoginServer: "([^"]+)"' values.yaml).Matches[0].Groups[1].Value
az acr login --name $acrName
docker build -t "$loginServer/respondr:preprod" .
docker push "$loginServer/respondr:preprod"

# 5. Deploy
kubectl apply -f redis-deployment.yaml -n respondr-preprod
kubectl apply -f respondr-k8s-generated.yaml -n respondr-preprod
kubectl -n respondr-preprod rollout status deployment/respondr-deployment
```

### Method 3: GitHub Actions (CI/CD)

Push to the `preprod` branch to trigger automated image building:

```bash
# Create and push to preprod branch
git checkout -b preprod
git push origin preprod
```

Then manually deploy using Method 1 or 2 with the built images.

### OIDC Setup for GitHub Actions

To enable GitHub Actions to push images to ACR, configure OIDC authentication:

```powershell
# This is automatically done when using Method 1 with -SetupGithubOidc
.\deploy-complete.ps1 -ResourceGroupName respondr -Namespace respondr-preprod -HostPrefix preprod -SetupGithubOidc -GithubRepo "scvsar/respondr"

# Or run OIDC setup separately for both main and preprod branches
.\setup-github-oidc.ps1 -ResourceGroupName respondr -Repo "scvsar/respondr" -Branch "main,preprod"
```

This configures:
- ✅ Azure AD app registration with federated identity credentials
- ✅ GitHub repository secrets (AZURE_CLIENT_ID, AZURE_TENANT_ID, etc.)
- ✅ ACR permissions for the service principal
- ✅ Support for both `main` and `preprod` branch workflows

## Verification

After deployment, verify everything is working:

```powershell
# Check deployment status
kubectl -n respondr-preprod get all

# Check ingress and certificates
kubectl -n respondr-preprod get ingress -o wide
kubectl -n respondr-preprod get certificates

# Test endpoint
curl -I https://preprod.rtreit.com
# Should return: HTTP/2 200 (after cert-manager provisions TLS)
```

## Troubleshooting

**Common Issues:**

1. **ImagePullBackOff**: 
   - Ensure `preprod` tag exists in ACR
   - Check AKS-ACR integration: `az aks update -g respondr -n <cluster> --attach-acr <acr>`

2. **CreateContainerConfigError**:
   - Missing secrets: Run secret copy step or use deploy-complete.ps1

3. **DNS not resolving**:
   - Verify A record points to Application Gateway IP: `nslookup preprod.rtreit.com`

4. **Certificate issues**:
   - Wait for cert-manager: `kubectl -n respondr-preprod describe certificate`

## Configuration Options

**Common parameters for scripts:**
- `-ResourceGroupName`: Azure resource group (e.g., "respondr")
- `-Domain`: Root domain (e.g., "rtreit.com") 
- `-Namespace`: K8s namespace (e.g., "respondr-preprod")
- `-HostPrefix`: DNS prefix (e.g., "preprod" → preprod.rtreit.com)
- `-ImageTag`: Docker tag (e.g., "preprod")
- `-SkipInfrastructure`: Skip Bicep infrastructure deployment
- `-SkipImageBuild`: Skip Docker build/push (use existing images)

## Architecture

**Traffic Flow:**
```
DNS (preprod.rtreit.com) 
  ↓
Application Gateway (same IP as prod)
  ↓ (host-based routing)
OAuth2 Proxy (port 4180) 
  ↓ (after auth)
FastAPI App (port 8000)
```

**Isolation:**
- ✅ Separate Kubernetes namespace
- ✅ Separate DNS hostname  
- ✅ Separate TLS certificate
- ✅ Separate image tags (preprod vs latest)
- ✅ Shared Application Gateway IP (cost-effective)
