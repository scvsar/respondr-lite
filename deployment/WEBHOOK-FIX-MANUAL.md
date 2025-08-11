# MANUAL FIX: ACR Webhook Cross-Environment Issue

## Problem
ACR webhook with scope "respondr:*" was triggering production restarts on preprod image pushes.

## Azure Portal Fix Steps

### 1. Delete the problematic webhook
1. Go to Azure Portal → Container Registry → respondrbt774d4d55kswacr
2. Go to "Webhooks" section
3. Delete webhook named "respondrrestart" (if it exists)

### 2. Create environment-specific webhooks

#### Main/Production Webhook:
- **Name**: `respondr-main`
- **Service URI**: `https://respondr.rtreit.com/internal/acr-webhook`
- **Actions**: Push
- **Scope**: `respondr:latest,respondr:main*`
- **Custom headers**: `X-ACR-Token=[your-webhook-token-from-secrets.yaml]`
- **Status**: Enabled

#### Preprod Webhook:
- **Name**: `respondr-preprod`  
- **Service URI**: `https://preprod.rtreit.com/internal/acr-webhook`
- **Actions**: Push
- **Scope**: `respondr:preprod*`
- **Custom headers**: `X-ACR-Token=[your-webhook-token-from-secrets.yaml]`
- **Status**: Enabled

## CLI Commands (if terminal works)

```powershell
$acrName = "respondrbt774d4d55kswacr"

# Delete problematic webhook
az acr webhook delete --registry $acrName --name "respondrrestart"

# Create main webhook (only latest/main tags)
az acr webhook create --registry $acrName --name "respondr-main" --actions push --uri "https://respondr.rtreit.com/internal/acr-webhook" --headers "X-ACR-Token=YOUR_TOKEN" --scope "respondr:latest,respondr:main*"

# Create preprod webhook (only preprod tags)
az acr webhook create --registry $acrName --name "respondr-preprod" --actions push --uri "https://preprod.rtreit.com/internal/acr-webhook" --headers "X-ACR-Token=YOUR_TOKEN" --scope "respondr:preprod*"

# Verify
az acr webhook list --registry $acrName -o table
```

## Result
- Main environment: Only restarts on `latest` or `main*` image pushes
- Preprod environment: Only restarts on `preprod*` image pushes  
- No more cross-environment restarts!

## Next Steps
1. Apply this fix immediately to prevent further production disruptions
2. Update deployment scripts to use the new environment-specific webhook configuration
3. Test by pushing to preprod branch again - should only restart preprod pods
