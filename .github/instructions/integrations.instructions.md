# Integration Instructions

External services include GroupMe, Azure OpenAI, Azure Storage, Entra ID,
Docker Hub, and Azure hosting services.

## Rules

- Keep each provider behind a focused adapter.
- Normalize provider data into project-owned structures.
- Use explicit timeouts and bounded retries.
- Retry only transient failures.
- Keep credentials and sessions out of React components.
- Do not log auth headers, tokens, or provider error bodies.
- Make live integration tests opt-in.
- Design failures to preserve responder facts.
- Preserve source identifiers for traceability.
