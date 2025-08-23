Respondr – Serverless Refactor Brief (ACA + Functions)

Goal: Deliver the same functional surface with radically lower cost (~$0/month for idle) by moving to:

Azure Functions (Consumption) for the incoming GroupMe webhook and housekeeping tasks (free grants: 1M executions + 400k GB‑s/month).
Azure Container Apps (Consumption) for the combined front‑end + back‑end container, scale to zero, and wake on demand via HTTP and Queue triggers (free grants: 180k vCPU‑s, 360k GiB‑s, 2M requests/month).
Azure Storage for queues and tables (replacing Redis). Note: lifecycle management natively covers Blob; Table has no built‑in TTL—so we add a tiny timer Function for deletes.
Built‑in Authentication on Container Apps (aka “Easy Auth”) with Microsoft Entra ID; identity arrives via X-MS-CLIENT-PRINCIPAL* headers.

1) Target Architecture (high level)
GroupMe  ──(HTTP POST)──► Azure Function (HTTP trigger)
                           └─► enqueues JSON → Azure Storage Queue  (respondr-incoming)

Container Apps (Consumption; minReplicas:0)
  └─ Same Docker image runs FastAPI + React build + background queue worker
     • Ingress: HTTPS; Easy Auth (Entra) required for UI/API (except health)
     • Scale rules:
         - HTTP concurrency (wake on web)
         - Azure Queue length (wake on message)  ◄── KEDA scaler (MI/no key)
     • Storage: Azure Table Storage (active responders) + (optional) Blob archive

Azure Functions (Consumption)
  • groupme_ingest (HTTP): validates + pushes to queue
  • table_purge (Timer): deletes Table rows older than N days (because Table has no TTL)

Why this is the cheapest fit

Scale‑to‑zero: Container Apps minReplicas: 0 + queue/http scale rules means no runtime cost when idle.
Generous free grants for ACA requests/compute and Functions executions—light traffic is commonly $0.
No App Gateway / AKS / OAuth proxy to pay for or operate. Authentication handled by Container Apps Authentication; your app reads user/claim headers (e.g., X-MS-CLIENT-PRINCIPAL-NAME).

2) Work Breakdown (order to implement)
Phase 0 – Repo & Operational Hygiene

 Create docs/ (this file), infra/, functions/, container/.

 Add a top‑level .env.sample with all env vars (see §4).

 Turn off the PoC bypass: disable_api_key_check = False in config.py.

Phase 1 – Storage & Data Contracts

 Schema for the queue message (JSON): use your existing WebhookMessage fields (name, text, created_at, group_id, plus optional debug flags).

 Table: ResponderMessages

PartitionKey: group_id (string)

RowKey: id (uuid)

Columns: those used today in storage.add_message() output (name, text, timestamp, timestamp_utc, vehicle, eta, eta_timestamp, eta_timestamp_utc, minutes_until_arrival, arrival_status, raw_status, status_source, status_confidence, team, group_id, created_at).

 Historical (optional/cheap): append raw inbound payloads as newline JSON in a Blob container ingest-raw/yyyymm/…ndjson so we can rely on Blob lifecycle to purge old months automatically.

Phase 2 – Azure Functions (Consumption)

Functions project: functions/ (Python, v2 isolated or v1 in‑proc; pick your standard).

groupme_ingest (HTTP trigger)

Validates shared secret (querystring or header). GroupMe has no native signature; we defend via an opaque token in the callback URL and IP filtering if desired.

Normalizes payload to WebhookMessage and enqueues to Storage Queue respondr-incoming.

Function returns 200 OK.

table_purge (Timer trigger)

Runs daily (or hourly), deletes Table rows older than RETENTION_DAYS. (Because Table Storage lacks TTL; unlike Blob.)

Cost note: Functions (Consumption) include 1M free executions + 400k GB‑s/month. With tiny payloads & short durations you’ll likely live inside free.

Phase 3 – Container App: merge front‑end + back‑end + worker

Single Docker image that serves:

FastAPI backend (your current routes), and

React static build (served by FastAPI), and

A background queue worker thread/process that drains respondr-incoming, runs llm.extract_details_from_text, and writes to Table via your storage facade.

Key changes in code:

