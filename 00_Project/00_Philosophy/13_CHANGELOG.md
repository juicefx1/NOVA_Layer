# NOVA Layer

# 13_CHANGELOG

## 2026-07-26 — Host Session 1.1 and Production Ready Maturity

- Expanded `HeadlessHostSession` with media validation, relink, save, and production promotion.
- Added shared `promote_to_production_ready` maturity rules requiring validated frames plus a render.
- Wired Workspace **Mark Production Ready** and ProjectController promotion with Reasoning history.
- Added Nuke / After Effects declarative adapter skeletons under `nova_layer.host.adapters`.
- Bumped host API to version 1.1 and extended `nova-host-session` commands.

## 2026-07-26 — Implementation Docs and Host Session Foundation

- Filled `00_Project/01_Implementation/` specs from the executable Phase 1 codebase.
- Added `HostSession` port and Qt-free `HeadlessHostSession` for DCC/automation adapters.
- Added `nova-host-session` CLI with JSON `status` and `export-render` commands.
- Documented host API version 1.0 and the remaining full DCC plug-in gap.

## 2026-07-26 — Production Smart Layer Export Formats

- Added OpenEXR half-float RGBA sequence export from verified Smart Layer renders.
- Added lossless RGBA QuickTime export using the Animation (`qtrle`) codec.
- Preserved the existing PNG sequence export behind a shared production export module.
- Added Workspace format selection and the `nova-export-render` CLI.
- Recorded `format_id`, file checksums, and codec metadata in export manifests.
- Added OpenEXR to the optional desktop dependency set.

## 2026-07-26 — Depth/Pose Hardening and Deterministic Smoke

- Rejected non-finite bridge joint coordinates, confidences, and sampled depth at the JSON boundary.
- Clarified detector confidence contract errors for non-finite values.
- Added Depth/Pose regression coverage for removed cases and temporal-transition coverage drops.
- Added `nova-depth-pose-smoke` for footage-free deterministic benchmark and self-comparison.
- Surfaced clearer Auto Fuse Pose errors when detected joints do not match artist labels.
- Widened Shot Range handle hit-testing so macOS full-height slider styles remain draggable.
- Synced README Current Status with completed SAM, Smart Layer render, and Depth/Pose work.

## 2026-07-24 — Skeleton Correction Development 0.1.5.dev0

