# Respondr – Serverless Refactor Plan (Azure Functions + Azure Container Apps)

> Purpose: Keep exactly the same functional surface while collapsing infra to the lowest-cost, scale‑to‑zero design. This brief is the single source of truth for the refactor. It is written for an automated coding agent and human reviewers.

---

## 0) Executive Summary

End state:
- Azure Functions (Consumption) handles GroupMe inbound webhook + housekeeping (Table retention).
- Azure Container Apps (Consumption, minReplicas: 0) runs a single Docker image that serves the FastAPI backend + React UI and a queue worker for LLM parsing & persistence.
- Azure Storage replaces Redis:
 - Queue respondr-incoming for ingest handoff and scale-from-zero.
 - Table ResponderMessages as the canonical store.
 - (Optional) Blob for raw ingest archives with lifecycle rules.
- Auth: Container Apps built-in authentication (Entra). App reads identity from X-MS-CLIENT-PRINCIPAL* headers. Domain allowlist + admin list enforced in app.

Why cheaper: Everything is consumption and scales to zero. No AKS, no App Gateway, no OAuth2 proxy, no Redis.

---

## 1) What Changes at a Glance (Delta Map)

| Area | Today | Target |
|---|---|---|
| Ingress from GroupMe | FastAPI /webhook | Azure Function groupme_ingest (HTTP), enqueues to Storage Queue |
| App runtime | AKS + OAuth proxy | Container Apps (Consumption) with Easy Auth |
| State | Redis + files | Azure Table (canonical), optional Blob archive |
| Background work | In-app | Queue worker in the same container image, auto-wakes via queue rule |
| AuthN | OAuth2 proxy headers | Easy Auth headers (X-MS-CLIENT-PRINCIPAL*), domain/admin checks remain |
| Cost posture | Always-on infra | Scale-to-zero; pay only when invoked |

---

## 2) Repository Plan


/ (repo root)
├─ container/ # Docker image & app runtime
│ ├─ Dockerfile
│ ├─ start.sh # launches uvicorn + worker (or startup thread)
│ └─ appsettings.json # optional local dev config
├─ functions/ # Azure Functions (Python)
│ ├─ groupme_ingest/ # HTTP trigger → enqueue
│ └─ table_purge/ # Timer trigger → delete old Table rows
├─ infra/ # Bicep/ARM and scripts
│ ├─ main.bicep # simplified resources (Storage, ACA, MI, Func)
│ └─ deploy.ps1/.sh
├─ docs/
│ └─ refactor-aca-serverless.md # this brief
├─ app/ # existing Python backend
│ ├─ ... existing modules (config.py, storage.py, llm.py, etc.)
│ └─ worker.py # new: queue consumer
└─ frontend/ # existing React app


---

## 3) Milestones & PR Checklist (ship in thin slices)

### PR1 – Storage & Config Scaffolding
- [ ] Add Table + Queue names to .env.sample.
- [ ] Ensure storage.py defaults to STORAGE_BACKEND=azure_table when not testing.
- [ ] Verify AzureTableStorage implementation (MI first; conn string fallback). If missing, add it.
- [ ] Implement get_storage_info() to reflect azure_table and health.

### PR2 – Ingest Function (HTTP → Queue)
- [ ] New Function functions/groupme_ingest (Python). Validates WEBHOOK_API_KEY (?k= or X-Webhook-Token).
- [ ] Normalizes payload to current WebhookMessage structure and enqueues JSON to STORAGE_QUEUE_NAME.
- [ ] Return 200 OK on success.

### PR3 – Queue Worker in Container App
- [ ] Add app/worker.py that reads messages, calls extract_details_from_text(...), then add_message(...) (which writes to Table).
- [ ] Make worker idempotent and at-least-once safe:
 - Calculate deterministic message_id (e.g., UUID5 over (group_id|name|created_at|text)), use as RowKey to avoid duplicates.
 - Upsert/merge semantics: if entity exists, update fields.
