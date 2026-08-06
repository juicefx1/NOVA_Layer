# NOVA Layer Phase 1 Source

This directory contains the executable Phase 1 vertical slice.

## Current Status

Implemented:

- Versioned Project, Sequence, Shot, Smart Layer, and Object Identity models
- Artist Intent and normalized guidance models
- Evidence, reasoning, frame-result, validation, lifecycle, and maturity models
- Model-independent segmentation and temporal propagation ports
- Deterministic mock capability adapters
- Atomic JSON `.nova` project save and restore
- Domain validation and identity-persistence tests
- PySide6 Welcome screen
- Create Project and Open Project flows
- Initial Workspace shell and project status
- PyAV media inspection and RGB frame decoding
- Timeline frame navigation
- Shot Range and Master Frame editing with project persistence
- Positive and negative point Artist Guidance
- Bounding Region Artist Guidance
- Artist-drawn Skeleton Joint and Bone Guidance
- Joint snapping, normalized persistence, and skeleton-only hypothesis generation
- Model-independent temporal Skeleton Tracking capability and per-frame pose observations
- Cyan tracked-pose overlays during timeline navigation
- Mask and skeleton confidence fusion for temporal Object Identity decisions
- Timeline hover details for fused identity and skeleton confidence
- Optional external skeleton-tracking adapter loading with validated safe fallback
- Persistent artist skeleton-correction keyframes with tracking override protection
- Timeline-frame Correct Pose mode with draggable joints and explicit Save Pose commit
- Magenta correction-keyframe timeline markers, navigation, tooltip, and count summary
- Confirmed correction removal with exact restoration of the replaced model observation
- Multi-anchor skeleton propagation from Master and nearest artist-correction keyframes
- Cancellable skeleton-only retracking without rerunning SAM mask propagation
- Validated semantic joint labels with in-viewer editing and adapter mapping
- NOVA-authored neutral BODY_25 interoperability preset with 25 labels and 24 bones
- Artist-guided skeleton fusion candidates with confidence/depth weighting and review
- Background Auto Fuse Pose workflow through a model-independent detection capability
- Environment-selected external Depth/pose detector with semantic result validation
- Versioned browser Depth/Pose JSON bridge contract and strict conversion adapter
- Resolution-independent normalized guidance persistence
- Automatic first Smart Layer creation in Hypothesis maturity
- Deterministic Object Hypothesis mask generation
- Candidate mask overlay with confidence
- Accept, Reject, and Refine review flow
- Evidence and Reasoning history for artist confirmation
- Start / Master / End comparison dialog
- Per-frame Accept and Correction Required decisions
- Validated maturity only after all three positions are accepted
- Per-frame correction guidance dialog
- Direction-local correction recomputation and Smart Layer version update
- High-priority artist correction Evidence
- Background frame decoding through Qt workers
- Latest-request-wins timeline behavior
- 45 ms scrub debounce and bounded LRU frame cache
- Generic cancellable background processing jobs
- Propagation progress, cancellation, completion, and failure states
- Commit-on-completion policy that discards partial automatic results
- Missing and changed source-media detection on project open
- Explicit media relink with fingerprint and Shot Range validation
- Pre-save recovery journal for every authoritative state update
- Explicit Restore or Discard workflow after interrupted saves
- Ordered project schema migration registry
- Non-destructive legacy loading and safe future-schema rejection
- Startup diagnostics for runtime, UI, media, persistence, and AI capabilities
- Explicit Mock Mode warnings without treating missing model weights as app failure
- Phase 1 acceptance runner with independent P1-AT-001 through P1-AT-009 evidence
- Machine-readable JSON and reviewable Markdown acceptance reports
- Protected Smart Layer render versions with persisted protection state
- Checksum-based comparison between consecutive render versions
- Transactional render-version deletion with protected-version blocking
- Monotonic render numbering that never reuses a deleted version
- Render audit details with source Smart Layer version, storage, and live integrity status
- Manifest-driven real-footage segmentation benchmark with IoU, precision, and recall
- Validated Master Frame export into an appendable benchmark dataset
- Workspace benchmark-case export for fully validated Smart Layers
- Real interactive-segmentation model evaluation on Apple Silicon MPS
- SAM 2.1 Hiera Small baseline with Hiera Tiny fallback and Mock Mode safety
- Non-blocking SAM hypothesis generation with commit-on-completion protection
- Content-aware SAM image-embedding reuse for repeated guidance on the same frame
- SAM 2.1 Video Predictor adapter with forward and reverse Master Mask propagation
- Reproducible procedural video benchmarks and NOVA temporal confidence
- Persistent Object Identity lifecycle observations with timeline markers
- Draggable Shot Range and Master Frame timeline handles
- Transparent RGBA extraction previews and versioned full-Shot Smart Layer renders
- Atomic RGBA PNG sequence export with per-frame SHA-256 integrity verification
- Protected render-version controls and checksum comparison in the Workspace
- Authenticated local Depth/Pose browser bridge, worker, and diagnostics
- Human-reviewed Depth/Pose benchmark, temporal gates, and regression comparison
- Project and Workspace Pose QA export into Depth/Pose datasets
- Deterministic Depth/Pose smoke suite without real footage
- Production Smart Layer export as PNG sequence, OpenEXR half-float RGBA, and RGBA QuickTime
- Headless host-session foundation (`nova-host-session`) for future DCC adapters
- Production-ready maturity promotion after validated frames and Smart Layer renders