- Added persistent artist-authored skeleton correction keyframes.
- Stored original mask confidence independently for deterministic confidence recomputation.
- Replaced corrected temporal poses with confidence 1.0 and artist provenance.
- Preserved artist corrections when temporal tracking is run again.
- Added correction Evidence, Smart Layer versioning, and benchmark-dataset lineage.
- Added a Correct Pose viewer mode with draggable magenta joints over cyan tracked poses.
- Added explicit Save Pose semantics and discarded uncommitted edits on tool/frame changes.
- Added clickable magenta timeline markers and hover details for corrected pose frames.
- Added correction counts to the lifecycle summary and restored markers from project state.
- Preserved the replaced model pose inside each first correction for exact restoration.
- Added confirmed Remove Correction UI, confidence restoration, Evidence, and versioning.
- Promoted saved pose corrections to nearest-anchor inputs for subsequent temporal tracking.
- Recorded anchor frame and Master/Artist source in every anchored tracking provenance record.
- Added cancellable `Update Pose Track` background processing without SAM mask propagation.
- Recomputed fused confidence, validation confidence, and lifecycle from pose-only results.
- Added Smart Layer snapshot protection so stale pose retracking results are discarded.
- Added unique validated semantic labels and named-joint mapping to skeleton guidance.
- Added Bone-mode joint-label editing and in-viewer label rendering.
- Added a one-click NOVA-authored BODY_25 interoperability skeleton preset.
- Kept the preset independent from OpenPose runtime code, weights, and licensing.
- Added label-matched artist/automatic skeleton fusion weighted by model and depth confidence.
- Preserved artist positions and flagged conflicts when automatic joints diverge excessively.
- Added persistent pending/accepted/rejected fusion candidates and artist review Evidence.
- Added yellow/orange/green fusion comparison overlays and explicit review UI.
- Added the model-independent automatic skeleton-detection capability and result contract.
- Added cancellable background `Auto Fuse Pose` processing with stale-state protection.
- Added a deterministic RGB/Depth-pose Mock for end-to-end fusion workflow validation.
- Added `NOVA_SKELETON_DETECTOR` external detector selection and application startup wiring.
- Added semantic-overlap, confidence-key/range, and provenance contract validation.
- Added explicit-mode failure and automatic safe fallback for unavailable external detectors.
- Extended `nova-skeleton-check` with a detection role and real detector invocation.
- Added JSON evidence for semantic labels, joint/depth confidence, and six contract checks.
- Inspected the supplied `openerai/depth-openpose-extractor` at commit `41d376cf6f81`.
- Confirmed browser WebGPU/WASM Depth Anything V2 plus MediaPipe-to-OpenPose-18 rendering.
- Identified missing repository licensing and missing raw JSON/depth output as integration blockers.
- Selected a future licensed local HTTP/JSON bridge rather than copying the browser application.
- Added the versioned NOVA Depth/Pose Frame JSON Schema 1.0.
- Added a strict browser-bridge adapter for landmarks, pose confidence, and depth confidence.
- Preserved artist topology while rejecting mismatched bridge frames and source dimensions.
- Added the versioned Depth/Pose Request JSON Schema with raw RGB8 base64 transport.
- Added a loopback-only HTTP provider with timeout and response-size safety limits.
- Wired `NOVA_DEPTH_POSE_BRIDGE_URL` into automatic detector selection with Mock fallback.
- Added the model-free `nova-depth-pose-bridge` loopback broker and random token authentication.
- Added long-polling browser jobs with single-use completion and strict result correlation.
- Added decoded RGB length, requested-label, frame, and dimension validation at the broker boundary.
- Added a packaged browser-worker UI that decodes RGB frames and runs authenticated job polling.
- Added a loopback-only ES provider boundary and documented Browser Provider Contract 1.0.
- Kept framework code and model weights outside NOVA until their individual licenses are approved.
- Added an opt-in MoveNet Lightning plus Depth Anything V2 Small browser provider.
- Added WebGPU/WASM depth and WebGL/CPU pose fallback selection with pinned runtime versions.
- Sampled normalized depth and local depth consistency at each requested semantic joint.
- Recorded the exact development model selection and unresolved release licensing gate.
- Verified real browser initialization with WebGPU depth and TensorFlow.js WebGL pose.
- Completed an authenticated NOVA-to-browser round trip using a generated 64×64 RGB frame.
- Added `nova-depth-pose-benchmark` for semantic real-footage Pose/Depth evaluation.
- Added normalized joint error, PCK, joint/depth coverage, confidence, provenance, and latency reports.
- Added per-case automatic gates and a representative Depth/Pose manifest template.
- Added required human-QA approval for official Depth/Pose benchmark cases.
- Locked reviewed ground-truth skeletons and source media with SHA-256/fingerprint verification.
- Added chained review history and the atomic `nova-depth-pose-review` command.
- Added an explicit `--allow-unreviewed` development-only benchmark path.
- Added `nova-depth-pose-review-assets` for visual skeleton QA before approval.
- Added source, artist-only, ground-truth-only, and combined pose review renders.
- Added semantic coordinate tables, media fingerprint checks, and atomic review publication.
- Added `nova-depth-pose-export` to create benchmark candidates from saved NOVA projects.
- Preferred Master Frame artist corrections, then accepted fusion, as ground-truth candidates.
- Rejected pending/rejected fusion and unreviewed automatic pose as benchmark truth.
- Recorded project, Shot, Smart Layer, layer-version, and selection provenance in exported cases.
- Added an in-workspace `Add Pose QA Case` action backed by the same validated exporter.
- Gated the action on semantic artist guidance and reviewed Master Frame pose evidence.
- Refreshed availability immediately after correction and fusion review state changes.
- Disabled Pose QA export during background processing and surfaced source/status after export.
- Added Skeleton Detection to Startup Diagnostics with bounded loopback health probing.
- Distinguished unavailable bridge, broker-only, active browser-worker, external adapter, and Mock states.
- Added worker heartbeat, pending-job, and active-job fields to the local broker health response.
- Preserved sampled per-joint depth separately from depth confidence across the detection contract.
- Persisted joint depth and raw depth confidence in Fusion candidates with backward-compatible defaults.
- Rejected unknown-label and non-finite sampled depth before authoritative project commit.
- Added depth sample count/range to the artist Fusion review and adapter conformance output.
- Added sampled-depth coverage, mean, minimum, maximum, and bone-endpoint delta to benchmark reports.
- Kept relative-depth summaries observational rather than misclassifying them as metric accuracy.
- Added per-joint relative-depth and depth-confidence annotations to the temporary Fusion preview.
- Cleared depth annotations with the rest of the review preview after the artist decision.
- Fixed accepted-fusion dataset export to retain the original rough artist pose as benchmark input.
- Added `depth_sequence` grouping for consecutive semantic-joint depth stability analysis.
- Added raw and affine-invariant relative temporal depth deltas to benchmark reports.
- Used normalized relative deltas for suite summaries to avoid monocular scale/offset misuse.
- Added a human-readable Markdown companion to every Depth/Pose benchmark JSON report.
- Summarized suite decisions, per-case metrics, runtime provenance, errors, and temporal depth.
- Advanced Depth/Pose benchmark reports to schema 1.1 with actual-versus-required gate evidence.
- Preserved PCK radius and not-evaluated requirements when a case ends in an execution error.
- Added a separate minimum sampled-depth coverage gate so confidence-only outputs cannot pass.
- Added sampled-depth coverage regression blocking to baseline/candidate comparison.
- Extended the deterministic Depth/Pose Mock with reproducible per-joint relative-depth samples.
- Added an optional absolute suite gate for mean temporal relative-depth instability.
- Failed configured temporal suites when no comparable transition evidence exists.
- Left new exports ungated until reviewed footage exists and illustrated a provisional `0.15` limit.
- Recorded expected, comparable, and missing temporal transitions instead of silently dropping them.
- Added optional temporal-transition coverage gating and cross-report regression blocking.
- Assigned exported project cases to their Smart Layer depth sequence automatically.
- Added `nova-depth-pose-compare` with JSON and Markdown regression decisions.
- Added mean and per-case Pose quality, coverage, latency, and temporal-depth regression gates.
- Blocked removed baseline cases and candidates that fail their own configured suite gates.
- Reused the immutable baseline registry and checksum-verified promotion workflow.

