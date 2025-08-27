# GitHub Actions CI/CD Setup for Preprod Deployment

This guide explains how to set up automated deployment to Azure Container Apps when changes are merged to the `preprod` branch.

## Overview

The workflow (`deploy-preprod.yml`) automatically:
1. Builds a Docker image with version tagging (date.buildnumber format)
2. Pushes the image to Docker Hub
3. Deploys to Azure Container Apps
4. Creates a deployment summary

## Prerequisites

1. **Docker Hub Account** with repository `randytreit/respondr`
2. **Azure Subscription** with Container Apps deployed
3. **GitHub repository** with Actions enabled

## Setup Steps

### 1. Create Azure Service Principal for GitHub Actions

Create a service principal with contributor access to your resource group:

```bash
# Create service principal
az ad sp create-for-rbac \
  --name "github-actions-respondr-preprod" \
  --role contributor \
  --scopes /subscriptions/<SUBSCRIPTION_ID>/resourceGroups/respondrlite \
  --sdk-auth
```

**Alternative: Use OIDC (Recommended for better security)**

```bash
# Create app registration
az ad app create --display-name "github-actions-respondr-preprod"

# Get the app ID
APP_ID=$(az ad app list --display-name "github-actions-respondr-preprod" --query "[0].appId" -o tsv)

# Create service principal
az ad sp create --id $APP_ID

# Get Object ID of the service principal
ASSIGNEE_OBJECT_ID=$(az ad sp show --id $APP_ID --query id -o tsv)

# Assign contributor role to the resource group
az role assignment create \
  --role contributor \
  --assignee-object-id $ASSIGNEE_OBJECT_ID \
  --scope /subscriptions/<SUBSCRIPTION_ID>/resourceGroups/respondrlite

# Configure federated credential for GitHub Actions
az ad app federated-credential create \
  --id $APP_ID \
  --parameters '{
    "name": "github-preprod-deployment",
    "issuer": "https://token.actions.githubusercontent.com",
    "subject": "repo:<YOUR_GITHUB_ORG>/<YOUR_REPO>:ref:refs/heads/preprod",
    "description": "GitHub Actions preprod branch deployment",
    "audiences": ["api://AzureADTokenExchange"]
  }'
```

### 2. Configure GitHub Repository Secrets

Go to your GitHub repository → Settings → Secrets and variables → Actions

Add the following secrets:

#### For Docker Hub:
- `DOCKER_USERNAME`: Your Docker Hub username
- `DOCKER_TOKEN`: Docker Hub access token (create at https://hub.docker.com/settings/security)

#### For Azure (OIDC method):
- `AZURE_CLIENT_ID`: The Application (client) ID from the app registration
- `AZURE_TENANT_ID`: Your Azure AD tenant ID
- `AZURE_SUBSCRIPTION_ID`: Your Azure subscription ID

#### For Azure (Service Principal with secret - alternative method):
If not using OIDC, you'll need:
- `AZURE_CREDENTIALS`: The entire JSON output from the `az ad sp create-for-rbac` command

### 3. Update Workflow Configuration

Edit `.github/workflows/deploy-preprod.yml` and update:

```yaml
env:
  CONTAINER_APP_NAME: respondrlite-ca-667cdd10  # Your actual Container App name
  RESOURCE_GROUP: respondrlite                   # Your resource group name
  DOCKER_REPO: randytreit/respondr               # Your Docker Hub repository
```

### 4. Alternative: Using Azure Container Registry

If you prefer Azure Container Registry over Docker Hub:

```yaml
# Replace Docker Hub login with ACR login
- name: Log in to Azure Container Registry
  uses: azure/docker-login@v1
  with:
    login-server: ${{ secrets.ACR_LOGIN_SERVER }}
    username: ${{ secrets.ACR_USERNAME }}
    password: ${{ secrets.ACR_PASSWORD }}

# Update DOCKER_REPO environment variable
env:
  DOCKER_REPO: myacr.azurecr.io/respondr
```

## Workflow Triggers

The workflow runs on:
- **Push to preprod branch**: Automatic deployment when changes are merged
- **Manual trigger**: Can be triggered manually from Actions tab

## Version Tagging

The workflow uses date-based versioning:
- Format: `YYYY-MM-DD.N` (e.g., `2025-08-27.1`)
- Automatically increments build number for same day
- Tags as `latest` and `preprod` for easy reference

## Monitoring Deployments

### GitHub Actions UI
- View deployment progress: Actions tab → Deploy to Preprod workflow
- Check deployment summary after each run
- Review logs for troubleshooting

### Azure Portal
- Monitor Container App revisions
- Check application logs
- Verify traffic distribution

## Advanced Configuration

### Multiple Environments

Create separate workflows for different environments:

```yaml
# .github/workflows/deploy-prod.yml
on:
  push:
    branches:
      - main

env:
  CONTAINER_APP_NAME: respondrlite-prod
  # ... other prod-specific settings
```

### Approval Gates

Add manual approval for production deployments:

```yaml
jobs:
  approve:
    runs-on: ubuntu-latest
    environment: production  # Configure in repo settings
    steps:
      - run: echo "Approved for production"
  
  deploy:
    needs: approve
    # ... deployment steps
```

### Rollback Strategy

Add rollback capability:

```yaml
- name: Rollback on failure
  if: failure()
  run: |
    # Get previous revision
    PREVIOUS=$(az containerapp revision list \
      -g ${{ env.RESOURCE_GROUP }} \
      -n ${{ env.CONTAINER_APP_NAME }} \
      --query "[1].name" -o tsv)
    
    # Activate previous revision
    az containerapp revision activate \
      -g ${{ env.RESOURCE_GROUP }} \
      -n ${{ env.CONTAINER_APP_NAME }} \
      --revision $PREVIOUS
```

## Troubleshooting

### Common Issues

1. **Authentication failures**
   - Verify service principal has correct permissions
   - Check secret values are correctly set
   - Ensure OIDC federation is configured for correct branch

2. **Docker push failures**
   - Verify Docker Hub credentials
   - Check repository exists and is accessible
   - Ensure Docker Hub rate limits not exceeded

3. **Deployment failures**
   - Verify Container App name is correct
   - Check Azure CLI is using correct subscription
   - Review Container App logs in Azure Portal

### Debug Mode

Enable debug logging by adding:

```yaml
env:
  ACTIONS_RUNNER_DEBUG: true
  ACTIONS_STEP_DEBUG: true
```

## Security Best Practices

1. **Use OIDC instead of secrets** when possible
2. **Limit service principal scope** to specific resource group
3. **Rotate secrets regularly**
4. **Use environments** for production with protection rules
5. **Enable branch protection** on preprod/main branches
6. **Review deployment logs** regularly

## Local Testing

Test the deployment script locally:

```powershell
# Equivalent to what GitHub Actions runs
.\deployment\build-push-docker.ps1 -Deploy -ResourceGroup respondrlite
```

## Support

For issues:
1. Check GitHub Actions logs
2. Review Azure Container Apps diagnostics
3. Verify all secrets are correctly configured
4. Test deployment script locally first