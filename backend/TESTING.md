# Testing Against Different Environments

This guide explains how to run tests against local, preprod, and production environments.

## Available Test Scripts

### 1. `test_webhook.py` - Comprehensive webhook testing
```bash
# Test locally (default)
python test_webhook.py

# Test against production
python test_webhook.py --production
```

### 2. `test_preprod.py` - Preprod-specific testing
```bash
# Run basic preprod test suite
python test_preprod.py

# Send custom message to preprod
python test_preprod.py --name "Your Name" --message "Your test message"
```

### 3. `test_acr_webhook.py` - ACR webhook testing (unit tests)
```bash
# Run ACR webhook unit tests
pytest test_acr_webhook.py -v
```

## Environment URLs

| Environment | Webhook URL | Dashboard URL | API URL |
|-------------|-------------|---------------|---------|
| Local | `http://localhost:8000/webhook` | `http://localhost:8000` | `http://localhost:8000/api/responders` |
| Preprod | `https://preprod.rtreit.com/webhook` | `https://preprod.rtreit.com` | `https://preprod.rtreit.com/api/responders` |
| Production | `https://respondr.rtreit.com/webhook` | `https://respondr.rtreit.com` | `https://respondr.rtreit.com/api/responders` |

## Prerequisites

### Environment Setup
1. **API Key**: Ensure `WEBHOOK_API_KEY` is set in environment or `.env` file
   ```bash
   # Generate .env file with current secrets
   cd deployment
   .\create-secrets.ps1
   ```

2. **Python Dependencies**: Install required packages
   ```bash
   pip install -r requirements.txt
   ```

### Authentication

- **Webhook endpoint**: Uses API key authentication (`X-API-Key` header)
- **Dashboard/API**: Uses Azure AD OAuth2 (manual browser login required)

## Testing Scenarios

### Basic Functionality Test
```bash
# Test preprod with the Unit→Team column change
python test_preprod.py
```

### Comprehensive Webhook Testing
```bash
# Test all webhook scenarios against preprod
# (Modify test_webhook.py to add preprod option)
python test_webhook.py --production  # Currently tests production
```

### Custom Message Testing
```bash
# Send specific test message
python test_preprod.py --name "Test User" --message "Responding with SAR-1, ETA 10 minutes"
```

## Verification Steps

After sending test messages:

### 1. Automated Verification (Local only)
The `test_webhook.py` script automatically fetches and analyzes API responses for local testing.

### 2. Manual Verification (Preprod/Production)
1. **Open browser**: Navigate to environment URL
2. **Sign in**: Use Azure AD credentials
3. **Check dashboard**: Verify test messages appear
4. **Validate parsing**: Check vehicle/ETA extraction
5. **Verify UI changes**: Confirm "Unit" column shows "Team" (for preprod)

## Troubleshooting

### Common Issues

**Authentication Errors (401)**
- Check `WEBHOOK_API_KEY` in environment
- Regenerate secrets: `.\create-secrets.ps1`

**Connection Errors**
- Verify environment URLs are accessible
- Check firewall/network settings
- For local: ensure server is running on port 8000

**OAuth2 Issues (Dashboard)**
- Clear browser cache/cookies
- Try incognito/private browsing
- Check Azure AD app registration permissions

### Debug Information

**Check Environment Variables**
```bash
python -c "import os; print('API Key:', 'SET' if os.getenv('WEBHOOK_API_KEY') else 'NOT SET')"
```

**Test Connectivity**
```bash
# Test webhook endpoint
curl -X POST https://preprod.rtreit.com/webhook -H "Content-Type: application/json" -d "{}"

# Test API endpoint (requires OAuth2)
curl https://preprod.rtreit.com/api/responders
```

## Creating Custom Tests

### Example: Test Specific Functionality
```python
import requests
import os

def test_custom_scenario():
    webhook_url = "https://preprod.rtreit.com/webhook"
    api_key = os.getenv('WEBHOOK_API_KEY')
    
    test_message = {
        "id": "12345",
        "name": "Test User",
        "text": "Your test scenario here",
        "created_at": 1234567890,
        # ... other required GroupMe fields
    }
    
    headers = {
        'Content-Type': 'application/json',
        'X-API-Key': api_key
    }
    
    response = requests.post(webhook_url, json=test_message, headers=headers)
    print(f"Status: {response.status_code}")
    print(f"Response: {response.text}")

if __name__ == "__main__":
    test_custom_scenario()
```

## Testing the Unit→Team Change

To specifically verify the column header change:

1. **Send test message**:
   ```bash
   python test_preprod.py --name "Column Test" --message "Testing Team column header"
   ```

2. **Manual verification**:
   - Visit: https://preprod.rtreit.com
   - Sign in with Azure AD
   - Check that the table header shows "Team" instead of "Unit"
   - Verify the message appears in the list

3. **Compare with production**:
   - Visit: https://respondr.rtreit.com  
   - Confirm it still shows "Unit" (until deployed)