## 2026-07-24 — Skeleton Guidance Adapter Release 0.1.4

- Added artist-drawn joint and bone guidance with normalized project persistence.
- Added temporal skeleton observations, overlays, confidence fusion, and provenance.
- Added optional external skeleton-adapter loading with safe Mock fallback.
- Added contract validation that protects frame scope, joint identity, bone topology, and state.
- Added `nova-skeleton-check` for standalone adapter conformance verification.
- Prepared the complete skeleton-guidance feature set for the 0.1.4 release candidate.
- Built and verified the 0.1.4 Wheel with SHA-256 `fc1b1af9ad0485d1c40478912cfe7271aee20e3332d810aa7b131aef931619e6`.
- Passed isolated installation smoke coverage for 14 command modules and GUI startup.
- Sealed and re-audited immutable candidate `nova-layer-0.1.4-fc1b1af9ad04`.

## 2026-07-23 — Model Evaluation Baseline

- Selected SAM 2.1 Hiera Small as the Phase 1 baseline with Hiera Tiny fallback.
- Deferred SAM 3.1 to a future CUDA workstation benchmark.
- Added the model evaluation plan, runtime preflight report generator, and tests.
- Kept model weights external and preserved the model-independent capability boundary.
- Installed and pinned PyTorch 2.7.1 with torchvision 0.22.1 for the SAM 2.1 baseline.
- Verified a real matrix operation on the M1 Pro GPU through the PyTorch MPS backend.
- Added RGB-frame input to the interactive-segmentation capability contract.
- Added a tested SAM 2.1 image adapter for point, negative-point, and box guidance.
- Completed the first Hiera Tiny MPS inference with 0.978 confidence in 18.6 seconds.
- Added automatic real-model selection with explicit Mock Mode fallback.
- Moved interactive hypothesis generation to a cancellable background job.
- Added snapshot validation so stale SAM results cannot overwrite a changed Shot.
- Added a thread-safe, content-aware image-embedding cache for repeated SAM guidance.
- Persisted embedding cache-hit information in capability provenance.
- Added continuous RGB Shot Range input to the temporal-propagation capability contract.
- Added the SAM 2.1 Video Predictor adapter with Master Mask conditioning.
- Verified real forward and reverse MPS tracking on a five-frame synthetic Shot.
- Recorded 11.962 seconds cold execution time and correct masks at both range endpoints.
- Added artist-drawn skeleton guidance and model-independent temporal skeleton tracking.
- Fused mask and skeleton confidence into temporal Object Identity decisions.
- Persisted skeleton confidence/provenance and exposed both scores in timeline hover details.
- Added environment-selected external skeleton adapters with contract validation and safe fallback.
- Wired the selected skeleton adapter into normal application startup.
- Added a skeleton-adapter contract guard for frame scope, identity, topology, and provenance.
- Ensured malformed external pose results fail before authoritative project commit.
- Added `nova-skeleton-check` for standalone external-adapter contract verification.
- Included the new command module in isolated Wheel installation smoke coverage.
- Added deterministic translation, occlusion-recovery, and similar-distractor benchmarks.
- Measured endpoint IoU and confidence calibration gaps on the real MPS video path.
- Passed all procedural scenarios; the similar-distractor minimum IoU was 0.9371.
- Added NOVA temporal confidence from logit certainty and master/transition area consistency.
- Added a disappearance safety cap so consecutive empty masks cannot regain high confidence.
- Extended evaluation with motion blur, full occlusion recovery, and frame exit scenarios.
- Added persistent per-frame temporal identity observations to Smart Layers.
- Connected SAM visibility to Tracked, Temporarily Lost, and Recovered lifecycle transitions.
- Kept intermediate observations separate from Start/Master/End validation cards.
- Required both visible mask evidence and sufficient confidence before declaring recovery.
- Prevented low-confidence hallucinated masks from changing Temporarily Lost to Recovered.
- Added lifecycle markers to the Workspace timeline.
- Added hover details and click-to-navigate behavior for Tracked, Lost, and Recovered frames.
- Restored timeline markers from persisted Smart Layer observations on project open.
- Added draggable Shot Range start, end, and Master Frame timeline handles.
- Constrained range handles around the Master Frame and synchronized inspector previews.
- Preserved explicit Apply semantics before timeline range edits become authoritative.
- Added RGB plus mask composition into transparent RGBA extraction previews.
- Stored Start, Master, and End preview PNGs under each `.nova` package.
- Persisted preview references and source-mask lineage in Smart Layers.
- Displayed the Master Frame extraction after successful three-point validation.
- Emitted preview-ready UI events only after authoritative project save succeeds.
- Persisted every temporal mask while keeping intermediate frames out of validation cards.
- Added versioned, cancellable full-Shot Smart Layer RGBA rendering.
- Added staging and stale-state checks before render outputs become authoritative.
- Added `renders/` to atomic project-package preservation.
- Added render-version selection to the Workspace.
- Added atomic external RGBA PNG sequence export with standalone metadata.
- Prevented export overwrites when a version destination already exists.
- Added per-frame SHA-256 metadata to Smart Layer render versions.
- Added render integrity verification and a Workspace Verify Render action.
- Blocked export when a rendered frame is missing or its checksum has changed.
- Added exported file size and checksum records to standalone manifests.
- Added persistent protection state for important Smart Layer render versions.
- Added Workspace controls for protecting a selected render version.
- Added frame-by-frame checksum comparison against the previous render version.
- Added identical, changed, added, and removed frame summaries in the Workspace.
- Added confirmed deletion of unprotected render versions and their PNG assets.
- Added quarantine-and-rollback handling so failed saves restore staged render assets.
- Blocked deletion of protected versions and disabled their Workspace delete action.
- Added a persistent high-water counter so deleted render version numbers are never reused.
- Recorded the source Smart Layer version on every new render.
- Added Render Details with creation time, frame range, storage size, protection, and integrity.
- Reverified frame checksums whenever Render Details is opened.
- Added a manifest-driven real-footage interactive-segmentation benchmark runner.
- Added per-case IoU, precision, recall, confidence, latency, and isolated error reporting.
- Added machine-readable JSON and reviewable Markdown benchmark reports.
- Rejected accidental Mock Mode quality runs unless explicitly allowed.
- Added a representative-shot manifest template for licensed local footage.
- Added a dataset builder for exporting validated Master Frames from `.nova` projects.
- Preserved Artist Guidance and Project/Shot/Smart Layer lineage in exported cases.
- Added source-media availability, maturity, accepted-mask, duplicate, and IoU validation.
- Added temporary-file commits so interrupted dataset exports do not leave partial cases.
- Marked newly exported annotations as QA candidates rather than automatic ground truth.
- Added atomic approved/rejected human-review decisions with reviewer, timestamp, and notes.
- Blocked unreviewed and rejected cases from model-quality benchmarks by default.
- Added an explicit development-only override for testing the dataset pipeline.
- Locked approved Ground Truth masks to their SHA-256 digest at review time.
- Blocked benchmark cases when an approved mask is missing or changes after review.
- Required revised annotations to pass human QA again before quality evaluation.
- Preserved the imported source-media fingerprint in every exported dataset case.
- Locked the media fingerprint into the human-review audit record.
- Compared inspected footage against the reviewed fingerprint before frame decoding and scoring.
- Blocked replaced or re-encoded media from silently reusing incompatible annotations.
- Added manifest-level mean IoU, case pass-rate, and mean-latency quality gates.
- Added actual-versus-required gate evidence to JSON and Markdown benchmark reports.
- Changed benchmark exit status to require every configured suite gate to pass.
- Added default promotion gates to newly created benchmark datasets.
- Added baseline-versus-candidate real-footage benchmark comparison.
- Added mean and per-case IoU regression budgets plus a mean-latency budget.
- Blocked model promotion when baseline cases disappear from the candidate report.
- Required candidate suite gates and regression checks to pass together.
- Added JSON and Markdown regression-decision reports with blocking reasons.
- Bound regression decisions to exact baseline and candidate report SHA-256 digests.
- Added gated promotion of passing candidates into immutable baseline snapshots.
- Added an atomic active-baseline registry with complete promotion history.
- Blocked modified candidates, failed comparisons, failed suite gates, and duplicate snapshots.
- Added full baseline-registry audits for missing, unsafe, and checksum-mismatched snapshots.
- Added safe reactivation of previously promoted model baselines.
- Blocked every baseline switch until the complete registry passes integrity verification.
- Added append-only activation history for model-baseline rollback evidence.
- Added an Add Benchmark Case action to the Workspace for validated Smart Layers.
- Added dataset-directory and case-ID prompts without exposing project-package internals.
- Kept exported Workspace cases in candidate status so human Ground Truth QA remains mandatory.
- Added controller success events and actionable Workspace export status messages.
- Added visual Ground Truth QA packages with source, overlay, and mask PNGs per case.
- Added a self-contained dark HTML review index for side-by-side annotation inspection.
- Verified media fingerprints and frame/mask dimensions before producing QA assets.
- Made review output directories immutable to preserve evidence for each annotation revision.
- Added adapter, adapter version, model identifier, and device to each benchmark result.
- Added selected checkpoint path and SHA-256 to real-model benchmark reports.
- Preserved model provenance and exact checkpoint identity in promoted baseline registry entries.
- Distinguished exact model weights even when different files reuse the same checkpoint name.
- Added append-only Ground Truth review history across approvals, rejections, and revisions.
- Preserved the reviewer, timestamp, notes, mask checksum, and media fingerprint per decision.
- Required the active review to match the latest audit-history entry before benchmarking.
- Verified the complete approved → rejected → revised → approved workflow.
- Added canonical SHA-256 hashes to every Ground Truth QA decision.
- Linked each review record to the previous decision hash as a tamper-evident chain.
- Validated the complete chain and active-review linkage before benchmark execution.
- Added a regression test proving that modification of an earlier review invalidates the audit.
- Added 12 installed CLI entry points for the app, model/data, and release operations.
- Added importability coverage for every declared command target.
- Fixed Hatch metadata generation for the pinned optional SAM-2 direct reference.
- Verified editable package installation and help execution for all 10 non-GUI commands.
- Added Wheel structure, command, metadata, RECORD, size, and SHA-256 verification.
- Blocked release artifacts that accidentally embed model checkpoint files.
- Built and verified the first `nova_layer-0.1.0` Wheel under `07_Build`.
- Added gated, atomic assembly of immutable release-candidate directories.
- Required both a matching valid Wheel report and fully passing Phase 1 acceptance evidence.
- Added per-file size and SHA-256 metadata to the release manifest.
- Advanced the package version to 0.1.1 without overwriting the preserved 0.1.0 artifact.
- Built, verified, and sealed the first 0.1.1 release candidate under `08_Release`.
- Added repeatable post-assembly audits for sealed release candidates.
- Added missing, unexpected, size-mismatched, checksum-mismatched, and unsafe-file detection.
- Reverified the embedded Wheel and Phase 1 acceptance evidence during every release audit.
- Added historical command-inventory compatibility for immutable older releases.
- Re-audited the sealed 0.1.1 candidate successfully with all three files valid.
- Added isolated temporary-target installation smoke tests for built Wheels.
- Verified imports resolve from the installed Wheel rather than the working source tree.
- Executed every historical non-GUI command module declared by the target Wheel.
- Added GUI entry-module import verification without starting a blocking desktop event loop.
- Passed the 0.1.1 install smoke test across all 12 non-GUI modules.
- Bound installation-smoke reports to the exact Wheel SHA-256.
- Upgraded release-candidate format v2 to require passing installation evidence.
- Added explicit Wheel, Wheel-report, smoke-report, and acceptance-report artifact roles.
- Advanced the package version to 0.1.2 and preserved the earlier 0.1.0/0.1.1 artifacts.
- Built a valid 0.1.2 Wheel and passed installation smoke across 13 non-GUI modules.
- Sealed and re-audited the four-file 0.1.2 release candidate successfully.
- Added model-independent Skeleton Joint, Bone, and Skeleton Guidance domain models.
- Added normalized bone drawing with nearby-joint snapping in the Workspace Viewer.
- Persisted skeleton topology as Artist Intent and included it in benchmark dataset lineage.
- Converted artist joints into high-priority positive segmentation prompts.
- Enabled Object Hypothesis generation from skeleton-only guidance.
- Kept external OpenPose/depth implementations behind a future optional capability adapter.
- Added a model-independent Skeleton Tracking capability contract.
- Added deterministic temporal joint tracking for model-free workflow and persistence tests.
- Persisted normalized per-frame Skeleton observations, confidence, and capability provenance.
- Added cyan tracked-pose overlays while retaining the yellow artist reference skeleton.
- Restored temporal skeleton observations from saved `.nova` projects.

