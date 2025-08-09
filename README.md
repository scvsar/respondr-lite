# SCVSAR Response Tracker

A web application that tracks responses to Search and Rescue mission call‑outs. It listens to GroupMe webhooks, uses Azure OpenAI to extract responder details, and shows them on a secure, real‑time dashboard.

## What’s in the box

- FastAPI backend + React frontend
- OAuth2 Proxy sidecar for Azure AD/Entra auth
- Redis for shared state across replicas
- Containerized, Kubernetes‑ready with AGIC + Let’s Encrypt

## End‑to‑end deployment (recommended)

Use the single command flow for a complete setup, including infra, OAuth2, template generation, app deploy, and validation.

```powershell
# Prereqs: Azure CLI, Docker Desktop, kubectl, PowerShell 7+
az login
az account set --subscription <your-subscription-id>

cd deployment
./deploy-complete.ps1 -ResourceGroupName respondr -Domain "paincave.pro"
```

What this does:
- Creates/uses the resource group and deploys infra (AKS, ACR, OpenAI, networking)
- Enables AGIC and cert‑manager, waits for the Application Gateway
- Creates Azure AD app and configures OAuth2 Proxy
- Generates tenant‑specific files from templates (gitignored)
- Builds, pushes, and deploys the app with OAuth2
- Prompts you to add DNS A record and then obtains Let’s Encrypt certs
- Runs validation and smoke checks

DNS step: When prompted, add an A record for your host (e.g., respondr.paincave.pro) to the shown App Gateway IP, then continue. Propagation typically takes 5–60 minutes.

## Template‑based deployment (portable config)

Generated at deploy time and never committed:
- `values.yaml` (environment discovery)
- `secrets.yaml` (OAuth2 + app secrets)
- `respondr-k8s-generated.yaml` (final manifest)

Source templates you can read and version:
- `respondr-k8s-unified-template.yaml` (single source of truth)
- `secrets-template.yaml`, `letsencrypt-issuer.yaml`, `redis-deployment.yaml`

Manual template flow (optional):
```powershell
cd deployment
./generate-values.ps1 -ResourceGroupName respondr -Domain "paincave.pro"
./deploy-template-based.ps1 -ResourceGroupName respondr -Domain "paincave.pro"
```

## Validate, redeploy, and cleanup

- Validate environment or app:
```powershell
cd deployment
./validate.ps1 -ResourceGroupName respondr -Phase env   # AKS/AGIC/ACR/cert‑manager
./validate.ps1 -ResourceGroupName respondr -Phase app   # Workload smoke
```

- Redeploy after code changes (build, push, rollout):
```powershell
cd deployment
./redeploy.ps1 -Action build -ResourceGroupName respondr
```

- Cleanup:
```powershell
cd deployment
./cleanup.ps1 -ResourceGroupName respondr -Force   # full resource group cleanup
```

## Automatic rollouts on new images (ACR webhook)

When a new image is pushed to ACR, you can auto-restart the AKS deployment to pull the latest tag:

- Backend exposes an authenticated endpoint: `POST /internal/acr-webhook`
  - Requires header `X-ACR-Token: <token>` (or `?token=<token>`)
  - Token is stored in Kubernetes secret `respondr-secrets` key `ACR_WEBHOOK_TOKEN`
- The handler patches the Deployment pod template with a restart timestamp, triggering a rolling restart
- RBAC (Role/RoleBinding) allows the service account to patch Deployments in namespace `respondr`
- OAuth2 Proxy skips auth for this path

Wire it up in ACR:
1) In Azure Portal → Container Registry → Webhooks → Add
   - Name: respondr-restart
   - Service URI: https://respondr.paincave.pro/internal/acr-webhook
   - Actions: Push
   - Custom headers: X-ACR-Token: <same token as in secret>
2) Ensure your Deployment uses `imagePullPolicy: Always` (templates updated)
3) Verify by pushing a new image tag or re-pushing latest; watch rollout: `kubectl rollout status deploy/respondr-deployment -n respondr`

