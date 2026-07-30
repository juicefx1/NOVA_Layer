# NOVA Layer — Phase 1 Model Evaluation Plan

Version: 1.0 Draft  
Status: In Progress  
Date: 2026-07-23

## Decision

Use **SAM 2.1 Hiera Small** as the first real-model baseline and **Hiera Tiny** as the
memory/latency fallback. Defer SAM 3.1 to a CUDA workstation benchmark.

This is a baseline decision, not a final production-model commitment. NOVA Layer keeps the
model behind the existing interactive-segmentation and temporal-propagation capability ports.

## Rationale

- SAM 2.1 exposes point, box, refinement, and video propagation workflows needed by Phase 1.
- Its code and checkpoints use Apache-2.0, which is clearer for prototype and product evaluation.
- Hiera Small offers a practical quality/performance starting point; Tiny supplies a controlled
  fallback if unified-memory pressure or latency is unacceptable.
- SAM 3.1 officially targets Python 3.12+, PyTorch 2.7+, and CUDA 12.6+. It remains relevant for
  later multi-object evaluation but is not the local Apple Silicon baseline.
- PyTorch provides an MPS backend, but official SAM 2 installation guidance is Linux/CUDA-first.
  MPS execution must therefore be demonstrated rather than assumed.

## Evaluation Gates

1. Runtime: supported PyTorch imports in the isolated NOVA environment.
2. Accelerator: MPS is available and a tensor operation completes without fallback failure.
3. Model load: checkpoint loads without modifying the domain or UI layers.
4. Prompt parity: positive point, negative point, and bounding box map to the existing port.
5. Image quality: masks retain normalized coordinates and return binary `uint8` data.
6. Temporal behavior: forward and backward propagation preserve frame-number mapping.
7. Interaction latency: master-frame correction remains usable on the target machine.
8. Memory stability: repeated hypotheses and propagation do not grow memory without bound.
9. Recovery: cancellation or model failure leaves the confirmed project state unchanged.

## Representative Shot Set

The first benchmark set must contain short, licensed or internally generated shots covering:

- a clearly separated rigid subject;
- fine boundaries such as hair, fur, foliage, or translucent detail;
- fast motion and motion blur;
- partial and full occlusion followed by reappearance;
- similar-looking distractor objects;
- scale, pose, lighting, and orientation change.

Ground-truth masks are required at minimum for Start, Master, End, occlusion entry/exit, and the
worst-motion frame. Record IoU, boundary F-score, correction count, propagation drift, latency,
peak memory, and failure/recovery behavior.

## Pass Criteria

- No identity switch on the representative shot set.
- Start/Master/End validation frames are mapped correctly in both directions.
- Median master-frame response is at most 2 seconds on the target M1 Pro machine.
- Peak memory stays within the machine's practical interactive budget.
- Low-confidence or failed outputs enter artist review and never overwrite confirmed state.
- At least one candidate demonstrates a complete project save/reload round trip with provenance.

## Execution Order

1. Run `python -m nova_layer.model_evaluation` and retain the generated preflight report.
2. Install the optional PyTorch runtime in the project virtual environment.
3. Verify MPS availability and execute a minimal tensor smoke test.
4. Integrate the SAM 2.1 image predictor behind `InteractiveSegmentationCapability`.
5. Benchmark Hiera Small, then Tiny only if latency or memory fails.
6. Integrate video propagation after the master-frame adapter passes contract tests.
7. Record the recommendation and either promote the adapter or preserve Mock Mode.

## Current Evidence

- PyTorch 2.7.1 MPS tensor smoke test: passed on the target M1 Pro.
- SAM 2.1 Hiera Tiny model load and mask prediction: passed.
- Synthetic 640 × 360 steady-state prompt refinement: 0.022 seconds after warm-up.
- Real-footage quality, high-resolution memory, and temporal propagation: pending licensed footage.
- Five-frame SAM 2.1 MPS bidirectional propagation smoke test: passed in 11.962 seconds cold.
- Temporal confidence calibration and real-footage propagation quality: pending licensed footage.
- Procedural translation endpoint IoU: 1.0000 in both directions.
- Procedural occlusion-recovery endpoint IoU: 1.0000 in both directions.
- Similar-distractor minimum endpoint IoU: 0.9371; maximum confidence gap: 0.0608.
- Motion-blur minimum endpoint IoU: 0.9998.
- Full-occlusion recovery minimum endpoint IoU: 0.9998.
- Frame-exit empty masks: IoU 1.0000 with NOVA confidence capped at 0.4000, forcing review.
- Browser Depth/Pose transport smoke (64×64 synthetic RGB): passed on WebGPU + TensorFlow.js WebGL.
- Deterministic Depth/Pose mock smoke with temporal gates and self-comparison: passed.
- Licensed real-footage Depth/Pose accuracy, latency, and temporal stability: pending.

## External References

- SAM 2 official repository: https://github.com/facebookresearch/sam2
- SAM 3 official repository: https://github.com/facebookresearch/sam3
- PyTorch MPS backend: https://docs.pytorch.org/docs/stable/notes/mps