Version : 1.0 Draft

Status : Internal

Author : Supernova Studios

---

# 2026-07-23

## Phase 1 Vertical Slice - Acceptance Runner

- Added an independent runner for P1-AT-001 through P1-AT-009.
- Added JSON and Markdown evidence reports with duration, status, and exact test references.
- Added safe capability-exception handling that preserves Project and Object Identity state.
- Added a real low-confidence propagation safety test using the 0.60 identity threshold.
- Verified that ambiguous results become Correction Required and cannot mature to Validated.
- Passed all 9 acceptance criteria and all 28 automated tests.
- Advanced the roadmap from Phase 1 Vertical Slice to Phase 1 Model Evaluation.

## Phase 1 Vertical Slice - Startup Diagnostics

- Added startup checks for Python, Qt, PyAV, NumPy, project persistence, AI runtime, segmentation, and propagation.
- Added Pass, Warning, and Fail severity levels with component versions.
- Added an atomic persistence self-test during diagnostics.
- Added explicit deterministic Mock Mode reporting when PyTorch or model weights are unavailable.
- Added a diagnostics summary and detailed report to the Welcome screen.
- Disabled project actions only for blocking failures, not expected prototype warnings.
- Added tests for required components, severity, summary, and persistence health.

## Phase 1 Vertical Slice - Schema Migration

