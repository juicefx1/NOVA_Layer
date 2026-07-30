from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from uuid import uuid4

import numpy as np

from nova_layer.app.object_workflow_controller import ObjectWorkflowController
from nova_layer.object_workflow.adapters.local_matting_extraction import (
    LocalMattingExtractionEngine,
)
from nova_layer.object_workflow.adapters.neural_matting import (
    BACKEND_ID,
    FakeOnnxSession,
    MattingBackendError,
    NeuralMattingBackend,
    model_fingerprint,
    onnx_runtime_available,
    probe_neural_matting_availability,
    resolve_matting_onnx_model,
)
from nova_layer.object_workflow.adapters.trimap import (
    TRIMAP_BACKGROUND,
    TRIMAP_FOREGROUND,
    TRIMAP_UNKNOWN,
    build_trimap_from_binary_mask,
)
from nova_layer.object_workflow.domain.binary_mask import BinaryMask
from nova_layer.object_workflow.domain.models import ExtractionSettings
from nova_layer.object_workflow.ports.extraction_provider import ExtractionRuntimeConfig
from nova_layer.object_workflow.ports.precision_extraction import (
    PrecisionExtractionError,
    PrecisionExtractionRequest,
    PrecisionExtractionSuccess,
)


def _rgb(width: int, height: int) -> bytes:
    return bytes([40, 80, 120]) * (width * height)


