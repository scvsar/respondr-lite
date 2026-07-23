---
name: groupme-pipeline
description: Use when changing GroupMe webhook validation, Azure Function ingestion, Queue messages, wake behavior, worker processing, retries, or duplicate delivery.
---

# GroupMe Pipeline

## Message Path

```text
GroupMe -> Function -> Queue -> Worker -> AI -> Storage
```

## Rules

1. Authenticate the webhook before enqueue.
2. Validate the payload with Pydantic.
3. Preserve source IDs as strings.
4. Preserve raw message text.
5. Acknowledge only after a successful enqueue.
6. Assume duplicate and out-of-order delivery.
7. Make worker processing idempotent.
8. Bound retries and poison-message behavior.
9. Treat container wake as best-effort.
10. Do not log full headers or secret query values.

## Test Matrix

- Valid authenticated message
- Missing or invalid token
- Allowed and disallowed group IDs
- Malformed JSON and invalid schema
- Duplicate delivery
- Queue failure
- Wake failure after successful enqueue
- Worker retry exhaustion
- Storage failure