- Added an ordered, copy-on-migrate project schema registry.
- Added the initial legacy 0.9 to 1.0 hierarchy migration.
- Preserved the original project package during load-only migration.
- Added migration status reporting in the Workspace.
- Rejected unknown and future schemas without writing or overwriting project data.
- Added tests for legacy conversion, migration reporting, source preservation, and future-version rejection.

## Phase 1 Vertical Slice - Autosave Recovery

- Added a recovery journal before every authoritative atomic project save.
- Removed recovery journals only after the replacement package is committed successfully.
- Added interrupted-session detection when opening projects.
- Added explicit Restore and Discard choices without silently overwriting the last valid project.
- Added in-place Workspace refresh after recovery.
- Added tests for successful cleanup, recovery loading, discard, controller restore, and journal removal.

## Phase 1 Vertical Slice - Media Relink

- Added source existence and fingerprint validation when opening a project.
- Added Linked, Missing, and Changed media states.
- Blocked frame requests and processing while relink is required.
- Added explicit relink confirmation for changed source content.
- Rejected replacement media that cannot contain the saved Shot Range.
- Cleared the frame cache and restored the Master Frame after a successful relink.
- Added tests for missing, changed, confirmed replacement, and short replacement media.

## Phase 1 Vertical Slice - Processing Jobs

