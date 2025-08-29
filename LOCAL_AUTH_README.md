# Local Authentication Setup

This guide explains how to set up and use the local authentication system for external users (deputies, etc.) who cannot use OAuth consent in their organization.

## Overview

The application now supports **dual authentication**:
1. **SSO/EasyAuth**: For SCVSAR staff using their scvsar.org accounts
2. **Local accounts**: For deputies and external users with username/password

## Configuration

### Environment Variables

Add these to your `.env` file or container environment:

```bash
# Enable local authentication
ENABLE_LOCAL_AUTH=true

# Secret key for JWT tokens (generate a secure random string)
LOCAL_AUTH_SECRET_KEY=your-very-secure-secret-key-here

# Session duration in hours (default: 24)
LOCAL_AUTH_SESSION_HOURS=24

# Azure Table Storage table name for local users (default: LocalUsers)
LOCAL_USERS_TABLE=LocalUsers
```

### Generate Secret Key

Generate a secure secret key:
```bash
python -c "import secrets; print(secrets.token_urlsafe(32))"
```

## Creating Local Users

### Method 1: Command Line Script

Use the provided script to create users:

```bash
cd backend
python create_local_user.py deputy1 deputy1@sheriff.org "Deputy John Smith" --organization "Sheriff Dept"
```

For admin users:
```bash
python create_local_user.py admin admin@example.org "Admin User" --admin
```

### Method 2: API Endpoints (Admin Required)

Once you have at least one admin user, you can create additional users via the API:

```bash
# Create a new user
POST /api/auth/local/admin/create-user
{
  "username": "deputy2",
  "password": "secure-password",
  "email": "deputy2@sheriff.org",
  "display_name": "Deputy Jane Doe",
  "organization": "Sheriff Department",
  "is_admin": false
}
```

## User Experience

### Login Flow

1. **Login Choice Page**: Users see two options:
   - "SCVSAR Staff Login" → EasyAuth/SSO
   - "Deputy/External Login" → Username/password form

2. **Local Login Form**: Simple username/password form with validation

3. **Session Management**: Users stay logged in for configured duration

### User Management

**Self-service features:**
- Change password: `/api/auth/local/change-password`
- View profile: `/api/auth/local/me`

**Admin features:**
- List users: `/api/auth/local/admin/users`
- Create users: `/api/auth/local/admin/create-user`
- Reset passwords: `/api/auth/local/admin/reset-password`

## API Endpoints

### Public Endpoints
- `GET /api/auth/local/enabled` - Check if local auth is enabled
- `POST /api/auth/local/login` - Login with username/password
- `POST /api/auth/local/logout` - Logout from session
- `GET /api/auth/local/me` - Get current user info
- `POST /api/auth/local/change-password` - Change own password

### Admin Endpoints (Require Admin Authentication)
- `GET /api/auth/local/admin/users` - List all local users
- `POST /api/auth/local/admin/create-user` - Create new user
- `POST /api/auth/local/admin/reset-password` - Reset user password

## Security Features

- **PBKDF2 Password Hashing**: 100,000 iterations with salt
- **JWT Session Tokens**: Secure session management with expiration
- **HTTP-Only Cookies**: Prevent XSS attacks on session tokens
- **Input Validation**: Comprehensive validation on all inputs
- **Admin-Only Operations**: User management restricted to admins
- **Audit Logging**: All authentication events are logged

## Deployment

### Container Apps Configuration

The Bicep template automatically excludes local auth routes from EasyAuth when authentication is enabled:

```bicep
excludedPaths: [
  '/.auth/*'
  '/api/auth/local/*'
  '/api/auth/local/enabled'
  '/api/user'
  '/static/*'
  '/*.js'
  '/*.css'
  '/*.png'
  '/*.ico'
  '/health'
]
```

### Database Requirements

Local users are stored in Azure Table Storage in the configured table (default: `LocalUsers`). The table is created automatically when the first user is added.

## Troubleshooting

### Common Issues

1. **"Local authentication is not enabled"**
   - Check `ENABLE_LOCAL_AUTH=true` in environment
   - Verify environment variables are loaded correctly

2. **JWT token errors**
   - Ensure `LOCAL_AUTH_SECRET_KEY` is set and consistent across restarts
   - Check token expiration with `LOCAL_AUTH_SESSION_HOURS`

3. **User creation fails**
   - Verify Azure Table Storage connection
   - Check table permissions
   - Ensure user doesn't already exist

### Debug Mode

Enable debug logging:
```bash
DEBUG_LOG_HEADERS=true
```

This will log authentication headers for troubleshooting.

## Migration from OAuth-Only

1. **Deploy with local auth disabled** (default behavior)
2. **Create admin user** using the command-line script
3. **Enable local auth** by setting `ENABLE_LOCAL_AUTH=true`
4. **Create additional users** as needed
5. **Test dual authentication** before announcing to users

The system gracefully handles both authentication methods simultaneously.