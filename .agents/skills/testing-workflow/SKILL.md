---
name: testing-workflow
description: Use when writing, running, selecting, or debugging Respondr Lite backend, Function, React, integration, or regression tests.
---

# Testing Workflow

## Test Layers

- Curated full suite: `.\run-tests.ps1`
- Curated backend: `Push-Location backend; python run_tests.py; Pop-Location`
- Frontend: `Push-Location frontend; $env:CI='true'; npm test -- --watchAll=false --ci; Pop-Location`
- Frontend build: `Push-Location frontend; npm run build; Pop-Location`

## Rules

1. Add a failing regression test before a defect fix when practical.
2. Use synthetic responder and mission data.
3. Mock Azure OpenAI, GroupMe, Entra, storage, clocks, and network calls.
4. Keep live integration tests opt-in.
5. Test behavior instead of implementation details.
6. Avoid arbitrary sleeps.
7. Run the narrowest useful test while iterating.
8. Run the curated suite before handoff.
9. Report only checks that ran in the current worktree.

Some tests outside `backend\run_tests.py` need live configuration.
Inspect a test before running it.
