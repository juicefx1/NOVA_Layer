# Production Depth Adapter License Record (Phase D3.5)

Date reviewed: 2026-08-10

## Selected production default

- Model: Depth Anything V2 Small (ViT-S / `vits`)
- Checkpoint filename: `depth_anything_v2_vits.pth`
- NOVA `model_id`: `depth_anything_v2_small`
- Upstream: https://github.com/DepthAnything/Depth-Anything-V2
- Upstream code license: Apache-2.0 (vendored under
  `src/nova_layer/adapters/capabilities/_vendor/` with LICENSE + NOTICE)
- Upstream Small weights license: Apache-2.0 (per official README LICENSE section)
- Base / Large / Giant: CC-BY-NC-4.0 — **excluded** from NOVA production default

## Weight distribution policy

- Weights are **not** bundled in the NOVA wheel
- No HuggingFace / torch.hub / CDN auto-download in D3.5
- Operator supplies offline checkpoint via:
  1. `NOVA_DEPTH_MODEL_PATH`
  2. `~/.nova_layer/models/depth/depth_anything_v2_vits.pth`
  3. `~/Library/Application Support/NOVA Layer/models/depth/depth_anything_v2_vits.pth`
- Optional integrity: `NOVA_DEPTH_MODEL_SHA256` (verify only when configured; do not invent digests)

## Training-data commercial risk

An upstream question about training-dataset commercial risk for Depth Anything V2
Small remains an open counsel item (also noted in `06_BROWSER_MODEL_LICENSE_RECORD.md`).
This record is an engineering gate, not legal advice.

## Browser path

The browser `onnx-community/depth-anything-v2-small` provider remains a separate
Depth/Pose fusion pathway and is **not** the native Depth Assist production default.
