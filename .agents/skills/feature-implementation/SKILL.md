---
name: feature-implementation
description: Implement scoped Respondr Lite features across FastAPI, React, Azure Functions, queues, storage, authentication, and infrastructure. Use when a request requires a production-ready behavior change with tests and validation.
---

# Feature Implementation

## Workflow

1. Define acceptance criteria and failure behavior.
2. Identify each affected architecture layer.
3. Preserve raw messages and stable identifiers.
4. Preserve idempotency and timezone-aware ordering.
5. Keep provider behavior behind existing boundaries.
6. Validate all external and model-derived data.
7. Preserve authenticated access and scale-to-zero behavior.
8. Add focused deterministic tests.
9. Run the relevant curated checks.
10. Report migrations, deployment needs, and remaining risk.

## Rules

- Keep the change within the user-approved scope.
- Reuse existing patterns before adding dependencies.
- Do not mutate live services without explicit authorization.
- Preserve unrelated worktree changes.
