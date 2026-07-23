---
name: debug-investigation
description: Investigate Respondr Lite defects with a root-cause-first trace across webhook ingestion, queues, AI extraction, storage, authentication, APIs, and React. Use for bugs, regressions, intermittent failures, and unexplained production behavior.
---

# Debug Investigation

## Workflow

1. Record the expected and actual behavior.
2. Reproduce the issue with synthetic data.
3. Identify stable message or request identifiers.
4. Trace each applicable architecture boundary.
5. Separate configuration, cold-start, provider, retry, and code failures.
6. Prove the root cause with a test, log, or code-path evidence.
7. Apply the smallest correct fix when implementation is in scope.
8. Add regression coverage.
9. Report the remaining operational risk.

## Rules

- Do not expose secrets or production responder data.
- Prefer deterministic tests over live service probes.
- Do not treat a correlated event as the root cause without evidence.
- Keep diagnosis separate from implementation when the user requests diagnosis.
