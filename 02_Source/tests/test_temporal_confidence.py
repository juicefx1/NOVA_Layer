import numpy as np

from nova_layer.app.temporal_confidence import evaluate_temporal_confidence


def test_stable_mask_retains_high_temporal_confidence() -> None:
    reference = np.zeros((10, 10), dtype=np.bool_)
    reference[2:8, 2:8] = True
    logits = np.where(reference, 8.0, -8.0).astype(np.float32)

    result = evaluate_temporal_confidence(logits, reference, reference)

    assert result.score > 0.99
    assert result.master_area_consistency == 1.0
    assert result.transition_area_consistency == 1.0


def test_disappearing_mask_is_forced_below_review_threshold() -> None:
    reference = np.zeros((10, 10), dtype=np.bool_)
    reference[2:8, 2:8] = True
    logits = np.full((10, 10), -8.0, dtype=np.float32)

    result = evaluate_temporal_confidence(logits, reference, reference)

    assert result.logit_certainty > 0.99
    assert result.score < 0.60
    assert result.master_area_consistency == 0.0


def test_consecutive_empty_predictions_do_not_restore_confidence() -> None:
    reference = np.zeros((10, 10), dtype=np.bool_)
    reference[2:8, 2:8] = True
    previous = np.zeros_like(reference)
    logits = np.full((10, 10), -8.0, dtype=np.float32)

    result = evaluate_temporal_confidence(logits, reference, previous)

    assert result.transition_area_consistency == 1.0
    assert result.score <= 0.40
