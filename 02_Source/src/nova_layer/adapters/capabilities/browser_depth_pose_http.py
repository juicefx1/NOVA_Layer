from __future__ import annotations

import base64
import json
from collections.abc import Callable
from typing import Any, cast
from urllib.parse import urlparse
from urllib.request import Request, urlopen

import numpy as np
from numpy.typing import NDArray

Transport = Callable[[Request, float, int], bytes]


def _default_transport(request: Request, timeout: float, maximum_bytes: int) -> bytes:
    with urlopen(request, timeout=timeout) as response:  # noqa: S310 - URL is loopback-validated
        payload = cast(bytes, response.read(maximum_bytes + 1))
    if len(payload) > maximum_bytes:
        raise ValueError("depth/pose bridge response exceeds the configured size limit")
    return payload


class LocalDepthPoseHttpProvider:
    """POST RGB frames to a loopback-only licensed browser bridge."""

    def __init__(
        self,
        endpoint: str,
        *,
        timeout_seconds: float = 30.0,
        maximum_response_bytes: int = 4 * 1024 * 1024,
        transport: Transport | None = None,
    ) -> None:
        parsed = urlparse(endpoint)
        if parsed.scheme != "http" or parsed.hostname not in {"127.0.0.1", "localhost", "::1"}:
            raise ValueError("depth/pose bridge endpoint must be a local HTTP address")
        if timeout_seconds <= 0 or maximum_response_bytes <= 0:
            raise ValueError("bridge timeout and response limit must be positive")
        self.endpoint = endpoint
        self.timeout_seconds = timeout_seconds
        self.maximum_response_bytes = maximum_response_bytes
        self._transport = transport or _default_transport

    def __call__(
        self,
        frame_number: int,
        image: NDArray[np.uint8],
        labels: tuple[str, ...],
    ) -> dict[str, Any]:
        if image.ndim != 3 or image.shape[2] != 3 or image.dtype != np.uint8:
            raise ValueError("bridge input must be an RGB uint8 image")
        contiguous = np.ascontiguousarray(image)
        height, width = contiguous.shape[:2]
        request_payload = {
            "schema_version": "1.0",
            "frame_number": frame_number,
            "width": width,
            "height": height,
            "requested_labels": list(labels),
            "image": {
                "encoding": "rgb8_base64",
                "data": base64.b64encode(contiguous.tobytes()).decode("ascii"),
            },
        }
        request = Request(
            self.endpoint,
            data=json.dumps(request_payload, separators=(",", ":")).encode("utf-8"),
            headers={"Content-Type": "application/json", "Accept": "application/json"},
            method="POST",
        )
        raw = self._transport(
            request,
            self.timeout_seconds,
            self.maximum_response_bytes,
        )
        decoded = json.loads(raw.decode("utf-8"))
        if not isinstance(decoded, dict):
            raise ValueError("depth/pose bridge response must be a JSON object")
        return decoded
