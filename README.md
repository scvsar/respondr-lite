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

Admin-only editing
- All mutating actions (Add/Edit/Delete, bulk delete, deleted-items admin) require admin users.
- Admins are configured via the environment variable `ALLOWED_ADMIN_USERS` (comma‑separated emails), which is populated from `deployment/values.yaml` key `allowedAdminUsers` by the template processor.
- Non‑admin users are read‑only; the UI hides Edit controls based on `/api/user` → `is_admin`.

To enable admins, add to `deployment/values.yaml`:

allowedAdminUsers:
  - "first.admin@yourdomain.org"
  - "second.admin@yourdomain.org"

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

When a new image is pushed to ACR, an ACR Webhook calls the backend to trigger a rolling restart so pods pull the latest image.

- Endpoint: `POST /internal/acr-webhook`
  - Header: `X-ACR-Token: <token>` (or `?token=<token>`)
  - Token stored in secret `respondr-secrets` key `ACR_WEBHOOK_TOKEN`
- Handler patches the Deployment pod template with a restart timestamp → rolling restart
- OAuth2 Proxy skips auth for this path (regex exempt)

Environment‑scoped webhooks (recommended):
- Production (main): webhook name `respondrmain`, scope `respondr:latest`, URL `https://respondr.<domain>/internal/acr-webhook`
- Pre‑production: webhook name `respondrpreprod`, scope `respondr:preprod*`, URL `https://respondr-preprod.<domain>/internal/acr-webhook`

Automated setup:
```powershell
# Detects your environment and configures a correctly-scoped ACR webhook
./deploy-complete.ps1 -ResourceGroupName respondr -Domain "<your-domain>" -SetupAcrWebhook
# OR
./deploy-template-based.ps1 -ResourceGroupName respondr -Domain "<your-domain>" -SetupAcrWebhook

# Direct call (examples)
./configure-acr-webhook.ps1 -ResourceGroupName respondr -Domain "<your-domain>" -Environment main   -HostPrefix respondr
./configure-acr-webhook.ps1 -ResourceGroupName respondr -Domain "<your-domain>" -Environment preprod -HostPrefix respondr-preprod
```

Manual ACR wiring (Portal):
1) Container Registry → Webhooks → Add
   - Name: `respondrmain`  | `respondrpreprod`
   - Service URI: `https://respondr.<domain>/internal/acr-webhook` | `https://respondr-preprod.<domain>/internal/acr-webhook`
   - Actions: Push
   - Scope: `respondr:latest` (prod) | `respondr:preprod*` (preprod)
   - Custom header: `X-ACR-Token: <same token as in Kubernetes secret>`
2) Ensure `imagePullPolicy: Always`
3) Push an image and watch rollout: `kubectl rollout status deploy/respondr-deployment -n <namespace>`

## CI/CD with GitHub Actions

Automated tests run on PRs, and on merge to `main` an image is built and pushed to ACR.

What runs
- PRs to main: Backend tests with a uv virtualenv (no deploy)
- Push to main: Build Docker image, login to ACR, push `latest` and commit SHA tags

Setup (recommended: OIDC, no client secret)
Prereqs: Azure CLI (`az login`), GitHub CLI (`gh auth login`), Owner/Admin on the repo, and Contributor on the Azure subscription.

Option A — One‑time automated setup
1) From `deployment/`, run the OIDC + secrets setup:
   - `./setup-github-oidc.ps1 -ResourceGroupName <rg> -Repo <owner/repo>`
   - This will:
     - Create/find an Azure App Registration + Service Principal
     - Add federated credentials for the repo (branch and pull_request)
     - Assign AcrPush on your ACR
     - Set these repo secrets: AZURE_CLIENT_ID, AZURE_TENANT_ID, AZURE_SUBSCRIPTION_ID, ACR_NAME, ACR_LOGIN_SERVER

Option B — Service Principal (JSON secret)
- Create an App Registration + Client Secret manually, assign AcrPush to your ACR, then set one secret:
  - AZURE_CREDENTIALS: JSON with clientId, clientSecret, subscriptionId, tenantId
- You can omit the OIDC secrets if you use AZURE_CREDENTIALS.

Minimal required secrets
- Prefer OIDC: AZURE_CLIENT_ID, AZURE_TENANT_ID, AZURE_SUBSCRIPTION_ID
- Or Service Principal: AZURE_CREDENTIALS (JSON)
- ACR resolution: ACR_NAME (e.g., respondracr) or ACR_LOGIN_SERVER (e.g., respondracr.azurecr.io)

How the workflow works
- Tests job (PRs and pushes):
  - Installs uv, creates `.venv`, installs `backend/requirements.txt`
  - Sets `WEBHOOK_API_KEY=test-key` and runs `pytest` for `backend` while ignoring `backend/test_system.py`
- Build job (push to main only):
  - Logs into Azure via OIDC or AZURE_CREDENTIALS
  - Resolves ACR login server using ACR_NAME or ACR_LOGIN_SERVER
  - `az acr login`, then Docker build and push with two tags: `latest` and the commit SHA

