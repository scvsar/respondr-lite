import os
from dotenv import load_dotenv
from openai import AzureOpenAI

def test_azure_openai_connection():
    # Load environment variables
    load_dotenv()
    
    # Get Azure OpenAI configuration
    api_key = os.getenv("AZURE_OPENAI_API_KEY")
    endpoint = os.getenv("AZURE_OPENAI_ENDPOINT")
    deployment = os.getenv("AZURE_OPENAI_DEPLOYMENT")
    api_version = os.getenv("AZURE_OPENAI_API_VERSION")
    
    if not api_key or not endpoint or not deployment or not api_version:
        print("Error: Missing required environment variables.")
        print(f"API Key: {'✓' if api_key else '✗'}")
        print(f"Endpoint: {'✓' if endpoint else '✗'}")
        print(f"Deployment: {'✓' if deployment else '✗'}")
        print(f"API Version: {'✓' if api_version else '✗'}")
        return False
    
    print(f"Using Azure OpenAI endpoint: {endpoint}")
    print(f"Using deployment: {deployment}")
    print(f"Using API version: {api_version}")
    
    # Initialize Azure OpenAI client
    client = AzureOpenAI(
        api_key=api_key,
        azure_endpoint=endpoint,
        api_version=api_version,
    )
    
    try:
        # Test simple completion
        response = client.chat.completions.create(
            model=deployment,
            messages=[{"role": "user", "content": "Hello! Can you confirm this connection is working?"}],
            temperature=0,
        )
        
        # Print the response
        reply = response.choices[0].message.content.strip()
        print("\nResponse from Azure OpenAI:")
        print(reply)
        print("\n✓ Connection test successful!")
        return True
        
    except Exception as e:
        print("\n✗ Error testing Azure OpenAI connection:")
        print(f"Error details: {e}")
        return False

if __name__ == "__main__":
    test_azure_openai_connection()