def _square_mask(width: int, height: int) -> BinaryMask:
    data = bytearray(width * height)
    for y in range(height // 4, 3 * height // 4):
        for x in range(width // 4, 3 * width // 4):
            data[y * width + x] = 255
    return BinaryMask.from_pixels(width, height, bytes(data))


def _dummy_onnx(path: Path) -> Path:
    path.write_bytes(b"ONNX_DUMMY_CHECKPOINT_BYTES")
    return path


class NeuralMattingAvailabilityTests(TestCase):
    def test_probe_missing_dependency_or_model(self) -> None:
        status, message = probe_neural_matting_availability(
            model_path=None,
            environ={},
            require_onnx=True,
        )
        self.assertEqual("unavailable", status)
        if not onnx_runtime_available():
            self.assertIn("DEPENDENCY_MISSING", message)
        else:
            self.assertIn("MODEL_MISSING", message)

    def test_probe_missing_model_when_onnx_optional(self) -> None:
        status, message = probe_neural_matting_availability(
            model_path=None,
            environ={},
            require_onnx=False,
        )
        self.assertEqual("unavailable", status)
        self.assertIn("MODEL_MISSING", message)

    def test_probe_invalid_extension(self) -> None:
        with TemporaryDirectory() as tmp:
            bad = Path(tmp) / "model.bin"
            bad.write_bytes(b"not-an-onnx-file!!!!")
            status, message = probe_neural_matting_availability(
                model_path=bad,
                environ={},
                require_onnx=False,
            )
            self.assertEqual("unavailable", status)
            self.assertIn("MODEL_INVALID", message)

    def test_resolve_order_prefers_explicit(self) -> None:
        with TemporaryDirectory() as tmp:
            explicit = _dummy_onnx(Path(tmp) / "explicit.onnx")
            env_model = _dummy_onnx(Path(tmp) / "env.onnx")
            resolved = resolve_matting_onnx_model(
                explicit=explicit,
                environ={"NOVA_MATTING_ONNX_MODEL": str(env_model)},
            )
            self.assertEqual(explicit.resolve(), resolved)


class FakeSessionNeuralBackendTests(TestCase):
    def test_lazy_session_and_reuse(self) -> None:
        with TemporaryDirectory() as tmp:
            model = _dummy_onnx(Path(tmp) / "neural_matting.onnx")
            sessions: list[FakeOnnxSession] = []

            def factory(_path: Path) -> FakeOnnxSession:
                session = FakeOnnxSession()
                sessions.append(session)
                return session

            backend = NeuralMattingBackend(model_path=model, session_factory=factory)
            self.assertIsNone(backend._session)
            width, height = 32, 24
            rgb = np.frombuffer(_rgb(width, height), dtype=np.uint8).reshape(
                (height, width, 3)
            )
            mask = _square_mask(width, height)
            trimap = build_trimap_from_binary_mask(
                width=width,
                height=height,
                binary_foreground=np.frombuffer(mask.data, dtype=np.uint8).reshape(
                    (height, width)
                )
                > 0,
                unknown_radius=2,
            )
            alpha1 = backend.estimate_alpha(
                source_rgb=rgb,
                trimap=trimap,
                should_cancel=lambda: False,
            )
            alpha2 = backend.estimate_alpha(
                source_rgb=rgb,
                trimap=trimap,
                should_cancel=lambda: False,
            )
            self.assertEqual(1, len(sessions))
            self.assertEqual(2, sessions[0].run_count)
            self.assertEqual((height, width), alpha1.shape)
            self.assertTrue(np.allclose(alpha1, alpha2))
            labels = trimap.as_array()
            self.assertTrue(np.all(alpha1[labels == TRIMAP_FOREGROUND] == 1.0))
            self.assertTrue(np.all(alpha1[labels == TRIMAP_BACKGROUND] == 0.0))
            self.assertGreater(
                float(alpha1[labels == TRIMAP_UNKNOWN].mean()),
                0.0,
            )
            self.assertEqual(BACKEND_ID, backend.last_run_metadata["backend_id"])
            self.assertIsNotNone(backend.last_run_metadata["model_fingerprint"])
            self.assertNotIn("model_path", backend.last_run_metadata)

    def test_cancel_before_inference(self) -> None:
        with TemporaryDirectory() as tmp:
            model = _dummy_onnx(Path(tmp) / "neural_matting.onnx")
            backend = NeuralMattingBackend(
                model_path=model,
                session_factory=lambda _p: FakeOnnxSession(),
            )
            width, height = 16, 16
            rgb = np.frombuffer(_rgb(width, height), dtype=np.uint8).reshape(
                (height, width, 3)
            )
            mask = _square_mask(width, height)
            trimap = build_trimap_from_binary_mask(
                width=width,
                height=height,
                binary_foreground=np.frombuffer(mask.data, dtype=np.uint8).reshape(
                    (height, width)
                )
                > 0,
                unknown_radius=1,
            )
            from nova_layer.object_workflow.adapters.neural_matting import MattingCancelled

            with self.assertRaises(MattingCancelled):
                backend.estimate_alpha(
                    source_rgb=rgb,
                    trimap=trimap,
                    should_cancel=lambda: True,
                )

    def test_model_missing_raises(self) -> None:
        backend = NeuralMattingBackend(model_path=None, environ={})
        with self.assertRaises(MattingBackendError) as ctx:
            backend.ensure_session()
        self.assertEqual("MODEL_MISSING", ctx.exception.code)

    def test_fingerprint_stable(self) -> None:
        with TemporaryDirectory() as tmp:
            model = _dummy_onnx(Path(tmp) / "f.onnx")
            self.assertEqual(model_fingerprint(model), model_fingerprint(model))


class EngineNeuralSelectionTests(TestCase):
    def test_neural_backend_via_settings_no_silent_fallback(self) -> None:
        with TemporaryDirectory() as tmp:
            model = _dummy_onnx(Path(tmp) / "neural_matting.onnx")
            fake = FakeOnnxSession()
            engine = LocalMattingExtractionEngine(
                matting_backend="neural_onnx",
                matting_onnx_model_path=str(model),
                neural_session_factory=lambda _p: fake,
                matting_unknown_radius=2,
            )
            width, height = 24, 24
            request = PrecisionExtractionRequest(
                request_id=uuid4(),
                source_width=width,
                source_height=height,
                source_rgb=_rgb(width, height),
                mask=_square_mask(width, height),
                provider_options={
                    "extraction_settings": {
                        "matting_backend": "neural_onnx",
                        "matting_unknown_radius": 2,
                        "matting_preserve_known_regions": True,
                        "matting_refinement_strength": 1.0,
                        "edge_blur_radius": 0.0,
                        "expand_contract_pixels": 0,
                        "cleanup_radius": 0,
                        "premultiply_alpha": False,
                    },
                    "should_cancel": lambda: False,
                },
            )
            result = engine.extract(request)
            self.assertIsInstance(result, PrecisionExtractionSuccess)
            assert isinstance(result, PrecisionExtractionSuccess)
            self.assertEqual("neural_onnx", result.diagnostics["backend_id"])
            self.assertEqual("neural_onnx_matting_v1", result.diagnostics["algorithm"])
            self.assertNotIn("/tmp", str(result.diagnostics))
            self.assertGreaterEqual(fake.run_count, 1)
            soft = int(result.diagnostics["soft_alpha_pixel_count"])
            self.assertGreater(soft, 0)

    def test_missing_model_does_not_fall_back(self) -> None:
        width, height = 16, 16
        request = PrecisionExtractionRequest(
            request_id=uuid4(),
            source_width=width,
            source_height=height,
            source_rgb=_rgb(width, height),
            mask=_square_mask(width, height),
            provider_options={
                "extraction_settings": {"matting_backend": "neural_onnx"},
                "should_cancel": lambda: False,
            },
        )
        engine = LocalMattingExtractionEngine(
            matting_backend="neural_onnx",
            matting_onnx_model_path="/nonexistent/path/model.onnx",
            neural_session_factory=lambda _p: FakeOnnxSession(),
        )
        result = engine.extract(request)
        self.assertIsInstance(result, PrecisionExtractionError)
        assert isinstance(result, PrecisionExtractionError)
        self.assertEqual("MODEL_MISSING", result.error_code)

    def test_color_affinity_still_default(self) -> None:
        engine = LocalMattingExtractionEngine(matting_unknown_radius=2)
        width, height = 20, 20
        result = engine.extract(
            PrecisionExtractionRequest(
                request_id=uuid4(),
                source_width=width,
                source_height=height,
                source_rgb=_rgb(width, height),
                mask=_square_mask(width, height),
                provider_options={"should_cancel": lambda: False},
            )
        )
        self.assertIsInstance(result, PrecisionExtractionSuccess)
        assert isinstance(result, PrecisionExtractionSuccess)
        self.assertEqual("color_affinity", result.diagnostics["backend_id"])


class SettingsAndControllerTests(TestCase):
    def test_extraction_settings_include_backend(self) -> None:
        settings = ExtractionSettings(matting_backend="neural_onnx")
        self.assertEqual("neural_onnx", settings.matting_backend)
        snapshot = ExtractionRuntimeConfig(matting_backend="neural_onnx").settings_snapshot()
        self.assertEqual("neural_onnx", snapshot["matting_backend"])

    def test_controller_backend_selection(self) -> None:
        controller = ObjectWorkflowController()
        state = controller.view_state()
        self.assertEqual("color_affinity", state.precision_extraction_matting_backend)
        self.assertTrue(state.neural_matting_availability_message)
        controller.set_extraction_refinement(matting_backend="neural_onnx")
        updated = controller.view_state()
        self.assertEqual("neural_onnx", updated.precision_extraction_matting_backend)
        self.assertEqual(
            "neural_onnx",
            controller._extraction_runtime_config.settings_snapshot()["matting_backend"],
        )
