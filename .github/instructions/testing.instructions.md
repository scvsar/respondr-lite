# Testing Instructions

## Default Test Surfaces

- All checks: `.\run-tests.ps1`
- Backend: `Push-Location backend; python run_tests.py; Pop-Location`
- Frontend: `Push-Location frontend; $env:CI='true'; npm test -- --watchAll=false --ci; Pop-Location`
- Frontend build: `Push-Location frontend; npm run build; Pop-Location`

## Rules

- Reproduce a defect with a failing test when practical.
- Use synthetic responder and mission data.
- Mock Azure, GroupMe, Entra, clocks, and network calls.
- Keep live integration tests outside the default suite.
- Test duplicate delivery and malformed data.
- Test retry exhaustion and auth failures.
- Assert observable behavior.
- Do not add arbitrary sleeps.
- State which checks ran.
