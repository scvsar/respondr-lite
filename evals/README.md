# Respondr evaluation system

This package compares responder-message extraction strategies. It measures quality, latency, reliability, token use, and cost. It keeps live model calls optional.

Use Python 3.11 or later.

## Install

Install all local evaluation tools:

```powershell
py -3.11 -m pip install -e "evals[test,llm,labeling]"
```

The `test` extra includes scikit-learn.

## Review production candidates

Read active production messages into an ignored local file:

```powershell
respondr-eval sample-prod
```

The command is read-only. It does not change Azure storage. It pseudonymizes responder and group fields. Message text can still contain private information. It retains source IDs for local traceability.

Start the private review interface:

```powershell
respondr-eval label
```

The server binds to `127.0.0.1`. Do not bind it to a network interface. Approve, correct, or skip each proposal. Then select **Assign splits**.

Select **Results** in the interface to inspect benchmark reports. The results view reads private reports from `evals\results`. It shows:

- The strategy leaderboard and acceptance-target status.
- Quality, cost, latency, and reliability metrics.
- Status confusion matrices.
- Paired strategy comparisons.
- Pseudonymous case-level results for all strategies.

The results view does not show responder message text.

The local dataset is `evals\local\prod-ground-truth.jsonl`. Git ignores this directory because the file contains responder messages.

## Validate and split a dataset

```powershell
respondr-eval validate evals\local\prod-ground-truth.jsonl
respondr-eval split evals\local\prod-ground-truth.jsonl
```

The split command keeps messages from one mission in one split. It prevents direct mission leakage across training and test data.

## Run the offline example

```powershell
respondr-eval run evals\configs\example_experiments.json
```

The example compares:

- A deterministic heuristic baseline.
- A TF-IDF and logistic-regression baseline.
- A development-set hyperparameter sweep.

Reports go to `evals\results`. Predictions go to `evals\cache`. Git ignores both directories.

Keep the labeler running after the benchmark completes. Refresh the **Results** view, and select the new run.

## Run live model experiments

Add a `production_llm` experiment:

```json
{
  "name": "nano-prompt-v2",
  "type": "production_llm",
  "deployment": "azure-deployment-name",
  "model_id": "gpt-5-nano",
  "prompt_path": "../prompts/prompt-v2.json",
  "reasoning_effort": "low",
  "verbosity": "low",
  "max_tokens": 512,
  "max_concurrency": 4,
  "repetitions": 3
}
```

Then run:

```powershell
respondr-eval run path\to\experiment.json --allow-live-llm
```

The adapter calls the production extraction pipeline. The adapter can replace only the Azure deployment and approved experiment settings. It records all retries and token use.

`max_concurrency` controls parallel live calls. The runner accepts values from 1 through 16. Start with a low value.

Prompt files can use these tokens:

- `{{text}}`
- `{{base_time}}`
- `{{previous_eta_iso}}`

Copy `configs\pricing.example.json` to an ignored local file. Add the current Azure prices and effective date. Do not compare dollar cost without a dated price.

## Metrics

The report includes:

- Status accuracy, macro-F1, and the confusion matrix.
- Per-status precision, recall, and support.
- Configurable, operationally weighted status error.
- Vehicle accuracy.
- ETA presence accuracy.
- ETA accuracy within the configured tolerance.
- ETA mean absolute error.
- Full-record exact match.
- Schema failure and retry rates.
- p50 and p95 latency.
- Input and output tokens.
- Cost per 1,000 messages.
- Bootstrap confidence intervals.
- Paired wins, ties, losses, and exact-match deltas.
- Pseudonymous case-level expected and actual values.

Set all acceptance targets before the run. The runner selects the least expensive strategy that meets every target.

## Data contract

Each JSONL record contains:

- `case_id`: Stable evaluation identity.
- `input`: Message, timezone-aware base time, mission timezone, and prior-message context.
- `reference`: Reviewed status, vehicle, and UTC ETA.
- `annotation`: Review state, reviewer, notes, and proposal source.
- `provenance`: Source identity and mission grouping.
- `observations`: Production and heuristic proposals.
- `split`: `train`, `dev`, `test`, or `unassigned`.

Use `approved` and `corrected` records for evaluation. Do not treat automatic proposals as ground truth.
