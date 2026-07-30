from pathlib import Path

import numpy as np

from nova_layer.adapters.capabilities.sam2_image import (
    Sam2ImageSegmentationCapability,
    Sam2UnavailableError,
)
from nova_layer.domain.models import BoundingRegion, GuidancePoint


class RecordingPredictor:
    def __init__(self) -> None:
        self.image: np.ndarray | None = None
        self.arguments: dict[str, object] = {}
        self.set_image_calls = 0

    def set_image(self, image: np.ndarray) -> None:
        self.image = image
        self.set_image_calls += 1

    def predict(self, **kwargs: object) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
        self.arguments = kwargs
        masks = np.zeros((3, 8, 10), dtype=np.bool_)
        masks[1, 2:6, 3:8] = True
        return masks, np.asarray([0.2, 0.9, 0.4], dtype=np.float32), np.zeros((3, 1))


def test_sam2_adapter_maps_normalized_guidance_and_selects_best_mask() -> None:
    predictor = RecordingPredictor()
    adapter = Sam2ImageSegmentationCapability(Path("unused.pt"), predictor=predictor, device="mps")

    result = adapter.predict(
        frame_number=12,
        image=np.zeros((8, 10, 3), dtype=np.uint8),
        width=10,
        height=8,
        points=[
            GuidancePoint(x=0.5, y=0.25, polarity="positive"),
            GuidancePoint(x=0.2, y=0.75, polarity="negative"),
        ],
        bounding_region=BoundingRegion(x=0.1, y=0.25, width=0.6, height=0.5),
    )

    np.testing.assert_array_equal(
        predictor.arguments["point_coords"], np.asarray([[5.0, 2.0], [2.0, 6.0]])
    )
    np.testing.assert_array_equal(predictor.arguments["point_labels"], np.asarray([1, 0]))
    np.testing.assert_array_equal(predictor.arguments["box"], np.asarray([1.0, 2.0, 7.0, 6.0]))
    assert result.confidence == np.float32(0.9)
    assert result.mask.dtype == np.uint8
    assert result.mask.sum() == 20 * 255
    assert result.provenance.model_identifier == "unused"
    assert result.provenance.settings["embedding_cache_hit"] is False


def test_sam2_adapter_reuses_embedding_only_for_identical_frame() -> None:
    predictor = RecordingPredictor()
    adapter = Sam2ImageSegmentationCapability(Path("unused.pt"), predictor=predictor)
    image = np.zeros((8, 10, 3), dtype=np.uint8)
    arguments = {
        "frame_number": 4,
        "image": image,
        "width": 10,
        "height": 8,
        "points": [GuidancePoint(x=0.5, y=0.5, polarity="positive")],
        "bounding_region": None,
    }

    first = adapter.predict(**arguments)  # type: ignore[arg-type]
    second = adapter.predict(**arguments)  # type: ignore[arg-type]
    changed = image.copy()
    changed[0, 0] = 255
    adapter.predict(**(arguments | {"image": changed}))  # type: ignore[arg-type]

    assert first.provenance.settings["embedding_cache_hit"] is False
    assert second.provenance.settings["embedding_cache_hit"] is True
    assert predictor.set_image_calls == 2


def test_sam2_adapter_reports_missing_checkpoint() -> None:
    adapter = Sam2ImageSegmentationCapability(Path("missing.pt"))

    try:
        adapter.predict(
            frame_number=0,
            image=np.zeros((8, 10, 3), dtype=np.uint8),
            width=10,
            height=8,
            points=[GuidancePoint(x=0.5, y=0.5, polarity="positive")],
            bounding_region=None,
        )
    except Sam2UnavailableError as exc:
        assert "checkpoint not found" in str(exc)
    else:
        raise AssertionError("missing checkpoint should fail explicitly")
