---
name: react-dashboard
description: Use when changing the React responder dashboard, routing, auth-aware navigation, API state, responsive layouts, status presentation, or frontend tests.
---

# React Dashboard

## When to Use

- Edit files under `frontend\src\`.
- Add or change dashboard, admin, profile, login, or debug views.
- Change polling, loading, error, stale, or empty states.
- Change mobile or desktop layout.

## Rules

1. Make status, ETA, vehicle, identity, and update time easy to scan.
2. Support phone and desktop widths.
3. Show loading, empty, stale, partial, unauthorized, and error states.
4. Use semantic controls and accessible names.
5. Keep keyboard focus visible.
6. Do not rely on color alone.
7. Keep tokens in the existing auth and API clients.
8. Never treat hidden UI as authorization.
9. Do not put secrets in `REACT_APP_*` variables.

## Validation

- Use synthetic data.
- Run focused React tests.
- Run `npm test -- --watchAll=false --ci`.
- Run `npm run build`.
- Inspect the running view at phone and desktop widths.
