# AGENTS.md

## Project Context

Respondr Lite is a serverless Search and Rescue (SAR) response tracker. It
collects GroupMe call-out replies, extracts structured responder information,
and shows the current response picture on an authenticated dashboard.

Primary goals:

- Accept webhook traffic quickly and reliably.
- Preserve the original responder message and its traceability.
- Extract vehicle, ETA, and response status without inventing facts.
- Give coordinators a clear, current, mobile-friendly dashboard.
- Keep idle cloud cost near zero through Azure consumption services.

This system supports human SAR coordination. It does not dispatch resources,
replace an incident commander, or make safety-critical decisions.

## Style Rules

- Do not use emojis in code, logs, documentation, or generated copy unless the
  user explicitly asks for them.
- Do not use em dashes. Use a hyphen, comma, parentheses, or a new sentence.
- Use American English.
- Use active voice and short sentences in documentation.
- Keep comments focused on why a decision exists.
- Keep commands, identifiers, paths, payload fields, and quoted text exact.

## Documentation and Reports

- Use ASD-STE100 Simplified Technical English, Issue 9, for all
  documentation and reports unless the user requests a different style.
- This rule applies to new text and to text that you change.
- This rule applies to plans, reviews, issue text, pull request text, release
  notes, and generated reports.
- Use approved words only with their approved meanings and parts of speech.
- Use established project terms as technical nouns or technical verbs. Use
  each term consistently.
- Use American English spelling.
- Keep a multi-word noun to three words or fewer.
- Use active voice when the agent is known.
- Do not use contractions, Latin abbreviations, or semicolons.
- Put one instruction in each sentence unless actions occur at the same time.
- Use no more than 20 words in a procedural sentence.
- Use no more than 25 words in a descriptive sentence.
- Use no more than six sentences in one paragraph.
- Keep code, identifiers, commands, paths, protocol fields, quoted text, and
  legal text exact.
- Do not claim STE conformance unless you checked the text against the Issue 9
  rules and dictionary.