Not yet implemented:

- Full host DCC plug-ins (Nuke / After Effects / Resolve UI panels)

In progress:

- Headless host-session API for DCC and automation adapters
- Licensed real-footage Depth/Pose accuracy and latency measurement
- Real-footage segmentation quality dataset acquisition and promotion
- Browser provider redistribution license gate for commercial release

## Development Environment

The project requires Python 3.12 or newer. Do not use the macOS system Python.

After creating and activating a Python 3.12 virtual environment:

```bash
python -m pip install -e '.[dev]'
pytest
```

Editable installation provides these official commands:

- `nova-layer`
- `nova-acceptance`
- `nova-model-preflight`
- `nova-video-benchmark`
- `nova-real-benchmark`
- `nova-dataset-export`
- `nova-dataset-review`
- `nova-review-assets`
- `nova-benchmark-compare`
- `nova-baseline-promote`
- `nova-baseline-activate`
- `nova-release-verify`
- `nova-release-candidate`
- `nova-release-audit`
- `nova-install-smoke`
- `nova-skeleton-check`
- `nova-depth-pose-bridge`
- `nova-depth-pose-benchmark`
- `nova-depth-pose-review`
- `nova-depth-pose-review-assets`
- `nova-depth-pose-export`
- `nova-depth-pose-compare`
- `nova-depth-pose-smoke`
- `nova-export-render`
- `nova-host-session`

The Hatch metadata explicitly permits the pinned SAM-2 Git reference in the optional AI group,
so both editable and wheel metadata generation remain valid.

Build and verify a release Wheel:

```bash
python -m pip wheel . --no-deps --wheel-dir ../07_Build/wheels
nova-release-verify ../07_Build/wheels/nova_layer-0.1.0-py3-none-any.whl \
  --report ../07_Build/reports/nova_layer-0.1.0-wheel.json
```

Verification checks package metadata, RECORD, all declared console commands, artifact SHA-256,
and confirms that `.pt`, `.pth`, or `.ckpt` model weights are not embedded.

Seal a release candidate only after Wheel and Phase 1 acceptance verification:

```bash
nova-release-candidate \
  ../07_Build/wheels/nova_layer-1.0.0rc1-py3-none-any.whl \
  ../07_Build/reports/nova_layer-1.0.0rc1-wheel.json \
  ../07_Build/reports/nova_layer-1.0.0rc1-install-smoke.json \
  ../06_Test/reports/phase1_acceptance_latest.json \
  --release-root ../08_Release
```


