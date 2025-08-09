# Respondr — SAR Response Tracker

A web app to track responses to Search and Rescue call‑outs. It listens to GroupMe webhooks, uses Azure OpenAI to extract responder details (vehicle and ETA), normalizes data, and shows it on a secure, real‑time dashboard.

## Highlights

- Multi‑tenant Azure AD auth via OAuth2 Proxy sidecar (domain‑based allow list)
- AI‑assisted message parsing (vehicle + ETA to HH:MM)
- Redis for shared state across replicas
- Single, template‑driven Kubernetes manifest
- Optional ACR webhook to auto‑rollout on new images

## Topology (high level)

```
GroupMe → Webhook Caller                    ACR → ACR Webhook  
         (X-API-Key)                              (X-ACR-Token)
              │                                        │
              ▼                                        ▼
        Ingress (AGIC) ←─────────────────────────── Ingress (AGIC)
           │       └── TLS (Let’s Encrypt)
           ▼
    OAuth2 Proxy (sidecar)
     ├─ /webhook → skipped (regex)
     ├─ /internal/acr-webhook → skipped (regex)
     └─ other paths → OAuth2 (Azure AD multi‑tenant)
           │
           ▼
       Respondr Backend (FastAPI)
        ├─ GroupMe: Azure OpenAI (extract vehicle, ETA)
        ├─ Normalize ETA → HH:MM; compute minutes/status
        ├─ Persist to Redis (shared state)
        └─ ACR: Validate token & trigger K8s restart
           │
           ▼
       Dashboard/API (OAuth2‑protected)
```

## Application endpoints

Examples (using respondr.example.com):

- Dashboard (OAuth2‑protected): https://respondr.example.com
- API (OAuth2‑protected via ingress): https://respondr.example.com/api/responders
- Webhook (API key header, OAuth2 bypassed): https://respondr.example.com/webhook
- ACR Webhook (token header, OAuth2 bypassed): https://respondr.example.com/internal/acr-webhook
- Health (proxy ping): https://respondr.example.com/ping

For your deployment, replace `respondr.example.com` with your actual host.

Notes
- OAuth2 Proxy protects routes by default. `/webhook` and `/internal/acr-webhook` are regex‑exempt and require headers `X-API-Key` and `X-ACR-Token` respectively.
- `/api/responders` is protected when accessed through ingress; liveness/readiness probes target the pod directly.
- `/ping` is served by OAuth2 Proxy and returns 200 without auth, useful for external health checks.

## What’s included

- FastAPI backend + React frontend
- OAuth2 Proxy for Azure AD/Entra auth (multi‑tenant)
- Redis for shared state across replicas
- Containerized, Kubernetes‑ready with AGIC + Let’s Encrypt

## End‑to‑end deployment (recommended)

One command flow for infra, OAuth2, templates, app deploy, and validation.

```powershell
# Prereqs: Azure CLI, Docker Desktop, kubectl, PowerShell 7+
az login
az account set --subscription <your-subscription-id>

cd deployment
./deploy-complete.ps1 -ResourceGroupName respondr -Domain "<your-domain>"

# Include ACR webhook setup for automatic redeployments
./deploy-complete.ps1 -ResourceGroupName respondr -Domain "<your-domain>" -SetupAcrWebhook
```

What this does:
- Creates/uses the resource group; deploys AKS, ACR, OpenAI, networking
- Enables AGIC and cert‑manager; waits for Application Gateway
- Creates Azure AD app and configures OAuth2 Proxy
- Generates tenant‑specific files from templates (gitignored)
- Builds, pushes, and deploys the app with OAuth2
- Prompts for DNS A record; obtains Let’s Encrypt certs
- Runs validation and smoke checks

DNS step: When prompted, add an A record for your host (e.g., respondr.<your-domain>) to the shown App Gateway IP, then continue. Propagation typically takes 5–60 minutes.

## Multi‑tenant authentication

- Uses Azure AD “common” endpoint to accept users from any tenant
- Application validates user email domains against allowed list
- Allowed domains configured in `deployment/values.yaml` under `allowedEmailDomains`

