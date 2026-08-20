"""Unused-file scoring: a rule-based heuristic bootstrapped into a classifier.

Methodology
-----------
There is no ground truth for "is this file unused" -- nobody hand-labels
their own filesystem. Instead we use weak supervision:

1. Files untouched for `UNUSED_CONFIDENT_DAYS` are confidently labeled
   "unused" (1); files touched within `ACTIVE_CONFIDENT_DAYS` are
   confidently labeled "active" (0). Everything in between is unlabeled.
2. If both classes have at least `MIN_TRAINING_SAMPLES_PER_CLASS` examples,
   a RandomForestClassifier is trained on the confident examples and used to
   score every file (including the confident ones, for a consistent scale).
   This lets the model generalize the heuristic's intuition -- e.g. "large
   files in a Downloads-like directory decay faster than source code" --
   to the ambiguous middle group instead of leaving them unscored.
3. Otherwise (too few confident examples -- e.g. a small or freshly-touched
   tree) we fall back to a pure heuristic score so the tool still produces
   a ranked list on a first run.

Either path produces the same 0-1 "probability this file is unused" score,
so downstream code (recommender.py, the GUI) doesn't need to know which one
ran.
"""

from __future__ import annotations

import math
import time
from dataclasses import dataclass

from storage_ai.config import (
    ACTIVE_CONFIDENT_DAYS,
    MIN_TRAINING_SAMPLES_PER_CLASS,
    UNUSED_CONFIDENT_DAYS,
    categorize_extension,
)
from storage_ai.models import FileRecord, UnusedCandidate

_SECONDS_PER_DAY = 86400
_CATEGORY_DECAY_RISK = {
    "temp": 0.9,
    "installer": 0.8,
    "archive": 0.6,
    "media": 0.4,
    "image": 0.35,
    "document": 0.3,
    "code": 0.1,
    "other": 0.4,
}


@dataclass
class _Features:
    record: FileRecord
    days_since_access: float
    days_since_modified: float
    log_size: float
    category_risk: float


def _extract_features(record: FileRecord, now: float) -> _Features:
    return _Features(
        record=record,
        days_since_access=max(0.0, (now - record.accessed_time) / _SECONDS_PER_DAY),
        days_since_modified=max(0.0, (now - record.modified_time) / _SECONDS_PER_DAY),
        log_size=math.log1p(record.size),
        category_risk=_CATEGORY_DECAY_RISK[categorize_extension(record.extension)],
    )


def _heuristic_score(features: _Features) -> float:
    """0-1 score blending recency and how "disposable" the file type is."""
    access_component = min(1.0, features.days_since_access / UNUSED_CONFIDENT_DAYS)
    modified_component = min(1.0, features.days_since_modified / UNUSED_CONFIDENT_DAYS)
    return 0.5 * access_component + 0.2 * modified_component + 0.3 * features.category_risk


def score_files(records: list[FileRecord], now: float | None = None) -> list[UnusedCandidate]:
    now = time.time() if now is None else now
    all_features = [_extract_features(r, now) for r in records]

    labels: list[int | None] = []
    for f in all_features:
        if f.days_since_access >= UNUSED_CONFIDENT_DAYS and f.days_since_modified >= UNUSED_CONFIDENT_DAYS:
            labels.append(1)
        elif f.days_since_access <= ACTIVE_CONFIDENT_DAYS:
            labels.append(0)
        else:
            labels.append(None)

    n_unused = sum(1 for l in labels if l == 1)
    n_active = sum(1 for l in labels if l == 0)

    model = None
    if n_unused >= MIN_TRAINING_SAMPLES_PER_CLASS and n_active >= MIN_TRAINING_SAMPLES_PER_CLASS:
        model = _train_classifier(all_features, labels)

    candidates: list[UnusedCandidate] = []
    for f, label in zip(all_features, labels):
        if model is not None:
            score = _model_score(model, f)
            reason = "learned from access-pattern history"
        else:
            score = _heuristic_score(f)
            reason = "heuristic: recency + file-type risk"

        if label == 1:
            reason = f"untouched for {int(f.days_since_access)}+ days"

        candidates.append(
            UnusedCandidate(
                path=f.record.path,
                size=f.record.size,
                days_since_access=f.days_since_access,
                days_since_modified=f.days_since_modified,
                score=score,
                reason=reason,
            )
        )

    candidates.sort(key=lambda c: c.score, reverse=True)
    return candidates


def _feature_matrix(features: list[_Features]) -> list[list[float]]:
    return [
        [f.days_since_access, f.days_since_modified, f.log_size, f.category_risk]
        for f in features
    ]


def _train_classifier(all_features: list[_Features], labels: list[int | None]):
    from sklearn.ensemble import RandomForestClassifier

    training_features = [f for f, l in zip(all_features, labels) if l is not None]
    training_labels = [l for l in labels if l is not None]

    model = RandomForestClassifier(n_estimators=100, max_depth=6, random_state=42)
    model.fit(_feature_matrix(training_features), training_labels)
    return model


def _model_score(model, features: _Features) -> float:
    proba = model.predict_proba([_feature_matrix([features])[0]])[0]
    classes = list(model.classes_)
    return float(proba[classes.index(1)]) if 1 in classes else 0.0