The release directory is content-addressed and immutable. A format-v2 candidate requires a valid
Wheel report, a passing installation-smoke report bound to the same Wheel SHA-256, and fully
passing acceptance evidence. Its manifest records every included file's name, role, size, and
SHA-256; partial or failed assembly is discarded.

Re-audit a sealed candidate at any later time:

```bash
nova-release-audit ../08_Release/nova-layer-0.1.1-2a60a698fdc3
```

The audit detects missing, unexpected, resized, or checksum-mismatched files; reopens and verifies
the embedded Wheel; and confirms that acceptance remains fully passing. Historical candidates use
the command inventory stored in their own Wheel report, so newer CLI additions do not invalidate
an older immutable release.

Smoke-test the installed Wheel in an isolated temporary target:

```bash
nova-install-smoke ../07_Build/wheels/nova_layer-1.0.0rc1-py3-none-any.whl \
  --report ../07_Build/reports/nova_layer-1.0.0rc1-install-smoke.json
```


The smoke test installs only the target Wheel, confirms imports resolve from that installation,
runs `--help` for every non-GUI command declared inside that exact Wheel, and imports the GUI entry
module. Historical Wheels are tested against their own entry-point inventory.

Desktop dependencies can be installed separately:

```bash
python -m pip install -e '.[desktop,dev]'
```

The desktop extra includes OpenEXR, Pillow, PySide6, PyAV, and NumPy for the Workspace
GUI and production Smart Layer export (PNG sequence, OpenEXR Current Render Look,
OpenEXR Scene Linear, and lossless RGBA QuickTime).

Scene Linear (`scene_openexr_sequence`) additionally requires OpenImageIO for EXR
scene-float decode. Where PyPI wheels exist:

```bash
python -m pip install -e '.[desktop,oiio]'
```

On hosts without OpenImageIO wheels (common on macOS), install OpenImageIO via conda
or the system package manager so `import OpenImageIO` succeeds, then use
`nova-layer[desktop]`. OCIO Display/View tooling is optional via `.[color]`.

```bash
nova-export-render MyProject.nova --output ~/Exports --format openexr_sequence --version 1
nova-export-render MyProject.nova --output ~/Exports --format scene_openexr_sequence --version 1
nova-export-render MyProject.nova --output ~/Exports --format rgba_mov --version 1
nova-export-render MyProject.nova --output ~/Exports --format png_sequence --version 1
```

Workspace **Export Render…** offers the same formats after integrity verification succeeds. Each
export writes an atomic package directory containing the media and a standalone `manifest.json`.

Headless host automation uses the Qt-free session API:

```bash
nova-host-session MyProject.nova status
nova-host-session MyProject.nova export-render --output ~/Exports --format openexr_sequence --version 1
```

`status` prints a JSON snapshot (`host_api_version` 1.1) for DCC adapters, including media link
state and production-ready eligibility blockers.

```bash
nova-host-session MyProject.nova validate-media
nova-host-session MyProject.nova relink /path/to/footage.mov --accept-changed
nova-host-session MyProject.nova promote-production-ready
nova-host-session MyProject.nova menu-nuke
```

Declarative Nuke / After Effects menu maps ship as adapter skeletons. Full in-host UI panels are
not packaged yet; adapters should wrap `nova_layer.host.HeadlessHostSession`.

AI dependencies remain optional:

```bash
python -m pip install -e '.[ai]'
```

Model weights are not part of the repository and must not be committed.

The desktop app automatically selects the local SAM 2.1 checkpoint when MPS is available.
Set `NOVA_AI_MODE=mock` to force deterministic development mode, or
`NOVA_SAM2_CHECKPOINT=/absolute/path/model.pt` to use a different checkpoint.

Generate the current machine's model-evaluation preflight report with:

```bash
python -m nova_layer.model_evaluation
```

Run the labeled real-footage segmentation benchmark with:

```bash
python -m nova_layer.real_footage_benchmark \
  ../06_Test/datasets/real_footage_manifest.json \
  --output ../06_Test/reports
```