## Local development

Pick a mode that suits your workflow:

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

## Application endpoints

- Dashboard (OAuth2‑protected): https://respondr.paincave.pro
- API (OAuth2‑protected via ingress): https://respondr.paincave.pro/api/responders
- Webhook (API key header, OAuth2 bypassed): https://respondr.paincave.pro/webhook
- Health (proxy ping): https://respondr.paincave.pro/ping

Notes
- The OAuth2 Proxy protects all routes by default. In our deployment, `/webhook` is exempted from OAuth2 and instead requires the header `X-API-Key` matching `WEBHOOK_API_KEY`.
- `/api/responders` is not exempted; when accessed through ingress it’s OAuth2‑protected. Liveness/readiness probes hit the pod directly.
- `/ping` is served by OAuth2 Proxy and returns 200 without auth; useful for external health checks.

## Real‑world troubleshooting (short list)

- AGIC/App Gateway timing
  - First creation typically takes 5–10 minutes. The deployment waits automatically.
  - If validation shows a transient warning, re‑run: `./validate.ps1 -ResourceGroupName respondr -Phase env`.

- Can’t get AppGW ports in validation
  - Script now queries by resource ID (no MC RG guess). If it still warns, re‑run once after a few minutes.

- SSL not issued
  - Ensure DNS A record points to the Application Gateway public IP and has propagated.
  - Check cert status: `kubectl get certificate -n respondr` and `kubectl logs -n cert-manager deploy/cert-manager`.

- OAuth2 login loops
  - Recreate OAuth config: `./setup-oauth2.ps1 -ResourceGroupName respondr -Domain "paincave.pro"` then `kubectl rollout restart deploy/respondr-deployment -n respondr`.

- Image pull issues
  - Use the redeploy action (`-Action build`) which handles ACR tagging/push and updates the deployment.

## Notes on architecture

- OAuth2 Proxy runs as a sidecar to protect the app behind Azure AD/Entra.
- Redis provides shared state so replicas don’t need sticky sessions.
- A single unified template drives the Kubernetes manifests for simplicity and tenant portability.

### How AI processes responder messages

- Inbound message arrives via `/webhook` (requires `X-API-Key`).
- Backend builds a time‑aware prompt that instructs the model to:
  - Extract `vehicle` (exact SAR unit, POV, Unknown) from free text
  - Convert ETA durations (e.g., “15 min”, “half hour”, “2 hours”) into an actual 24‑hour `HH:MM` time using current time
  - Normalize clock times (e.g., “11:45 PM” → `23:45`)
  - Return strict JSON: `{ "vehicle": "...", "eta": "HH:MM" }`
- The response is parsed and validated; ETA is post‑processed to ensure format and to compute:
  - `eta_timestamp` (full datetime), `minutes_until_arrival`, and `arrival_status`
- The message record is appended to storage and served by the dashboard/API.

Model/runtime
- Azure OpenAI Chat Completions via `openai` Azure client
- Deployment, endpoint, API key, and version are provided via env vars

### High‑level data flow

```
GroupMe → Webhook Caller
         (X-API-Key)
              │
              ▼
        Ingress (AGIC)
           │       └── TLS (Let’s Encrypt)
           ▼
    OAuth2 Proxy (sidecar)
     ├─ /webhook → skipped (regex)
     └─ other paths → OAuth2 (Azure AD)
           │
           ▼
       Respondr Backend (FastAPI)
        ├─ Azure OpenAI (extract vehicle, ETA)
        ├─ Normalize ETA → HH:MM and compute minutes/status
        └─ Save to Redis (shared state)
           │
           ▼
       Dashboard/API (OAuth2‑protected)
```

## Contributing

1. Fork and create a feature branch
2. Make changes and test locally
3. Open a pull request

## License

MIT — see `LICENSE`.