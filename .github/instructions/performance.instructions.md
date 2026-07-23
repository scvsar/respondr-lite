# Performance and Serverless Cost Instructions

Optimize for reliable response visibility and low idle cost.

## Rules

- Return from ingestion after validation and enqueue.
- Keep health checks cheap.
- Avoid network calls during unauthenticated frontend startup.
- Avoid blocking I/O on the FastAPI event loop.
- Bound queue polling, retries, and model token use.
- Keep data freshness explicit when batching or caching.
- Measure cold starts, queue age, processing time, and API latency.
- Do not add an always-on service without a cost review.
