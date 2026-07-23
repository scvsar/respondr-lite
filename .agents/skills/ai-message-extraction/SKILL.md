---
name: ai-message-extraction
description: Use when changing Azure OpenAI prompts, structured responder extraction, retry behavior, confidence, token limits, or model-output tests.
---

# AI Message Extraction

## When to Use

- Edit `backend\app\llm.py`.
- Change extracted vehicle, ETA, or responder status fields.
- Change prompt text, response parsing, token limits, or retry policy.
- Diagnose malformed or incomplete model output.

## Rules

1. Preserve the original GroupMe message.
2. Treat model output as untrusted.
3. Validate every structured result before persistence.
4. Use unknown values when the message has insufficient evidence.
5. Do not infer field operations or responder priority.
6. Bound timeouts, token limits, and retries.
7. Keep model deployment and API settings configurable.
8. Keep full prompts, credentials, and sensitive data out of logs.

## Test Matrix

- Clear positive response with vehicle and ETA
- Terse response
- Explicit negative response
- Correction of an earlier response
- Ambiguous time or vehicle
- Irrelevant message
- Malformed model response
- Token exhaustion and retry exhaustion

Use mocked model responses in the default suite.
Make live Azure OpenAI tests opt-in.
