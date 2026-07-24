"""Classical text classification with an optional development-set sweep."""

from __future__ import annotations

from itertools import product
from statistics import mean
from typing import Any

from ..schema import EvalCase
from .base import Prediction, Strategy
from .heuristic import HeuristicStrategy


def _macro_f1(expected: list[str], actual: list[str]) -> float:
    labels = sorted(set(expected) | set(actual))
    scores = []
    for label in labels:
        true_positive = sum(e == label and a == label for e, a in zip(expected, actual))
        false_positive = sum(e != label and a == label for e, a in zip(expected, actual))
        false_negative = sum(e == label and a != label for e, a in zip(expected, actual))
        precision = true_positive / (true_positive + false_positive) if true_positive + false_positive else 0
        recall = true_positive / (true_positive + false_negative) if true_positive + false_negative else 0
        scores.append(
            2 * precision * recall / (precision + recall)
            if precision + recall
            else 0.0
        )
    return mean(scores) if scores else 0.0


class _ConstantModel:
    def __init__(self, value: str):
        self.value = value

    def predict(self, texts: list[str]) -> list[str]:
        return [self.value for _ in texts]


class ClassicalStrategy(Strategy):
    kind = "classical"

    def __init__(
        self,
        name: str = "tfidf-logreg-v1",
        tune: bool = False,
        params: dict[str, Any] | None = None,
    ):
        self.name = name
        self.tune = tune
        self.params = params or {
            "analyzer": "char_wb",
            "ngram_min": 3,
            "ngram_max": 5,
            "c": 2.0,
            "class_weight": "balanced",
        }
        self.status_model: Any = None
        self.vehicle_model: Any = None
        self.heuristic = HeuristicStrategy()
        self.sweep_results: list[dict[str, Any]] = []

    @staticmethod
    def _pipeline(params: dict[str, Any]):
        try:
            from sklearn.feature_extraction.text import TfidfVectorizer
            from sklearn.linear_model import LogisticRegression
            from sklearn.pipeline import Pipeline
        except ImportError as exc:
            raise RuntimeError(
                "Classical experiments require: pip install -e 'evals[ml]'"
            ) from exc
        return Pipeline(
            [
                (
                    "tfidf",
                    TfidfVectorizer(
                        analyzer=params["analyzer"],
                        ngram_range=(params["ngram_min"], params["ngram_max"]),
                        min_df=1,
                        sublinear_tf=True,
                    ),
                ),
                (
                    "classifier",
                    LogisticRegression(
                        C=params["c"],
                        class_weight=params["class_weight"],
                        max_iter=1500,
                        random_state=20260723,
                    ),
                ),
            ]
        )

    @classmethod
    def _fit_label(cls, texts: list[str], labels: list[str], params: dict[str, Any]):
        if len(set(labels)) == 1:
            return _ConstantModel(labels[0])
        model = cls._pipeline(params)
        model.fit(texts, labels)
        return model

    def _fit_models(self, cases: list[EvalCase], params: dict[str, Any]):
        texts = [str(case.input["text"]) for case in cases]
        statuses = [case.reference.status for case in cases]
        vehicles = [case.reference.vehicle for case in cases]
        return (
            self._fit_label(texts, statuses, params),
            self._fit_label(texts, vehicles, params),
        )

    def fit(
        self, train_cases: list[EvalCase], dev_cases: list[EvalCase] | None = None
    ) -> None:
        if not train_cases:
            raise ValueError("Classical strategy requires reviewed training cases")
        if self.tune:
            if not dev_cases:
                raise ValueError("Classical tuning requires reviewed development cases")
            grid = product(
                ("char_wb", "word"),
                ((2, 4), (3, 5)),
                (0.5, 2.0, 8.0),
                (None, "balanced"),
            )
            candidates = []
            for analyzer, ngrams, c_value, class_weight in grid:
                params = {
                    "analyzer": analyzer,
                    "ngram_min": ngrams[0],
                    "ngram_max": ngrams[1],
                    "c": c_value,
                    "class_weight": class_weight,
                }
                status_model, vehicle_model = self._fit_models(train_cases, params)
                dev_texts = [str(case.input["text"]) for case in dev_cases]
                expected_statuses = [case.reference.status for case in dev_cases]
                predicted_statuses = list(status_model.predict(dev_texts))
                status_score = _macro_f1(
                    expected_statuses,
                    predicted_statuses,
                )
                vehicle_score = mean(
                    predicted == case.reference.vehicle
                    for predicted, case in zip(
                        vehicle_model.predict(dev_texts),
                        dev_cases,
                    )
                )
                candidates.append(
                    {
                        "params": params,
                        "status_accuracy": status_score,
                        "vehicle_accuracy": vehicle_score,
                        "score": (status_score + vehicle_score) / 2,
                    }
                )
            candidates.sort(
                key=lambda item: (
                    item["score"],
                    item["status_accuracy"],
                    item["vehicle_accuracy"],
                ),
                reverse=True,
            )
            self.sweep_results = candidates
            self.params = candidates[0]["params"]
        final_cases = train_cases + list(dev_cases or []) if self.tune else train_cases
        self.status_model, self.vehicle_model = self._fit_models(final_cases, self.params)

    def predict(self, case: EvalCase) -> Prediction:
        if self.status_model is None or self.vehicle_model is None:
            raise RuntimeError("Classical strategy must be fit before prediction")
        text = str(case.input["text"])
        heuristic = self.heuristic.predict(case)
        status = str(self.status_model.predict([text])[0])
        vehicle = str(self.vehicle_model.predict([text])[0])
        if heuristic.vehicle != "Unknown":
            vehicle = heuristic.vehicle
        return Prediction(
            status=status,
            vehicle=vehicle,
            eta_iso=heuristic.eta_iso,
            metadata={"params": self.params},
        ).validated()

    def describe(self) -> dict[str, Any]:
        return {
            **super().describe(),
            "tune": self.tune,
            "selected_params": self.params,
            "sweep_results": self.sweep_results,
        }
