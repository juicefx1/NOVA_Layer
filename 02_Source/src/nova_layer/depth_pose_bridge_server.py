from __future__ import annotations

import argparse
import base64
import binascii
import json
import secrets
import threading
import uuid
from collections import deque
from dataclasses import dataclass, field
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from importlib.resources import files
from time import monotonic
from typing import Annotated, Any, cast
from urllib.parse import parse_qs, urlparse

from pydantic import BaseModel, ConfigDict, Field, model_validator

from nova_layer.adapters.capabilities.browser_depth_pose import DepthPoseBridgePayload

MAX_REQUEST_BYTES = 64 * 1024 * 1024
MAX_RESULT_BYTES = 4 * 1024 * 1024


class BridgeImage(BaseModel):
    model_config = ConfigDict(extra="forbid")

    encoding: Annotated[str, Field(pattern=r"^rgb8_base64$")]
    data: str


class DepthPoseRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Annotated[str, Field(pattern=r"^1\.0$")]
    frame_number: Annotated[int, Field(ge=0)]
    width: Annotated[int, Field(gt=0)]
    height: Annotated[int, Field(gt=0)]
    requested_labels: list[Annotated[str, Field(pattern=r"^[a-z][a-z0-9_]*$")]]
    image: BridgeImage

    @model_validator(mode="after")
    def validate_image_and_labels(self) -> DepthPoseRequest:
        if len(self.requested_labels) != len(set(self.requested_labels)):
            raise ValueError("requested labels must be unique")
        try:
            raw = base64.b64decode(self.image.data, validate=True)
        except (binascii.Error, ValueError) as exc:
            raise ValueError("image data must be valid base64") from exc
        if len(raw) != self.width * self.height * 3:
            raise ValueError("RGB8 image byte length does not match its dimensions")
        return self


@dataclass(slots=True)
class BridgeJob:
    id: str
    request: DepthPoseRequest
    completed: threading.Event = field(default_factory=threading.Event)
    result: DepthPoseBridgePayload | None = None
    error: str | None = None


class DepthPoseBroker:
    def __init__(self) -> None:
        self._condition = threading.Condition()
        self._pending: deque[BridgeJob] = deque()
        self._active: dict[str, BridgeJob] = {}
        self._last_worker_poll: float | None = None

    def submit(self, request: DepthPoseRequest, timeout: float) -> DepthPoseBridgePayload:
        job = BridgeJob(id=uuid.uuid4().hex, request=request)
        with self._condition:
            self._pending.append(job)
            self._active[job.id] = job
            self._condition.notify()
        if not job.completed.wait(timeout):
            with self._condition:
                self._active.pop(job.id, None)
                try:
                    self._pending.remove(job)
                except ValueError:
                    pass
            raise TimeoutError("no browser worker completed the depth/pose request")
        if job.error is not None:
            raise RuntimeError(job.error)
        if job.result is None:
            raise RuntimeError("browser worker completed without a result")
        return job.result

    def next_job(self, timeout: float) -> BridgeJob | None:
        with self._condition:
            self._last_worker_poll = monotonic()
            if not self._pending:
                self._condition.wait(timeout)
            return self._pending.popleft() if self._pending else None

    def health(self) -> dict[str, Any]:
        with self._condition:
            worker_connected = (
                self._last_worker_poll is not None and monotonic() - self._last_worker_poll <= 30.0
            )
            return {
                "status": "ready",
                "schema_version": "1.0",
                "worker_connected": worker_connected,
                "pending_jobs": len(self._pending),
                "active_jobs": len(self._active),
            }

    def complete(self, job_id: str, payload: dict[str, Any]) -> None:
        with self._condition:
            job = self._active.pop(job_id, None)
        if job is None:
            raise KeyError("unknown or expired bridge job")
        try:
            result = DepthPoseBridgePayload.model_validate(payload)
            if (
                result.frame_number != job.request.frame_number
                or result.width != job.request.width
                or result.height != job.request.height
            ):
                raise ValueError("worker result does not match the job frame and dimensions")
            unexpected = {joint.label for joint in result.joints} - set(
                job.request.requested_labels
            )
            if unexpected:
                raise ValueError(f"worker returned unrequested labels: {sorted(unexpected)}")
            job.result = result
        except Exception as exc:
            job.error = str(exc)
        finally:
            job.completed.set()


