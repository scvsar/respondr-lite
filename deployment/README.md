# Respondr Kubernetes Deployment Guide

This directory contains all the necessary files to deploy the Respondr application to a Kubernetes cluster.

## Prerequisites

- Docker installed and running
- Kubernetes cluster access (kubectl configured)
- NGINX Ingress Controller installed in your cluster
- Azure OpenAI API credentials

## Architecture

The deployment includes:
- **Deployment**: 2 replicas of the Respondr application
- **Service**: ClusterIP service for internal communication
- **Ingress**: NGINX ingress for external access
- **Secret**: Secure storage for Azure OpenAI credentials

## Quick Start

### 1. Build the Docker Image

```bash
# From the project root directory
docker build -t respondr:latest .
```

### 2. Test Locally (Optional)

```bash
# Test the Docker container locally
docker run -d --name respondr-test -p 8080:8000 --env-file backend/.env respondr:latest

# Test the application
curl http://localhost:8080/api/responders

# Clean up
docker stop respondr-test && docker rm respondr-test
```

### 3. Configure Secrets (IMPORTANT!)

**Option A: Using the deployment script (Recommended)**
```powershell
# Navigate to the deployment directory
cd deployment

# Deploy with your Azure OpenAI API key (script will create secrets.yaml)
./deploy-to-k8s.ps1 -AzureOpenAIApiKey "your-api-key-here"
```

**Option B: Manual secret configuration**
```bash
# 1. Copy the template and fill in your values
cp secrets-template.yaml secrets.yaml

# 2. Edit secrets.yaml with your actual Azure OpenAI credentials
# Replace YOUR_AZURE_OPENAI_API_KEY_HERE with your actual API key
```

**SECURITY NOTE**: The `secrets.yaml` file is gitignored and should NEVER be committed to version control!

### 4. Deploy to Kubernetes

#### Option A: Using the PowerShell Script (Recommended)

```powershell
# Deploy with API key (creates secrets.yaml automatically)
./deploy-to-k8s.ps1 -AzureOpenAIApiKey "your-api-key-here"

# Or deploy to a specific namespace
./deploy-to-k8s.ps1 -Namespace "respondr" -AzureOpenAIApiKey "your-api-key-here"

# If you already have secrets.yaml configured
./deploy-to-k8s.ps1

# Dry run to see what would be deployed
./deploy-to-k8s.ps1 -DryRun
```

#### Option B: Manual Deployment

```bash
# 1. Ensure you have secrets.yaml configured (see step 3)
# 2. Deploy secrets first
kubectl apply -f secrets.yaml

# 3. Deploy the application
kubectl apply -f respondr-k8s-template.yaml

# 4. Wait for deployment to be ready
kubectl wait --for=condition=available --timeout=300s deployment/respondr-deployment

# 5. Check status
kubectl get pods -l app=respondr
kubectl get services -l app=respondr
kubectl get ingress respondr-ingress
```

### 4. Configure Access

Add the following to your `/etc/hosts` file (or equivalent):
```
127.0.0.1 respondr.local
```

Or configure your DNS to point `respondr.local` to your ingress controller's IP.

## Configuration

### Environment Variables

The application requires these Azure OpenAI configuration values:

- `AZURE_OPENAI_API_KEY`: Your Azure OpenAI API key
- `AZURE_OPENAI_ENDPOINT`: Your Azure OpenAI endpoint URL
- `AZURE_OPENAI_DEPLOYMENT`: The deployment name (e.g., "gpt-4o-mini")
- `AZURE_OPENAI_API_VERSION`: API version (e.g., "2025-01-01-preview")

### Resource Limits

Default resource configuration:
- **Requests**: 256Mi memory, 250m CPU
- **Limits**: 512Mi memory, 500m CPU

Adjust these in `respondr-k8s.yaml` based on your cluster capacity and requirements.

## Accessing the Application

Once deployed, you can access:

- **Frontend**: http://respondr.local
- **API**: http://respondr.local/api/responders
- **Webhook**: http://respondr.local/webhook
- **Dashboard**: http://respondr.local/dashboard

## Testing the Deployment

### Test the API
```bash
curl http://respondr.local/api/responders
```

### Send a Test Webhook
```bash
curl -X POST http://respondr.local/webhook \
  -H "Content-Type: application/json" \
  -d '{
    "name": "Test User",
    "text": "I am responding with SAR78, ETA 15 minutes",
    "created_at": '$(date +%s)'
  }'
```

### Run the Test Suite
```bash
# From the backend directory
cd ../backend
python test_webhook.py
```

