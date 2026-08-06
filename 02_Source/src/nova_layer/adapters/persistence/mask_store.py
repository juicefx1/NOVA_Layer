from __future__ import annotations

from pathlib import Path

import numpy as np
from numpy.typing import NDArray
from PySide6.QtGui import QImage

from nova_layer.adapters.persistence.safe_paths import (
    UnsafePackagePathError,
    resolve_within_root,
)


class MaskStoreError(RuntimeError):
    pass


class PngMaskStore:
    def save(self, package_path: Path, relative_path: str, mask: NDArray[np.uint8]) -> Path:
        try:
            destination = resolve_within_root(package_path, relative_path)
        except UnsafePackagePathError as exc:
            raise MaskStoreError(str(exc)) from exc
        destination.parent.mkdir(parents=True, exist_ok=True)
        contiguous = np.ascontiguousarray(mask)
        height, width = contiguous.shape
        image = QImage(
            contiguous.data,
            width,
            height,
            width,
            QImage.Format.Format_Grayscale8,
        ).copy()
        if not image.save(str(destination)):
            raise MaskStoreError(f"Could not save mask: {destination}")
        return destination

    def load(self, package_path: Path, relative_path: str) -> NDArray[np.uint8]:
        try:
            source = resolve_within_root(
                package_path,
                relative_path,
                must_exist=True,
                expect="file",
            )
        except UnsafePackagePathError as exc:
            raise MaskStoreError(str(exc)) from exc
        image = QImage(str(source))
        if image.isNull():
            raise MaskStoreError(f"Could not load mask: {source}")
        grayscale = image.convertToFormat(QImage.Format.Format_Grayscale8)
        height, width = grayscale.height(), grayscale.width()
        stride = grayscale.bytesPerLine()
        data = np.frombuffer(grayscale.bits(), dtype=np.uint8, count=height * stride)
        return data.reshape(height, stride)[:, :width].copy()
