# Python Instructions

Apply these rules to backend, Function, simulator, and helper code.

## Rules

- Target Python 3.11 or later.
- Add type hints to new public functions.
- Use Pydantic for external data validation.
- Use timezone-aware datetimes.
- Use `pathlib.Path` for files.
- Catch specific exceptions at boundaries.
- Do not use bare `except`.
- Do not return stack traces from HTTP endpoints.
- Set timeouts for network and Azure calls.
- Keep import-time work small.
- Add focused pytest coverage.

Run `python run_tests.py` from `backend\` for curated backend tests.
