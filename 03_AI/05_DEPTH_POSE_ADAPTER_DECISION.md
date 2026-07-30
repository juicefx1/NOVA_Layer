# Depth and Pose Adapter Decision

Date: 2026-07-25  
Status: Exact repository inspected; integration blocked on license and machine-readable output

## Requested Repository Name

The exact repository was supplied and inspected at commit
`41d376cf6f81001cfe540287428442849cb3d797`:

- Repository: <https://github.com/openerai/depth-openpose-extractor>
- Browser application: static HTML/JavaScript served by a minimal Node.js server
- Repository license: **not declared**; no license file was present at the inspected commit
- Repository activity at inspection: 7 commits, no releases

## Actual Runtime Architecture

The browser path performs three separate operations:

- Depth Anything V2 Small through Transformers.js, preferring WebGPU and falling back to WASM;
- MediaPipe PoseLandmarker with 33 landmarks converted to a rendered COCO/OpenPose-18 skeleton;
- optional MediaPipe hand, face, and person segmentation results.

It downloads JavaScript libraries and model assets from jsDelivr, Hugging Face, and Google at
runtime. The tool exports rendered depth, pose, and mask **videos**. It does not expose the raw pose
landmarks, visibility confidence, raw depth array, or per-joint sampled depth through JSON or an
HTTP API.

The included ComfyUI workflow is a configuration file, not an inference implementation. It depends
on `comfyui_controlnet_aux`, VideoHelperSuite, LayerStyle, DWPose assets, and Depth Anything V2.

## Important Interpretation

The repository does not provide one model that converts a depth map directly into a semantic
skeleton. It runs separate depth and pose estimators. NOVA should therefore treat them as two
pieces of Evidence:

1. a pose detector supplies semantic 2D joints and per-joint confidence;
2. a depth estimator supplies depth values and local depth confidence;
3. NOVA matches those results to the artist's rough labeled skeleton;
4. Artist-Guided Skeleton Fusion produces a reviewable proposal.

This is consistent with NOVA's current `SkeletonDetectionCapability` and fusion review gate.

## Integration Decision

Do not copy or vendor `app.js` or the ComfyUI workflow into NOVA at this time. The missing repository
license does not grant redistribution or derivative-work permission. Its rendered-video output is
also insufficient for NOVA's semantic joint and confidence contract.

Preferred integration order:

1. Ask the repository owner to add an explicit license.
2. Request or contribute a machine-readable per-frame export containing MediaPipe landmarks,
   visibility, image dimensions, and the raw normalized depth array or per-joint depth samples.
3. Prefer a local HTTP/JSON bridge so the browser/WebGPU runtime remains isolated from PySide and
   NOVA's pinned Python dependencies.
4. Convert COCO-18/MediaPipe output to normalized semantic joints; BODY_25-only joints must remain
   unmatched unless a higher-quality DWPose path supplies them.
5. Validate the result through NOVA's normal skeleton-detection contract guard.
6. Enable it through `NOVA_DEPTH_POSE_BRIDGE_URL=http://127.0.0.1:<port>/<path>` and benchmark on
   the M1 Pro.

NOVA now implements both sides of its transport boundary: the versioned
`contracts/depth_pose_request_v1.schema.json` request,
`contracts/depth_pose_frame_v1.schema.json` response, a loopback-only HTTP client, and
`BrowserDepthPoseDetectionCapability`. Automatic selection is available through
`NOVA_DEPTH_POSE_BRIDGE_URL`; an existing `NOVA_SKELETON_DETECTOR` setting takes precedence. The
supplied repository still needs an explicitly licensed sender/local endpoint that accepts and
emits these payloads.

The HTTP client rejects non-loopback hosts, requires RGB8 input, applies a 30-second timeout, and
caps responses at 4 MiB. This avoids silently uploading source footage to a remote service and
places a hard bound on malformed responses.

NOVA also ships the model-free `nova-depth-pose-bridge` broker. It binds only to `127.0.0.1`,
generates a random shared token by default, validates decoded RGB byte length, and coordinates one
NOVA request with one browser worker result. The worker uses long polling and may only return
requested semantic labels with matching frame metadata. This server is NOVA-owned infrastructure;
it deliberately contains no code or model assets from the inspected repository.

## macOS Strategy

- Phase A: verify the unmodified browser application in current Chrome using WebGPU, with WASM as
  its documented fallback. Node.js 24.16.0 is already available on the development Mac.
- Phase B: add a licensed JSON bridge and measure WebGPU pose/depth latency independently from SAM.
- Phase C: evaluate the ComfyUI DWPose + Depth Anything V2 path only as a separate optional runtime;
  the Large depth checkpoint alone is documented by the workflow as approximately 1.34 GB.
- Keep the current deterministic Mock as a development fallback.

The official CMU OpenPose runtime is not the preferred embedded path: it is an older C++/Caffe
stack, its documented free-use terms are non-commercial, and it does not provide the desired
PyTorch MPS integration. BODY_25 names remain useful solely as an interoperability schema.

## Licensing Gate

The inspected repository has no declared license, so NOVA cannot copy, modify, redistribute, or
ship its code based only on public GitHub visibility. Before integration, record and approve:

- repository commit and an explicit owner-provided license;
- pose model code and weight licenses;
- depth model code and weight licenses;
- redistribution permissions;
- required notices and attribution;
- commercial-use compatibility.

No external code or weights should enter a NOVA release candidate until this gate passes.
