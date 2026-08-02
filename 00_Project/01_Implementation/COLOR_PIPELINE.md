# NOVA Layer Color Pipeline

**Status:** Active (Phase 8 / Phase 9A lock)  
**Audience:** Developer, Maintainer  
**Scope:** Pixel contracts, processing color policies, raw/preview/source caches, Smart Layer render/export color metadata.

This document records the color pipeline completed through Phase 8. System-layer
architecture remains in `ARCHITECTURE.md`. This file is the authority for
viewer / processing / render **pixel contracts** and cache behaviour.

Authority for the SOURCE bake identity string:

- Code: `nova_layer.app.processing_frames.SOURCE_TRANSFORM_VERSION`
- Current value: `source_legacy_srgb_v1`

If the code constant changes, update this document and golden tests together.

---

## A. Pixel contracts

### PREVIEW

| Field | Contract |
|---|---|
| Type | `uint8` RGB (`H×W×3`) |
| Source | Viewer path via `FrameDecodeService.get_preview_frame` / `PreviewPipeline.read_frame` |
| Transforms | Active session Exposure + Display + View (OCIO or Legacy composition) |
| Intent | What the artist sees in the Viewer |
| Cache | Preview cache (keyed by path, frame, transform identity) + raw reuse for EXR |

### SOURCE

| Field | Contract |
|---|---|
| Type | `uint8` RGB (`H×W×3`) |
| Source | `get_processing_frame(..., policy=SOURCE)` / source cache |
| Transforms | **Independent of Viewer Exposure / Display / View** |
| EXR | Scene float → fixed Legacy linear→sRGB bake (`SOURCE_TRANSFORM_VERSION = source_legacy_srgb_v1`, exposure 0) |
| Non-EXR | Raster uint8 RGB (no viewer transform) |
| Intent | Reproducible capability / propagation / opt-in final render input |
| Note | SOURCE is **not** scene-linear; it is a stable processing raster |

### SCENE

| Field | Contract |
|---|---|
| Type | `float32` RGB(A) via `SceneFrame` |
| Source | EXR + OpenImageIO through `get_scene_frame` / raw cache |
| Transforms | No display transform; no exposure |
| Range decode | Not supported (`decode_frame_range` rejects SCENE) |
| Intent | Raw EXR access only — not used as general processing/render range policy |

---

## B. Feature policy matrix

| Feature | Default policy | Optional / notes |
|---|---|---|
| Viewer | PREVIEW | Session Exposure / Display / View |
| Validation preview | PREVIEW | `get_preview_frame` |
| Extraction preview | PREVIEW | `get_preview_frame` |
| Background Removal preview | PREVIEW | Single-frame; no `color_policy` API |
| SAM hypothesis | SOURCE | Via `_get_source_processing_frame` |
| SAM correction | SOURCE | Same |
| Skeleton retracking / fusion | SOURCE | Same |
| Propagation (anchor + range) | SOURCE | `decode_frame_range(..., policy=SOURCE)` / `_decode_shot_frames` default |
| Background Removal clip | PREVIEW | Opt-in SOURCE via `color_policy=` |
| Smart Layer render | PREVIEW | Opt-in SOURCE via `color_policy=` |
| Export (host / assets) | *(preserve render)* | PNG / uint8 EXR / MOV copy; no re-decode |
| True Scene EXR export | — | Opt-in `scene_openexr_sequence`: export-time raw+mask; EXR+OIIO only |
| Mask-only paths | N/A | Masks are alpha/matte; color policy does not apply |

`ProcessingColorPolicy.SCENE` is not a Smart Layer render policy. Render APIs reject SCENE.
True Scene pixels are produced only by the dedicated export format.

---

## C. Cache architecture

```text
EXR (OIIO)
  → SceneFrameSource / ImageSequenceReader
  → RawFrameCache          (float32 SceneFrame)
  → Exposure + DisplayTransform (session)
  → PreviewFrameCache      (PREVIEW uint8)

RawFrameCache
  → fixed SOURCE Legacy linear→sRGB (exposure 0)
  → SourceFrameCache       (SOURCE uint8, key includes SOURCE_TRANSFORM_VERSION)
```

