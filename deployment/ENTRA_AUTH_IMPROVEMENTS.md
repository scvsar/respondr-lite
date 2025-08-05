# Entra Authentication Improvements

This document summarizes the improvements made to the post-deploy script and Kubernetes manifests to fully implement Microsoft Entra authentication as recommended in the security review.

## Key Improvements Made

### 1. AKS Workload Identity Enhancements

#### ✅ Webhook Verification
- Added check for azure-workload-identity-webhook-mutator pods in kube-system namespace
- Warns if webhook is not found (may require manual installation on older AKS versions)

#### ✅ Namespace Isolation
- Created dedicated `respondr` namespace instead of using `default`
- Updated federated credential subject to use correct namespace: `system:serviceaccount:respondr:respondr-sa`
- All Kubernetes resources now deploy to the `respondr` namespace

#### ✅ Enhanced RBAC Permissions
- Added Storage Blob Data Contributor role for storage account access
- Added Cognitive Services OpenAI User role for OpenAI access
- Added tenant ID annotation to service account for cross-tenant scenarios

#### ✅ Required Pod Labels
- Added `azure.workload.identity/use: "true"` label to deployment pod template
- This is mandatory for workload identity token injection

### 2. Application Gateway Ingress Controller (AGIC) Improvements

#### ✅ Extension Installation
- Automatically installs/updates `application-gateway-preview` extension
- Required for auth-setting commands

#### ✅ Proper Identity Management
- Creates dedicated user-assigned managed identity for Application Gateway
- Assigns Network Contributor role on the resource group
- Handles existing identities gracefully (no duplicate creation)

#### ✅ AGIC Permissions
- Assigns Managed Identity Operator role to AGIC identity
- Enables AGIC to impersonate other managed identities when needed

#### ✅ Enhanced App Registration
- Creates Entra app registration with proper redirect URI
- Uses dynamic DNS zone discovery for redirect URI configuration
- Fallback to placeholder when DNS not configured
- Updates existing app registrations instead of creating duplicates

#### ✅ Secure Secret Management
- Stores client secrets in Azure Key Vault when available
- Uses Key Vault reference in auth-setting (recommended practice)
- Fallback to raw secret only when Key Vault not available

#### ✅ Proper Auth-Setting Configuration
- Creates auth-setting with correct parameters
- References auth-setting in Ingress via `appgw.ingress.kubernetes.io/auth-setting` annotation
- Removed manual listener updates (handled by AGIC automatically)

### 3. Storage Account Discovery Improvements

#### ✅ Robust Resource Discovery
- Tries to get storage account name from Bicep outputs first
- Falls back to intelligent discovery with pattern matching
- Warns when multiple accounts found and uses naming patterns to identify the correct one
- Handles cases where no storage account exists

### 4. Kubernetes Manifest Updates

#### ✅ Enhanced Security Configuration
```yaml
# Required workload identity label
metadata:
  labels:
    azure.workload.identity/use: "true"

# Enhanced service account
metadata:
  annotations:
    azure.workload.identity/client-id: CLIENT_ID_PLACEHOLDER
    azure.workload.identity/tenant-id: TENANT_ID_PLACEHOLDER
```

#### ✅ Improved Ingress Configuration
```yaml
metadata:
  annotations:
    appgw.ingress.kubernetes.io/auth-setting: respondrAuth  # Direct reference
    appgw.ingress.kubernetes.io/ssl-redirect: "true"        # Force HTTPS
spec:
  tls:
    - hosts:
      - HOSTNAME_PLACEHOLDER
      secretName: respondr-tls
```

### 5. Deployment Script Enhancements

#### ✅ Dynamic Configuration
- Retrieves identity client ID and tenant ID from Azure deployment outputs
- Uses actual DNS zone for hostname configuration
- Replaces all placeholders in templates automatically

#### ✅ Enhanced Security Information
- Displays authentication status and security features enabled
- Provides proper HTTPS URLs for testing
- Clear guidance on authentication flow

## Security Features Now Enabled

1. **Microsoft Entra Authentication**: All traffic through Application Gateway requires Azure AD authentication
2. **Workload Identity**: Pods securely access Azure resources without storing secrets
3. **TLS Termination**: Application Gateway handles SSL/TLS termination
4. **Namespace Isolation**: Dedicated namespace for better security boundaries
5. **Secret Management**: Client secrets stored in Key Vault when available
6. **Role-Based Access**: Proper Azure RBAC assignments for all components

## Usage Instructions

1. **Run the post-deploy script first** to configure authentication:
   ```powershell
   .\deployment\post-deploy.ps1 -ResourceGroupName "respondr"
   ```

2. **Then run the deployment script** to deploy the application:
   ```powershell
   .\deployment\deploy-to-k8s.ps1 -ResourceGroupName "respondr"
   ```

3. **Access the application** via the authenticated endpoint:
   - Navigate to `https://respondr.<your-domain>` in a browser
   - You'll be redirected to Microsoft sign-in
   - After authentication, you'll have access to the application

## Verification Steps

1. **Check workload identity webhook**:
   ```bash
   kubectl get pods -n kube-system -l app=azure-workload-identity-webhook-mutator
   ```

2. **Verify authentication setting**:
   ```bash
   az network application-gateway auth-setting show \
     --gateway-name <appgw-name> \
     --resource-group respondr \
     --name respondrAuth
   ```

3. **Test pod identity**:
   ```bash
   kubectl exec -n respondr deployment/respondr-deployment -- \
     curl -s http://169.254.169.254/metadata/identity/oauth2/token \
     --header "Metadata: true" \
     --data "api-version=2018-02-01&resource=https://storage.azure.com/"
   ```

All recommendations from the security review have been implemented, providing a fully secure, Entra-authenticated deployment.
