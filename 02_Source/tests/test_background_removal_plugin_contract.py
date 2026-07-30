"""Contract tests for the official Background Removal matting plugin.

Design authority: Revised Background Removal implementation design
(ConfirmedMaskRefine, MVP: registration / engine / package / tests / docs).

These tests define the plugin contract. They are expected to FAIL until
``plugins/nova_background_removal/`` is implemented (engine + manifests).

Do not weaken assertions to match a missing implementation.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from typing import Any
from unittest import TestCase
from uuid import uuid4

from nova_layer.object_workflow.adapters.precision_extraction_registry import (
    PrecisionExtractionProviderRegistry,
    build_default_precision_extraction_registry,
)
from nova_layer.object_workflow.domain.binary_mask import BinaryMask
from nova_layer.object_workflow.plugin_sdk import (
    PACKAGE_FORMAT_VERSION,
    SDK_VERSION,
    PluginManager,
    load_manifest,
    validate_plugin_package,
)
from nova_layer.object_workflow.ports.extraction_provider import ExtractionRuntimeConfig
from nova_layer.object_workflow.ports.precision_extraction import (
    PrecisionExtractionEngine,
    PrecisionExtractionError,
    PrecisionExtractionRequest,
    PrecisionExtractionSuccess,
)

# --- Contract constants (design lock) -------------------------------------------------

REPO_ROOT = Path(__file__).resolve().parents[2]
PLUGIN_DIR = REPO_ROOT / "plugins" / "nova_background_removal"
PLUGIN_ID = "nova.background_removal"
PROVIDER_ID = "nova.background_removal"
MASK_POLICY_ID = "ConfirmedMaskRefine"
# Default dilation (pixels) for MP-3 outside-mask clamp — engine must honour or report.
DEFAULT_MASK_DILATION_RADIUS = 2
# Alpha at or below this is treated as background for clamp checks.
ALPHA_EPS = 2


def _rgb(width: int, height: int, r: int = 40, g: int = 80, b: int = 120) -> bytes:
    return bytes([r, g, b]) * (width * height)


def _empty_mask(width: int, height: int) -> BinaryMask:
    return BinaryMask.from_pixels(width, height, bytes([0] * (width * height)))


def _square_mask(width: int, height: int, margin: int = 2) -> BinaryMask:
    data = bytearray(width * height)
    for y in range(margin, height - margin):
        for x in range(margin, width - margin):
            data[y * width + x] = 255
    return BinaryMask.from_pixels(width, height, bytes(data))


def _dilate_binary(mask: BinaryMask, radius: int) -> bytes:
    """Pure-Python binary dilation for MP-3 oracle (contract helper, not production)."""
    if radius <= 0:
        return mask.data
    w, h = mask.width, mask.height
    src = mask.data
    out = bytearray(w * h)
    for y in range(h):
        for x in range(w):
            if src[y * w + x] == 0:
                continue
            for dy in range(-radius, radius + 1):
                for dx in range(-radius, radius + 1):
                    if dx * dx + dy * dy > radius * radius:
                        continue
                    nx, ny = x + dx, y + dy
                    if 0 <= nx < w and 0 <= ny < h:
                        out[ny * w + nx] = 255
    return bytes(out)


def _erode_binary(mask: BinaryMask, radius: int) -> bytes:
    if radius <= 0:
        return mask.data
    w, h = mask.width, mask.height
    src = mask.data
    out = bytearray(w * h)
    for y in range(h):
        for x in range(w):
            ok = True
            for dy in range(-radius, radius + 1):
                for dx in range(-radius, radius + 1):
                    if dx * dx + dy * dy > radius * radius:
                        continue
                    nx, ny = x + dx, y + dy
                    if not (0 <= nx < w and 0 <= ny < h) or src[ny * w + nx] == 0:
                        ok = False
                        break
                if not ok:
                    break
            if ok:
                out[y * w + x] = 255
    return bytes(out)


def _require_plugin_dir() -> Path:
    if not PLUGIN_DIR.is_dir():
        raise AssertionError(
            "Background Removal plugin not implemented: "
            f"expected plugin directory at {PLUGIN_DIR}"
        )
    return PLUGIN_DIR


def _load_engine_module() -> Any:
    """Load plugins/nova_background_removal/engine.py (production module)."""
    plugin_dir = _require_plugin_dir()
    engine_path = plugin_dir / "engine.py"
    if not engine_path.is_file():
        raise AssertionError(
            "Background Removal engine not implemented: "
            f"expected {engine_path}"
        )
    module_name = "nova_background_removal_engine_contract"
    spec = importlib.util.spec_from_file_location(module_name, engine_path)
    if spec is None or spec.loader is None:
        raise AssertionError(f"could not load engine module from {engine_path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


def _create_engine(config: ExtractionRuntimeConfig | None = None) -> PrecisionExtractionEngine:
    module = _load_engine_module()
    factory = getattr(module, "create_engine", None)
    engine_cls = getattr(module, "BackgroundRemovalEngine", None)
    runtime = config or ExtractionRuntimeConfig(selected_provider_id=PROVIDER_ID)
    if callable(factory):
        engine = factory(runtime)
    elif engine_cls is not None:
        engine = engine_cls(runtime)
    else:
        raise AssertionError(
            "engine.py must export create_engine(config) or BackgroundRemovalEngine"
        )
    if not hasattr(engine, "extract"):
        raise AssertionError("engine must implement extract()")
    return engine  # type: ignore[no-any-return]


def _register_plugin(
    extraction: PrecisionExtractionProviderRegistry | None = None,
) -> tuple[PrecisionExtractionProviderRegistry, list[Any]]:
    plugin_dir = _require_plugin_dir()
    roots = plugin_dir.parent
    registry = extraction or build_default_precision_extraction_registry()
    manager = PluginManager(
        plugin_roots=roots,
        include_default_roots=False,
        environ={},
    )
    infos = manager.load_and_register(extraction_registry=registry)
    return registry, infos


class BackgroundRemovalPackageContractTests(TestCase):
    """Package / manifest validation contract."""

    def test_plugin_directory_and_required_files_exist(self) -> None:
        plugin_dir = _require_plugin_dir()
        for name in ("manifest.json", "package.json", "plugin.py", "engine.py"):
            path = plugin_dir / name
            self.assertTrue(path.is_file(), f"missing required file: {path}")

    def test_package_validation_ok(self) -> None:
        plugin_dir = _require_plugin_dir()
        result = validate_plugin_package(plugin_dir)
        self.assertTrue(result.ok, result.errors)
        assert result.plugin_manifest is not None
        assert result.package_manifest is not None
        self.assertEqual(PLUGIN_ID, result.plugin_manifest.plugin_id)
        self.assertEqual("matting", result.plugin_manifest.plugin_type)
        self.assertEqual(SDK_VERSION, result.plugin_manifest.sdk_version)
        self.assertEqual(PACKAGE_FORMAT_VERSION, result.package_manifest.package_format)
        self.assertEqual(PLUGIN_ID, result.package_manifest.plugin_id)
        self.assertTrue(result.compatibility is not None and result.compatibility.compatible)

    def test_manifest_load_matches_contract_ids(self) -> None:
        plugin_dir = _require_plugin_dir()
        manifest = load_manifest(plugin_dir)
        self.assertEqual(PLUGIN_ID, manifest.plugin_id)
        self.assertEqual("matting", manifest.plugin_type)
        self.assertEqual(SDK_VERSION, manifest.sdk_version)
        self.assertTrue(len(manifest.capabilities) >= 1)


class BackgroundRemovalRegistrationContractTests(TestCase):
    """Registration + discovery contract."""

    def test_plugin_registration_and_provider_discovery(self) -> None:
        builtins = build_default_precision_extraction_registry()
        builtin_ids = {item.provider_id for item in builtins.list()}
        registry, infos = _register_plugin(
            extraction=build_default_precision_extraction_registry()
        )
        matching = [item for item in infos if item.plugin_id == PLUGIN_ID]
        self.assertEqual(1, len(matching), f"expected plugin {PLUGIN_ID} registered: {infos}")
        self.assertEqual("available", matching[0].availability, matching[0].failure_reason)
        self.assertTrue(registry.contains(PROVIDER_ID))
        descriptor = registry.get(PROVIDER_ID)
        self.assertEqual(PROVIDER_ID, descriptor.provider_id)
        self.assertEqual("local", descriptor.provider_kind)
        self.assertTrue(descriptor.capabilities.supports_binary_mask)
        self.assertTrue(descriptor.capabilities.supports_alpha_matting)
        # Additive: builtins preserved (ADR-005).
        self.assertTrue(builtin_ids.issubset({p.provider_id for p in registry.list()}))

    def test_availability_probe_reports_unavailable_without_model(self) -> None:
        registry, _infos = _register_plugin(
            extraction=build_default_precision_extraction_registry()
        )
        self.assertTrue(registry.contains(PROVIDER_ID))
        unavailable_config = ExtractionRuntimeConfig(
            selected_provider_id=PROVIDER_ID,
            matting_onnx_model_path="/nonexistent/nova_bg_removal_model.onnx",
            provider_options={"background_removal_force_unavailable": True},
        )
        descriptors = {
            item.provider_id: item for item in registry.list(unavailable_config)
        }
        self.assertIn(PROVIDER_ID, descriptors)
        self.assertEqual(
            "unavailable",
            descriptors[PROVIDER_ID].availability,
            "probe must mark provider unavailable when model/deps are missing "
            "or force_unavailable is set",
        )
        self.assertTrue(str(descriptors[PROVIDER_ID].availability_message).strip())

    def test_availability_probe_can_report_available(self) -> None:
        registry, _infos = _register_plugin(
            extraction=build_default_precision_extraction_registry()
        )
        available_config = ExtractionRuntimeConfig(
            selected_provider_id=PROVIDER_ID,
            provider_options={"background_removal_force_available": True},
        )
        descriptors = {
            item.provider_id: item for item in registry.list(available_config)
        }
        self.assertEqual("available", descriptors[PROVIDER_ID].availability)


class BackgroundRemovalMaskContractTests(TestCase):
    """Confirmed-mask mandatory + Mask Policy MP-1..MP-6."""

    def setUp(self) -> None:
        self.engine = _create_engine()

    def _request(
        self,
        *,
        width: int = 16,
        height: int = 16,
        mask: BinaryMask | None = None,
        rgb: bytes | None = None,
        provider_options: dict[str, Any] | None = None,
    ) -> PrecisionExtractionRequest:
        use_mask = mask if mask is not None else _square_mask(width, height)
        return PrecisionExtractionRequest(
            request_id=str(uuid4()),
            source_width=width,
            source_height=height,
            source_rgb=rgb if rgb is not None else _rgb(width, height),
            mask=use_mask,
            provider_options=dict(provider_options or {}),
        )

    def test_confirmed_mask_is_mandatory_on_success_path(self) -> None:
        """Valid non-empty confirmed mask is required for Success."""
        result = self.engine.extract(self._request())
        self.assertIsInstance(result, PrecisionExtractionSuccess)
        assert isinstance(result, PrecisionExtractionSuccess)
        self.assertEqual(PROVIDER_ID, result.provider_id)
        self.assertEqual(16 * 16 * 4, len(result.image.data))

    def test_mp1_dimension_mismatch_errors(self) -> None:
        result = self.engine.extract(
            self._request(width=16, height=16, mask=_square_mask(8, 8))
        )
        self.assertIsInstance(result, PrecisionExtractionError)
        assert isinstance(result, PrecisionExtractionError)
        self.assertIn(
            result.error_code,
            {"INVALID_REQUEST", "DIMENSION_MISMATCH", "MASK_SIZE_MISMATCH"},
        )

    def test_mp2_empty_mask_errors(self) -> None:
        result = self.engine.extract(self._request(mask=_empty_mask(16, 16)))
        self.assertIsInstance(result, PrecisionExtractionError)
        assert isinstance(result, PrecisionExtractionError)
        self.assertEqual("EMPTY_MASK", result.error_code)

    def test_mp3_alpha_outside_dilated_confirm_is_clamped(self) -> None:
        width = height = 24
        mask = _square_mask(width, height, margin=8)
        result = self.engine.extract(self._request(width=width, height=height, mask=mask))
        self.assertIsInstance(result, PrecisionExtractionSuccess)
        assert isinstance(result, PrecisionExtractionSuccess)
        allowed = _dilate_binary(mask, DEFAULT_MASK_DILATION_RADIUS)
        rgba = result.image.data
        for i in range(width * height):
            alpha = rgba[i * 4 + 3]
            if allowed[i] == 0:
                self.assertLessEqual(
                    alpha,
                    ALPHA_EPS,
                    f"MP-3 violated: alpha={alpha} outside dilated confirm at index {i}",
                )

    def test_mp4_known_interior_not_erased(self) -> None:
        width = height = 24
        mask = _square_mask(width, height, margin=6)
        result = self.engine.extract(
            self._request(
                width=width,
                height=height,
                mask=mask,
                provider_options={"mask_policy_preserve_interior": True},
            )
        )
        self.assertIsInstance(result, PrecisionExtractionSuccess)
        assert isinstance(result, PrecisionExtractionSuccess)
        interior = _erode_binary(mask, DEFAULT_MASK_DILATION_RADIUS)
        rgba = result.image.data
        interior_alphas = [
            rgba[i * 4 + 3] for i in range(width * height) if interior[i] == 255
        ]
        self.assertTrue(interior_alphas, "test fixture must yield interior pixels")
        self.assertGreaterEqual(min(interior_alphas), 200)

    def test_mp5_rgba_composites_source_rgb(self) -> None:
        width = height = 12
        r, g, b = 10, 20, 30
        rgb = _rgb(width, height, r=r, g=g, b=b)
        mask = _square_mask(width, height, margin=3)
        result = self.engine.extract(
            self._request(width=width, height=height, mask=mask, rgb=rgb)
        )
        self.assertIsInstance(result, PrecisionExtractionSuccess)
        assert isinstance(result, PrecisionExtractionSuccess)
        rgba = result.image.data
        for i in range(width * height):
            alpha = rgba[i * 4 + 3]
            if alpha < 250:
                continue
            self.assertEqual(r, rgba[i * 4 + 0])
            self.assertEqual(g, rgba[i * 4 + 1])
            self.assertEqual(b, rgba[i * 4 + 2])

    def test_mp6_diagnostics_record_mask_policy(self) -> None:
        result = self.engine.extract(self._request())
        self.assertIsInstance(result, PrecisionExtractionSuccess)
        assert isinstance(result, PrecisionExtractionSuccess)
        diagnostics = result.diagnostics
        self.assertIsInstance(diagnostics, dict)
        policy = diagnostics.get("mask_policy_id") or diagnostics.get("mask_policy")
        self.assertEqual(MASK_POLICY_ID, policy)
        self.assertIn("mask_dilation_radius", diagnostics)
        self.assertEqual(DEFAULT_MASK_DILATION_RADIUS, int(diagnostics["mask_dilation_radius"]))
        self.assertIn("mask_clamp_outside_applied", diagnostics)
        self.assertIsInstance(diagnostics["mask_clamp_outside_applied"], bool)