Copy `06_Test/datasets/real_footage_manifest.example.json`, then replace its media and
ground-truth paths with licensed local assets. Paths are resolved relative to the manifest.
Mock Mode is rejected unless `--allow-mock` is explicitly supplied, preventing accidental
quality reports from being generated with the deterministic development adapter.

Export an artist-validated Master Frame from a `.nova` project into the dataset:

```bash
python -m nova_layer.benchmark_dataset \
  /path/to/project.nova \
  --output ../06_Test/datasets/representative_shots \
  --case-id human-closeup-01
```

The builder copies only the accepted mask, references the original linked media, preserves
normalized Artist Guidance, and records the source project, Shot, Smart Layer, and layer version.
Exported masks remain artist-reviewed candidates; production ground-truth QA is still required.
The same export is available from the Workspace through **Add Benchmark Case** after the Smart
Layer reaches Validated maturity. The artist chooses a dataset directory and case ID; successful
export is reported in the Workspace status bar.

After a human edge and identity review, record the QA decision:

```bash
python -m nova_layer.benchmark_review \
  ../06_Test/datasets/representative_shots/real_footage_manifest.json \
  human-closeup-01 \
  --status approved \
  --reviewer "Artist Name" \
  --notes "Hair and motion-blur edges checked at 200%."
```

The quality benchmark accepts only `approved` annotations. `--allow-unreviewed` exists solely
for dataset-pipeline development and must not be used for model-quality decisions.

Generate a visual QA package before recording review decisions:

```bash
python -m nova_layer.benchmark_review_assets \
  ../06_Test/datasets/representative_shots/real_footage_manifest.json \
  --output ../06_Test/datasets/representative_shots/review-v1
```

Open the generated `index.html` to compare the decoded source frame, red Ground Truth overlay,
and binary mask for every case. Output directories are immutable; use a new review directory for
revised annotations.

Approval records the Ground Truth PNG's SHA-256 digest. If that mask changes afterward, the
benchmark refuses to load the case until a reviewer inspects and approves the revised annotation.
The source-media fingerprint from the `.nova` project is locked into the same review record and
checked again after media inspection, preventing replaced or re-encoded footage from silently
using an annotation created for different pixels.
Every approved or rejected decision is appended to `review_history` with its reviewer, timestamp,
notes, mask checksum, and media fingerprint. The active `review` must exactly match the latest
history entry, preventing silent replacement or deletion of earlier QA decisions.
Review entries form a SHA-256 chain: each decision includes its own canonical record hash and the
previous decision's hash. Any edit to an earlier status, reviewer, note, checksum, or linkage makes
the complete annotation audit invalid before benchmark execution.

The manifest-level `gates` object defines promotion criteria across the full suite:
`minimum_mean_iou`, `minimum_pass_rate`, and optional `maximum_mean_duration_seconds`.
The command exits successfully only when all configured gates pass, and records actual versus
required values in both report formats.
Every result also records adapter, adapter version, model identifier, and device. Real-model runs
hash the selected checkpoint file with SHA-256, and baseline promotion preserves that provenance
so model decisions refer to exact weights rather than a filename alone.

Compare an approved baseline report with a candidate model report before promotion:

```bash
python -m nova_layer.benchmark_comparison \
  /path/to/baseline.json \
  /path/to/candidate.json \
  --output ../06_Test/reports
```

The default regression budget allows at most a 0.01 IoU drop and a 20% mean-latency increase.
Promotion is also blocked when a shared case regresses beyond budget, a baseline case disappears,
or the candidate fails its own suite gates. Both budgets are configurable from the CLI.

Promote an unchanged candidate report after a passing comparison:

```bash
python -m nova_layer.benchmark_baseline \
  /path/to/candidate.json \
  ../06_Test/reports/real_footage_regression_latest.json \
  --registry ../06_Test/model_registry \
  --label sam2-tiny-mps-v1
```