## Monitoring

### Check Pod Status
```bash
kubectl get pods -l app=respondr
kubectl logs -l app=respondr --tail=100
```

### Check Service Status
```bash
kubectl get services -l app=respondr
kubectl describe service respondr-service
```

### Check Ingress Status
```bash
kubectl get ingress respondr-ingress
kubectl describe ingress respondr-ingress
```

## Updates and Scaling

### Upgrading the Application

For production upgrades with new code changes:

```powershell
# Full upgrade with new version (builds and pushes new container)
./upgrade-k8s.ps1 -Version "v1.1" -ResourceGroupName "respondr"

# Upgrade with automatic rollback on failure
./upgrade-k8s.ps1 -Version "v1.2" -ResourceGroupName "respondr" -RollbackOnFailure

# Use existing image (skip build)
./upgrade-k8s.ps1 -Version "v1.1" -ResourceGroupName "respondr" -SkipBuild

# Dry run to see what would happen
./upgrade-k8s.ps1 -Version "v1.3" -ResourceGroupName "respondr" -DryRun
```

### Quick Redeploy Options

For common redeployment scenarios:

```powershell
# Build new image with timestamp and deploy
./redeploy.ps1 -Action "build" -ResourceGroupName "respondr"

# Restart existing deployment (same image, fresh pods)
./redeploy.ps1 -Action "restart"

# Update configuration (apply new secrets and restart)
./redeploy.ps1 -Action "update-config"
```

### Manual Update Commands

```bash
# Build new image with a tag
docker build -t respondr:v1.1 .

# Update deployment
kubectl set image deployment/respondr-deployment respondr=respondr:v1.1

# Check rollout status
kubectl rollout status deployment/respondr-deployment
```

### Scale the Application
```bash
# Scale to 3 replicas
kubectl scale deployment respondr-deployment --replicas=3

# Check scaling status
kubectl get pods -l app=respondr
```

### Rollback if Needed

```bash
# Rollback to previous version
kubectl rollout undo deployment/respondr-deployment

# Rollback to specific revision
kubectl rollout undo deployment/respondr-deployment --to-revision=2

# Check rollout history
kubectl rollout history deployment/respondr-deployment
```

## Troubleshooting

### Common Issues

1. **Pods not starting**: Check logs with `kubectl logs -l app=respondr`
2. **Ingress not working**: Ensure NGINX Ingress Controller is installed
3. **Azure OpenAI errors**: Verify credentials in the secret
4. **DNS resolution**: Check `/etc/hosts` or DNS configuration

### Debug Commands
```bash
# Get detailed pod information
kubectl describe pods -l app=respondr

# Check events
kubectl get events --sort-by=.metadata.creationTimestamp

# Port forward for direct access (bypass ingress)
kubectl port-forward service/respondr-service 8080:80
```

## Cleanup

To remove the deployment:
```bash
kubectl delete -f respondr-k8s.yaml
```

Or if deployed to a specific namespace:
```bash
kubectl delete namespace respondr
```

## File Structure

```
deployment/
├── README.md                    # This file
├── respondr-k8s-template.yaml   # Kubernetes manifests (safe to commit)
├── secrets-template.yaml        # Secret template (safe to commit)
├── secrets.yaml                 # Actual secrets (DO NOT COMMIT - gitignored)
├── deploy-to-k8s.ps1           # Initial deployment script
├── upgrade-k8s.ps1             # Production upgrade script
├── redeploy.ps1                # Quick redeploy script
├── .gitignore                   # Prevents committing secrets
├── main.bicep                   # Azure infrastructure (if using Azure)
├── post-deploy.ps1              # Post-deployment script
├── cleanup.ps1                  # Resource cleanup script
├── test-pod.yaml                # Test pod configuration
└── respondr-k8s.yaml            # Legacy file (contains placeholder secrets)
```

## Security Considerations

- Azure OpenAI credentials are stored in Kubernetes secrets
- The application runs as a non-root user in the container
- Resource limits are configured to prevent resource exhaustion
- Health checks ensure only healthy pods receive traffic

## Production Recommendations

1. **Use a proper image registry** (Azure Container Registry, Docker Hub, etc.)
2. **Configure persistent storage** if you need data persistence
3. **Set up monitoring** with Prometheus/Grafana
4. **Configure log aggregation** with ELK stack or similar
5. **Use TLS/SSL** with proper certificates
6. **Implement backup strategies** for any persistent data
7. **Set up CI/CD pipelines** for automated deployments
