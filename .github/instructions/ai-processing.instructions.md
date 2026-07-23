# AI Processing Instructions

Apply these rules to model prompts, schemas, parsing, configuration, and
related tests.

## Rules

- Treat model output as untrusted.
- Validate structured output before persistence.
- Preserve the raw input message.
- Represent unknown values as unknown.
- Do not guess responder facts.
- Use bounded token limits, timeouts, and retries.
- Keep deployment names and API versions configurable.
- Redact credentials and unrelated personal data.
- Use mocked responses in the default test suite.
- Make live Azure OpenAI tests opt-in.
- Test terse, ambiguous, corrected, negative, and malformed messages.
- Do not use the model to recommend field operations.

Prompt or schema changes are behavior changes.
Add regression fixtures for the changed behavior.
