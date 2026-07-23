---
name: emoji-cleanup
description: Find and remove decorative, accidental, or machine-added emoji from Respondr Lite code, logs, documentation, comments, tests, and configuration. Use for emoji cleanup while preserving intentional user-facing symbols.
---

# Emoji Cleanup

## Workflow

1. Search the requested scope for emoji and pictographic symbols.
2. Classify each match by purpose.
3. Preserve symbols that carry required user meaning.
4. Remove decorative symbols from technical content.
5. Replace semantic symbols with clear text when needed.
6. Check tests, snapshots, selectors, and string length assumptions.
7. Run the narrowest relevant validation.
8. Report preserved exceptions.

## Rules

- Do not change unrelated text.
- Do not rewrite Git history unless the user requests it.
- Preserve third-party fixtures and protocol samples when exact text matters.
- Follow the repository default that technical content does not use emoji.
