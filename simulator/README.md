# SAR message simulator

The simulator creates synthetic Search and Rescue mission traffic.
It does not copy production messages into a mission.

## Team message profiles

`team_message_profiles.json` contains aggregate patterns from 408 production messages.
It contains message counts, status counts, vehicle counts, text length data, and team subjects.
It does not contain message text, responder names, source identifiers, or mission identifiers.

The profiles cover these teams:

- 4X4
- ASAR
- ESAR
- IMT
- K9
- MSAR
- OSU
- SSAR
- Tracker

The production sample is small for 4X4, ESAR, and Tracker.
Treat results for these teams as low confidence.

## Generator methods

The simulator has three message generator methods.

The heuristic method uses team templates and aggregate vehicle rates.
The mission fallback path uses this method.

The classical ML method uses a conditional word-bigram model.
It learns only approved SAR words and safe time tokens.
It cannot learn a responder name or a location token.
The benchmark trains this model in memory from the private local corpus.

The AI method sends aggregate team profiles and controlled requests to Azure OpenAI.
It does not send production message text.
A local safety check replaces an unsafe or uncontrolled result with a heuristic result.
The benchmark reports the safety repair rate.

The AI mission planner also receives the aggregate team profiles.
It must match each message to the sender team.

## Generator benchmark

The generator benchmark is separate from the extraction benchmark.
It compares message generation quality and operating cost signals.

The fixed benchmark uses a mission-held-out split.
No mission can occur in both the training data and the test data.
The current split has 323 training messages and 85 test messages.

Run the offline methods:

```powershell
.\.venv\Scripts\python.exe -m simulator.generator_benchmark
```

Run the live AI method:

```powershell
$env:AZURE_OPENAI_ENDPOINT = "<endpoint>"
$env:AZURE_OPENAI_API_KEY = "<key>"
$env:AZURE_OPENAI_API_VERSION = "2024-12-01-preview"
$env:AZURE_OPENAI_DEPLOYMENT = "<deployment>"
.\.venv\Scripts\python.exe -m simulator.generator_benchmark --include-ai --model-id "<model>"
```

The command writes these local reports:

- `evals\generator-results\message-generator-benchmark.html`
- `evals\generator-results\message-generator-benchmark.json`

Git ignores the report directory.
The reports contain aggregate metrics and synthetic samples only.
They do not contain production messages.

## Metrics

The benchmark fixes its weights and targets in `generator_benchmark_config.json`.
It measures these properties:

- Requested status, vehicle, and ETA control
- Team classifier accuracy
- Status classifier accuracy
- Team text similarity
- Message length fit
- Unique message rate
- Exact copy rate for messages with five or more words
- Five-word sequence overlap
- Failure rate
- Safety repair rate
- Model tokens
- Mean amortized generation latency

The report does not calculate model cost.
Use dated provider prices with the token counts for a cost calculation.

The private corpus team classifier has low held-out accuracy.
This result shows that many team messages use similar language.
Do not use team classifier accuracy as the only quality measure.

## Benchmark limits

This is a development benchmark.
Its design used aggregate facts from the current production corpus.
It is not a sealed test.

Use future production messages for a sealed test.
Add human ratings for team fit and semantic plausibility before a simulator release.
