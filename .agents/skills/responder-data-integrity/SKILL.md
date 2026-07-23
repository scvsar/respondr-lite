---
name: responder-data-integrity
description: Use when changing responder records, message identity, ETA, vehicle, status, timestamps, corrections, delete behavior, or stored schema compatibility.
---

# Responder Data Integrity

## Rules

1. Preserve the original message and source identifiers.
2. Keep external IDs as strings.
3. Distinguish missing, unknown, negative, and failed extraction.
4. Use timezone-aware timestamps.
5. Make duplicate delivery safe.
6. Preserve correction and soft-delete traceability.
7. Do not invent ETA, vehicle, availability, location, or status.
8. Plan compatibility before changing field names, keys, or partitions.
9. Use synthetic data in tests and artifacts.

## Change Checklist

- Identify the source of truth for each field.
- Identify idempotency and ordering behavior.
- Identify old stored entities that the new code must read.
- Define how unknown and invalid values serialize.
- Add regression fixtures for duplicates and corrections.
- Test retention, delete, restore, and migration behavior when applicable.