- [ ] Start worker via: (a) a background thread on FastAPI startup, or (b) a secondary process in start.sh. Prefer thread for simplicity.

### PR4 – Auth: Switch to Easy Auth Headers
- [ ] In user.py, prefer headers:
 - X-MS-CLIENT-PRINCIPAL-NAME → email/UPN
 - X-MS-CLIENT-PRINCIPAL (base64 JSON) → claims fallback
- [ ] Keep old headers as fallback for local/dev.
- [ ] Keep domain allowlist and allowed_admin_users logic.

### PR5 – Remove Redis Assumptions & Tighten Config
- [ ] Remove/ignore Redis config in config.py unless explicitly selected in env.
- [ ] Delete PoC override: disable_api_key_check = True → derive from env only.
- [ ] Add /healthz unauthenticated route.

### PR6 – Timer Function (Table Retention)
- [ ] functions/table_purge (Timer) deletes ResponderMessages older than RETENTION_DAYS.
- [ ] Optional: append raw ingest to Blob .ndjson with lifecycle on container (Blob lifecycle is native; Table needs this function).

### PR7 – Infra
- [ ] Bicep or CLI to deploy: Storage (Queue, Table), Container Apps Env, Container App, Function App, User‑Assigned MI, and role assignments:
 - MI → Storage Queue Data Contributor and Table Data Contributor.
 - If using separate scaler identity, grant Queue Data Reader.
- [ ] Container App: enable Authentication (Entra) + require auth for UI/API.
- [ ] Scale rules: HTTP concurrency + Azure Queue.

### PR8 – Cutover & Delete Legacy
- [ ] Move GroupMe webhook URL to the Function endpoint.
- [ ] End-to-end verification.
- [ ] Remove AKS/AppGW/OAuth2-proxy/Redis assets.

---

## 4) Interfaces & Data Contracts (Source of Truth)

### 4.1 Queue Message (enqueued by Function)
json
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


### 4.2 Table Schema: ResponderMessages
- PartitionKey: group_id
- RowKey: deterministic message_id (UUID5 hash of (group_id|name|created_at|text)), or preexisting id if present
- Columns:
 - id, name, text, timestamp, timestamp_utc, vehicle, eta, eta_timestamp, eta_timestamp_utc, minutes_until_arrival,
 - arrival_status, raw_status, status_source, status_confidence, team, group_id, created_at, deleted_at (nullable)

