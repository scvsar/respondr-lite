---
name: evaluation-benchmarking
description: Build, run, or compare Respondr extraction evaluations across heuristics, classical ML, prompt variants, and live language models. Use for benchmark datasets, ground-truth review, model or prompt selection, hyperparameter sweeps, cost analysis, quality gates, and agent competitions.
---

# Evaluation Benchmarking

Use `evals\README.md` for commands and data contracts.
Use `evals\COMPETITION.md` when agents compete.

## Rules

1. Fix the dataset fingerprint, split, targets, ETA tolerance, and pricing date before an experiment.
2. Tune only on `train` and `dev`.
3. Use `test` only for final selection.
4. Do not read held-out labels during strategy development.
5. Do not commit files in `evals\local`, `evals\cache`, or `evals\results`.
6. Do not include raw responder text, names, or source IDs in reports or logs.
7. Keep live model calls opt-in.
8. Run the no-network heuristic baseline first.
9. Run the classical baseline before live model experiments.
10. Use the production pipeline adapter for language-model experiments.
11. Record the deployment, model ID, prompt version, parameters, retries, tokens, latency, and dated price.
12. Compare experiments on the same cases with paired statistics.
13. Select the least expensive strategy that meets all fixed targets.
14. Write documentation in ASD-STE100 style.

## Workflow

1. Validate the reviewed dataset.
2. Assign mission-grouped splits.
3. Copy and lock the experiment configuration.
4. Run rules and classical strategies.
5. Tune classical strategies on `dev`.
6. Run prompt and model variants only when cheaper strategies miss the target.
7. Review target failures and paired deltas.
8. Run the held-out test once for final selection.
9. Report limitations and data coverage.

Do not weaken a target after results are visible. Start a new benchmark version if the target must change.
