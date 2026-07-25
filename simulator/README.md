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

The simulator has four message generator methods.

The heuristic method uses team templates and aggregate vehicle rates.
The mission fallback path uses this method.

The classical ML method uses a conditional word-bigram model.
It learns only approved SAR words and safe time tokens.
It cannot learn a responder name or a location token.
The benchmark trains this model in memory from the private local corpus.

The retrieval ML method learns safe message structures from the private corpus.
It replaces vehicle and ETA values with controlled slots.
It rejects structures that contain unapproved words or personal data.
It also rejects an output that exactly matches a training message.
It uses the heuristic method when no compatible safe structure exists.

The AI method sends aggregate team profiles and controlled requests to Azure OpenAI.
It does not send production message text.
A local safety check replaces an unsafe or uncontrolled result with a heuristic result.
The benchmark reports the safety repair rate.

The AI mission planner also receives the aggregate team profiles.
It must match each message to the sender team.

## Generator benchmark

The generator benchmark is separate from the extraction benchmark.
It compares message generation quality and operating cost signals.

Version 2 is the default generator benchmark.
It keeps the version 1 configuration unchanged.
Version 3 compares the current AI prompt with the responder context prompt.
It scores the raw AI text before a safety repair.
It also reports paired improvements, regressions, and repair changes.
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

- `evals\generator-results\v2\message-generator-benchmark.html`
- `evals\generator-results\v2\message-generator-benchmark.json`

Run the version 3 prompt comparison:

```powershell
.\.venv\Scripts\python.exe -m simulator.generator_benchmark `
  --config simulator\generator_benchmark_config_v3.json `
  --output evals\generator-results\v3 `
  --include-ai `
  --model-id "<model>"
```

The command writes the version 3 reports to `evals\generator-results\v3`.

Run the PPE model comparison:

```powershell
.\.venv\Scripts\python.exe -m simulator.generator_benchmark `
  --config simulator\generator_benchmark_config_v4.json `
  --output evals\generator-results\v4 `
  --include-ai `
  --model-deployment ai-gpt-5.4-nano=gpt-5.4-nano `
  --model-deployment ai-gpt-5.6-luna=gpt-5.6-luna
```

The command uses `responder-context-v2` for both model deployments.

Git ignores the report directory.
The reports contain aggregate metrics and synthetic samples only.
They do not contain production messages.

## Metrics

The benchmark fixes its weights and targets in `generator_benchmark_config.json`.
It measures these properties:

- Requested status, vehicle, and ETA control
- Message semantic validity
- Fluency acceptance
- Raw control, semantic validity, and fluency before a safety repair
- Team classifier accuracy
- Status classifier accuracy
- Team text similarity
- Message length fit
- Unique message rate
- Exact copy rate for messages with five or more words
- Five-word sequence overlap
- Failure rate
- Safety repair rate
- Heuristic fallback rate
- Model tokens
- Mean amortized generation latency

The report does not calculate model cost.
Use dated provider prices with the token counts for a cost calculation.

The private corpus team classifier has low held-out accuracy.
This result shows that many team messages use similar language.
Do not use team classifier accuracy as the only quality measure.

The fluency classifier is an automated proxy.
It does not replace human review.
The report identifies heuristic fallback and safety repair samples.

## Benchmark limits

This is a development benchmark.
Its design used aggregate facts from the current production corpus.
It is not a sealed test.

Use future production messages for a sealed test.
Add human ratings for team fit and semantic plausibility before a simulator release.
