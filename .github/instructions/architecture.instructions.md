# Architecture Instructions

## Message Path

Keep the production path explicit:

```text
GroupMe -> Azure Function -> Storage Queue -> Container App worker
        -> Azure OpenAI -> Table Storage -> FastAPI -> React
```

## Rules

- Keep ingestion fast.
- Do not wait for AI before webhook acknowledgment.
- Assume queues deliver at least once.
- Make processing idempotent with stable source identifiers.
- Preserve the original responder message beside derived fields.
- Keep provider details at adapter boundaries.
- Keep React components free of provider orchestration.
- Do not wake the backend from an unauthenticated browser path.
- Preserve scale-to-zero behavior unless the cost change is explicit.
- Avoid layers that only forward calls and own no policy.

## Failure Direction

- Ingestion failure returns an explicit error.
- Wake failure does not undo a successful enqueue.
- AI failure creates an observable unparsed state.
- Durable storage failure stays visible.
- Dashboard failure states do not imply current responder data.