### 4.3 Admin/Debug Endpoints (unchanged behavior)
- /api/debug/* guarded by admin checks (Easy Auth headers + allowlist).

---

## 5) Environment Variables (One List, Two Runtimes)

Common
- TIMEZONE=America/Los_Angeles
- ALLOWED_EMAIL_DOMAINS=scvsar.org,rtreit.com
- ALLOWED_ADMIN_USERS=randy@...,alice@...
- RETENTION_DAYS=30

Storage
- STORAGE_ACCOUNT_NAME=<name>
- STORAGE_TABLE_NAME=ResponderMessages
- STORAGE_QUEUE_NAME=respondr-incoming
- (Optional) AZURE_STORAGE_CONNECTION_STRING (fallback; MI preferred)

Security
- WEBHOOK_API_KEY=<opaque> (Functions)
- BACKEND_API_KEY=<opaque> (X-API-Key for backend routes)

LLM
- AZURE_OPENAI_API_KEY=...
- AZURE_OPENAI_ENDPOINT=...
- AZURE_OPENAI_DEPLOYMENT=...
- AZURE_OPENAI_API_VERSION=2024-02-01

Worker
- ENABLE_QUEUE_WORKER=true (Container App)
- WORKER_POLL_BATCH=16
- WORKER_VISIBILITY_TIMEOUT=30
- WORKER_IDLE_SLEEP_SEC=3

---

## 6) Code Changes by File (Precise)

### 6.1 user.py – prefer Easy Auth
python
def _try_easyauth_headers(request):
 email = request.headers.get("X-MS-CLIENT-PRINCIPAL-NAME")
 if email:
 return email
 b64 = request.headers.get("X-MS-CLIENT-PRINCIPAL")
 if b64:
 import base64, json
 claims = json.loads(base64.b64decode(b64).decode("utf-8")).get("claims", [])
 c = {x.get("typ"): x.get("val") for x in claims}
 return c.get("http://schemas.xmlsoap.org/ws/2005/05/identity/claims/emailaddress") or c.get("preferred_username") or c.get("name")
 return None

Integrate this at the top of get_user_info() before current header fallbacks.

### 6.2 storage.py – default to Azure Table
- Default STORAGE_BACKEND=azure_table.
- Ensure AzureTableStorage uses DefaultAzureCredential if available.
- add_message(...) should upsert on (PartitionKey, RowKey).

### 6.3 config.py
- Remove hard override disable_api_key_check = True.
- Keep all feature toggles behind env.

### 6.4 New app/worker.py
python
import os, json, threading, time
from azure.identity import DefaultAzureCredential
from azure.storage.queue import QueueClient
from .storage import add_message
from .llm import extract_details_from_text
from .utils import parse_datetime_like

SA = os.getenv("STORAGE_ACCOUNT_NAME")
QN = os.getenv("STORAGE_QUEUE_NAME", "respondr-incoming")

def _queue():
 conn = os.getenv("AZURE_STORAGE_CONNECTION_STRING")
 if conn:
 return QueueClient.from_connection_string(conn, QN)
 cred = DefaultAzureCredential()
 return QueueClient(f"https://{SA}.queue.core.windows.net", QN, credential=cred)

def _message_id(m):
 import uuid
 key = f"{m.get('group_id','')}|{m.get('name','')}|{m.get('created_at','')}|{m.get('text','')}"
 return str(uuid.uuid5(uuid.NAMESPACE_URL, key))

def run_worker_loop():
 if os.getenv("ENABLE_QUEUE_WORKER", "false").lower() != "true":
 return
 q = _queue()
 batch = int(os.getenv("WORKER_POLL_BATCH", "16"))
 vis = int(os.getenv("WORKER_VISIBILITY_TIMEOUT", "30"))
 idle = float(os.getenv("WORKER_IDLE_SLEEP_SEC", "3"))
 while True:
 got = False
 for msg in q.receive_messages(messages_per_page=batch, visibility_timeout=vis):
 got = True
 payload = json.loads(msg.content)
 base = parse_datetime_like(payload.get("created_at"))
 parsed = extract_details_from_text(payload.get("text", ""), base_time=base, prev_eta_iso=None)
 entity = {
 "id": _message_id(payload),
 "name": payload.get("name"),
 "text": payload.get("text"),
 "timestamp": base.isoformat() if base else None,
 "timestamp_utc": base.astimezone().__class__.utc.__call__().isoformat() if base else None,
 "vehicle": parsed.get("vehicle"),
 "eta": parsed.get("eta"),
 "eta_timestamp": parsed.get("eta_timestamp"),
 "eta_timestamp_utc": parsed.get("eta_timestamp_utc"),
 "minutes_until_arrival": parsed.get("minutes_until_arrival"),
 "arrival_status": parsed.get("arrival_status"),
 "raw_status": parsed.get("raw_status"),
 "status_source": parsed.get("status_source"),
 "status_confidence": parsed.get("status_confidence"),
 "team": parsed.get("team", "Unknown"),
 "group_id": payload.get("group_id") or "unknown",
 "created_at": int(payload.get("created_at") or 0)
 }
 add_message(entity)
 q.delete_message(msg)
 if not got:
 time.sleep(idle)

# Option A: call from FastAPI startup (preferred)
thread = threading.Thread(target=run_worker_loop, daemon=True)
thread.start()

*(Keep comments minimal; adjust the UTC line if needed—use your existing helpers such as now_tz.)

### 6.5 App startup hook
- In main.py (or FastAPI app factory), spawn worker.run_worker_loop() in a background thread only when ENABLE_QUEUE_WORKER=true.

### 6.6 /healthz
- Add a simple unauthenticated GET returning { "ok": true } for readiness/liveness.

---

## 7) Azure Functions – Minimal Sketches

### 7.1 functions/groupme_ingest/__init__.py
python
import os, json
import azure.functions as func
from azure.storage.queue import QueueClient
from azure.identity import DefaultAzureCredential

WEBHOOK_KEY = os.getenv("WEBHOOK_API_KEY")
SA = os.getenv("STORAGE_ACCOUNT_NAME")
QN = os.getenv("STORAGE_QUEUE_NAME", "respondr-incoming")

def _queue():
 conn = os.getenv("AZURE_STORAGE_CONNECTION_STRING")
 if conn:
 return QueueClient.from_connection_string(conn, QN)
 cred = DefaultAzureCredential()
 return QueueClient(f"https://{SA}.queue.core.windows.net", QN, credential=cred)

async def main(req: func.HttpRequest) -> func.HttpResponse:
 token = req.params.get('k') or req.headers.get('X-Webhook-Token')
 if token != WEBHOOK_KEY:
 return func.HttpResponse("unauthorized", status_code=401)
 body = req.get_json()
 msg = {
 "name": body.get("name") or "Unknown",
 "text": body.get("text") or "",
 "created_at": int(body.get("created_at") or 0),
 "group_id": str(body.get("group_id") or "unknown"),
 **{k:v for k,v in body.items() if k.startswith("debug_")}
 }
 _queue().send_message(json.dumps(msg))
 return func.HttpResponse("ok", status_code=200)


### 7.2 functions/table_purge/__init__.py
python
import os, datetime as dt
import azure.functions as func
from azure.data.tables import TableServiceClient
from azure.identity import DefaultAzureCredential

SA = os.getenv("STORAGE_ACCOUNT_NAME")
TN = os.getenv("STORAGE_TABLE_NAME", "ResponderMessages")
RETENTION = int(os.getenv("RETENTION_DAYS", "30"))

def _table():
 conn = os.getenv("AZURE_STORAGE_CONNECTION_STRING")
 if conn:
 return TableServiceClient.from_connection_string(conn).get_table_client(TN)
 cred = DefaultAzureCredential()
 return TableServiceClient(endpoint=f"https://{SA}.table.core.windows.net", credential=cred).get_table_client(TN)

def _older_than(ts_iso):
 try:
 return dt.datetime.fromisoformat(ts_iso.replace('Z','+00:00')) < (dt.datetime.utcnow() - dt.timedelta(days=RETENTION))
 except:
 return False

def main(mytimer: func.TimerRequest) -> None:
 table = _table()
 for ent in table.list_entities():
 ts = ent.get('timestamp_utc') or ent.get('timestamp')
 if ts and _older_than(ts):
 table.delete_entity(partition_key=ent['PartitionKey'], row_key=ent['RowKey'])


---

## 8) Container Apps Configuration (Consumption)

Ingress
- external: true, targetPort: 8000 (uvicorn)

Scale
- minReplicas: 0, maxReplicas: 3
- Rules:
 - HTTP concurrency: concurrentRequests: 5
 - Azure Queue: queueName: respondr-incoming, queueLength: 5, accountName: <storage>
 - auth.identity: set to the app's User‑Assigned MI

AuthN
- Enable Authentication → Microsoft provider (Entra) → Require authentication.
- App reads X-MS-CLIENT-PRINCIPAL-NAME/X-MS-CLIENT-PRINCIPAL.

Identity & Roles
- Assign User‑Assigned Managed Identity to the app.
- Grant MI the following on the Storage Account:
 - Storage Queue Data Contributor (app worker)
 - Storage Table Data Contributor (app persist)
 - If using a separate scaler identity, grant it Storage Queue Data Reader

---

## 9) Infra: Bicep Sketches (illustrative; normalize in infra/main.bicep)

### 9.1 Storage (Account + Queue + Table)
bicep
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


(Add Container Apps Env, Container App, UAMI, Function App, and role assignments in the same template.)*

---

## 10) Security Model (Definitive)

- Function ingress: shared secret in URL or header; optional IP filters. No PII stored beyond responder names/messages.
- App UI/API: Entra login via Easy Auth; app still enforces ALLOWED_EMAIL_DOMAINS and ALLOWED_ADMIN_USERS.
- Internal APIs: Routes that are not user-facing should require X-API-Key = BACKEND_API_KEY.
- Storage access: Always prefer Managed Identity. Connection strings only for local/dev.
- Idempotency: Deterministic RowKey + upsert semantics.

---

## 11) Observability & Ops

- Function logs: ingestion successes/failures.
- Queue metrics: length ⇒ scaling signal.
- Container logs: worker dequeues, LLM parse outcomes, persistence results.
- Health: /healthz served without auth.
- Alerts: queue length stuck > threshold; Function errors; Container crashloop.

---

## 12) Test Plan (Scripts)

### 12.1 Ingest Path
bash
curl -X POST "https://<func>.azurewebsites.net/api/groupme_ingest?k=$WEBHOOK_API_KEY" \
 -H 'Content-Type: application/json' \
 -d '{
 "name":"Jane Smith",
 "text":"Responding SAR-78, ETA 25",
 "created_at": 1734989162,
 "group_id":"96018206"
 }'

- Expect: 200 OK. Message appears in Queue; Container App scales from 0 and writes to Table.

### 12.2 UI Path
- Browse Container App URL → Entra login → /api/user reflects email domain + admin flag.

### 12.3 CSV Export & UTC Toggle
- Confirm /api/responders data renders; export CSV works; UTC toggle behaves as before.

### 12.4 Retention
- Insert an old row (timestamp_utc older than RETENTION_DAYS) and confirm table_purge removes it on next schedule.

---

## 13) Risks & Mitigations

- Cold start latency: Acceptable trade‑off for cost; queue-trigger rule wakes app when traffic hits.
- Duplicate messages (at-least-once queue): deterministic RowKey + upsert avoids dupes.
- LLM errors/timeouts: current llm.py already handles fallbacks; log and continue.
- Time zones/DST: keep TIMEZONE and zoneinfo guidance; warn if fallback in config.py.
- Table query patterns: read paths already bounded (by team/group); acceptable for this scale.

---

## 14) Definition of Done (Final)

- [ ] Function receives GroupMe POST → enqueues → Container App auto-scales → worker parses → Table updated → UI shows responders.
- [ ] Easy Auth wired; only allowed domains see the UI; admin endpoints restricted.
- [ ] Redis removed; Table/Queue everywhere; optional Blob archive with lifecycle.
- [ ] Bicep/CLI/GitHub Actions deploy the whole stack.
- [ ] Idle cost ≈ zero; scale-to-zero verified.

---

## 15) Commit Message Hints

- feat: add Azure Table/Queue scaffolding and env plumbed
- feat(functions): HTTP ingest to queue with MI
- feat(app): background queue worker with idempotent upsert
- feat(auth): prefer Easy Auth headers; keep fallbacks
- chore: default storage backend to azure_table; remove Redis usage
- feat: timer function for Table retention
- infra: Bicep for Storage+ACA+MI+Func; role assignments

---

## 16) Rollback Plan

- Keep old AKS ingress endpoint active until Function ingest path is validated.
- Feature-flag the worker (ENABLE_QUEUE_WORKER=false) to stop processing while leaving UI available.
- If needed, temporarily point GroupMe back to old endpoint.

---

End of brief.**