- Reference:
  [ASD-STE100 Issue 9](https://www.asd-ste100.org/assets/files/ASD-STE100_ISSUE9.pdf).

## Development Environment

- The repository is normally developed on Windows.
- Use PowerShell (`pwsh`) for repository scripts and command examples.
- Use `rg` for text and file search.
- Python services must run on Python 3.11 or later.
- Frontend work uses Node.js 20 in CI.
- Code deployed in containers or Azure Functions must also work on Linux.
- Never assume a developer has live Azure credentials or access to production.

## Essential Commands

- Start the full local stack:
  `.\dev-local.ps1`
- Start selected local components:
  `.\dev-local.ps1 -Function`
  `.\dev-local.ps1 -Backend`
  `.\dev-local.ps1 -Frontend`
- Run the curated backend and frontend tests:
  `.\run-tests.ps1`
- Run curated backend tests:
  `Push-Location backend; python run_tests.py; Pop-Location`
- Run frontend tests once:
  `Push-Location frontend; $env:CI='true'; npm test -- --watchAll=false --ci; Pop-Location`
- Build the frontend:
  `Push-Location frontend; npm run build; Pop-Location`
- Build the backend image:
  `docker build -f Dockerfile.backend -t respondr-lite:local .`
- Validate local configuration:
  `.\validate-local-env.ps1`
- Deploy infrastructure:
  `Push-Location deployment; .\deploy-from-scratch.ps1 -ResourceGroup <name> -Location <region>; Pop-Location`

Prefer the curated test entry points. Some files under `backend\tests\` are
manual, integration, or environment-dependent checks.

## Repository Structure

- `backend\`: FastAPI API, background queue worker, AI extraction, auth, and
  storage adapters.
- `backend\app\routers\`: HTTP route modules.
- `backend\app\llm.py`: Azure OpenAI message extraction.
- `backend\app\queue_listener.py`: queue processing loop.
- `backend\app\storage.py` and `storage_backends.py`: storage abstraction and
  implementations.
- `functions\`: Azure Functions for webhook ingestion and local login.
- `frontend\`: React dashboard and authentication clients.
- `infra\`: Bicep infrastructure definitions.
- `deployment\`: deployment and environment-management scripts.
- `simulator\`: mission simulation and analysis tools.
- `scripts\`: operational diagnostics and local helper scripts.
- `missions\`: local mission artifacts. Treat operational content as
  sensitive.
- `.agents\skills\`: reusable agent workflows shared across agent surfaces.
- `.codex\`: Codex project runtime settings, hooks, and custom agents.
- `.github\`: GitHub Actions and Copilot-specific adapters.

## Architecture

The normal message path is:

```text
GroupMe webhook
  -> Azure Function validation
  -> Azure Storage Queue
  -> Container App queue worker
  -> Azure OpenAI structured extraction
  -> Azure Table Storage
  -> authenticated React dashboard
```

Keep these boundaries explicit:

- The ingestion Function authenticates and validates a request, enqueues one
  normalized message, and returns quickly.
- The queue separates webhook availability from AI and storage latency.
- The worker owns AI extraction, retry policy, and persistence.
- The backend API owns authorization and responder data access.
- The frontend renders server state. It does not reproduce backend policy.
- Provider-specific code stays at the edge behind small service or adapter
  boundaries.

Do not bypass the queue for the production webhook path unless the user asks
for an architectural change and the reliability trade-off is documented.

## SAR Data Integrity

- Preserve the original GroupMe text and stable source identifiers.
- Treat GroupMe IDs as strings. Do not coerce them to numbers.
- Make duplicate delivery safe. Webhook and queue retries must not create
  duplicate responder records.
- Keep timestamps timezone-aware. Use the configured `TIMEZONE` for display
  policy and UTC for durable ordering when practical.
- Distinguish missing, unknown, and explicitly negative responses.
- Do not infer an ETA, vehicle, availability, location, or status without
  evidence in the message.
- Keep soft-delete and restore behavior traceable.
- Do not permanently delete mission or responder data without explicit user
  authorization and a verified target.
- Add migration or compatibility handling before changing stored entity
  keys, partitions, field names, or timestamp formats.

## AI Extraction Rules

- Treat model output as untrusted input.
- Request structured output and validate it before persistence.
- Keep extraction schemas explicit and backward compatible.
- Preserve the raw message next to derived fields.
- Record confidence or uncertainty when the current data model supports it.
- Use bounded retries, timeouts, and token limits.
- Retry only failures that can plausibly succeed on another attempt.
- Do not silently convert an extraction failure into a confident response.
- Do not place credentials, auth headers, full tokens, or unrelated personal
  data in prompts or logs.
- Keep production model and deployment names configurable.
- Use deterministic mocks or fakes in normal automated tests. Live model tests
  must be opt-in.
- Prompt changes are behavior changes. Add representative tests for terse,
  ambiguous, negative, corrected, and malformed responder messages.
- The AI may summarize or classify a responder message. It must not dispatch,
  prioritize, or recommend field operations.

## Webhook and Queue Rules

- Authenticate with `WEBHOOK_API_KEY` when configured.
- When no key is configured, enforce the allowed GroupMe group policy.
- Validate payloads with Pydantic before enqueueing them.
- Return stable, minimal error responses. Do not return connection strings,
  stack traces, or provider details to callers.
- Do not log full request headers. Headers can contain tokens or platform
  identifiers.
- Keep queue names and storage API versions configurable.
- Handle Azure Queue messages as at-least-once delivery.
- Bound retry and poison-message behavior. Never spin forever on one message.
- Keep wake requests best-effort. A wake failure must not undo a successful
  enqueue.

## Backend Rules

- Keep FastAPI routes thin. Put reusable policy in services or focused helpers.
- Validate request and response shapes with Pydantic models.
- Use FastAPI dependencies for authentication and authorization.
- Require authentication for all responder and administration routes.
- Keep health endpoints cheap and free of sensitive configuration.
- Do not perform blocking network or storage calls directly on the async event
  loop when a non-blocking alternative or thread boundary exists.
- Use explicit timeouts for HTTP and Azure SDK operations.
- Keep storage fallback behavior observable. Do not silently mask durable
  storage failure with memory-only success in production.

## Authentication and Privacy

- Support Entra ID and local JWT flows without weakening either flow.
- Validate issuer, audience, signature, expiry, and required claims.
- Keep admin authorization server-side. UI visibility is not authorization.
- Keep local-auth bypass settings disabled outside explicit local test use.
- Never use the checked-in fallback JWT secret in a deployed environment.
- Treat names, email addresses, GroupMe identifiers, messages, ETAs, vehicle
  details, and mission artifacts as sensitive operational data.
- Redact tokens, cookies, connection strings, passwords, and storage keys from
  logs and test artifacts.
- Use least-privilege managed identities and RBAC where supported.

## Frontend Rules

- Keep coordinator actions usable on phone and desktop layouts.
- Preserve readable status, ETA, vehicle, responder identity, and update time.
- Show loading, empty, stale, partial, unauthorized, and error states
  explicitly.
- Do not claim real-time freshness unless the data refresh behavior supports
  the claim.
- Keep auth token handling in the existing auth clients and API wrapper.
- Do not put secrets in `REACT_APP_*` variables. React build variables are
  public in the browser bundle.
- Prefer accessible semantic controls, visible keyboard focus, sufficient
  contrast, and touch targets that work on mobile.
- A visual change requires a browser-based check at representative desktop
  and mobile widths when practical.

## Azure and Deployment Rules

- Keep preproduction and production resources, variables, and secrets
  separate.
- Prefer managed identity and OIDC over long-lived credentials.
- Keep scale-to-zero behavior intact unless the user accepts the cost change.
- Review queue polling, KEDA rules, minimum replicas, and health probes
  together when changing scaling behavior.
- Treat Bicep as the source of truth for infrastructure when a resource is
  managed under `infra\`.
- Keep deployment scripts idempotent where practical.
- Never deploy, rotate secrets, modify live resources, or run a mission
  simulator against a live endpoint without explicit user authorization.
- Validate deployment workflow changes without printing secret values.

## Testing and Quality

- Add or update tests for every behavior change and fixed defect.
- For a defect, first add a test that fails for the reported behavior when
  practical.
- Use fake Azure services, storage backends, clocks, and model responses for
  fast deterministic tests.
- Keep live Azure, GroupMe, Entra, and OpenAI checks outside the default unit
  suite.
- Test retry boundaries, duplicate delivery, malformed model output, auth
  failures, and storage fallback paths when those areas change.
- Run the narrowest relevant test while iterating, then run the curated suite
  before handoff.
- Run `git diff --check` after text-heavy or multi-file changes.
- Do not claim a test passed unless it ran in the current worktree.

## Security and Secrets

- Never commit, print, or log API keys, tokens, passwords, connection strings,
  private keys, webhook secrets, deployment credentials, or local `.env`
  values.
- Do not open `.env`, `.env.prod`, `.env.populated`, mission data, or captured
  production payloads unless the task explicitly requires that sensitive
  content.
- Use `.env.sample` and simulator example files to understand configuration.
- Use synthetic responder data in tests, screenshots, and documentation.
- Treat external webhook bodies, JWT claims, model output, and stored entities
  as untrusted input.
- Avoid broad exception responses that expose internal details.

## Cross-Platform Rules

- Use `pathlib.Path` in Python for filesystem work.
- Do not hardcode Windows path separators in Python or JavaScript.
- Use PowerShell for repository automation when a cross-platform PowerShell
  script already exists.
- Keep container and Azure Function paths case-correct for Linux.
- Do not rely on a developer-only process, file, or credential in production
  code.

## Markdown Code Fences

When writing GitHub-rendered markdown:

- Do not label Windows commands as `bash`.
- Use `powershell`, `cmd`, or an unlabeled fence.
- Use Windows paths for commands intended to run in the normal development
  environment.

## Pull Requests

- Check the current branch and worktree before editing.
- Preserve unrelated user changes.
- Keep changes scoped and explain operational risk.
- Include tests or a clear reason why a test does not apply.
- Call out changes to auth, retention, AI extraction, storage keys, scaling,
  deployment, or mission-data behavior.
- Do not push, deploy, arm auto-merge, or change live infrastructure unless
  the user explicitly asks.

## Agent Setup

- This file is the canonical shared instruction file for Codex, Claude Code,
  and GitHub Copilot.
- Reusable workflows have their canonical source in `.agents\skills\`.
- Codex and Copilot discover `.agents\skills\` directly.
- Claude skill mirrors belong in `.claude\skills\`.
- Keep Claude skill mirrors byte-aligned with `.agents\skills\`.
- Codex runtime settings, hooks, MCP servers, and agents belong in `.codex\`.
- Claude settings and agents belong in `.claude\`.
- Copilot-specific adapters belong in `.github\`.
- `CLAUDE.md` imports this file with `@AGENTS.md`.
- `.github\copilot-instructions.md` imports this file with `@../AGENTS.md`.
- Claude and Copilot CLI share project MCP servers from `.mcp.json`.
- Codex MCP adapters belong in `.codex\config.toml`.
- Keep personal MCP authentication, credentials, and private defaults outside
  the repository.
- Do not duplicate durable repository rules in provider-specific files.
  Update this file instead.
