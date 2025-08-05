# Respondr Deployment Strategy Guide

## Script Overview

### `deploy-complete.ps1` - Full Stack Deployment
**Use when:** Setting up new environments or complete infrastructure deployment

```powershell
# First-time setup with infrastructure
.\deploy-complete.ps1 -ResourceGroupName "respondr" -Domain "paincave.pro"

# Application-only deployment (infrastructure exists)
.\deploy-complete.ps1 -ResourceGroupName "respondr" -SkipInfrastructure

# Without OAuth2 (uses Application Gateway auth)
.\deploy-complete.ps1 -ResourceGroupName "respondr" -UseOAuth2:$false
```

**Features:**
- ✅ Bicep infrastructure deployment
- ✅ Azure AD app registration
- ✅ DNS and certificate setup
- ✅ Complete automation
- ✅ Production-ready

### `deploy-unified.ps1` - Application Deployment
**Use when:** Updating existing applications or switching authentication modes

```powershell
# OAuth2 mode (default)
.\deploy-unified.ps1

# Direct access mode
.\deploy-unified.ps1 -NoOAuth2

# Skip confirmations
.\deploy-unified.ps1 -NoOAuth2 -Force
```

**Features:**
- ✅ Fast deployment
- ✅ OAuth2 vs Direct mode switching
- ✅ Unified template approach
- ✅ Development-friendly

### ~~`deploy-to-k8s.ps1`~~ - DEPRECATED
**Status:** Legacy script, use `deploy-unified.ps1` instead

## Prerequisites

### For `deploy-complete.ps1`:
- Azure subscription with permissions
- Domain name configured
- kubectl configured
- Azure CLI logged in

### For `deploy-unified.ps1`:
- Existing Azure infrastructure
- Kubernetes cluster access
- `.env` file with configuration:
  ```
  ACR_IMAGE=your-acr.azurecr.io/respondr:tag
  HOSTNAME=your-hostname.domain.com
  TENANT_ID=your-tenant-id
  CLIENT_ID=your-client-id
  ```

## Decision Matrix

| Scenario | Recommended Script |
|----------|-------------------|
| New environment setup | `deploy-complete.ps1` |
| Application code updates | `deploy-unified.ps1` |
| Switch OAuth2 ↔ Direct | `deploy-unified.ps1 -NoOAuth2` |
| Infrastructure changes | `deploy-complete.ps1` |
| Development testing | `deploy-unified.ps1` |
| Production deployment | `deploy-complete.ps1` |
| Quick iterations | `deploy-unified.ps1` |

## Migration from Legacy

If currently using `deploy-to-k8s.ps1`:
1. Update to `deploy-unified.ps1`
2. Ensure `.env` file has required variables
3. Test with `-NoOAuth2` if you need direct access

## Next Steps

1. **Keep both** `deploy-complete.ps1` and `deploy-unified.ps1`
2. **Remove** `deploy-to-k8s.ps1` (deprecated)
3. **Update documentation** to clarify usage
4. **Test** unified deployment script with current configuration
