# Agent competition protocol

Use this protocol when agents improve extraction strategies.

## Coordinator setup

1. Freeze the reviewed dataset and record its SHA-256 fingerprint.
2. Freeze the mission-grouped split.
3. Freeze the target thresholds, ETA tolerance, and dated pricing file.
4. Keep test labels outside the competitors' working context.
5. Give each competitor the same train and development data.
6. Give each competitor the same time and model-call budget.

## Competitor rules

1. Change only the assigned strategy or prompt artifacts.
2. Do not inspect test labels or another competitor's results.
3. Do not change the dataset, targets, tolerance, or pricing.
4. Record all training and live-call cost.
5. Use development results for iteration.
6. Submit a strategy configuration and a commit.

## Final evaluation

1. Run each submitted configuration against the same held-out test cases.
2. Use cached raw model responses only when the configuration hash is identical.
3. Compare exact-match results with paired bootstrap intervals.
4. Reject a result that misses any operational target.
5. Select the least expensive passing result.
6. Use p95 latency as the next tie-breaker.
7. Use exact-match accuracy as the final tie-breaker.

Start a new competition version if any fixed input must change.