- Added a reusable Qt background job service with progress, completion, cancellation, and failure signals.
- Moved bidirectional propagation into a cancellable background operation.
- Added latest UI processing state, progress bar, current-step messages, and Cancel action.
- Added a commit-on-completion rule so cancelled or failed jobs cannot write partial Smart Layer results.
- Added tests for progress, completion, cancellation, and partial-result discard behavior.

# 2026-07-22

## Phase 1 Vertical Slice - Background Frame Decode

- Moved timeline frame decoding to Qt background workers.
- Added latest-request-wins behavior so stale decode results cannot overwrite the Viewer.
- Added a bounded LRU frame cache with defensive frame copies.
- Added timeline scrub debouncing to reduce redundant decode work.
- Preserved synchronous validation-preview loading outside interactive timeline navigation.
- Added tests for cache hits, eviction, and bounded cache size.

## Phase 1 Vertical Slice - Correction and Local Re-Propagation

- Added a per-frame Correction dialog with positive, negative, and Bounding Region guidance.
- Added high-priority Artist Evidence for accepted corrections.
- Recomputed only the affected backward or forward validation result.
- Preserved the existing Object Identity while increasing the Smart Layer version.
- Returned corrected results to Pending for explicit artist re-validation.
- Added tests for correction masks, direction-local reasoning, versioning, and final validation.

