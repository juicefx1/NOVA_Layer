from __future__ import annotations

from pathlib import Path

import numpy as np
from numpy.typing import NDArray
from PySide6.QtGui import QImage

from nova_layer.adapters.persistence.safe_paths import (
    UnsafePackagePathError,
    resolve_within_root,
)


class PreviewStoreError(RuntimeError):
    pass


class PngPreviewStore:
    def save(self, package_path: Path, relative_path: str, rgba: NDArray[np.uint8]) -> Path:
        if rgba.dtype != np.uint8 or rgba.ndim != 3 or rgba.shape[2] != 4:
            raise PreviewStoreError("Extraction preview must be an RGBA uint8 image.")
        try:
            destination = resolve_within_root(package_path, relative_path)
        except UnsafePackagePathError as exc:
            raise PreviewStoreError(str(exc)) from exc
        destination.parent.mkdir(parents=True, exist_ok=True)
        contiguous = np.ascontiguousarray(rgba)
        height, width, channels = contiguous.shape
        image = QImage(
            contiguous.data,
            width,
            height,
            channels * width,
            QImage.Format.Format_RGBA8888,
        ).copy()
        if not image.save(str(destination)):
            raise PreviewStoreError(f"Could not save extraction preview: {destination}")
        return destination
