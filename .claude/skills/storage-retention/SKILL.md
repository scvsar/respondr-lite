---
name: storage-retention
description: Use when changing Azure Table Storage, memory or file fallback, entity keys, partitions, soft delete, restore, purge, retention, or storage health behavior.
---

# Storage and Retention

## Rules

1. Keep Azure Table Storage as the durable production path.
2. Make fallback behavior explicit and observable.
3. Do not report memory-only success as durable production success.
4. Preserve stable entity identity.
5. Keep partition and row key changes backward compatible.
6. Use timezone-aware retention comparisons.
7. Preserve soft-delete and restore traceability.
8. Require explicit authorization for permanent deletion.
9. Do not log entity content that contains private responder data.

## Test Matrix

- Save and load
- Duplicate upsert
- Primary storage failure
- Fallback selection
- Soft delete and restore
- Retention boundary
- Invalid or missing timestamp
- Old and new schema compatibility