## Phase 1 Vertical Slice - Validation Review

- Added a simultaneous Start, Master, and End comparison dialog.
- Added frame and candidate-mask composite previews with confidence display.
- Added per-frame Accept and Correction Required decisions.
- Added persisted validation Reasoning Records for artist decisions.
- Added the Confirmed to Validated maturity transition only when all three frames are accepted.
- Added tests proving that Correction Required prevents premature validation.

## Phase 1 Vertical Slice - Bidirectional Propagation

- Added deterministic mask propagation from the confirmed Master Frame to Shot Range start and end.
- Added separate backward and forward Frame Results with temporal Evidence Records.
- Added persisted masks for all three Phase 1 validation positions.
- Added the Object Lifecycle transition from Confirmed to Tracked.
- Added a Workspace propagation action and validation-ready state.
- Added tests for direction, target frames, mask assets, and Object Identity continuity.

## Phase 1 Vertical Slice - Object Hypothesis

- Added deterministic candidate-mask generation from points and Bounding Region guidance.
- Added lossless PNG mask persistence without losing existing project assets during atomic saves.
- Added candidate mask overlay, confidence display, and Accept, Reject, and Refine controls.
- Added capability Evidence Records and artist-decision Reasoning Records.
- Added the transition from Hypothesis/Candidate to Confirmed Object Identity.
- Added tests for mask persistence, artist confirmation, maturity, lifecycle, and validation state.

