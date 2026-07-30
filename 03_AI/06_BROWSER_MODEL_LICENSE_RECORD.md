# Browser Model License Record

Date reviewed: 2026-07-25

## Selected development configuration

- Pose runtime: TensorFlow.js pose-detection 2.1.3, Apache-2.0
- Pose model: MoveNet SinglePose Lightning, 17 COCO semantic keypoints
- Depth runtime: Transformers.js 3.7.2, Apache-2.0
- Depth model: `onnx-community/depth-anything-v2-small`, Apache-2.0 model card; derived from
  `depth-anything/Depth-Anything-V2-Small`, which the upstream project explicitly identifies as
  Apache-2.0

The Base, Large, and Giant Depth Anything V2 variants are excluded because upstream identifies
them as CC-BY-NC-4.0. This record is an engineering gate, not legal advice. Before public or
commercial distribution, archive exact package notices, model-card revisions, weight hashes, and
the outcome of counsel/owner review. An upstream question about training-dataset commercial risk
for the Small checkpoint remained open at review time, so release redistribution remains blocked.

## Runtime behavior

The provider is NOVA-authored glue code. It downloads pinned JavaScript packages and model assets
only after the artist presses **Load provider and start**. Depth prefers WebGPU and falls back to
the Transformers.js default WASM runtime. MoveNet prefers TensorFlow.js WebGL and falls back to
CPU. No third-party source or weight is embedded in the NOVA repository.

## Development runtime verification

Verified on 2026-07-25 on the development Mac with a generated 64×64 RGB frame:

- provider initialization completed;
- runtime reported `browser-webgpu+tfjs-webgl`;
- NOVA submitted frame 7 through the authenticated loopback HTTP client;
- the browser ran both pose and depth inference and returned Schema 1.0;
- frame number and dimensions matched and the broker accepted the result;
- no human was present in the synthetic rectangle, so zero detected joints was expected;
- ONNX Runtime reported that shape-related nodes were assigned to CPU, a performance warning rather
  than an inference failure.

This verifies transport and runtime compatibility. Accuracy, per-joint depth quality, real-footage
latency, and temporal stability still require the controlled footage benchmark.