The comparison binds both input reports by SHA-256. Promotion copies the approved candidate into
an immutable, content-addressed snapshot and atomically updates the active-baseline registry and
history. A modified candidate, failed comparison, failed suite gates, or duplicate snapshot is
rejected.

Audit all immutable snapshots or reactivate a previous baseline:

```bash
python -m nova_layer.benchmark_baseline_activate ../06_Test/model_registry
python -m nova_layer.benchmark_baseline_activate \
  ../06_Test/model_registry --activate sam2-tiny-mps-v1
```

Activation is refused unless every registered snapshot exists and matches its recorded SHA-256.
Successful switches are appended to `activation_history`, preserving baseline rollback evidence.

## Architecture Rule

Domain modules must not import PySide6, PyAV, PyTorch, or any named AI model package.

Infrastructure packages implement the stable ports defined under `nova_layer.ports`.

Artist-drawn skeletons are stored as model-independent `SkeletonGuidance` rather than OpenPose
objects. Each joint becomes high-priority positive segmentation guidance while bone topology is
preserved for future pose/depth adapters and temporal identity reasoning. External pose extractors
must remain optional adapters behind this domain representation.
Temporal skeleton adapters receive the artist's reference topology plus decoded Shot frames and
return normalized per-frame skeletons with confidence and provenance. The deterministic adapter
keeps the workflow testable now; a licensed depth/OpenPose implementation can replace it without
changing Project files, Artist Intent, or the Workspace.
Temporal identity confidence uses a 70% mask and 30% skeleton weighted score when a tracked
skeleton is available, while mask-only shots retain their original confidence. Both the fused
identity score and the independent skeleton score/provenance are persisted for auditability.

An external pose implementation can be selected without importing it into the NOVA domain:

```bash
NOVA_SKELETON_ADAPTER="your_package.adapter:create" nova-layer
```

The factory must return an object implementing `SkeletonTrackingCapability`, including `track()`
and `skeleton_tracking` provenance. In normal `auto` mode an unavailable adapter falls back to the
deterministic tracker with a diagnostic message. Set `NOVA_AI_MODE=skeleton` to require the external
adapter and fail startup clearly instead of falling back.

All externally loaded trackers are wrapped by NOVA's contract validator before use. Results are
rejected before project commit when they contain duplicate or unrequested frames, change the
artist's joint identities or bone topology, or report non-skeleton provenance. This keeps external
model failures isolated from authoritative Smart Layer state.

Validate an adapter independently before enabling it in the application:

```bash
nova-skeleton-check "your_package.adapter:create"
```

Validate an automatic Depth/pose detector with the same command:

```bash
nova-skeleton-check "your_depth_package.adapter:create" --role detection
```

The command emits a machine-readable JSON result and exits non-zero when loading or any contract
check fails, making it suitable for adapter CI and future third-party repository evaluation.
Detection-role reports include semantic labels, model confidence, depth confidence, provenance,
and all six detector contract checks.

Per-frame artist skeleton corrections are stored independently from model observations. A
correction preserves the Master Frame joint identities and bone topology, records confidence 1.0
with artist provenance and Evidence, recomputes the fused identity score from the retained raw mask
confidence, and remains authoritative when propagation is run again.

To correct a tracked pose, navigate to a frame with a cyan skeleton and choose `Correct Pose`.
NOVA displays a magenta editable copy: drag its joints, then choose `Save Pose`. Leaving the frame
or switching tools discards uncommitted edits, while saving records the authoritative correction.
Saved correction frames appear as magenta timeline markers. They are clickable, identify the
artist correction in their tooltip, contribute to the `Corrected` summary count, and are restored
from the Smart Layer when the project is reopened.
`Remove Correction` requires confirmation and restores the exact model-tracked pose that the first
artist edit replaced, including skeleton provenance and confidence. The fused identity score is
recomputed from the retained raw mask score, and the removal is recorded as new artist Evidence
rather than erasing history.

