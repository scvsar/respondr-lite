---
name: ux-inspection
description: Use when visually reviewing or fixing the Respondr Lite dashboard, mobile layouts, clipping, accessibility, stale states, or screenshot regressions.
---

# UX Inspection

## Workflow

1. Start the frontend with synthetic data.
2. Capture the current view.
3. Inspect at a phone width and a desktop width.
4. Diagnose each visible defect.
5. Apply the smallest viable fix.
6. Re-capture the exact scenario.
7. Verify each original finding.
8. Run React tests and a production build.

## Review Order

1. Broken or blank regions
2. Incorrect or stale status
3. Clipping and overflow
4. Scanability and information order
5. Mobile touch targets
6. Keyboard focus
7. Contrast and color-only meaning
8. Loading, empty, unauthorized, and error states

Every visual claim needs browser evidence from the current session.
Do not use production mission data in screenshots.
