# NOVA Layer Color Pipeline

**Status:** Active (Phase 8 / Phase 9A lock / Phase 10A–10B / Phase 10C-1 contracts)  
**Audience:** Developer, Maintainer  
**Scope:** Pixel contracts, processing color policies, raw/preview/source caches, Smart Layer render/export color metadata.

This document records the color pipeline completed through Phase 8, with True Scene
export (10A), SceneFrame color-space tagging (10B), and working-space **contracts**
(10C-1). System-layer architecture remains in `ARCHITECTURE.md`. This file is the
authority for viewer / processing / render **pixel contracts** and cache behaviour.

Authority for the SOURCE bake identity string:

- Code: `nova_layer.app.processing_frames.SOURCE_TRANSFORM_VERSION`
- Current value: `source_legacy_srgb_v1`

Working-space converter identity (no pixel convert in 10C-1):

- Code: `nova_layer.app.working_space.WORKING_CONVERTER_VERSION`
- Current value: `working_scene_v1`

If the code constant changes, update this document and golden tests together.

---

## A. Pixel contracts

### SceneFrame (file-native float)

| Field | Contract |
|---|---|
| Type | `float32` RGB via `SceneFrame` |
| Pixels | **File-native** floating RGB from EXR/OIIO (sanitize only) |
| Transforms | No display / view / exposure; **no** working-space conversion |
| `color_space` | Interpretation *tag* from file metadata or user — **not** a converted result |
| `color_space_source` | `oiio` / `user` / `unspecified` |
| Does **not** guarantee | OCIO `scene_linear` role, specific primaries, or project ICS conversion |

### PREVIEW

| Field | Contract |
|---|---|
| Type | `uint8` RGB (`H×W×3`) |
| Source | Viewer path via `FrameDecodeService.get_preview_frame` / `PreviewPipeline.read_frame` |
| Transforms | Active session Exposure + Display + View (OCIO or Legacy composition) |
| `input_color_space` | **PREVIEW interpretation** only — OCIO `DisplayViewTransform` source |
| Tag policy | SceneFrame.`color_space` is **never** auto-substituted for `input_color_space` |
| Intent | What the artist sees in the Viewer |
| Cache | Preview cache (keyed by path, frame, transform identity) + raw reuse for EXR |

### SOURCE

| Field | Contract |
|---|---|
| Type | `uint8` RGB (`H×W×3`) |
| Source | `get_processing_frame(..., policy=SOURCE)` / source cache |
| Transforms | **Independent of Viewer Exposure / Display / View** |
| EXR | Scene float → fixed Legacy linear→sRGB bake (`SOURCE_TRANSFORM_VERSION = source_legacy_srgb_v1`, exposure 0) |
| Gamut caveat | Fixed bake assumes Rec.709-linear / sRGB-linear family; wide-gamut tags (ACEScg, Linear P3, Rec.2020, …) emit a diagnostic warning — **pixels are unchanged in Phase 10B** |
| Non-EXR | Raster uint8 RGB (no viewer transform) |
| Intent | Reproducible capability / propagation / opt-in final render input |
| Note | SOURCE is **not** scene-linear; it is a stable processing raster |

### SCENE

| Field | Contract |
|---|---|
| Type | `SceneFrame` (file-native float RGB + tags) |
| Source | EXR + OpenImageIO through `get_scene_frame` / raw cache |
| Transforms | No display transform; no exposure; tag returned as decoded |
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
| True Scene EXR export | — | Opt-in `scene_openexr_sequence`: export-time file-native float + mask; EXR+OIIO only |
| Mask-only paths | N/A | Masks are alpha/matte; color policy does not apply |

`ProcessingColorPolicy.SCENE` is not a Smart Layer render policy. Render APIs reject SCENE.
True Scene pixels are produced only by the dedicated export format.

---

## C. Cache architecture

```text
EXR (OIIO)
  → SceneFrameSource / ImageSequenceReader  (+ optional color_space tag)
  → RawFrameCache          (float32 SceneFrame; key = path, frame)
  → (Phase 10C-2+) WorkingSceneCache  (working float; key = path, frame, WorkingTransformIdentity)
  → Exposure + DisplayTransform (session; PREVIEW uses input_color_space today)
  → PreviewFrameCache      (PREVIEW uint8)

RawFrameCache
  → fixed SOURCE Legacy linear→sRGB (exposure 0)
  → SourceFrameCache       (SOURCE uint8, key includes SOURCE_TRANSFORM_VERSION)
```

| Event | Raw | Preview | Source |
|---|---|---|---|
| `input_color_space` / display / view / exposure change | **keep** | **clear** | **keep** |
| Reader / media change | clear | clear | clear |

RawFrameCache key remains `(path, frame)` — ICS changes do **not** clear raw.
SceneFrame tags are stored on the cached frame and survive copy-on-get.

Non-EXR media skip the raw float path: PREVIEW/SOURCE both consume uint8 rasters
from the reader (SOURCE without viewer bake; PREVIEW with session transform when
the reader applies it — current ImageSequenceReader/PyAv keep raster for SOURCE).

