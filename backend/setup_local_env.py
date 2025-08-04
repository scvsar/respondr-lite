#!/usr/bin/env python3

"""
Helper script to create a .env file for local development
Gets the values from your Azure deployment
"""

import subprocess
import os

def get_azure_openai_config(resource_group="respondr"):
    """Get Azure OpenAI configuration from Azure"""
    
    print(f"Getting Azure OpenAI configuration from resource group: {resource_group}")
    
    try:
        # Get OpenAI account name
        cmd = f'az cognitiveservices account list -g "{resource_group}" --query "[?kind==\'OpenAI\'].name" -o tsv'
        result = subprocess.run(cmd, shell=True, capture_output=True, text=True)
        openai_name = result.stdout.strip()
        
        if not openai_name:
            print("❌ No Azure OpenAI account found")
            return None
            
        print(f"✅ Found OpenAI account: {openai_name}")
        
        # Get endpoint
        cmd = f'az cognitiveservices account show -n "{openai_name}" -g "{resource_group}" --query "properties.endpoint" -o tsv'
        result = subprocess.run(cmd, shell=True, capture_output=True, text=True)
        endpoint = result.stdout.strip()
        
        # Get API key
        cmd = f'az cognitiveservices account keys list -n "{openai_name}" -g "{resource_group}" --query "key1" -o tsv'
        result = subprocess.run(cmd, shell=True, capture_output=True, text=True)
        api_key = result.stdout.strip()
        
        # Get deployments
        cmd = f'az cognitiveservices account deployment list -n "{openai_name}" -g "{resource_group}" --query "[].name" -o json'
        result = subprocess.run(cmd, shell=True, capture_output=True, text=True)
        
        import json
        deployments = json.loads(result.stdout)
        
        # Ensure deployments is a list
        if isinstance(deployments, str):
            deployments = [deployments]
        
        print(f"✅ Found deployments: {deployments}")
        
        # Choose deployment (prefer gpt-4o-mini, gpt-4o, etc.)
        preferred = ["gpt-4o-mini", "gpt-4o", "gpt-4", "gpt-35-turbo"]
        deployment = None
        
        for pref in preferred:
            if pref in deployments:
                deployment = pref
                break
        
        if not deployment and deployments:
            deployment = deployments[0]
            
        return {
            "AZURE_OPENAI_API_KEY": api_key,
            "AZURE_OPENAI_ENDPOINT": endpoint,
            "AZURE_OPENAI_DEPLOYMENT": deployment,
            "AZURE_OPENAI_API_VERSION": "2024-12-01-preview"
        }
        
    except Exception as e:
        print(f"❌ Error getting Azure config: {e}")
        return None

def create_env_file(config):
    """Create .env file with the configuration"""
    
    env_content = f"""# Azure OpenAI Configuration for Local Development
# Generated automatically from Azure deployment

AZURE_OPENAI_API_KEY={config['AZURE_OPENAI_API_KEY']}
AZURE_OPENAI_ENDPOINT={config['AZURE_OPENAI_ENDPOINT']}
AZURE_OPENAI_DEPLOYMENT={config['AZURE_OPENAI_DEPLOYMENT']}
AZURE_OPENAI_API_VERSION={config['AZURE_OPENAI_API_VERSION']}
"""
    
    with open('.env', 'w') as f:
        f.write(env_content)
    
    print("✅ Created .env file successfully!")
    print(f"   Endpoint: {config['AZURE_OPENAI_ENDPOINT']}")
    print(f"   Deployment: {config['AZURE_OPENAI_DEPLOYMENT']}")
    print(f"   API Version: {config['AZURE_OPENAI_API_VERSION']}")

def main():
    print("Setting up local development environment")
    print("=" * 50)
    
    # Check if .env already exists
    if os.path.exists('.env'):
        response = input("❓ .env file already exists. Overwrite? (y/N): ")
        if response.lower() != 'y':
            print("Cancelled.")
            return
    
    # Get configuration from Azure
    config = get_azure_openai_config()
    
    if config:
        create_env_file(config)
        print(f"\n🎉 Setup complete!")
        print(f"You can now run: python main.py")
        print(f"And test with: python test_webhook.py")
    else:
        print(f"\n❌ Failed to get Azure configuration")
        print(f"Make sure you're logged into Azure CLI and have access to the resource group")

if __name__ == "__main__":
    main()