storage.py → default STORAGE_BACKEND=azure_table. Ensure Table backend is robust and MI‑auth capable.

user.py → add Easy Auth header parsing first (keep old headers as fallback):

Prefer X-MS-CLIENT-PRINCIPAL (Base64 JSON with claims) and X-MS-CLIENT-PRINCIPAL-NAME / X-MS-CLIENT-PRINCIPAL-ID.

frontend.py → unchanged except ensure static path exists in container image.

New app/worker.py (or integrate into main.py): polling loop using azure-storage-queue with short sleeps when empty. When running in Container Apps, KEDA will scale in to 0 when queue is empty.

Keep /api/debug/* admin‑only, but shift auth to Entra (see §5).

Phase 4 – Scale rules & Authentication on Container Apps

Scale rules on the Container App:

HTTP (concurrency) → wakes app on UI/API traffic.

Azure Queue (respondr-incoming) → wakes app when messages arrive (KEDA). Use Managed Identity for the scaler; no storage keys.

Authentication: enable Container Apps Authentication with Microsoft Entra ID, set Require authentication for the app (except allow unauthenticated /healthz if you want). Headers with claims are injected (e.g., X-MS-CLIENT-PRINCIPAL-NAME).

Phase 5 – Infra as Code + CI/CD

Consolidate infra in Bicep (see §6) to provision:

Storage Account + Queue + Table

Container Apps Environment, User‑Assigned Managed Identity, Container App

Function App (Consumption), App Settings, MI

GitHub Actions:

Build/push container to ACR.

az containerapp update or deploy via Bicep.

azure-functions deploy for functions/.

Phase 6 – Cutover & Cleanup

Switch GroupMe callback URL to the Function endpoint (groupme_ingest), with secret.

Validate end‑to‑end (queue → container worker → table → UI).

Decom old AKS/AppGW/OAuth2‑Proxy/Redis artifacts.

3) Detailed Implementation Notes
3.1 Queue message contract (from groupme_ingest)
```
{
  "name": "Jane Smith",
  "text": "Responding, taking SAR-78, ETA 25",
  "created_at": 1734989162,
  "group_id": "96018206",
  "debug_sys_prompt": null,
  "debug_user_prompt": null,
  "debug_verbosity": null,
  "debug_reasoning": null,
  "debug_max_tokens": null
}
```
3.2 Worker logic (in the Container)
```
def run_worker_loop():
    q = make_queue_client()  # uses DefaultAzureCredential if MI present
    while True:
        msgs = q.receive_messages(messages_per_page=16, visibility_timeout=30)
        got = False
        for m in msgs:
            got = True
            payload = json.loads(m.content)  # SDK returns text (Base64 handled)
            # 1) build history snapshot if desired (read last messages for this user from Table)
            # 2) parsed = extract_details_from_text(...)
            # 3) construct message dict (same shape you store today)
            add_message(message)  # storage facade writes to Table
            q.delete_message(m)
        if not got:
            time.sleep(float(os.getenv("WORKER_IDLE_SLEEP_SEC", "3")))
```
3.3 Authentication header parsing in user.py
```
def _try_easyauth_headers(request):
    # Direct headers:
    email = request.headers.get("X-MS-CLIENT-PRINCIPAL-NAME") or None

    # Full claim bag (Base64 JSON):
    b64 = request.headers.get("X-MS-CLIENT-PRINCIPAL")
    if b64 and not email:
        import base64, json
        try:
            claims = json.loads(base64.b64decode(b64).decode("utf-8")).get("claims", [])
            c = {x["typ"]: x["val"] for x in claims if "typ" in x and "val" in x}
            email = c.get("http://schemas.xmlsoap.org/ws/2005/05/identity/claims/emailaddress") \
                 or c.get("preferred_username") or c.get("name")
        except Exception:
            pass
    return email
```
The Container Apps auth sidecar handles login, sessions, and injects these headers.

3.4 Replace Redis with Azure Table Storage

In storage.py, set default STORAGE_BACKEND=azure_table.

Ensure AzureTableStorage uses DefaultAzureCredential first, then falls back to connection string if provided. Prefer MI in both Functions and Container Apps.

get_storage_info() should reflect current backend azure_table and health.

3.5 Security model

Function endpoint: secret token required (?k=... or X-Webhook-Token).

Container App UI/API: Require Entra sign‑in via Container Apps Authentication; your own code still enforces allowed domains and allowed_admin_users.

Backend API keys: For routes marked “API key auth,” use X-API-Key and a secret injected via Container App secret.

3.6 Cost controls

Container App:

minReplicas: 0, attach HTTP and azure-queue scale rules to wake on demand.

Functions:

Consumption plan (not Premium). Free grant covers most light workloads.

Storage:

Use Blob lifecycle policies for historical logs; add Timer Function to purge Table entities (since no native TTL).

4) Environment variables (single source of truth)

Common

ALLOWED_EMAIL_DOMAINS=scvsar.org,rtreit.com

ALLOWED_ADMIN_USERS="randy@...,alice@..."

Storage

STORAGE_ACCOUNT_NAME=<name>

STORAGE_TABLE_NAME=ResponderMessages

STORAGE_QUEUE_NAME=respondr-incoming

Security

WEBHOOK_API_KEY=<opaque-secret-for-function>

BACKEND_API_KEY=<opaque-secret-for-app-routes>

LLM

AZURE_OPENAI_API_KEY=...

AZURE_OPENAI_ENDPOINT=...

AZURE_OPENAI_DEPLOYMENT=...

AZURE_OPENAI_API_VERSION=2024-02-01

App behavior

TIMEZONE=America/Los_Angeles

DEBUG_FULL_LLM_LOG=false

RETENTION_DAYS=30

5) Ingress + Auth expectations (Container Apps)

Ingress: external: true, allowInsecure: false, targetPort: 8000 (uvicorn port).

Auth (Entra): “Require authentication” and choose Microsoft provider. The auth sidecar injects identity via headers (e.g., X-MS-CLIENT-PRINCIPAL-NAME), which we now consume. Add /.auth/login/aad and /.auth/logout links if you want explicit UI affordances.

6) Infrastructure as Code (Bicep/YAML snippets)

Keep one deploy: storage + queue + table + container apps env + container app + uami + functions.

6.1 Storage: Queue + Table
```
param location string = resourceGroup().location
param saName string
param tableName string = 'ResponderMessages'
param queueName string = 'respondr-incoming'

resource sa 'Microsoft.Storage/storageAccounts@2023-01-01' = {
  name: saName
  location: location
  sku: { name: 'Standard_LRS' }
  kind: 'StorageV2'
  properties: { minimumTlsVersion: 'TLS1_2' }
}

resource qsvc 'Microsoft.Storage/storageAccounts/queueServices@2023-01-01' = {
  name: 'default'
  parent: sa
}

resource queue 'Microsoft.Storage/storageAccounts/queueServices/queues@2023-01-01' = {
  name: queueName
  parent: qsvc
}

resource tsvc 'Microsoft.Storage/storageAccounts/tableServices@2023-01-01' = {
  name: 'default'
  parent: sa
}

resource table 'Microsoft.Storage/storageAccounts/tableServices/tables@2023-01-01' = {
  name: tableName
  parent: tsvc
}
```
6.2 Container Apps Environment + UAMI + App (Consumption)

Use User‑Assigned Managed Identity for both app storage access and the KEDA scaler (queue rule). KEDA MI example for queues is supported.

YAML sketch (apply via az containerapp create --yaml or Bicep equivalent):
```
type: Microsoft.App/containerApps@2024-03-01
name: respondr-app
location: <region>
identity:
  type: UserAssigned
  userAssignedIdentities:
    <uamiResourceId>: {}
properties:
  managedEnvironmentId: <envResourceId>
  configuration:
    ingress:
      external: true
      allowInsecure: false
      targetPort: 8000
    registries:
      - server: <acrName>.azurecr.io
        identity: <uamiResourceId>
    secrets:
      - name: backend-api-key
        value: <set-with-az-cli>
  template:
    containers:
      - name: respondr
        image: <acrName>.azurecr.io/respondr:latest
        env:
          - name: STORAGE_ACCOUNT_NAME
            value: <saName>
          - name: STORAGE_TABLE_NAME
            value: ResponderMessages
          - name: STORAGE_QUEUE_NAME
            value: respondr-incoming
          - name: BACKEND_API_KEY
            secretRef: backend-api-key
    scale:
      minReplicas: 0
      maxReplicas: 3
      rules:
        - name: http
          http:
            concurrentRequests: 5
        - name: queue
          azureQueue:
            queueName: respondr-incoming
            queueLength: "5"
            accountName: <saName>
          auth:
            - identity: <uamiResourceId>   # KEDA uses MI to read queue depth
```
6.3 Enable Authentication (Container Apps)

Portal or ARM: Enable “Authentication” → Microsoft as provider → Require authentication; after that, your app reads identity headers (no SDK necessary).

6.4 Azure Functions (Consumption)

Two functions (groupme_ingest HTTP, table_purge Timer). Function app uses:

AzureWebJobsStorage (required by Functions host).

Managed Identity to access Storage Table/Queue, or connection string if you prefer.

7) Code Tasks (granular)

 Default storage backend → azure_table.

 User auth → Add Easy Auth parsing in user.py (see §3.3); keep existing fallbacks for local/dev.

 Remove Redis assumptions in config.py, storage.py.

 Queue worker module → new app/worker.py; start it when ENABLE_QUEUE_WORKER=true or always in ACA.

 Health endpoints → /healthz (no auth) for readiness/liveness.

 Config cleanup: remove AKS/ACR webhook knobs that are no longer used.

 ENV gating:

ALLOW_LOCAL_AUTH_BYPASS=false in prod; true for dev only.

Move hard‑coded disable flags back to env (remove the temporary disable_api_key_check = True).

8) CI/CD (sketch)

Container

Build image → push to ACR

az containerapp update \ --name respondr-app --resource-group <rg> \ --image <acr>.azurecr.io/respondr:<sha>

Functions

func azure functionapp publish <funcAppName> --python (or az functionapp deployment source config-zip)

Secrets (API keys, OpenAI) are set with az containerapp secret set and Function App settings.

9) Test Plan & Acceptance

Ingest path

Post a GroupMe‑style JSON to Function (groupme_ingest?k=SECRET) → message lands in Queue.

Verify KEDA scales Container App from 0 → 1 (see ACA “Revisions/Replicas”). Queue drains, Table rows appear.

UI path

Browse to Container App URL: redirected to Entra login. After login, /api/user returns allowed domain, is_admin correct.

End‑to‑end

UI shows active responders (Table). Avg ETA, sort, filters work.

Export CSV still works (UTC toggle verified).

Shutdown

After queue empties and idle web traffic, replicas scale back to 0.

Retention

Timer Function deletes rows older than RETENTION_DAYS. Blob lifecycle policy removes old .ndjson archives (if enabled).

10) Open Questions / Assumptions

GroupMe security: No signature header; we use an opaque secret + IP filter. (If GroupMe adds signatures later, we can verify.)

LLM costs: unchanged; retained Azure OpenAI config & prompts.

Cold start: acceptable. Optional: Function can “warm” the app via a ping when it enqueues a message.

Single vs dual container apps: We’re running worker+web in one app to minimize cost/ops. If you want strict isolation later, split into two apps sharing code/image and keep the queue scale rule on the worker app.

11) Quick Reference (docs)

ACA Authentication / Easy Auth (headers like X-MS-CLIENT-PRINCIPAL-* and redirect flows), and how to enable Entra.

ACA free grant & scale to zero: 180k vCPU‑s, 360k GiB‑s, 2M requests monthly; minReplicas: 0.

KEDA scale on Azure Storage Queue with Managed Identity in Container Apps: sample rule and identity wiring.

Functions (Consumption) free grant: 1M executions + 400k GB‑s/month.

Blob lifecycle management is supported; Table isn’t (use a purge Function).

12) Definition of Done

✅ Function endpoint receives GroupMe POST → enqueues to Storage Queue.

✅ Container App scales from 0 on queue or HTTP → processes queue → writes Table → UI displays.

✅ Easy Auth wired; only allowed domains can see the UI; admin list enforced.

✅ Redis removed; Table/Queue used everywhere; (optional) Blob archive + lifecycle.

✅ Bicep/CLI deploys the entire stack; GitHub Actions builds & deploys both artifacts.

✅ Idle cost ≈ $0 (consumption plans + free grants), scale‑to‑zero verified.