Cache objects:

| Cache | Payload | Primary consumers |
|---|---|---|
| Raw | float32 EXR `SceneFrame` (+ tags) | SCENE API, PREVIEW bake, SOURCE bake, True Scene |
| Working (10C-1 skeleton) | float32 `WorkingSceneFrame` | Not wired — PREVIEW/SOURCE/export follow-on |
| Preview | PREVIEW uint8 | Viewer, validation, BG preview, default render |
| Source | SOURCE uint8 | SAM, skeleton, propagation, SOURCE render |

### Working + Source v1 invalidation contract (Phase 10C-1 documented; wired in 10C-2+)

| Event | Raw | Working | Preview | Source v1 |
|---|---|---|---|---|
| Exposure | **keep** | **keep** | **clear** | **keep** |
| Display / View | **keep** | **keep** | **clear** | **keep** |
| Interpretation CS (`input_color_space`) | **keep** | **invalidate if used as fallback source** | **clear** | **keep** |
| Working CS | **keep** | **clear** | **clear** | **keep** |
| OCIO Config | **keep** | **clear** | **clear** | **keep** |
| Media relink | **clear** | **clear** | **clear** | **clear** |

Phase 10C-1 ships `WorkingSpaceSettings`, `WorkingTransformIdentity`,
`WorkingSceneFrame`, and `WorkingSceneCache` **without** connecting them to
`PreviewPipeline` or converting pixels.

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
4. **`scene_openexr_sequence` (Phase 10A/10B)** is a separate opt-in True Scene export:
   - Export-time compose of file-native `SceneFrame` float RGB + Smart Layer mask
   - **No working-space conversion** in this phase (`working_color_space=null`,
     `color_transform_applied=false`, `scene_display_transformed=false`)
   - Metadata separation:
     - `source_color_space` — SceneFrame tag (`"unspecified"` if missing)
     - `interpretation_color_space` — resolved project/workspace `input_color_space`
     - `export_color_space` — equals `source_color_space` (not forced equal to interpretation)
     - `input_color_space` — backward-compatible alias of interpretation
   - Straight alpha (`A = mask/255`, RGB preserved where A=0)
   - half OpenEXR with **no** 0–1 remapping; `pixel_encoding=file_native_scene_half`
   - Requires EXR image sequence + OpenImageIO
   - Does **not** change package render PNGs or render-time color policy
5. **Metadata sidecar:** `renders/vXXXX/color_policy.json` (project schema unchanged)
   describes the uint8 render; True Scene export writes its own manifest fields and does
   not overwrite that sidecar.
6. **Alpha for uint8 compose:** `compose_rgba` — RGB from frame, A from mask,
   `premultiplied=false`.
7. **`ProcessingColorPolicy.SCENE` remains rejected for Smart Layer render.**
   True Scene is export-only.
8. **Canonical working-space conversion** is staged:
   - **Phase 10C-1:** contracts / identity / diagnostics / cache skeleton only
     (`WorkingSpaceSettings`, `WorkingSceneFrame`, `WorkingSceneCache`);
     `working_enabled=false` by default; **no** source→working pixel convert.
   - **Phase 10C-2+:** optional Working path for PREVIEW, then SOURCE v2 / export.

---

## F. Reproducibility guarantees

| Guarantee | Detail |
|---|---|
| SOURCE processing invariance | Same media + SOURCE bake → bit-identical uint8 across Viewer Exposure/Display/View changes |
| PREVIEW intentional variance | Same media + different Exposure/View → different preview RGB |
| Propagation | Anchor and range decode use SOURCE |
| Export interpretation | Hosts/QA must read render sidecar / export manifest `color_policy` |
| Cache non-pollution | SOURCE put never writes preview cache; transform change does not drop raw/source |
| True Scene fidelity | Exported RGB equals file-native SceneFrame floats (plus mask alpha); tags are metadata only |

---

## Related code

| Area | Module |
|---|---|
| Policy enum / version | `nova_layer.app.processing_frames` |
| SceneFrame / tags | `nova_layer.ports.scene_frames` |
| Working space contracts | `nova_layer.app.working_space` |
| WorkingSceneFrame | `nova_layer.ports.scene_frames.WorkingSceneFrame` |
| WorkingSceneCache | `nova_layer.app.working_scene_cache` |
| SOURCE risk helper | `nova_layer.app.scene_color_space` |
| Pipeline / caches | `nova_layer.app.preview_pipeline` |
| Decode façade | `nova_layer.app.frame_decode_service` |
| Range decode | `nova_layer.app.range_decode` |
| Render metadata | `nova_layer.app.render_color_metadata` |
| True Scene EXR | `nova_layer.export.scene_exr` |
| Controller wiring | `nova_layer.app.project_controller` |
| Alpha compose | `nova_layer.app.preview_extraction.compose_rgba` |
| Export | `nova_layer.export.smart_layer` |
| Golden regression | `02_Source/tests/test_color_pipeline_golden.py` |
