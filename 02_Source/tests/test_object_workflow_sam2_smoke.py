"""Optional real SAM 2 smoke test. Excluded from the default pytest command.

Run explicitly when local artefacts exist:

  cd 02_Source
  .venv/bin/pytest tests/test_object_workflow_sam2_smoke.py -m real_model -q
"""

from __future__ import annotations

import struct
import time
import zlib
from pathlib import Path
from tempfile import TemporaryDirectory

import pytest

from nova_layer.object_workflow.adapters.core_inference_factory import default_sam2_checkpoint
from nova_layer.object_workflow.adapters.sam2_core_inference import Sam2CoreInferenceEngine
from nova_layer.object_workflow.domain.models import IntentInstruction, IntentPayload
from nova_layer.object_workflow.ports.core_inference import CoreInferenceRequest

pytestmark = pytest.mark.real_model


def _png_bytes(width: int, height: int, fill: int = 128) -> bytes:
    raw = bytearray()
    for _ in range(height):
        raw.append(0)
        raw.extend([fill] * width)
    compressed = zlib.compress(bytes(raw), level=9)
    ihdr = struct.pack(">IIBBBBB", width, height, 8, 0, 0, 0, 0)

    def chunk(tag: bytes, data: bytes) -> bytes:
        crc = zlib.crc32(tag)
        crc = zlib.crc32(data, crc) & 0xFFFFFFFF
        return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", crc)

    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", ihdr)
        + chunk(b"IDAT", compressed)
        + chunk(b"IEND", b"")
    )


@pytest.fixture
def checkpoint() -> Path:
    path = default_sam2_checkpoint()
    if not path.is_file():
        pytest.skip(f"SAM 2 checkpoint absent: {path}")
    return path


def test_real_sam2_smoke_and_timing(checkpoint: Path) -> None:
    import importlib.util

    if importlib.util.find_spec("sam2") is None or importlib.util.find_spec("torch") is None:
        pytest.skip("SAM-2 / torch not installed")

    engine = Sam2CoreInferenceEngine(checkpoint=checkpoint, device="auto")
    with TemporaryDirectory() as tmp:
        source = Path(tmp) / "smoke.png"
        width, height = 64, 48
        source.write_bytes(_png_bytes(width, height, fill=110))
        instruction = IntentInstruction(
            schema_name="nova.intent.guidance.v1",
            payload=IntentPayload(
                signals=[
                    {"type": "positive_point", "x": 0.5, "y": 0.5},
                    {"type": "bounding_box", "x": 0.25, "y": 0.25, "width": 0.4, "height": 0.4},
                ]
            ),
        )
        request = CoreInferenceRequest(
            request_id="smoke-1",
            source_image_path=str(source),
            source_width=width,
            source_height=height,
            media_type="image/png",
            content_fingerprint="smoke",
            intent_instruction=instruction,
        )

        t0 = time.perf_counter()
        first = engine.generate_hypothesis(request)
        first_s = time.perf_counter() - t0
        assert getattr(first, "mask", None) is not None
        assert first.mask.width == width
        assert first.mask.height == height

        t1 = time.perf_counter()
        second = engine.generate_hypothesis(request)
        warm_s = time.perf_counter() - t1
        assert getattr(second, "mask", None) is not None

        print(
            "sam2_smoke",
            {
                "device": engine.device,
                "input": f"{width}x{height}",
                "init_plus_first_s": round(first_s, 3),
                "warm_s": round(warm_s, 3),
                "confidence": round(float(first.confidence), 4),
            },
        )
