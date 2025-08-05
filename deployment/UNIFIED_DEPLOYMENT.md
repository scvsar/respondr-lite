# Respondr Unified Deployment Guide

## Overview

The unified deployment system provides a single template and script that can deploy Respondr in either OAuth2-protected mode or direct access mode, depending on your needs.

## Quick Start

### 1. Setup Secrets
```powershell
.\create-secrets.ps1 -ResourceGroupName your-resource-group
```

### 2. Deploy

**OAuth2 Protected (Recommended for Production):**
```powershell
.\deploy-unified.ps1
```

**Direct Access (Development/Testing):**
```powershell
.\deploy-unified.ps1 -NoOAuth2
```

## Deployment Modes

### OAuth2 Protected Mode (Default)
- ✅ **Security**: Azure AD authentication required
- ✅ **Enterprise Ready**: Full OAuth2 integration
- ✅ **Selective Bypass**: Webhook endpoint bypasses authentication
- ✅ **Production Ready**: Secure for public deployment

**Architecture:**
```
Internet → Ingress → OAuth2 Proxy → FastAPI App
                         ↓
                   Webhook Bypass → FastAPI App
```

### Direct Access Mode (`-NoOAuth2`)
- ✅ **Simplicity**: No authentication setup required
- ✅ **Development Friendly**: Direct access to all endpoints
- ✅ **Testing**: Easy for automated testing and development
- ⚠️ **Security**: No authentication protection

**Architecture:**
```
Internet → Ingress → FastAPI App
```

## Command Reference

### Basic Usage
```powershell
# OAuth2 protected deployment (default)
.\deploy-unified.ps1

# Direct access deployment
.\deploy-unified.ps1 -NoOAuth2

# Skip confirmation prompts
.\deploy-unified.ps1 -NoOAuth2 -Force

# Show help
.\deploy-unified.ps1 -Help
```

### Post-Deployment

**Check deployment status:**
```bash
kubectl get pods -n respondr
kubectl logs -n respondr -l app=respondr
```

**Test the application:**
```bash
# Test webhook (works in both modes)
python backend/test_webhook.py --production

# Access dashboard
# OAuth2 mode: Sign in with Azure AD required
# Direct mode: No authentication needed
```

## Files Created

The unified deployment creates:
- `respondr-k8s-processed.yaml` - Processed deployment manifest (temporary)
- Kubernetes resources in the `respondr` namespace

## Configuration Details

### OAuth2 Mode Configuration
- **OAuth2 Proxy**: Running as sidecar container
- **Service Port**: 80 → OAuth2 Proxy (4180) → App (8000)
- **Authentication**: Required for dashboard/API, bypassed for webhook
- **Session Affinity**: ClientIP with 3-hour timeout

### Direct Access Mode Configuration
- **No OAuth2 Proxy**: Single container deployment
- **Service Port**: 80 → App (8000)
- **Authentication**: None required
- **Session Affinity**: ClientIP with 3-hour timeout

## When to Use Each Mode

### Use OAuth2 Mode When:
- Deploying to production
- Need enterprise security
- Multiple users will access the dashboard
- Compliance requires authentication
- Integrating with organizational identity

### Use Direct Access Mode When:
- Development and testing
- Single-user scenarios
- Behind corporate firewall
- Need simple webhook-only access
- Debugging authentication issues

## Migration

### From Direct to OAuth2:
1. Run `create-secrets.ps1` to ensure OAuth2 secrets exist
2. Deploy with: `.\deploy-unified.ps1`

### From OAuth2 to Direct:
1. Deploy with: `.\deploy-unified.ps1 -NoOAuth2`

## Troubleshooting

### Common Issues

**Secrets Missing:**
```bash
kubectl get secrets -n respondr
# Should show: respondr-secrets, oauth2-secrets (OAuth2 mode only)
```

**Deployment Not Ready:**
```bash
kubectl describe deployment respondr-deployment -n respondr
kubectl logs -n respondr -l app=respondr --tail=50
```

**Authentication Issues (OAuth2 mode):**
```bash
kubectl logs -n respondr -l app=respondr -c oauth2-proxy
```

### Health Checks

**Application Health:**
```bash
# Direct mode
curl https://your-domain/api/responders

# OAuth2 mode (requires browser auth)
# Visit: https://your-domain/api/responders
```

**Webhook Test:**
```bash
python backend/test_webhook.py --production
```

## Legacy Deployment Files

The following files remain for compatibility but are no longer recommended:
- `respondr-k8s.yaml` - OAuth2 deployment (legacy)
- `respondr-k8s-oauth2.yaml` - OAuth2 deployment (legacy)
- `deploy-to-k8s.ps1` - Legacy deployment script

Use `deploy-unified.ps1` for all new deployments.
