import base64
import json
import threading
from http.server import ThreadingHTTPServer
from importlib.resources import files
from urllib.request import Request, urlopen

import pytest
from pydantic import ValidationError

from nova_layer.depth_pose_bridge_server import (
    DepthPoseBroker,
    DepthPoseRequest,
    make_handler,
)


def request_payload() -> dict[str, object]:
    return {
        "schema_version": "1.0",
        "frame_number": 12,
        "width": 2,
        "height": 1,
        "requested_labels": ["left_shoulder"],
        "image": {
            "encoding": "rgb8_base64",
            "data": base64.b64encode(bytes(range(6))).decode("ascii"),
        },
    }


def result_payload() -> dict[str, object]:
    return {
        "schema_version": "1.0",
        "frame_number": 12,
        "width": 2,
        "height": 1,
        "pose_model": "licensed-pose",
        "depth_model": "licensed-depth",
        "runtime": "browser-webgpu",
        "joints": [
            {
                "label": "left_shoulder",
                "x": 0.25,
                "y": 0.5,
                "confidence": 0.9,
                "depth_confidence": 0.8,
                "depth": 0.4,
            }
        ],
    }


def test_request_rejects_wrong_rgb_byte_length() -> None:
    payload = request_payload()
    payload["width"] = 3

    with pytest.raises(ValidationError, match="byte length"):
        DepthPoseRequest.model_validate(payload)


def test_browser_worker_assets_are_packaged() -> None:
    worker_root = files("nova_layer.browser_worker")

    assert "NOVA Depth/Pose Worker" in worker_root.joinpath("index.html").read_text()
    script = worker_root.joinpath("worker.js").read_text()
    assert "createDepthPoseRuntime" in script
    assert "/api/worker/jobs/next" in script
    provider = worker_root.joinpath("movenet_depth_anything_v2.js").read_text()
    assert "SINGLEPOSE_LIGHTNING" in provider
    assert "onnx-community/depth-anything-v2-small" in provider


def test_broker_round_trip() -> None:
    broker = DepthPoseBroker()
    request = DepthPoseRequest.model_validate(request_payload())
    output: list[object] = []

    def submit() -> None:
        output.append(broker.submit(request, 1.0))

    thread = threading.Thread(target=submit)
    thread.start()
    job = broker.next_job(1.0)
    assert job is not None
    assert broker.health()["worker_connected"] is True
    broker.complete(job.id, result_payload())
    thread.join(timeout=1.0)

    assert not thread.is_alive()
    assert output[0].joints[0].label == "left_shoulder"  # type: ignore[union-attr]


def test_broker_rejects_unrequested_joint() -> None:
    broker = DepthPoseBroker()
    request = DepthPoseRequest.model_validate(request_payload())
    error: list[Exception] = []

    def submit() -> None:
        try:
            broker.submit(request, 1.0)
        except Exception as exc:
            error.append(exc)

    thread = threading.Thread(target=submit)
    thread.start()
    job = broker.next_job(1.0)
    assert job is not None
    payload = result_payload()
    payload["joints"][0]["label"] = "right_shoulder"  # type: ignore[index]
    broker.complete(job.id, payload)
    thread.join(timeout=1.0)

    assert error
    assert "unrequested labels" in str(error[0])


def test_http_broker_round_trip() -> None:
    token = "test-token"
    try:
        server = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(DepthPoseBroker(), token, 1.0))
    except PermissionError:
        pytest.skip("loopback sockets are disabled in this test sandbox")
    server_thread = threading.Thread(target=server.serve_forever)
    server_thread.start()
    host, port = server.server_address
    result: list[dict[str, object]] = []

    def post_nova_request() -> None:
        request = Request(
            f"http://{host}:{port}/api/nova/depth-pose",
            data=json.dumps(request_payload()).encode(),
            headers={"Content-Type": "application/json", "X-NOVA-Bridge-Token": token},
            method="POST",
        )
        with urlopen(request, timeout=2.0) as response:
            result.append(json.load(response))

    nova_thread = threading.Thread(target=post_nova_request)
    nova_thread.start()
    worker_request = Request(
        f"http://{host}:{port}/api/worker/jobs/next",
        headers={"X-NOVA-Bridge-Token": token},
    )
    with urlopen(worker_request, timeout=2.0) as response:
        job = json.load(response)
    completion_request = Request(
        f"http://{host}:{port}/api/worker/jobs/{job['job_id']}/result",
        data=json.dumps(result_payload()).encode(),
        headers={"Content-Type": "application/json", "X-NOVA-Bridge-Token": token},
        method="POST",
    )
    with urlopen(completion_request, timeout=2.0) as response:
        assert json.load(response)["status"] == "accepted"
    nova_thread.join(timeout=2.0)
    server.shutdown()
    server.server_close()
    server_thread.join(timeout=2.0)

    assert result[0]["pose_model"] == "licensed-pose"
