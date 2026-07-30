from __future__ import annotations

from pathlib import Path
from typing import Any

from nova_layer.object_workflow.plugin_sdk.constants import (
    SUPPORTED_PLUGIN_TYPES,
    SUPPORTED_SDK_VERSIONS,
)
from nova_layer.object_workflow.plugin_sdk.errors import PluginValidationError
from nova_layer.object_workflow.plugin_sdk.manifest import PluginManifest, parse_manifest
from nova_layer.object_workflow.plugin_sdk.package.archive import (
    open_package,
    read_json_file,
    sha256_file,
)
from nova_layer.object_workflow.plugin_sdk.package.constants import (
    PACKAGE_MANIFEST_FILENAME,
    PLUGIN_MANIFEST_FILENAME,
    SUPPORTED_PACKAGE_FORMATS,
)
from nova_layer.object_workflow.plugin_sdk.package.errors import PluginPackageValidationError
from nova_layer.object_workflow.plugin_sdk.package.models import (
    PackageCompatibilityReport,
    PackageValidationResult,
    PluginPackageManifest,
)


def parse_package_manifest(
    raw: dict[str, Any],
    *,
    source_path: Path | None = None,
) -> PluginPackageManifest:
    package_format = _require_str(raw, "package_format")
    plugin_id = _require_str(raw, "plugin_id")
    version = _require_str(raw, "version")
    sdk_version = _require_str(raw, "sdk_version")
    display_name = str(raw.get("display_name", "")).strip()
    description = str(raw.get("description", "")).strip()
    author = str(raw.get("author", "")).strip()
    checksum = raw.get("checksum_sha256")
    checksum_sha256 = None if checksum in (None, "") else str(checksum).strip().lower()

    if package_format not in SUPPORTED_PACKAGE_FORMATS:
        raise PluginPackageValidationError(
            f"unsupported package_format: {package_format!r} "
            f"(supported: {sorted(SUPPORTED_PACKAGE_FORMATS)})",
            code="PLUGIN_PACKAGE_FORMAT_UNSUPPORTED",
        )
    if "/" in plugin_id or "\\" in plugin_id or ".." in plugin_id:
        raise PluginPackageValidationError(f"invalid package plugin_id: {plugin_id!r}")
    if checksum_sha256 is not None and len(checksum_sha256) != 64:
        raise PluginPackageValidationError(
            "checksum_sha256 must be a 64-character hex digest when provided",
            code="PLUGIN_PACKAGE_CHECKSUM_INVALID",
        )

    return PluginPackageManifest(
        package_format=package_format,
        plugin_id=plugin_id,
        version=version,
        sdk_version=sdk_version,
        display_name=display_name,
        description=description,
        author=author,
        checksum_sha256=checksum_sha256,
        source_path=source_path,
    )


def check_package_compatibility(
    package_manifest: PluginPackageManifest,
    plugin_manifest: PluginManifest,
) -> PackageCompatibilityReport:
    reasons: list[str] = []
    if package_manifest.package_format not in SUPPORTED_PACKAGE_FORMATS:
        reasons.append(
            f"unsupported package_format {package_manifest.package_format!r}"
        )
    if package_manifest.sdk_version not in SUPPORTED_SDK_VERSIONS:
        reasons.append(
            f"incompatible package sdk_version {package_manifest.sdk_version!r}"
        )
    if plugin_manifest.sdk_version not in SUPPORTED_SDK_VERSIONS:
        reasons.append(
            f"incompatible plugin sdk_version {plugin_manifest.sdk_version!r}"
        )
    if plugin_manifest.plugin_type not in SUPPORTED_PLUGIN_TYPES:
        reasons.append(f"unsupported plugin_type {plugin_manifest.plugin_type!r}")
    if package_manifest.plugin_id != plugin_manifest.plugin_id:
        reasons.append(
            "package.json plugin_id does not match manifest.json plugin_id"
        )
    if package_manifest.version != plugin_manifest.version:
        reasons.append("package.json version does not match manifest.json version")
    if package_manifest.sdk_version != plugin_manifest.sdk_version:
        reasons.append(
            "package.json sdk_version does not match manifest.json sdk_version"
        )
    return PackageCompatibilityReport(
        compatible=not reasons,
        reasons=tuple(reasons),
        sdk_version=plugin_manifest.sdk_version,
        package_format=package_manifest.package_format,
        plugin_type=plugin_manifest.plugin_type,
    )