When tracking runs again, NOVA treats the Master Frame and every saved pose correction as temporal
anchors. Each Shot frame is assigned to its nearest anchor and tracked from that pose, so a local
artist correction improves the surrounding motion instead of changing only one frame. Result
provenance records `skeleton_anchor_frame` and whether the source was `master` or
`artist_correction`.

After saving corrections, `Update Pose Track` runs the pose adapter alone in the background. It
keeps all existing mask assets, updates temporal skeletons and fused confidence, refreshes
validation confidence and lifecycle states, and commits only when the Smart Layer has not changed
during processing. Cancellation and stale results leave authoritative state untouched.

In Bone mode, double-click a joint to assign a semantic label such as `left_shoulder` or
`right_knee`. Labels must be unique `snake_case` identifiers, are rendered beside the joint, and
are persisted with Artist Guidance. Adapters can use `SkeletonGuidance.semantic_joint_map()` to
map named model keypoints without depending on joint list order.

`BODY_25` adds a neutral, fully labeled 25-joint skeleton that follows OpenPose's documented body
keypoint naming and output order. The preset geometry is authored by NOVA and includes no OpenPose
runtime code or weights. It can be posed by the artist like any other guidance skeleton; use of an
actual OpenPose engine remains an optional adapter subject to its separate license.

Artist-Guided Skeleton Fusion matches rough artist joints to automatic detections by semantic
label. Model confidence is multiplied by optional depth confidence before blending with the artist
position. Large positional disagreements are flagged and kept at the artist position rather than
silently averaged. The viewer compares artist guidance in yellow, automatic detection in orange,
and the fused proposal in green. Proposals remain `pending` until explicitly accepted or rejected;
only accepted results become Master Guidance or temporal correction keyframes.

`Auto Fuse Pose` decodes the current frame in the background and invokes the independent
`SkeletonDetectionCapability` with the labeled artist skeleton as a structural prompt. A detector
returns a semantic skeleton plus per-joint model and depth confidence; NOVA converts that result
into the normal fusion review candidate. The deterministic detector keeps the complete workflow
executable until a licensed real Depth/pose adapter is configured.

Configure an installed automatic detector independently from temporal tracking:

```bash
NOVA_SKELETON_DETECTOR="your_depth_package.adapter:create" nova-layer
```

The factory must implement `SkeletonDetectionCapability`. NOVA validates skeleton-detection
provenance, semantic overlap with the artist prompt, confidence label references, and every model
and depth confidence range before fusion. In `auto` mode loading failures safely use the Mock
detector; `NOVA_AI_MODE=skeleton` makes a configured invalid detector fail startup clearly.

The NOVA-owned browser bridge contract lives at
`03_AI/contracts/depth_pose_request_v1.schema.json` and
`03_AI/contracts/depth_pose_frame_v1.schema.json`. Start a compatible licensed local endpoint and
select it without installing a Python detector:

```bash
nova-depth-pose-bridge
# Copy the printed value into a second terminal:
NOVA_DEPTH_POSE_BRIDGE_URL="http://127.0.0.1:3456/api/nova/depth-pose?token=..." nova-layer
```

NOVA sends the current RGB frame as base64 plus its dimensions, frame number, and requested
semantic labels. The endpoint must return the
requested frame number and dimensions plus normalized semantic joints, pose confidence, depth
confidence, optional sampled depth, model identifiers, and runtime. The
`BrowserDepthPoseDetectionCapability` rejects mismatched frames or dimensions, recreates only
artist-defined bone connections, and converts the response into normal fusion Evidence without
copying the browser extractor implementation. For security and predictable latency, bridge URLs
are restricted to plain HTTP on `127.0.0.1`, `localhost`, or `::1`, with a 30-second timeout and a
4 MiB response limit. `NOVA_SKELETON_DETECTOR` takes precedence if both integrations are set.

Sampled per-joint depth is preserved separately from depth confidence throughout detection,
contract validation, Fusion review, project persistence, and adapter conformance reports. Fusion
continues to use confidence as a weight; it does not treat relative monocular depth as metric
distance. The review dialog shows the number and range of available depth samples, while rejecting
unknown-label, NaN, or infinite depth values before project commit.

