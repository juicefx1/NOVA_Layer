from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from numpy.typing import NDArray


@dataclass(frozen=True, slots=True)
class TemporalConfidence:
    score: float
    logit_certainty: float
    master_area_consistency: float
    transition_area_consistency: float


def _area_consistency(left: NDArray[np.bool_], right: NDArray[np.bool_]) -> float:
    left_area = int(left.sum())
    right_area = int(right.sum())
    if left_area == 0 and right_area == 0:
        return 1.0
    if left_area == 0 or right_area == 0:
        return 0.0
    return min(left_area, right_area) / max(left_area, right_area)


def evaluate_temporal_confidence(
    logits: NDArray[np.float32],
    reference_mask: NDArray[np.bool_],
    previous_mask: NDArray[np.bool_],
) -> TemporalConfidence:
    predicted_mask = logits > 0
    certainty = 1.0 / (1.0 + np.exp(-np.clip(np.abs(logits), 0.0, 30.0)))
    logit_certainty = float(certainty.mean())
    master_consistency = _area_consistency(predicted_mask, reference_mask)
    transition_consistency = _area_consistency(predicted_mask, previous_mask)
    score = 0.40 * logit_certainty + 0.35 * master_consistency + 0.25 * transition_consistency
    if reference_mask.any() and not predicted_mask.any():
        score = min(score, 0.40)
    return TemporalConfidence(
        score=score,
        logit_certainty=logit_certainty,
        master_area_consistency=master_consistency,
        transition_area_consistency=transition_consistency,
    )
