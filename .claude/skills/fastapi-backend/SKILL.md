---
name: fastapi-backend
description: Use when adding or changing FastAPI routes, dependencies, Pydantic schemas, background work, API errors, CORS, or backend service boundaries.
---

# FastAPI Backend

## When to Use

- Edit `backend\app\routers\`.
- Add request or response models.
- Change auth dependencies, CORS, health checks, or service wiring.
- Move policy between routes and services.

## Rules

1. Keep routes thin.
2. Validate external data with Pydantic.
3. Put authentication and authorization in dependencies.
4. Enforce admin policy on the server.
5. Return stable errors without stack traces or provider details.
6. Keep health checks cheap.
7. Avoid blocking I/O on the async event loop.
8. Set explicit timeouts for external calls.
9. Keep storage failure visible.

## Validation

- Add focused pytest coverage.
- Test authenticated, unauthorized, forbidden, malformed, and provider-failure
  paths when relevant.
- Run `python run_tests.py` from `backend\`.
