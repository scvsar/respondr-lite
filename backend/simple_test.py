import os
from dotenv import load_dotenv
from openai import AzureOpenAI

# Load environment variables
load_dotenv()

# Get Azure OpenAI configuration
api_key = os.getenv("AZURE_OPENAI_API_KEY")
endpoint = os.getenv("AZURE_OPENAI_ENDPOINT")
deployment = os.getenv("AZURE_OPENAI_DEPLOYMENT")
api_version = os.getenv("AZURE_OPENAI_API_VERSION", "2025-01-01-preview")

print(f"API Key: {api_key[:5]}...")
print(f"Endpoint: {endpoint}")
print(f"Deployment: {deployment}")
print(f"API Version: {api_version}")

# Initialize Azure OpenAI client
client = AzureOpenAI(
    api_key=api_key,
    azure_endpoint=endpoint,
    api_version=api_version,
)
print("Client initialized successfully")

# Test simple completion
try:
    response = client.chat.completions.create(
        model=deployment,
        messages=[{"role": "user", "content": "Hello! Can you confirm this connection is working?"}],
        temperature=0,
    )
    print("\nResponse from Azure OpenAI:")
    print(response.choices[0].message.content)
    print("\nConnection test successful!")
except Exception as e:
    print("\nError testing Azure OpenAI connection:")
    print(f"Error details: {e}")
