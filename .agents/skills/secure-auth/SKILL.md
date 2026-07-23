---
name: secure-auth
description: Use when changing Entra ID, MSAL, local JWT auth, login Functions, admin access, CORS, token claims, session settings, or auth-related UI.
---

# Secure Authentication

## Rules

1. Validate token signature, issuer, audience, expiry, and required claims.
2. Enforce admin authorization on the server.
3. Keep Entra and local JWT trust paths explicit.
4. Keep local bypass settings disabled outside local tests.
5. Never use fallback signing secrets in deployment.
6. Never put secrets in browser build variables.
7. Redact tokens, cookies, passwords, and claims that contain private data.
8. Fail closed on missing or invalid configuration.
9. Keep CORS origins explicit by environment.

## Test Matrix

- Valid Entra token
- Valid local token
- Expired token
- Wrong issuer or audience
- Missing required claims
- Non-admin user on admin route
- Disabled local auth
- Missing production secret
- Disallowed CORS origin