During Fusion review, orange detected joints show compact `z` relative-depth and `dc`
depth-confidence annotations beside their semantic labels. These annotations belong only to the
temporary review preview and are cleared after acceptance or rejection.

The bundled broker does not contain a pose or depth model. It holds each NOVA request while an
independent licensed browser worker polls `GET /api/worker/jobs/next`, performs inference, and
posts the contract response to `POST /api/worker/jobs/{job_id}/result`. Both worker endpoints
require the random token printed by the broker as either `X-NOVA-Bridge-Token` or the `token` query
parameter. `/health` is an unauthenticated readiness check and contains no source imagery.

Startup Diagnostics includes a **Skeleton Detection** row. It distinguishes an unconfigured Mock,
an unreachable configured bridge, a reachable broker with no browser worker, and a broker with a
recent worker poll. The health request has a 0.75-second timeout and never sends a frame. Keep the
worker page open; after 30 seconds without polling, diagnostics treats it as disconnected.

Open the printed `Browser worker` URL, enter the loopback URL of an approved ES provider module,
and press **Load provider and start**. The provider contract is documented in
`03_AI/contracts/depth_pose_browser_provider_v1.md`. The worker refuses remote provider URLs and
does not bundle or silently download any third-party inference framework or model.

The default local provider uses MoveNet SinglePose Lightning for 17 COCO joints and
`onnx-community/depth-anything-v2-small` for relative depth. It pins TensorFlow.js 4.22.0,
pose-detection 2.1.3, and Transformers.js 3.7.2. Pressing the start button explicitly downloads
those runtimes and model weights from their upstream hosts. Depth uses WebGPU when available and
falls back to WASM; pose uses WebGL with a CPU fallback. Model selection and the remaining release
licensing gate are recorded in `03_AI/06_BROWSER_MODEL_LICENSE_RECORD.md`.

Benchmark approved person footage with semantic artist and ground-truth joints:

```bash
NOVA_DEPTH_POSE_BRIDGE_URL="http://127.0.0.1:3456/api/nova/depth-pose?token=..." \
  nova-depth-pose-benchmark \
  06_Test/datasets/depth_pose_manifest.json \
  --output 06_Test/reports/depth_pose_benchmark_latest.json
```

Start from `06_Test/datasets/depth_pose_manifest.example.json`. Each case records a rough artist
skeleton, independently reviewed ground-truth joints, PCK radius, minimum PCK, joint coverage,
depth-confidence coverage, sampled-depth coverage, and maximum duration. Depth-confidence coverage
measures whether confidence evidence exists; sampled-depth coverage separately requires actual
per-joint depth values. Results include normalized mean joint error, PCK, both confidence coverage
values, sampled-depth coverage, sampled-depth mean/range, mean
bone-endpoint depth delta, confidence means, runtime provenance, and a deterministic pass/fail
decision. Report schema 1.1 also preserves the PCK radius and actual-versus-required evidence for
every configured PCK, joint-coverage, depth-coverage, and latency gate; execution errors retain
their requirements as not-evaluated evidence. Relative-depth summaries are observational and are
not treated as metric-distance
accuracy gates. Every run writes the requested machine-readable JSON and a same-named `.md`
report beside it. The Markdown report summarizes the suite decision, per-case Pose/Depth metrics,
runtime provenance, errors, and temporal transitions for human QA; JSON remains the authoritative
input for comparison and baseline promotion. No real footage is bundled with NOVA.

Assign the same `depth_sequence` to cases from the same subject and Shot. The report sorts those
cases by frame and compares overlapping semantic joints between consecutive samples. It records
raw absolute depth delta as a diagnostic, plus a per-frame min/max-normalized relative-depth delta
that removes monocular scale and offset ambiguity. Suite temporal summaries use the relative
metric; transitions with no usable within-frame depth range remain `null` rather than inventing a
stability score. Project exports automatically use the Smart Layer ID as their sequence key.

