import numpy as np

from nova_layer.app.preview_extraction import compose_rgba


def test_compose_rgba_preserves_rgb_and_uses_mask_as_alpha() -> None:
    frame = np.full((4, 6, 3), [10, 20, 30], dtype=np.uint8)
    mask = np.zeros((4, 6), dtype=np.uint8)
    mask[1:3, 2:5] = 200

    rgba = compose_rgba(frame, mask)

    assert rgba.shape == (4, 6, 4)
    assert np.array_equal(rgba[:, :, :3], frame)
    assert np.array_equal(rgba[:, :, 3], mask)
