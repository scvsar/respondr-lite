# Respondr Complete Deployment Guide with OAuth2 Authentication

## Quick Start (Zero to Production in 60 minutes)

This guide gets you from nothing to a fully working Respondr application with OAuth2 authentication in about 60 minutes.

### Prerequisites Checklist

- [ ] Azure CLI installed and logged in
- [ ] Docker Desktop running
- [ ] kubectl installed
- [ ] PowerShell 7+ 
- [ ] DNS access to configure A records
- [ ] Azure subscription with Contributor role

### One-Command Deployment

```powershell
# 1. Create resource group
az group create --name respondr --location westus

# 2. Run complete deployment (includes OAuth2 setup)
cd deployment
.\deploy-complete.ps1 -ResourceGroupName respondr -Domain "paincave.pro"
```

**That's it!** This single command:
✅ Deploys all Azure infrastructure (AKS, ACR, Application Gateway, OpenAI)
✅ Sets up OAuth2 Proxy with Azure AD authentication  
✅ Builds and deploys your application with authentication
✅ Configures Let's Encrypt SSL certificates
✅ Provides comprehensive deployment status

### What You Get

- **🔐 OAuth2 Authentication**: Users automatically redirected to Microsoft sign-in
- **🌐 HTTPS**: Automatic Let's Encrypt certificates with renewal
- **🚀 Production Ready**: AKS with Application Gateway, autoscaling, monitoring
- **🔒 Secure**: Zero application code changes for authentication
- **📊 Dashboard**: Real-time response tracking with AI-powered message parsing

## Timeline Expectations

| Phase | Duration | What Happens |
|-------|----------|--------------|
| Infrastructure | 10-15 min | Azure resources deployed |
| Post-Config | 15-20 min | AGIC, identities, auth setup |
| **OAuth2 Setup** | 3-5 min | **Azure AD app + OAuth2 proxy** |
| App Deployment | 5-10 min | Container build and deploy |
| DNS Config | **Manual** | **YOU must update DNS** |
| SSL Certificates | 2-10 min | Let's Encrypt issuance |

**Total: 45-75 minutes** (mostly waiting for Azure services)

## Critical DNS Step

**⚠️ IMPORTANT**: You must configure DNS immediately after deployment:

```powershell
# Get the Application Gateway IP from the deployment output
# Then update your DNS provider (NameCheap, GoDaddy, etc.) with:
# Type: A Record
# Name: respondr
# Value: [Application Gateway IP]
```

DNS must resolve BEFORE Let's Encrypt can issue certificates.

## Verification and Testing

```powershell
# Verify OAuth2 deployment
.\verify-oauth2-deployment.ps1 -Domain "paincave.pro"

# Run comprehensive end-to-end testing
.\test-end-to-end.ps1 -Domain "paincave.pro"
```

## Expected User Experience

1. User visits `https://respondr.paincave.pro`
2. **Automatic redirect to Microsoft sign-in page**
3. User enters Azure AD/Entra credentials
4. **Automatic redirect back to application dashboard**
5. Full access to all features without additional auth prompts

## What's New in This Deployment

### OAuth2 Proxy Sidecar Pattern
- **Zero application code changes** required
- **Transparent authentication** - your FastAPI app doesn't need to handle auth
- **Production-ready** authentication with proper session management
- **Automatic token refresh** and secure cookie handling

### Scripts Added/Updated
- `setup-oauth2.ps1` - Creates Azure AD app registration and OAuth2 configuration
- `deploy-complete.ps1` - Now includes OAuth2 setup by default
- `deploy-to-k8s.ps1` - Supports OAuth2 deployment template selection
- `verify-oauth2-deployment.ps1` - Comprehensive OAuth2 verification
- `test-end-to-end.ps1` - End-to-end testing including authentication flow

### Deployment Templates
- `respondr-k8s-oauth2-template.yaml` - OAuth2 proxy sidecar configuration
- `respondr-k8s-oauth2.yaml` - Generated OAuth2 deployment (after setup)

## Troubleshooting Common Issues

### OAuth2 Authentication Problems
```powershell
# Check OAuth2 proxy logs
kubectl logs -n respondr -l app=respondr -c oauth2-proxy

# Verify OAuth2 secrets
kubectl get secret oauth2-secrets -n respondr -o yaml

# Recreate OAuth2 setup if needed
.\setup-oauth2.ps1 -ResourceGroupName respondr -Domain "paincave.pro"
```

### DNS/Certificate Issues
```powershell
# Check certificate status
kubectl get certificate -n respondr

# Test DNS resolution
nslookup respondr.paincave.pro

# Check ingress status
kubectl get ingress -n respondr
```

### Deployment Issues
```powershell
# Check pod status
kubectl get pods -n respondr -l app=respondr

# View deployment logs
kubectl logs -n respondr -l app=respondr --tail=50
```

## Production Checklist

- [ ] DNS A record configured and propagating
- [ ] Let's Encrypt certificate issued (Ready status)
- [ ] OAuth2 authentication redirecting to Microsoft login
- [ ] Application dashboard accessible after authentication
- [ ] API endpoints working with authentication
- [ ] Webhook endpoint accepting POST requests
- [ ] Pod status: Running with 2/2 containers ready

## Support and Next Steps

### Immediate Testing
1. Visit your domain in browser
2. Verify Microsoft sign-in redirect
3. Test API endpoints after authentication
4. Send test webhook data

### Production Hardening
- Set up monitoring and alerting
- Configure backup strategies
- Implement CI/CD pipelines
- Review security configurations
- Set up log aggregation

### Scaling Considerations
- Configure horizontal pod autoscaling
- Review resource limits and requests
- Consider multi-region deployment
- Plan for high availability

---

## Summary

This deployment provides a **complete, production-ready application** with:

🔐 **Enterprise Authentication** via OAuth2 proxy and Azure AD
🌐 **Automatic HTTPS** with Let's Encrypt certificate management
🚀 **Container Orchestration** with Azure Kubernetes Service
🔒 **Zero Trust Security** with proper authentication and authorization
📊 **Real-time Dashboard** with AI-powered message processing

The OAuth2 sidecar pattern ensures your application gets enterprise-grade authentication without any code changes, making it perfect for production use while maintaining development simplicity.
