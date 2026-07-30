import base64
import json
from urllib.request import Request

import numpy as np
import pytest

from nova_layer.adapters.capabilities.browser_depth_pose_http import (
    LocalDepthPoseHttpProvider,
)


def test_local_http_provider_posts_exact_rgb_and_labels() -> None:
    captured: dict[str, object] = {}

    def transport(request: Request, timeout: float, maximum_bytes: int) -> bytes:
        captured["url"] = request.full_url
        captured["timeout"] = timeout
        captured["maximum_bytes"] = maximum_bytes
        captured["payload"] = json.loads((request.data or b"").decode("utf-8"))
        return json.dumps({"status": "ok"}).encode("utf-8")

    provider = LocalDepthPoseHttpProvider(
        "http://127.0.0.1:3456/api/nova/depth-pose",
        timeout_seconds=5.0,
        transport=transport,
    )
    image = np.arange(18, dtype=np.uint8).reshape(2, 3, 3)

    response = provider(7, image, ("left_shoulder", "left_wrist"))

    assert response == {"status": "ok"}
    assert captured["url"] == "http://127.0.0.1:3456/api/nova/depth-pose"
    payload = captured["payload"]
    assert isinstance(payload, dict)
    assert payload["frame_number"] == 7
    assert payload["requested_labels"] == ["left_shoulder", "left_wrist"]
    assert base64.b64decode(payload["image"]["data"]) == image.tobytes()


def test_local_http_provider_rejects_remote_or_invalid_image() -> None:
    with pytest.raises(ValueError, match="local HTTP"):
        LocalDepthPoseHttpProvider("https://example.com/api")
    provider = LocalDepthPoseHttpProvider(
        "http://localhost:3456/api",
        transport=lambda request, timeout, maximum: b"{}",
    )
    with pytest.raises(ValueError, match="RGB uint8"):
        provider(0, np.zeros((4, 4), dtype=np.uint8), ())
