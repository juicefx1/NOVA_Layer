from __future__ import annotations

import importlib
from collections.abc import Iterator, Sequence
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Protocol, cast

import numpy as np
from numpy.typing import NDArray
from PIL import Image

from nova_layer.app.temporal_confidence import evaluate_temporal_confidence
from nova_layer.domain.models import CapabilityProvenance
from nova_layer.ports.capabilities import PropagationResult, VideoFrame


class Sam2VideoUnavailableError(RuntimeError):
    """Raised when SAM 2 video propagation cannot be initialized."""


class _Tensor(Protocol):
    def cpu(self) -> _Tensor: ...

    def numpy(self) -> NDArray[np.float32]: ...


class _Sam2VideoPredictor(Protocol):
    def init_state(
        self,
        video_path: str,
        *,
        offload_video_to_cpu: bool,
        offload_state_to_cpu: bool,
        async_loading_frames: bool,
    ) -> object: ...

    def add_new_mask(
        self, inference_state: object, frame_idx: int, obj_id: int, mask: NDArray[np.bool_]
    ) -> object: ...

    def propagate_in_video(
        self,
        inference_state: object,
        *,
        start_frame_idx: int,
        max_frame_num_to_track: int,
        reverse: bool,
    ) -> Iterator[tuple[int, object, _Tensor]]: ...


class Sam2VideoPropagationCapability:
    """Bidirectional SAM 2.1 tracking from a confirmed NOVA master mask."""

    def __init__(
        self,
        checkpoint: Path,
        *,
        model_config: str = "configs/sam2.1/sam2.1_hiera_t.yaml",
        device: str = "mps",
        predictor: _Sam2VideoPredictor | None = None,
    ) -> None:
        self.checkpoint = checkpoint
        self.model_config = model_config
        self.device = device
        self._predictor = predictor

    @property
    def provenance(self) -> CapabilityProvenance:
        try:
            adapter_version = version("SAM-2")
        except PackageNotFoundError:
            adapter_version = "not-installed"
        return CapabilityProvenance(
            capability="temporal_propagation",
            adapter="sam2.1_hiera_video",
            adapter_version=adapter_version,
            model_identifier=self.checkpoint.stem,
            device=self.device,
            settings={"video_frames_cpu_offload": True, "state_cpu_offload": True},
        )

    def _load_predictor(self) -> _Sam2VideoPredictor:
        if self._predictor is not None:
            return self._predictor
        if not self.checkpoint.is_file():
            raise Sam2VideoUnavailableError(f"SAM 2 checkpoint not found: {self.checkpoint}")
        try:
            build_module = importlib.import_module("sam2.build_sam")
            predictor = build_module.build_sam2_video_predictor(
                self.model_config,
                str(self.checkpoint),
                device=self.device,
                apply_postprocessing=False,
                vos_optimized=False,
            )
            self._predictor = cast(_Sam2VideoPredictor, predictor)
        except Exception as exc:
            message = f"Could not initialize SAM 2 video predictor on {self.device}: {exc}"
            raise Sam2VideoUnavailableError(message) from exc
        return self._predictor

    def propagate(
        self,
        *,
        master_frame: int,
        target_frames: Sequence[int],
        reference_mask: str,
        reference_mask_data: NDArray[np.uint8],
        frames: Sequence[VideoFrame],
    ) -> list[PropagationResult]:
        del reference_mask
        ordered = sorted(frames, key=lambda item: item.frame_number)
        frame_numbers = [item.frame_number for item in ordered]
        if not ordered or master_frame not in frame_numbers:
            raise ValueError("Video propagation requires a frame sequence containing the master.")
        if any(
            right != left + 1 for left, right in zip(frame_numbers, frame_numbers[1:], strict=False)
        ):
            raise ValueError("Video propagation requires a continuous Shot Range.")
        if not set(target_frames).issubset(frame_numbers):
            raise ValueError("Every propagation target must exist in the supplied Shot Range.")
        height, width = ordered[0].image.shape[:2]
        if reference_mask_data.shape != (height, width):
            raise ValueError("The confirmed master mask must match the video frame dimensions.")
        if any(item.image.shape != (height, width, 3) for item in ordered):
            raise ValueError("All video frames must have identical RGB dimensions.")

        predictor = self._load_predictor()
        with TemporaryDirectory(prefix="nova_sam2_frames_") as directory:
            frame_directory = Path(directory)
            for index, frame in enumerate(ordered):
                Image.fromarray(frame.image, mode="RGB").save(
                    frame_directory / f"{index:06d}.jpg", quality=95, subsampling=0
                )
            state = predictor.init_state(
                str(frame_directory),
                offload_video_to_cpu=True,
                offload_state_to_cpu=True,
                async_loading_frames=False,
            )
            master_index = frame_numbers.index(master_frame)
            predictor.add_new_mask(
                state, master_index, 1, np.asarray(reference_mask_data > 0, dtype=np.bool_)
            )
            index_to_frame = dict(enumerate(frame_numbers))
            collected: dict[int, PropagationResult] = {}
            self._collect_direction(
                predictor,
                state,
                master_index,
                False,
                index_to_frame,
                set(target_frames),
                collected,
                reference_mask_data > 0,
            )
            self._collect_direction(
                predictor,
                state,
                master_index,
                True,
                index_to_frame,
                set(target_frames),
                collected,
                reference_mask_data > 0,
            )
        return [collected[frame] for frame in sorted(collected)]

    def _collect_direction(
        self,
        predictor: _Sam2VideoPredictor,
        state: object,
        master_index: int,
        reverse: bool,
        index_to_frame: dict[int, int],
        target_frames: set[int],
        collected: dict[int, PropagationResult],
        reference_mask: NDArray[np.bool_],
    ) -> None:
        iterator = predictor.propagate_in_video(
            state,
            start_frame_idx=master_index,
            max_frame_num_to_track=len(index_to_frame),
            reverse=reverse,
        )
        previous_mask = reference_mask
        reference_area = max(1, int(reference_mask.sum()))
        for local_index, _, mask_logits in iterator:
            logits = np.asarray(mask_logits.cpu().numpy()[0]).squeeze()
            mask_bool = np.asarray(logits > 0, dtype=np.bool_)
            confidence = evaluate_temporal_confidence(logits, reference_mask, previous_mask)
            previous_mask = mask_bool
            frame_number = index_to_frame.get(local_index)
            if frame_number is None or local_index == master_index:
                continue
            mask = np.asarray(mask_bool, dtype=np.uint8) * 255
            provenance = self.provenance.model_copy(
                update={
                    "settings": self.provenance.settings
                    | {
                        "logit_certainty": confidence.logit_certainty,
                        "master_area_consistency": confidence.master_area_consistency,
                        "transition_area_consistency": confidence.transition_area_consistency,
                    }
                }
            )
            collected[frame_number] = PropagationResult(
                frame_number=frame_number,
                mask_reference=f"masks/frame_{frame_number:06d}.png",
                mask=mask,
                confidence=confidence.score,
                provenance=provenance,
                is_validation_target=frame_number in target_frames,
                visible=bool(mask_bool.any()),
                area_ratio=float(int(mask_bool.sum()) / reference_area),
            )
