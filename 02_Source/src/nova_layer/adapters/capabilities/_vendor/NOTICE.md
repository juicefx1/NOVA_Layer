"""Third-party depth model code attribution (Phase D3.5).

Vendored sources under ``depth_anything_v2/`` are copied from:

  https://github.com/DepthAnything/Depth-Anything-V2

Upstream repository license: Apache License 2.0
(see ``DEPTH_ANYTHING_V2_LICENSE`` in this directory).

Includes DINOv2 Vision Transformer components that upstream redistributes
under Apache-2.0 (Meta Platforms copyright notices retained in file headers).

NOVA Layer does **not** redistribute Depth Anything V2 model weights in the
Python wheel. Offline checkpoints must be supplied by the operator.

Depth-Anything-V2-Small weights are identified by upstream as Apache-2.0.
Base/Large/Giant weights are CC-BY-NC-4.0 and must not be used as the
NOVA production default.
"""
