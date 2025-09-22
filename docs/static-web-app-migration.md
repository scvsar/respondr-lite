# Migration to Azure Static Web Apps + Container Apps

This document describes the migration from a full-stack Docker container to a separated architecture using Azure Static Web Apps for the frontend and Azure Container Apps for the backend.

## Architecture Overview

### Before (Full-Stack Container)
```
┌─────────────────────────────┐
│     Azure Container App     │
│  ┌─────────────────────────┐ │
│  │ Frontend (React Build)  │ │
│  │ Backend (FastAPI)       │ │
│  │ Static File Serving     │ │
│  └─────────────────────────┘ │
└─────────────────────────────┘
```

### After (Separated Architecture)
```
┌─────────────────────────────┐    ┌─────────────────────────────┐
│   Azure Static Web App      │    │     Azure Container App     │
│  ┌─────────────────────────┐ │    │  ┌─────────────────────────┐ │
│  │ Frontend (React SPA)    │◄┼────┼─►│ Backend (FastAPI Only)  │ │
│  │ CDN + Global Distrib.   │ │    │  │ REST API Endpoints      │ │
│  │ Free Tier               │ │    │  │ Authentication          │ │
│  └─────────────────────────┘ │    │  └─────────────────────────┘ │
└─────────────────────────────┘    └─────────────────────────────┘
```

## Benefits of the New Architecture

1. **Cost Optimization**: Frontend hosted on free Azure Static Web Apps tier
2. **Better Performance**: Frontend served via global CDN
3. **Simplified Scaling**: Frontend and backend can scale independently
4. **Improved Security**: Reduced attack surface for backend API
5. **Modern DevOps**: Separate CI/CD pipelines for frontend and backend

## Migration Steps

### 1. Update Infrastructure (Bicep Templates)

The infrastructure templates have been updated to support both architectures:

**New Parameters in `infra/main.bicep`:**
- `staticWebAppName`: Name for the Static Web App resource
- `repositoryUrl`: GitHub repository URL for automatic deployments
- `repositoryBranch`: Git branch to deploy from (default: main)
- `githubToken`: GitHub personal access token for deployments

**New Parameters in `infra/deploy.ps1`:**
- All the above parameters are now supported
- Can be left empty to skip Static Web App deployment

### 2. Update Deployment Scripts

**`deployment/deploy-from-scratch.ps1`** now includes:
- Static Web App name generation
- Parameters for GitHub integration
- Support for both architectures

### 3. Frontend Configuration

**New Files:**
- `frontend/public/staticwebapp.config.json`: Static Web App routing and auth config
- `frontend/src/config.js`: Dynamic API URL configuration
- `frontend/.env.production.template`: Production environment template
- `.github/workflows/azure-swa-deploy.yml`: GitHub Actions for automatic deployment

**Updated Files:**
- `backend/app/__init__.py`: Enhanced CORS configuration for Static Web Apps

### 4. Docker Configuration

**New Files:**
- `Dockerfile.backend`: Backend-only Docker image (no frontend build)

**Existing Files:**
- `Dockerfile`: Keep for backward compatibility or local development

## Deployment Options

### Option 1: Full Migration (Recommended)

Deploy both Static Web App and Container App with backend-only image:

```powershell
# 1. Build and push backend-only image
docker build -f Dockerfile.backend -t your-registry.azurecr.io/respondr-backend:latest .
docker push your-registry.azurecr.io/respondr-backend:latest

# 2. Deploy infrastructure with Static Web App
.\deployment\deploy-from-scratch.ps1 `
  -StaticWebAppName "your-spa-name" `
  -RepositoryUrl "https://github.com/yourusername/respondr-lite" `
  -GitHubToken "your-github-token"

# 3. Configure GitHub repository secrets and variables (see below)
```

### Option 2: Keep Single Container (Backward Compatible)

Continue using the existing full-stack container:

```powershell
# Deploy without Static Web App parameters
.\deployment\deploy-from-scratch.ps1
```

### Option 3: Gradual Migration

1. Deploy Static Web App alongside existing container
2. Test the new architecture
3. Switch traffic gradually
4. Retire the old container

## GitHub Configuration

### Required Secrets

Add these to your GitHub repository secrets:

1. **`AZURE_STATIC_WEB_APPS_API_TOKEN`**
   - Obtained from Static Web App deployment output
   - Used by GitHub Actions for deployments

### Required Variables

Add these to your GitHub repository variables:

1. **`REACT_APP_API_URL`**
   - Your Container App URL (e.g., `https://your-app.region.azurecontainerapps.io`)
   - Used by frontend to communicate with backend

### GitHub Actions Setup

The workflow in `.github/workflows/azure-swa-deploy.yml` will:
- Trigger on changes to the `frontend/` directory
- Build the React application
- Deploy to Azure Static Web Apps
- Handle pull request previews

## CORS Configuration

The backend has been updated to support Static Web Apps:

```python
# Automatic CORS configuration
origins = [
    "http://localhost:3100",  # Local development
    "http://127.0.0.1:3100",  # Local development
]

# Add Static Web App URL from environment
static_web_app_url = os.getenv("STATIC_WEB_APP_URL")
if static_web_app_url:
    origins.append(static_web_app_url)
    origins.append("https://*.azurestaticapps.net")
```

Set the `STATIC_WEB_APP_URL` environment variable in your Container App to your Static Web App URL.

## Environment Variables

### Backend (Container App)

Add/update these environment variables:

```bash
STATIC_WEB_APP_URL=https://your-spa-name.azurestaticapps.net
```

### Frontend (Static Web App)

Configure via GitHub Actions environment or staticwebapp.config.json:

```bash
REACT_APP_API_URL=https://your-container-app.region.azurecontainerapps.io
```

## Authentication

The Static Web App configuration supports Azure AD authentication:

1. **Static Web App**: Handles user authentication via Azure AD
2. **Container App**: Receives authenticated user context via API calls
3. **API Communication**: Uses the existing `/api/user` endpoint for user context

## Monitoring and Troubleshooting

### Common Issues

1. **CORS Errors**: Ensure `STATIC_WEB_APP_URL` is set in Container App environment
2. **API Not Found**: Verify `REACT_APP_API_URL` in GitHub variables
3. **Authentication Issues**: Check Azure AD configuration in both resources
4. **Build Failures**: Review GitHub Actions logs for frontend build issues

### Useful Commands

```powershell
# Check Container App logs
az containerapp logs show --name your-container-app --resource-group your-rg

# Check Static Web App deployment status
az staticwebapp show --name your-spa-name --resource-group your-rg

# Test API connectivity
curl https://your-container-app.region.azurecontainerapps.io/health
```

## Rollback Strategy

If issues arise, you can quickly rollback:

1. **Keep Old Container**: Don't delete the existing full-stack container initially
2. **DNS Switch**: Update DNS to point back to the old container
3. **Feature Flags**: Use environment variables to toggle between architectures

## Migration Helper Script

Use the provided migration helper:

```powershell
.\migrate-to-static-web-app.ps1 -ResourceGroup "your-rg" -GitHubRepo "yourusername/respondr-lite"
```

This script will guide you through the migration process and highlight manual steps.

## Support

For questions or issues with the migration:

1. Check the troubleshooting section above
2. Review Azure Static Web Apps documentation
3. Check GitHub Actions logs for build issues
4. Verify CORS and authentication configuration