Non-EXR media skip the raw float path: PREVIEW/SOURCE both consume uint8 rasters
from the reader (SOURCE without viewer bake; PREVIEW with session transform when
the reader applies it — current ImageSequenceReader/PyAv keep raster for SOURCE).

Cache objects:

| Cache | Payload | Primary consumers |
|---|---|---|
| Raw | float32 EXR `SceneFrame` | SCENE API, PREVIEW bake, SOURCE bake |
| Preview | PREVIEW uint8 | Viewer, validation, BG preview, default render |
| Source | SOURCE uint8 | SAM, skeleton, propagation, SOURCE render |

---

## D. Cache invalidation

| Event | Raw | Preview | Source |
|---|---|---|---|
| Exposure / Display / View change (`set_display_transform`) | **keep** | **clear** (count/bytes → 0) | **keep** |
| Reader / media change (`set_reader`, default) | clear | clear | clear |
| Project close / package change (`clear` / clear_all) | clear | clear | clear |
| Color settings applied as new display transform | keep | clear | keep |
| `SOURCE_TRANSFORM_VERSION` / source bake identity change | keep* | keep | **miss** (new key; old entries unused) |
| Explicit `clear_preview_cache` | keep | clear | keep |

\* Raw pixels do not depend on SOURCE transform version; only source-cache keys do.

Lifetime counters such as `raw_decodes` / `preview_generations` / hits-misses are
lifetime pipeline stats and are **not** reset by preview-only clears.

---

## E. Render / export contract

1. **Render-time `color_policy` is the final pixel contract for uint8 Smart Layer renders.**  
   PREVIEW bakes the viewer look; SOURCE bakes the fixed source path.
2. **Default export formats (`png_sequence`, `openexr_sequence`, `rgba_mov`) do not
   re-decode media** and do not re-apply color policy. They copy or convert existing
   render PNG (uint8-derived EXR / MOV).
3. **`openexr_sequence` is not true scene-linear.** Manifest records
   `scene_linear=false` and
   `pixel_encoding=display_or_source_uint8_scaled`.
4. **`scene_openexr_sequence` (Phase 10A)** is a separate opt-in True Scene export:
   - Export-time compose of `SceneFrame` (OIIO float RGB) + Smart Layer mask
   - Straight alpha (`A = mask/255`, RGB preserved where A=0)
   - half OpenEXR with **no** 0–1 remapping of scene RGB
   - Requires EXR image sequence + OpenImageIO (no Pillow / non-EXR / video fallback)
   - Does **not** change package render PNGs or render-time color policy
   - Manifest: `scene_linear=true`, `export_mode=compose_scene`,
     `pixel_encoding=scene_linear_half`, look fields null
5. **Metadata sidecar:** `renders/vXXXX/color_policy.json` (project schema unchanged)
   describes the uint8 render; True Scene export writes its own manifest fields and does
   not overwrite that sidecar.
6. **Alpha for uint8 compose:** `compose_rgba` — RGB from frame, A from mask,
   `premultiplied=false`.
7. **`ProcessingColorPolicy.SCENE` remains rejected for Smart Layer render.**
   True Scene is export-only.

---

## F. Reproducibility guarantees

| Guarantee | Detail |
|---|---|
| SOURCE processing invariance | Same media + SOURCE bake → bit-identical uint8 across Viewer Exposure/Display/View changes |
| PREVIEW intentional variance | Same media + different Exposure/View → different preview RGB |
| Propagation | Anchor and range decode use SOURCE |
| Export interpretation | Hosts/QA must read render sidecar / export manifest `color_policy` |
| Cache non-pollution | SOURCE put never writes preview cache; transform change does not drop raw/source |

---

## Related code

| Area | Module |
|---|---|
| Policy enum / version | `nova_layer.app.processing_frames` |
| Pipeline / caches | `nova_layer.app.preview_pipeline` |
| Decode façade | `nova_layer.app.frame_decode_service` |
| Range decode | `nova_layer.app.range_decode` |
| Render metadata | `nova_layer.app.render_color_metadata` |
| Controller wiring | `nova_layer.app.project_controller` |
| Alpha compose | `nova_layer.app.preview_extraction.compose_rgba` |
| Export | `nova_layer.export.smart_layer` |
| Golden regression | `02_Source/tests/test_color_pipeline_golden.py` |
