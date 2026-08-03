# NOVA Layer EXR Interoperability

**Status:** Active (Phase 10C audit — documented)  
**Audience:** Developer, Maintainer, QA  
**Scope:** External-tool behaviour of NOVA-authored OpenEXR, especially
`scene_openexr_sequence` (Scene Linear) vs `openexr_sequence` (Current Render Look).

This document records the Phase 10C interoperability audit. Pixel and export
contracts remain authoritative in [`COLOR_PIPELINE.md`](COLOR_PIPELINE.md).
Header metadata conventions are implemented in `nova_layer.export.scene_exr`
(Phase 10B).

---

## 1. Verification environment

| Component | Status on audit host |
|---|---|
| OpenEXR Python **3.4.13** (project `.venv`, pin `OpenEXR>=3.3,<4`) | Available — primary automated probe |
| **RV** (`/Applications/RV.app`, `rvls -x -yaml`) | Available — host listing probe |
| OpenImageIO Python | **Not installed** — skipped |
| `oiiotool` | **Not on PATH** — skipped |
| `exrheader` | **Not on PATH** — skipped |
| Nuke | **Not installed** — skipped |
| DJV | **Not installed** — skipped |

Audit method:

1. Generate a synthetic **4×4** Scene Linear EXR via `write_scene_openexr_rgba`
   with typed `SceneExrHeaderMetadata`.
2. Generate a matching Current Render Look EXR via `write_openexr_rgba` (uint8→half).
3. Round-trip with OpenEXR Python (channels, compression, pixels, `nova:*` attrs).
4. List with RV `rvls -x -yaml` when available.
5. Treat missing third-party CLIs as optional skips (see CI policy).

---

## 2. Compatibility matrix

| Tool | Result | Notes |
|---|---|---|
| OpenEXR Python 3.4.13 | **PASS** | HALF RGBA ZIP write/read; all authored `nova:*` keys round-trip |
| RV (`rvls -x -yaml`) | **PASS** | Opens file; reports ZIP, 4×4, HALF (16-bit float), FPS, full `EXR/nova:*` set |
| OpenImageIO Python | **SKIP** | Missing in project `.venv` |
| `oiiotool` | **SKIP** | Binary not available on audit host |
| `exrheader` | **SKIP** | Binary not available on audit host |
| Nuke | **SKIP** | Not installed |
| DJV | **SKIP** | Not installed |

Re-run probes on artist / CI machines when the skipped tools become available.

---

## 3. Pixel contract (Scene Linear EXR)

| Property | Contract |
|---|---|
| Channels | Named **R, G, B, A** (OpenEXR may list them alphabetically as A,B,G,R) |
| Pixel type | **HALF** (default; float optional in writer API) |
| Compression | **ZIP** (default) |
| RGB | File-native scene float values (no display/view/exposure bake; no 0–1 remapping) |
| Alpha | Mask `/ 255` → float; **`alpha_mode = straight`** |
| Premultiply | **`premultiplied = false`** (header int `0`) |
| Alpha = 0 | **RGB preserved** (not forced to zero) |
| Precision | Scene float32 → half → float32 round-trip within **half tolerance** |
| Encoding tag | `nova:pixelEncoding` / manifest `pixel_encoding = file_native_scene_half` |

Current Render Look EXR (`openexr_sequence`) remains **uint8-derived** half
(`pixel_encoding = display_or_source_uint8_scaled`) and is **not** scene-linear.

---

## 4. Header metadata

### Authority

- **`manifest.json` is authoritative** for export color/alpha/provenance.
- OpenEXR header attributes are a **convenience copy** for standalone file hand-off.
- Header write is **best-effort**: a failed custom attribute must not fail pixel export.

### Standard / general

| Key | Typical value |
|---|---|
| `software` | `NOVA Layer` (UTF-8 **bytes** on disk) |
| `framesPerSecond` | Shot frame rate (float) |

### NOVA custom (`nova:*`)

| Key | Meaning |
|---|---|
| `nova:colorPolicy` | `"scene"` for Scene Linear export |
| `nova:sceneLinear` | `1` (int) — display/output transform **not** baked into pixels |
| `nova:sourceColorSpace` | File/OIIO (or unspecified) tag on source SceneFrame |
| `nova:interpretationColorSpace` | Project/workspace interpretation ICS |
| `nova:premultiplied` | `0` |
| `nova:alphaMode` | `"straight"` |
| `nova:pixelEncoding` | `"file_native_scene_half"` |
| `nova:sourceRenderVersion` | Smart Layer render version (int) |
| `nova:sourceFingerprint` | Media fingerprint (not a filesystem path) |
| `nova:projectId` / `nova:shotId` / `nova:layerId` | IDs only |
| `nova:frameNumber` | Per-frame number |
| `nova:writerVersion` | e.g. `10B.1` |

`scene_linear=true` does **not** assert ACEScg or any OCIO `scene_linear` role.
Keep **source** and **interpretation** color spaces as separate fields — never merge
into a single ambiguous `inputColorSpace` in the header.

Chromaticities / adoptedNeutral / white-point injection are **out of scope**
(unreliable without verified evidence; see RV caveat below).

---

## 5. RV caveat (host color inference)

When chromaticities are absent, **RV may infer**:

- `ColorSpace/Primaries: Rec709`
- `ColorSpace/Transfer: Linear`

Observed on **both** Scene Linear and Look-baked samples during the audit.

**This inference is not written by NOVA** and does **not** replace:

- `nova:interpretationColorSpace` (project ICS), or
- `nova:sourceColorSpace` (file/source tag), or
- the export **manifest** color fields.

Operator checklist in RV / similar hosts:

1. Prefer `EXR/nova:sourceColorSpace` and `EXR/nova:interpretationColorSpace`.
2. Prefer `nova:sceneLinear` / `nova:pixelEncoding` over host ColorSpace guesses.
3. Prefer `manifest.json` when the export package is available.

---

## 6. Look-baked vs Scene Linear

| Aspect | Current Render Look (`openexr_sequence`) | Scene Linear (`scene_openexr_sequence`) |
|---|---|---|
| UI label | OpenEXR — Current Render Look | OpenEXR — Scene Linear |
| Pixels | PREVIEW/SOURCE render RGB as uint8 → `/255` → half | File-native scene float RGB + mask alpha → half |
| `scene_linear` | `false` | `true` |
| `pixel_encoding` | `display_or_source_uint8_scaled` | `file_native_scene_half` |
| `nova:*` header attrs | **Not** applied (Phase 10C scope) | Applied (Phase 10B) |
| `software` / FPS | Typically absent | Present when authored |
| Viewer look | Baked into uint8 render | **Not** applied |

How to tell them apart quickly: presence of `nova:sceneLinear=1` and
`nova:pixelEncoding=file_native_scene_half`, plus unmatched negative / >1 RGB in
Scene Linear samples.

---

## 7. Security / privacy

Header sanitization policy (Phase 10B):

- **Do not** store absolute source paths, project package paths, OCIO config absolute
  paths, home paths, usernames, or raw environment blobs in EXR headers.
- Allowed: fingerprints, UUIDs/ids, basename tokens, color-space names, render
  version, frame number, FPS, software identity.
- Phase 10C audit scan: **no** `/Users/…`, home, or username leakage in Scene Linear
  header string/bytes attributes.

Absolute `config_path` may still appear in **manifest** diagnostics for session
identity; that is separate from EXR header policy. Prefer sanitized / relative
values for shared packages when practical.

---

## 8. CI policy

| Layer | Policy |
|---|---|
| Minimum / required | OpenEXR Python round-trip (channels, half RGB/A, `nova:*` keys, sanitization) already covered by Phase 10A/10B tests |
| Optional | `pytest.importorskip` / `shutil.which` for OpenImageIO, `oiiotool`, `exrheader` |
| Nightly / manual | RV `rvls`, Nuke, DJV smoke when installed on artist or release machines |
| Missing tools | **Skip**, do not fail the required suite |

Future candidates: automated `oiiotool --info -v` capture, Nuke Reader metadata dump,
DJV info — behind optional markers.

---

## 9. Fixture policy

| Path | Policy |
|---|---|
| `02_Source/tmp/phase10c_interop/` | Local audit **artifact** directory |
| Git | **Do not commit** generated `.exr`, `rvls_*.yaml`, or `audit_report.json` |
| Tests | Recreate fixtures under pytest `tmp_path` (or equivalent) when needed |

Regenerate locally (example):

```bash
cd 02_Source
QT_QPA_PLATFORM=offscreen .venv/bin/python -c "
from pathlib import Path
import numpy as np
from nova_layer.export.scene_exr import SceneExrHeaderMetadata, write_scene_openexr_rgba
out = Path('tmp/phase10c_interop'); out.mkdir(parents=True, exist_ok=True)
rgba = np.zeros((4,4,4), dtype=np.float32); rgba[...,3] = 1
meta = SceneExrHeaderMetadata(
    color_policy='scene', scene_linear=True,
    source_color_space='ACEScg', interpretation_color_space='Linear Rec.709',
    premultiplied=False, alpha_mode='straight',
    pixel_encoding='file_native_scene_half', source_render_version=1,
    source_fingerprint='fp', project_id='p', shot_id='s', layer_id='l',
    frame_number=0, frames_per_second=24.0,
)
write_scene_openexr_rgba(out / 'scene_linear_4x4.exr', rgba, metadata=meta)
"
```

---

## 10. Related documents & code

| Resource | Role |
|---|---|
| [`COLOR_PIPELINE.md`](COLOR_PIPELINE.md) | Authoritative pixel / export contracts |
| [`README.md`](README.md) | Implementation doc index |
| `nova_layer.export.scene_exr` | Scene Linear writer + header serializer |
| `nova_layer.export.smart_layer` | Export formats + streaming scene path |
| `02_Source/tests/test_phase_10b_exr_header_metadata.py` | Header / sanitization / consistency tests |
| `02_Source/tests/test_phase_10a_true_scene_export.py` | Scene Linear pixel / manifest tests |

---

## 11. Audit conclusion

- Scene Linear OpenEXR from NOVA opens correctly under **OpenEXR Python** and **RV**.
- No blocking writer defect found for the checked tools.
- Document host Rec709/Linear inference; trust `nova:*` + manifest.
- Optional DCC tooling remains a follow-up verification track, not a gate for the
  existing OpenEXR Python automated suite.
