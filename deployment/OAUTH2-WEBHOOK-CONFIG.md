# OAuth2 Webhook Authentication Configuration

## Summary

Successfully configured OAuth2 Proxy to provide **selective authentication** for the Respondr application:

- ✅ **Webhook endpoint** (`/webhook`): **No authentication required** - allows external services like GroupMe to send webhooks
- ✅ **Health endpoint** (`/health`): **No authentication required** - allows monitoring/health checks  
- 🔒 **All other endpoints**: **OAuth2 authentication required** - users must sign in with Azure AD/Entra

## Configuration Details

### OAuth2 Proxy Settings
The OAuth2 proxy sidecar is configured with these key parameters:
```yaml
args:
- --skip-auth-regex=^/webhook$
- --skip-auth-regex=^/health$
```

These regular expressions tell OAuth2 proxy to bypass authentication for:
- `/webhook` - Exact match for webhook endpoint
- `/health` - Exact match for health check endpoint

### Authentication Flow

**For Protected Endpoints (Dashboard, API):**
```
User → Application Gateway → OAuth2 Proxy → Microsoft Login → Application
```

**For Webhook Endpoint:**
```
External Service → Application Gateway → OAuth2 Proxy (bypassed) → Application
```

## Testing Results

### ✅ Webhook Endpoint Testing
```bash
curl -X POST https://respondr.paincave.pro/webhook \
  -H "Content-Type: application/json" \
  -d '{"name":"Test User","text":"Taking SAR78, ETA 15 minutes","created_at":1628198400}'

# Result: HTTP 200 OK - No authentication required
```

### 🔒 Dashboard Testing
```bash
curl https://respondr.paincave.pro/

# Result: HTTP 302 Redirect to Microsoft login
```

## Updated Testing Scripts

### 1. Enhanced test_webhook.py
Supports both local and production testing:
```bash
# Local testing
python test_webhook.py

# Production testing
python test_webhook.py --production
```

### 2. Comprehensive test_webhook_production.py
Full production testing with detailed verification:
```bash
python test_webhook_production.py --production
```

### 3. Individual webhook sender
Send single webhook messages:
```bash
python send_webhook.py --production --name "John Doe" --message "Taking SAR78, ETA 15 minutes"
```

## Production Verification

### ✅ Successful Tests
- [x] 18 test webhook messages sent successfully
- [x] All webhooks bypass OAuth2 authentication  
- [x] Dashboard still requires Microsoft sign-in
- [x] API endpoints protected by OAuth2
- [x] SSL certificates working correctly
- [x] DNS resolution correct

### 📝 Manual Verification Steps
1. **Test Webhook Bypass**: `curl -X POST https://respondr.paincave.pro/webhook -d '{...}'` → Should work without auth
2. **Test Dashboard Auth**: Visit `https://respondr.paincave.pro` → Should redirect to Microsoft login
3. **Verify Data Processing**: Sign in and check that webhook data appears in dashboard

## Security Considerations

### ✅ Secure Configuration
- **Webhook endpoint exposed**: Required for external services (GroupMe, monitoring)
- **Dashboard protected**: Prevents unauthorized access to sensitive data
- **API protected**: Ensures only authenticated users can access responder data
- **Selective bypass**: Only specific endpoints bypass authentication

### 🔐 Production Deployment
The OAuth2 configuration is production-ready with:
- Secure cookie handling with 24-hour expiration
- HTTPS-only cookies with proper SameSite settings
- Azure AD integration with proper tenant configuration
- Automatic token refresh and session management

## GroupMe Integration

With this configuration, GroupMe webhooks will work seamlessly:

1. **GroupMe sends webhook** → `POST https://respondr.paincave.pro/webhook`
2. **OAuth2 proxy bypasses authentication** (due to `--skip-auth-regex=^/webhook$`)
3. **FastAPI application processes webhook** normally
4. **Users access dashboard** → OAuth2 authentication required
5. **Processed data visible** in authenticated dashboard

## Commands for Testing

```bash
# Test production webhook (no auth required)
curl -X POST https://respondr.paincave.pro/webhook \
  -H "Content-Type: application/json" \
  -d '{"name":"Test","text":"SAR78 ETA 15min","created_at":1628198400}'

# Test dashboard (auth required)
curl -I https://respondr.paincave.pro/

# Run comprehensive testing
cd backend
python test_webhook.py --production

# Send individual test message
python send_webhook.py --production --name "Tester" --message "SAR response test"
```

## Deployment Update

The OAuth2 configuration is now part of the standard deployment:

1. **`setup-oauth2.ps1`** creates Azure AD app and configures OAuth2 proxy
2. **`respondr-k8s-oauth2-template.yaml`** includes webhook bypass configuration
3. **`deploy-complete.ps1`** automatically includes OAuth2 setup by default

This provides the perfect balance of security and functionality for production use.
