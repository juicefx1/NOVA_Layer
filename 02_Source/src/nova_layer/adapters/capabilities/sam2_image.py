from __future__ import annotations

import importlib
from collections.abc import Sequence
from hashlib import blake2b
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
from threading import RLock
from typing import Protocol, cast

import numpy as np
from numpy.typing import NDArray

from nova_layer.domain.models import BoundingRegion, CapabilityProvenance, GuidancePoint
from nova_layer.ports.capabilities import SegmentationResult


class Sam2UnavailableError(RuntimeError):
    """Raised when the optional SAM 2 runtime cannot be initialized."""


class _Sam2ImagePredictor(Protocol):
    def set_image(self, image: NDArray[np.uint8]) -> None: ...

    def predict(
        self,
        *,
        point_coords: NDArray[np.float32] | None,
        point_labels: NDArray[np.int32] | None,
        box: NDArray[np.float32] | None,
        multimask_output: bool,
    ) -> tuple[NDArray[np.bool_], NDArray[np.float32], NDArray[np.float32]]: ...


class Sam2ImageSegmentationCapability:
    """SAM 2.1 image prompting behind NOVA's model-independent capability port."""

    def __init__(
        self,
        checkpoint: Path,
        *,
        model_config: str = "configs/sam2.1/sam2.1_hiera_t.yaml",
        device: str = "mps",
        predictor: _Sam2ImagePredictor | None = None,
    ) -> None:
        self.checkpoint = checkpoint
        self.model_config = model_config
        self.device = device
        self._predictor = predictor
        self._image_key: tuple[int, bytes] | None = None
        self._lock = RLock()

    @property
    def provenance(self) -> CapabilityProvenance:
        try:
            adapter_version = version("SAM-2")
        except PackageNotFoundError:
            adapter_version = "not-installed"
        return CapabilityProvenance(
            capability="interactive_segmentation",
            adapter="sam2.1_hiera_image",
            adapter_version=adapter_version,
            model_identifier=Path(self.checkpoint).stem,
            device=self.device,
        )

    def _load_predictor(self) -> _Sam2ImagePredictor:
        if self._predictor is not None:
            return self._predictor
        if not self.checkpoint.is_file():
            raise Sam2UnavailableError(f"SAM 2 checkpoint not found: {self.checkpoint}")
        try:
            build_module = importlib.import_module("sam2.build_sam")
            predictor_module = importlib.import_module("sam2.sam2_image_predictor")
            build_sam2 = build_module.build_sam2
            predictor_type = predictor_module.SAM2ImagePredictor
            model = build_sam2(
                self.model_config,
                str(self.checkpoint),
                device=self.device,
                apply_postprocessing=False,
            )
            self._predictor = cast(_Sam2ImagePredictor, predictor_type(model))
        except Exception as exc:
            message = f"Could not initialize SAM 2 on {self.device}: {exc}"
            raise Sam2UnavailableError(message) from exc
        return self._predictor

    def predict(
        self,
        *,
        frame_number: int,
        image: NDArray[np.uint8],
        width: int,
        height: int,
        points: Sequence[GuidancePoint],
        bounding_region: BoundingRegion | None,
    ) -> SegmentationResult:
        if image.shape != (height, width, 3) or image.dtype != np.uint8:
            raise ValueError("SAM 2 requires an RGB uint8 frame matching the declared dimensions.")
        if not points and bounding_region is None:
            raise ValueError("SAM 2 requires at least one point or bounding region.")

        point_coords = None
        point_labels = None
        if points:
            point_coords = np.asarray(
                [(point.x * width, point.y * height) for point in points], dtype=np.float32
            )
            point_labels = np.asarray(
                [1 if point.polarity == "positive" else 0 for point in points], dtype=np.int32
            )
        box = None
        if bounding_region is not None:
            box = np.asarray(
                [
                    bounding_region.x * width,
                    bounding_region.y * height,
                    (bounding_region.x + bounding_region.width) * width,
                    (bounding_region.y + bounding_region.height) * height,
                ],
                dtype=np.float32,
            )

        image_key = (frame_number, blake2b(image.tobytes(), digest_size=16).digest())
        with self._lock:
            predictor = self._load_predictor()
            embedding_cache_hit = image_key == self._image_key
            if not embedding_cache_hit:
                predictor.set_image(image)
                self._image_key = image_key
            masks, scores, _ = predictor.predict(
                point_coords=point_coords,
                point_labels=point_labels,
                box=box,
                multimask_output=True,
            )
        best_index = int(np.argmax(scores))
        mask = np.asarray(masks[best_index], dtype=np.uint8) * 255
        provenance = self.provenance.model_copy(
            update={"settings": {"embedding_cache_hit": embedding_cache_hit}}
        )
        return SegmentationResult(
            mask_reference=f"masks/hypothesis_{frame_number:06d}.png",
            mask=mask,
            confidence=float(scores[best_index]),
            provenance=provenance,
        )