Troubleshooting
- Azure login fails:
  - OIDC: Ensure federated credentials exist for your repo/branch, and the repo secrets AZURE_CLIENT_ID/AZURE_TENANT_ID/AZURE_SUBSCRIPTION_ID are set
  - SP JSON: Ensure AZURE_CREDENTIALS is valid JSON with the four fields and the SP has AcrPush on the ACR
- ACR not found or login server empty:
  - Set ACR_NAME or ACR_LOGIN_SERVER as a repo secret; confirm the ACR exists in the target subscription
- Push denied:
  - Verify AcrPush role assignment to the SP/App; re‑run `setup-github-oidc.ps1` if needed
- Webhook doesn’t redeploy:
  - Confirm ACR webhook is configured to POST to `/internal/acr-webhook` with header `X-ACR-Token`
  - Check the token in the ACR webhook matches the one stored in Kubernetes secret `respondr-secrets` (key `ACR_WEBHOOK_TOKEN`)

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

## Testing across environments (local, preprod, prod)

Quick guidance to exercise webhooks, APIs, and the UI in each environment.

Prereqs
- WEBHOOK_API_KEY configured (via environment or `deployment/create-secrets.ps1` which writes Kubernetes secrets and a local `.env`)
- Python deps installed for backend tests: `(cd backend; pip install -r requirements.txt)`

Key URLs (replace hosts for your setup)
- Local: http://localhost:8000 (webhook: `/webhook`, API: `/api/responders`, UI: `/`)
- Preprod: https://respondr-preprod.<your-domain> (webhook: `/webhook`, API: `/api/responders`)
- Production: https://respondr.<your-domain> (webhook: `/webhook`, API: `/api/responders`)

Common test flows (from `backend/`)
- Webhook, local default: `python test_webhook.py`
- Webhook, production: `python test_webhook.py --production`
- Preprod smoke and custom message: `python test_preprod.py [--name "Your Name" --message "Your test message"]`
- ACR webhook unit tests: `pytest test_acr_webhook.py -v`

Manual verification (preprod/prod)
1) Open the environment host in a browser and sign in via Azure AD
2) Confirm your test message appears on the dashboard and fields (vehicle, ETA) look correct
3) API spot check (requires OAuth via ingress): `GET /api/responders`

Troubleshooting
- 401 on webhook: ensure `X-API-Key` header matches `WEBHOOK_API_KEY`; regenerate secrets if needed (`deployment/create-secrets.ps1`)
- Connection errors: verify DNS points to App Gateway IP and cert-manager has issued TLS
- OAuth2 issues: try a private window, or validate the Azure AD app registration and allowed domains

## Pre‑production environment (separate namespace + host)

Deploy a fully isolated pre‑production environment that shares the same Application Gateway/Public IP using host‑based routing and a unique DNS name.

Key points:
- Separate Kubernetes namespace (e.g., `respondr-preprod`)
- Separate DNS host (e.g., `respondr-preprod.<domain>`) via `-HostPrefix`
- Separate image tag (e.g., `preprod`) to avoid impacting `latest`
- Separate ACR webhook, scoped to `respondr:preprod*` (see ACR section above)

Deploy (automated):
```powershell
cd deployment
./deploy-complete.ps1 -ResourceGroupName respondr -Domain "<your-domain>" `
  -Namespace respondr-preprod -HostPrefix respondr-preprod -ImageTag preprod -SkipInfrastructure
```

Manual flow (condensed):
```powershell
cd deployment
./generate-values.ps1 -ResourceGroupName respondr -Domain "<your-domain>" -Namespace respondr-preprod -HostPrefix respondr-preprod -ImageTag preprod
./process-template.ps1 -TemplateFile respondr-k8s-unified-template.yaml -OutputFile respondr-k8s-generated.yaml
kubectl create namespace respondr-preprod --dry-run=client -o yaml | kubectl apply -f -
kubectl -n respondr get secret respondr-secrets -o yaml | `
  sed 's/namespace: respondr/namespace: respondr-preprod/' | kubectl apply -f -
kubectl apply -f redis-deployment.yaml -n respondr-preprod
kubectl apply -f respondr-k8s-generated.yaml -n respondr-preprod
```

Add a DNS A record for your preprod host to the same App Gateway IP and wait for cert‑manager to issue TLS.

## Soft delete and recovery (safety net for deletes)

Deletes in the UI are “soft deletes.” Instead of permanently removing data, entries are moved to a separate Redis key so you can review and restore if needed.

- Active messages Redis key: `respondr_messages`
- Deleted messages Redis key: `respondr_deleted_messages`

New endpoints (OAuth2‑protected via ingress):
- `GET /api/deleted-responders` → list deleted messages (includes `deleted_at` timestamps)
- `POST /api/deleted-responders/undelete` → restore messages; body: `{ "ids": ["<id1>", "<id2>"] }`
- `DELETE /api/deleted-responders/{id}` → permanently remove an entry from deleted storage

Web views:
- Active dashboard: `/dashboard`
- Deleted dashboard: `/deleted-dashboard` (also linked from the main toolbar)

Typical recovery flow:
1) Open `/deleted-dashboard`, copy the message IDs you want to restore
2) Call `POST /api/deleted-responders/undelete` with those IDs
3) Verify the entries appear again on the main page and dashboard

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