# Mission Response Tracker

Tracks responses to mission call-outs. Goal is that Rave alert triggers monitoring of GroupMe responses, aggregating the response details into something useful for support/command.

## Infrastructure Overview

This project deploys the following Azure resources:

- **Azure Kubernetes Service (AKS)**: Hosts the application containers
- **Azure Container Registry (ACR)**: Stores container images
- **Azure OpenAI Service**: Provides AI capabilities for the application
- **Azure Storage Account**: Stores response data and other application files

## Prerequisites

- [Azure CLI](https://docs.microsoft.com/en-us/cli/azure/install-azure-cli) (latest version)
- [PowerShell](https://docs.microsoft.com/en-us/powershell/scripting/install/installing-powershell) (version 7.0 or higher)
- [kubectl](https://kubernetes.io/docs/tasks/tools/) (latest version)
- An active Azure subscription
- Contributor role or higher on your Azure subscription
- Docker Desktop installed

## Deployment Instructions

### 1. Prepare Environment

```powershell
# Login to Azure
az login

# Set the active subscription (if you have multiple subscriptions)
az account set --subscription <your-subscription-id>

# Create resource group
az group create --name responseinfra --location westus
```

### 2. Deploy Azure Resources

Deploy all required infrastructure using the Bicep template:

```powershell
# Deploy the Bicep template
az deployment group create --resource-group responseinfra --template-file deployment/main.bicep
```

You can customize deployment parameters as needed:

```powershell
# Example with custom parameters
az deployment group create --resource-group responseinfra --template-file deployment/main.bicep --parameters resourcePrefix=response-prod location=eastus
```

### 3. Run Post-Deployment Configuration

Execute the post-deployment script to configure resources:

```powershell
# Execute post-deployment script
.\deployment\post-deploy.ps1 -ResourceGroupName responseinfra
```

This script will:
- Configure AKS credentials
- Attach ACR to AKS
- Import a test image to ACR
- Deploy a test pod to verify configuration
- Check status of deployed resources

### 4. Cleanup Resources

When you need to tear down the infrastructure:

```powershell
# Clean up all resources
.\deployment\cleanup.ps1 -ResourceGroupName responseinfra
```

This will delete both the main resource group and the AKS-created resource group.

## Resource Naming

All resources are named deterministically to ensure idempotent deployments:

- AKS Cluster: `response-aks-cluster`
- ACR: `responseacr`
- OpenAI Account: `response-openai-account`
- Storage Account: `resp{uniqueString}store` (with a unique suffix based on resource group ID)

You can customize the prefix by setting the `resourcePrefix` parameter during deployment.

## Troubleshooting

### Common Issues

1. **OpenAI Account Soft-Deleted**: If you encounter an error about a soft-deleted OpenAI account, the deployment will automatically attempt to restore it. If this fails, you can purge the soft-deleted resource manually:
   ```powershell
   az resource delete --ids "/subscriptions/{subscription-id}/providers/Microsoft.CognitiveServices/locations/{location}/resourceGroups/{resource-group}/deletedAccounts/{account-name}" --api-version 2023-05-01
   ```

2. **Storage Account Name Already Taken**: The storage account has a unique suffix based on the resource group ID. If you still encounter a name conflict, you can specify a custom name during deployment:
   ```powershell
   az deployment group create --resource-group responseinfra --template-file deployment/main.bicep --parameters storageAccountName=mycustomname
   ```

3. **ACR Access Issues**: If you see `ImagePullBackOff` errors in your pods, ensure ACR is properly attached to AKS:
   ```powershell
   az aks update --name response-aks-cluster --resource-group responseinfra --attach-acr responseacr
   ```

4. **Image Already Exists Error**: When running the post-deployment script, you might see an error about "Tag nginx:test already exists in target registry". This is normal if you've run the script before and simply means the test image is already in your ACR.

5. **AKS Credential Issues**: If kubectl commands fail, refresh your credentials:
   ```powershell
   az aks get-credentials --resource-group responseinfra --name response-aks-cluster --overwrite-existing
   ```

3. **Resource Deletion Hangs**: AKS resource groups can sometimes take a long time to delete. Monitor in the Azure portal and retry if needed.

### Additional Resources

- [AKS Documentation](https://docs.microsoft.com/en-us/azure/aks/)
- [ACR Documentation](https://docs.microsoft.com/en-us/azure/container-registry/)
- [Azure OpenAI Documentation](https://docs.microsoft.com/en-us/azure/cognitive-services/openai/)
- [Azure Storage Documentation](https://docs.microsoft.com/en-us/azure/storage/)