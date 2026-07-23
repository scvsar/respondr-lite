# Security Instructions

## Core Rules

- Treat webhook bodies, JWT claims, model output, and storage as untrusted.
- Validate JWT signature, issuer, audience, expiry, and claims.
- Enforce admin authorization on the server.
- Authenticate GroupMe webhook traffic.
- Keep local auth bypasses disabled outside tests.
- Never put secrets in `REACT_APP_*` variables.
- Redact secrets and mission data from logs.
- Use least-privilege managed identity and RBAC.
- Fail closed on auth and configuration errors.

## Review Targets

- `backend\app\auth\`
- `backend\app\local_auth.py`
- `functions\local_login\`
- `functions\groupme_ingest\`
- CORS configuration
- GitHub Actions permissions
- Bicep identity and ingress settings