## Phase 1 Vertical Slice - Artist Guidance

- Added an interactive Master Frame viewer for positive and negative points.
- Added drag-based Bounding Region guidance.
- Added resolution-independent normalized Artist Intent coordinates.
- Added guidance overlays, tool modes, summary state, clear action, and automatic persistence.
- Added automatic first Smart Layer creation with Hypothesis maturity.
- Added persistence tests proving guidance restoration without changing Object Identity.

## Phase 1 Vertical Slice - Media and Shot Setup

- Added the PyAV media inspection and RGB frame decoding adapter.
- Added media fingerprint, time-base, pixel-format, and source relink fields.
- Added Workspace media import, viewer, timeline navigation, and media metadata display.
- Added editable Shot Range and Master Frame controls with project persistence.
- Added fake-adapter workflow tests and a generated-video PyAV integration test.

## Phase 1 Vertical Slice - Application Shell

- Created an isolated Python 3.12 environment and installed desktop and test dependencies.
- Added the PySide6 application entry point and dark desktop visual baseline.
- Added Welcome, Create Project, Open Project, and initial Workspace flows.
- Connected UI project actions to atomic `.nova` persistence through the application controller.
- Added headless UI tests and passed pytest, Ruff, formatting, and strict mypy validation.

## Phase 1 Vertical Slice - Domain Foundation

- Created the Python 3.12 project and dependency configuration.
- Added authoritative Project, Sequence, Shot, Smart Layer, Object Identity, Artist Intent, Evidence, Reasoning, and Frame Result models.
- Added model-independent segmentation and propagation capability ports.
- Added deterministic mock capability adapters for model-free UI and workflow development.
- Added atomic JSON `.nova` project persistence with rollback behavior.
- Added and passed tests for frame-range validation, deterministic capability output, and Object Identity save/restore continuity.

## Technology Baseline 1.0

- Selected a macOS ARM64, Python 3.12, PySide6, PyAV, OpenColorIO, and PyTorch baseline for Phase 1.
- Defined strict boundaries between UI, application services, domain models, media, AI capabilities, and persistence.
- Chose mock capability adapters for the first vertical slice and deferred model weights to evaluation.
- Documented Apple Silicon memory, MPS compatibility, variable-frame-rate media, and color-management risks.
- Advanced the roadmap to Phase 1 Vertical Slice.

## Phase 1 Implementation Specification 1.0

- Added an executable Phase 1 scope and explicit exclusions.
- Defined functional requirements, application areas, domain entities, and state models.
- Defined model-independent capability contracts for segmentation, propagation, and preview extraction.
- Defined the prototype project package, recovery behavior, acceptance tests, and implementation gates.

## Development Roadmap 1.1

- Added the Evidence and Reasoning Loop.
- Added the persistent Project → Sequence → Shot → Smart Layer → Object Identity hierarchy.
- Added Object Identity maturity stages from Hypothesis through Persistent.
- Defined the Smart Layer as the primary editable production asset.
- Connected evidence, reasoning, corrections, maturity, and persistence to Phase success criteria.
- Added project and sequence organization requirements to Production Integration.
- Corrected the duplicated Bidirectional Propagation section and malformed Markdown code fence.