def validate_plugin_package(path: Path | str) -> PackageValidationResult:
    """Validate package structure, manifests, filesystem entry, and compatibility."""
    package_path = Path(path).expanduser()
    errors: list[str] = []
    warnings: list[str] = []
    package_manifest: PluginPackageManifest | None = None
    plugin_manifest: PluginManifest | None = None
    compatibility: PackageCompatibilityReport | None = None
    opened = None
    try:
        opened = open_package(package_path)
        root = opened.root
        package_json = root / PACKAGE_MANIFEST_FILENAME
        plugin_json = root / PLUGIN_MANIFEST_FILENAME
        if not package_json.is_file():
            raise PluginPackageValidationError(
                f"missing {PACKAGE_MANIFEST_FILENAME}",
                code="PLUGIN_PACKAGE_MANIFEST_MISSING",
            )
        if not plugin_json.is_file():
            raise PluginPackageValidationError(
                f"missing {PLUGIN_MANIFEST_FILENAME}",
                code="PLUGIN_PACKAGE_PLUGIN_MANIFEST_MISSING",
            )

        package_manifest = parse_package_manifest(
            read_json_file(package_json),
            source_path=root,
        )
        try:
            plugin_manifest = parse_manifest(
                read_json_file(plugin_json),
                source_path=root,
            )
        except PluginValidationError as exc:
            raise PluginPackageValidationError(
                f"plugin manifest invalid: {exc.message}",
                code=exc.code,
            ) from exc

        entry = root / f"{plugin_manifest.entry_module}.py"
        entry_name = plugin_manifest.entry_module
        if (
            not entry_name
            or "/" in entry_name
            or "\\" in entry_name
            or ".." in entry_name
            or entry_name.startswith(".")
        ):
            raise PluginPackageValidationError(
                f"unsafe entry module name: {entry_name!r}",
                code="PLUGIN_PACKAGE_ENTRY_UNSAFE",
            )
        try:
            resolved_entry = entry.resolve()
            if not str(resolved_entry).startswith(str(root.resolve())):
                raise PluginPackageValidationError(
                    f"entry module escapes package root: {entry_name!r}",
                    code="PLUGIN_PACKAGE_ENTRY_UNSAFE",
                )
        except OSError as exc:
            raise PluginPackageValidationError(
                f"entry module is not resolvable: {entry_name!r}",
                code="PLUGIN_PACKAGE_ENTRY_UNSAFE",
            ) from exc
        if not entry.is_file():
            raise PluginPackageValidationError(
                f"entry module missing: {entry.name}",
                code="PLUGIN_PACKAGE_ENTRY_MISSING",
            )
        if entry.is_symlink():
            raise PluginPackageValidationError(
                f"entry module must not be a symbolic link: {entry.name}",
                code="PLUGIN_PACKAGE_SYMLINK_FORBIDDEN",
            )

        if package_path.is_file() and package_manifest.checksum_sha256:
            digest = sha256_file(package_path)
            if digest != package_manifest.checksum_sha256:
                raise PluginPackageValidationError(
                    "package checksum mismatch",
                    code="PLUGIN_PACKAGE_CHECKSUM_MISMATCH",
                )
        elif package_manifest.checksum_sha256 and package_path.is_dir():
            warnings.append(
                "checksum_sha256 is ignored for unpacked package directories"
            )

        compatibility = check_package_compatibility(package_manifest, plugin_manifest)
        if not compatibility.compatible:
            errors.extend(compatibility.reasons)
    except PluginPackageValidationError as exc:
        errors.append(f"{exc.code}: {exc.message}")
    except Exception as exc:  # noqa: BLE001
        errors.append(f"PLUGIN_PACKAGE_VALIDATION_ERROR: {exc}")
    finally:
        if opened is not None:
            opened.close()

    ok = not errors and compatibility is not None and compatibility.compatible
    return PackageValidationResult(
        ok=ok,
        package_path=package_path,
        package_manifest=package_manifest,
        plugin_manifest=plugin_manifest,
        compatibility=compatibility,
        errors=tuple(errors),
        warnings=tuple(warnings),
    )


def _require_str(raw: dict[str, Any], key: str) -> str:
    value = raw.get(key)
    if not isinstance(value, str) or not value.strip():
        raise PluginPackageValidationError(
            f"package field {key!r} must be a non-empty string"
        )
    return value.strip()