Set `gates.maximum_mean_temporal_relative_depth_delta` in the manifest to turn that summary into an
absolute suite gate. Newly exported datasets leave it `null` until reviewed baseline footage exists;
the representative example illustrates a provisional `0.15` budget. When the gate is configured,
the suite fails if its mean exceeds the limit or if no comparable transition exists. A temporal
suite therefore needs at least two usable cases sharing a `depth_sequence`.

Set `gates.minimum_temporal_transition_coverage` to require enough consecutive pairs to contain
overlapping semantic joints and usable within-frame depth ranges. The report retains every expected
pair, marks non-comparable transitions explicitly, and records comparable/expected coverage. The
example uses `0.8`; new exports leave both temporal gates `null` until the dataset has reviewed
multi-frame evidence.

Compare a new run against an approved Depth/Pose baseline:

```bash
nova-depth-pose-compare baseline.json candidate.json \
  --output 06_Test/reports/depth_pose_regression
```

The comparison blocks excessive mean or per-case joint-error increase, PCK drop, joint/depth/
sampled-depth coverage drop, latency increase, temporal relative-depth instability, removed
baseline cases, temporal-transition coverage loss, and candidate gate failures. Passing comparison
reports use the existing baseline integrity fields, so they can be promoted without a second
registry:

```bash
nova-baseline-promote candidate.json \
  06_Test/reports/depth_pose_regression/depth_pose_regression_latest.json \
  --registry 06_Test/depth_pose_registry --label depth-pose-webgpu
```

Prefer exporting a candidate directly from a saved NOVA project instead of authoring JSON:

```bash
nova-depth-pose-export MyProject.nova \
  --output 06_Test/datasets/my_pose_suite \
  --case-id standing-person-front
```

Verify the Depth/Pose pipeline without licensed footage using the deterministic smoke suite:

```bash
nova-depth-pose-smoke --output ../06_Test/reports/depth_pose_smoke
```

The smoke command writes a short synthetic clip, runs the Mock detector through the normal
benchmark and temporal gates, self-compares the report for regression-path coverage, and exits
non-zero when any gate fails. It proves transport, metrics, and promotion plumbing rather than
real-model accuracy.

The exporter uses the Master Frame artist skeleton as the rough prompt. Ground truth must come
from an artist-authored correction on that frame, or—if no correction exists—the latest accepted
fusion proposal. Pending/rejected fusion and unreviewed automatic detections are never exported as
truth. The candidate records project, Shot, Smart Layer, layer-version, source-media, and selection
provenance.

When an accepted Master Fusion is exported, its internally preserved pre-fusion artist skeleton is
used as the rough prompt—not the current guidance that was replaced by the fused pose. This keeps
rough input and reviewed target distinct for meaningful accuracy measurement.

The workspace exposes the same export as **Add Pose QA Case**. It appears only when the Master
Frame has semantic artist guidance plus an artist correction or accepted fusion result. The button
updates immediately after correction save/removal and fusion review, is disabled during background
processing, and reports the selected ground-truth source in the status bar.

Candidate annotations can be explored with `--allow-unreviewed`, but official benchmark runs
require approval. After recording the imported media fingerprint and reviewing every semantic
joint, first generate a visual QA package:

```bash
nova-depth-pose-review-assets 06_Test/datasets/depth_pose_manifest.json \
  --output 06_Test/review/depth_pose_candidate
```

Open the generated `index.html` and compare the source, yellow artist rough pose, cyan ground
truth, combined overlay, and label coordinate table. Review output is staged and published
atomically and refuses to overwrite an existing review directory. After visual inspection, lock
the case with:

```bash
nova-depth-pose-review 06_Test/datasets/depth_pose_manifest.json standing-person-front \
  --status approved --reviewer "QA Artist" --notes "joint labels and positions verified"
```

Approval atomically records the ground-truth skeleton SHA-256, media fingerprint, reviewer, time,
notes, and a chained review checksum. A changed skeleton, changed source fingerprint, broken review
history, or non-approved latest review blocks an official run before model inference.