This yields multi‑tenant sign‑in with app‑level authorization.

## Template‑based deployment (portable config)

Generated at deploy time (not committed):
- `deployment/values.yaml` (environment discovery)
- `deployment/secrets.yaml` (OAuth2 + app secrets)
- `deployment/respondr-k8s-generated.yaml` (final manifest)

Source templates you can read and version:
- `deployment/respondr-k8s-unified-template.yaml` (single source of truth)
- `deployment/secrets-template.yaml`, `deployment/letsencrypt-issuer.yaml`, `deployment/redis-deployment.yaml`

Manual template flow (optional):
```powershell
cd deployment
./generate-values.ps1 -ResourceGroupName respondr -Domain "<your-domain>"
./deploy-template-based.ps1 -ResourceGroupName respondr -Domain "<your-domain>"

# Include ACR webhook setup for automatic redeployments
./deploy-template-based.ps1 -ResourceGroupName respondr -Domain "<your-domain>" -SetupAcrWebhook
```

## Validate, redeploy, and cleanup

Validate environment or app:
```powershell
cd deployment
./validate.ps1 -ResourceGroupName respondr -Phase env   # AKS/AGIC/ACR/cert‑manager
./validate.ps1 -ResourceGroupName respondr -Phase app   # Workload smoke
```

Redeploy after code changes (build, push, rollout):
```powershell
cd deployment
./redeploy.ps1 -Action build -ResourceGroupName respondr
```

Cleanup:
```powershell
cd deployment
./cleanup.ps1 -ResourceGroupName respondr -Force   # full resource group cleanup
```

## Automatic rollouts on new images (ACR webhook)

When a new image is pushed to ACR, auto‑restart the AKS deployment to pull the latest tag.

- Endpoint: `POST /internal/acr-webhook`
  - Header: `X-ACR-Token: <token>` (or `?token=<token>`)
  - Token stored in secret `respondr-secrets` key `ACR_WEBHOOK_TOKEN`
- Handler patches the Deployment pod template with a restart timestamp → rolling restart
- RBAC permits patching Deployments in namespace `respondr`
- OAuth2 Proxy skips auth for this path

Automated setup (recommended):
```powershell
./deploy-complete.ps1 -ResourceGroupName respondr -Domain "<your-domain>" -SetupAcrWebhook
# OR
./deploy-template-based.ps1 -ResourceGroupName respondr -Domain "<your-domain>" -SetupAcrWebhook
# OR manually configure existing deployment
./configure-acr-webhook.ps1 -ResourceGroupName respondr -Domain "<your-domain>"
```

Manual ACR wiring:
1) Azure Portal → Container Registry → Webhooks → Add
   - Name: respondrrestart (alphanumeric only)
   - Service URI: https://<host>/internal/acr-webhook
   - Actions: Push; Scope: respondr:*
   - Custom header: X-ACR-Token: <same token as in secret>
2) Ensure `imagePullPolicy: Always`
3) Verify by pushing a new tag; watch: `kubectl rollout status deploy/respondr-deployment -n respondr`

## Local development

Pick a mode:
```powershell
# Full stack (backend + frontend)
./dev-local.ps1 -Full

# Backend only
./dev-local.ps1

# Containerized (compose)
./dev-local.ps1 -Docker
```

Tests:
```powershell
./run-tests.ps1                # all
(cd backend; python run_tests.py)
(cd frontend; npm test)
```

## How AI processes responder messages

- Inbound message via `/webhook` (requires `X-API-Key`)
- Backend builds a time‑aware prompt to extract:
  - `vehicle` (exact SAR unit, POV, Unknown)
  - `eta` → strict `HH:MM` (normalize clock times and durations)
- Response parsed and validated; post‑process to compute:
  - `eta_timestamp`, `minutes_until_arrival`, `arrival_status`
- Append message to storage and serve via API/dashboard

Model/runtime
- Azure OpenAI Chat Completions via Azure `openai` client
- Deployment, endpoint, API key, and version from env vars

## Contributing

1. Fork and create a feature branch
2. Make changes and test locally
3. Open a pull request

## License

MIT — see `LICENSE`.