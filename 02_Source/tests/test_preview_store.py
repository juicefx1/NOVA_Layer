from pathlib import Path

import numpy as np
from PySide6.QtGui import QImage

from nova_layer.adapters.persistence.preview_store import PngPreviewStore


def test_preview_store_preserves_png_alpha(tmp_path: Path) -> None:
    rgba = np.zeros((5, 7, 4), dtype=np.uint8)
    rgba[:, :, :3] = (20, 40, 60)
    rgba[1:4, 2:6, 3] = 173

    path = PngPreviewStore().save(tmp_path, "previews/test.png", rgba)
    restored = QImage(str(path)).convertToFormat(QImage.Format.Format_RGBA8888)
    stride = restored.bytesPerLine()
    raw = np.frombuffer(restored.bits(), dtype=np.uint8, count=restored.height() * stride)
    pixels = raw.reshape(restored.height(), stride)[:, : restored.width() * 4]
    pixels = pixels.reshape(restored.height(), restored.width(), 4)

    assert np.array_equal(pixels[:, :, 3], rgba[:, :, 3])
