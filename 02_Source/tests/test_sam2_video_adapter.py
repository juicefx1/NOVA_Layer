from pathlib import Path

import numpy as np

from nova_layer.adapters.capabilities.sam2_video import Sam2VideoPropagationCapability
from nova_layer.ports.capabilities import VideoFrame


class FakeTensor:
    def __init__(self, value: np.ndarray) -> None:
        self.value = value

    def cpu(self) -> "FakeTensor":
        return self

    def numpy(self) -> np.ndarray:
        return self.value


class FakeVideoPredictor:
    def __init__(self) -> None:
        self.master_index: int | None = None
        self.reverse_calls: list[bool] = []

    def init_state(self, video_path: str, **kwargs: object) -> object:
        assert len(list(Path(video_path).glob("*.jpg"))) == 5
        assert kwargs["offload_video_to_cpu"] is True
        return {}

    def add_new_mask(self, state: object, frame_idx: int, obj_id: int, mask: np.ndarray) -> object:
        del state, obj_id
        self.master_index = frame_idx
        assert mask.shape == (6, 8)
        return None

    def propagate_in_video(
        self, state: object, *, start_frame_idx: int, reverse: bool, **kwargs: object
    ) -> object:
        del state, kwargs
        assert start_frame_idx == 2
        self.reverse_calls.append(reverse)
        indices = range(2, -1, -1) if reverse else range(2, 5)
        for index in indices:
            logits = np.full((1, 1, 6, 8), 2.0 if index % 2 else -2.0, dtype=np.float32)
            yield index, [1], FakeTensor(logits)


def test_sam2_video_adapter_tracks_forward_and_backward_targets() -> None:
    predictor = FakeVideoPredictor()
    adapter = Sam2VideoPropagationCapability(Path("unused.pt"), predictor=predictor)
    frames = [
        VideoFrame(frame_number=number, image=np.zeros((6, 8, 3), dtype=np.uint8))
        for number in range(10, 15)
    ]

    results = adapter.propagate(
        master_frame=12,
        target_frames=[10, 14],
        reference_mask="master.png",
        reference_mask_data=np.full((6, 8), 255, dtype=np.uint8),
        frames=frames,
    )

    assert [item.frame_number for item in results] == [10, 11, 13, 14]
    assert [item.frame_number for item in results if item.is_validation_target] == [10, 14]
    assert predictor.master_index == 2
    assert predictor.reverse_calls == [False, True]
    assert all(item.provenance.device == "mps" for item in results)