def make_handler(
    broker: DepthPoseBroker, token: str, inference_timeout: float
) -> type[BaseHTTPRequestHandler]:
    class Handler(BaseHTTPRequestHandler):
        server_version = "NOVA-DepthPose-Bridge/1.0"

        def _authorized(self) -> bool:
            query_token = parse_qs(urlparse(self.path).query).get("token", [""])[0]
            supplied = self.headers.get("X-NOVA-Bridge-Token", query_token)
            return secrets.compare_digest(supplied, token)

        def _json(self, status: HTTPStatus, payload: dict[str, Any]) -> None:
            encoded = json.dumps(payload, separators=(",", ":")).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(encoded)))
            self.send_header("Access-Control-Allow-Origin", "null")
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(encoded)

        def _asset(self, name: str, content_type: str) -> None:
            encoded = files("nova_layer.browser_worker").joinpath(name).read_bytes()
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(encoded)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(encoded)

        def _read_json(self, maximum: int) -> dict[str, Any]:
            try:
                length = int(self.headers.get("Content-Length", "0"))
            except ValueError as exc:
                raise ValueError("invalid Content-Length") from exc
            if length <= 0 or length > maximum:
                raise ValueError("request body size is invalid")
            decoded = json.loads(self.rfile.read(length))
            if not isinstance(decoded, dict):
                raise ValueError("request body must be a JSON object")
            return decoded

        def do_OPTIONS(self) -> None:  # noqa: N802
            self.send_response(HTTPStatus.NO_CONTENT)
            self.send_header("Access-Control-Allow-Origin", "null")
            self.send_header("Access-Control-Allow-Headers", "Content-Type,X-NOVA-Bridge-Token")
            self.send_header("Access-Control-Allow-Methods", "GET,POST,OPTIONS")
            self.end_headers()

        def do_GET(self) -> None:  # noqa: N802
            path = urlparse(self.path).path
            if path == "/health":
                self._json(HTTPStatus.OK, broker.health())
                return
            if path in {"/", "/worker"}:
                self._asset("index.html", "text/html; charset=utf-8")
                return
            if path == "/worker.js":
                self._asset("worker.js", "text/javascript; charset=utf-8")
                return
            if path == "/providers/movenet-depth-anything-v2.js":
                self._asset("movenet_depth_anything_v2.js", "text/javascript; charset=utf-8")
                return
            if not self._authorized():
                self._json(HTTPStatus.UNAUTHORIZED, {"error": "invalid bridge token"})
                return
            if path != "/api/worker/jobs/next":
                self._json(HTTPStatus.NOT_FOUND, {"error": "not found"})
                return
            job = broker.next_job(20.0)
            if job is None:
                self.send_response(HTTPStatus.NO_CONTENT)
                self.send_header("Access-Control-Allow-Origin", "null")
                self.end_headers()
                return
            self._json(
                HTTPStatus.OK,
                {"job_id": job.id, "request": job.request.model_dump(mode="json")},
            )

        def do_POST(self) -> None:  # noqa: N802
            if not self._authorized():
                self._json(HTTPStatus.UNAUTHORIZED, {"error": "invalid bridge token"})
                return
            path = urlparse(self.path).path
            try:
                if path == "/api/nova/depth-pose":
                    request = DepthPoseRequest.model_validate(self._read_json(MAX_REQUEST_BYTES))
                    result = broker.submit(request, inference_timeout)
                    self._json(HTTPStatus.OK, result.model_dump(mode="json"))
                    return
                prefix, suffix = "/api/worker/jobs/", "/result"
                if path.startswith(prefix) and path.endswith(suffix):
                    job_id = path[len(prefix) : -len(suffix)]
                    broker.complete(job_id, self._read_json(MAX_RESULT_BYTES))
                    self._json(HTTPStatus.OK, {"status": "accepted"})
                    return
                self._json(HTTPStatus.NOT_FOUND, {"error": "not found"})
            except TimeoutError as exc:
                self._json(HTTPStatus.GATEWAY_TIMEOUT, {"error": str(exc)})
            except KeyError as exc:
                self._json(HTTPStatus.NOT_FOUND, {"error": str(exc)})
            except Exception as exc:
                self._json(HTTPStatus.BAD_REQUEST, {"error": str(exc)})

        def log_message(self, format: str, *args: object) -> None:
            return

    return Handler


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the NOVA local Depth/Pose browser broker.")
    parser.add_argument("--port", type=int, default=3456)
    parser.add_argument("--token", default="", help="Shared local token; generated if omitted")
    parser.add_argument("--inference-timeout", type=float, default=30.0)
    args = parser.parse_args()
    if not 0 <= args.port <= 65535 or args.inference_timeout <= 0:
        parser.error("port and inference timeout must be valid positive values")
    token = args.token or secrets.token_urlsafe(24)
    server = ThreadingHTTPServer(
        ("127.0.0.1", args.port), make_handler(DepthPoseBroker(), token, args.inference_timeout)
    )
    host, port = cast(tuple[str, int], server.server_address)
    print(f"NOVA Depth/Pose bridge listening on http://{host}:{port}")
    print(f"Browser worker: http://{host}:{port}/worker?token={token}")
    print(f'NOVA_DEPTH_POSE_BRIDGE_URL="http://{host}:{port}/api/nova/depth-pose?token={token}"')
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
