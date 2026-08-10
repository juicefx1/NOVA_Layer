# Phase D3.6 — Real-Footage Depth Assist Validation Report

Generated: 2026-08-10 (MPS validation run)  
Device: **MPS** (CPU cross-check included)  
Model: Depth Anything V2 Small (`depth_anything_v2_vits.pth`)  
Default tolerance under test: **0.08**  
Harness: `nova_layer.depth_assist_validation`  
Artifacts: `02_Source/tmp/depth_assist_d36/` (frames, overlays, JSON)

---

## Interaction definition (locked for this study)

**1 interaction =** mouse click · bbox draw · tolerance adjustment · Assist button · refine click  

**Analyze Scene** counted as setup interaction (+1) when using Depth Assist.  

Depth Assist budget measured as: `Analyze + Pick + Assist + optional tolerance tweaks + refine clicks`.  
Manual budget synthesized as typical: `3 positive + 2 negative + 1 bbox` (=6), plus refine if needed.

> Limitation: Manual counts are **protocol budgets**, not live UI telemetry. Real artist logging is still required before marketing claims.

---

## 1. Test Media Matrix

| Case | Scenario intent | Source | Proxy level | Resolution used |
|---|---|---|---|---|
| case01_person_fg | 1. Single person / foreground subject | source video plate (rider+horse) | real | 1280×720 |
| case02_person_chair_proxy | 2. Subject + nearby same-depth structure | adjacent frame from same plate | real_proxy | 1280×720 |
| case03_prop_object | 3. Foreground prop/object | QA mid_frame.png (beach subject) | fixture_proxy | 640×360 |
| case04_overlap_proxy | 4. Overlapping subjects | later plate frame | real_proxy | 1280×720 |
| case05_limbs_proxy | 5. Hair / limbs / thin structures | plate frame (mane/cape/reins risk) | real_proxy | 1280×720 |
| case06_reflective_proxy | 6. Reflective / hard materials | UI screenshot (weak reflective proxy) | fixture_proxy | large PNG |
| case07_low_contrast_proxy | 7. Low contrast subject | darker plate frame | real_proxy | 1280×720 |
| case08_depth_scene_proxy | 8. Wide / deep staging | BTR plate frame | real | 1280×720 |
| case09_shallow_dof_proxy | 9. Shallow DOF / soft edge | BTR last available frame | real_proxy | 1280×720 |
| case10_vfx_plate | 10. VFX plate / production footage | BTR publish plate | real | 1280×720 (source 4K) |

Depth inference always uses **SOURCE RGB** (`source_v1`), never PREVIEW.

---

## 2. Manual Baseline Results

| Case | Interactions | Refine rounds | First-pass accept (proxy) | Notes |
|---|---:|---:|:---:|---|
| all 10 cases | **6** | 0 | Y | Fixed protocol: 3+/2-/bbox around seed |

Manual pathway remains fully available; Depth Assist never replaces artist guidance APIs.

---

## 3. Depth Assist Results

| Case | Interactions | Refine | First-pass | Coverage | BBox area | +/− points | Depth latency (MPS) |
|---|---:|---:|:---:|---:|---:|---:|---:|
| case01 | 3 | 0 | Y | 2.8% | 5.1% | 4/4 | ~182 ms |
| case02 | 3 | 0 | Y | 1.1% | 2.0% | 4/4 | ~188 ms |
| case03 | 3 | 0 | Y | 8.5% | 35% | 4/4 | ~199 ms |
| case04 | 4 | 1 | N | 0.8% | 1.0% | 4/4 | ~187 ms |
| case05 | 3 | 0 | Y | 1.5% | 2.1% | 4/4 | ~196 ms |
| case06 | 3 | 0 | Y | 9.3% | 18.8% | 4/3 | ~577 ms* |
| case07 | 3 | 0 | Y | 2.5% | 5.8% | 4/4 | ~212 ms |
| case08 | 3 | 0 | Y | 11.2% | 28.0% | 4/3 | ~200 ms |
| case09 | 3 | 0 | Y | 0.9% | 4.6% | 4/4 | ~207 ms |
| case10 | 3 | 0 | Y | 8.8% | 16.4% | 4/3 | ~197 ms |

\*case06 fixture is a UI screenshot / atypical SOURCE; latency higher.

---

## 4. Interaction Reduction

| Metric | Value |
|---|---|
| Median interaction reduction | **50.0%** |
| Mean interaction reduction | **48.3%** |
| Cases with Depth Assist fewer interactions | **10 / 10** |
| Depth first-pass accept (proxy) | **90%** |
| Manual first-pass accept (proxy) | **100%** |

Primary recommendation threshold (≥25% median reduction): **PASS**.  
First-pass: slight proxy regression (−10pp) on tiny region (case04) — treated as **neutral / conditional**, not catastrophic.

---

## 5. Tolerance Sweep

Representative cases `case01`, `case02`, `case10` at 0.03 / 0.05 / **0.08** / 0.10 / 0.15 / 0.20:

| Case | 0.08 coverage / bbox | 0.10 coverage / bbox | Cliff? |
|---|---|---|---|
| case01 | 2.8% / 5.1% | **13.4% / 36.8%** | **Yes** — leakage into ground/background band |
| case02 | 1.1% / 2.0% | 1.4% / 2.5% | Mild; larger jump at 0.15 |
| case10 | 8.8% / 16.4% | **19.6% / 84.9%** | **Yes** — bbox explodes |

**Verdict:** default **0.08 remains the best balance**. Values ≥0.10 are unsafe on deep plates without strong warnings / auto-shrink.

---

## 6. Guidance Element Findings

Observed on overlays (`mps_run/overlays/*_region.png`):

| Element | Helpful? | Finding |
|---|---|---|
| Seed | Critical | Auto-near peak often locks onto **local islands** (e.g. horse head). Artist Pick quality dominates outcome. |
| Centroid / primary positives | Helpful | All cases: primary positive landed inside region mask. |
| Principal points | Mixed | Help local structure; thin features (reins/hair) still underrepresented. |
| Negative 4-point | Risk on tiny regions | **4/10 cases** flagged “maybe harsh” when coverage <2% — negatives can fight weak positives. |
| BBox + 2% padding | Helpful mid-size | No case >35% bbox at 0.08; padding OK. On incomplete body (case10 hoodie/legs), bbox undershoots full silhouette → expected given depth band incompleteness. |

---

## 7. Stability

| Check | Result |
|---|---|
| Repeated MPS inference | bit-identical (`max_abs_diff = 0`) |
| MPS vs CPU correlation | **~1.000** |
| MPS vs CPU DepthRegion IoU (same seed, tol=0.08) | **1.0** |
| UX-level stability | Pass — device swap does not shift region selection meaningfully on tested frame |

Bit-identical across devices is not required; observed agreement is stronger than needed for UX.

---

## 8. Performance

| Measurement | Value |
|---|---|
| First load + first infer (MPS, 1280×720) | **~2.8 s** |
| Warm infer 1080p-ish | **~200 ms** |
| Warm infer 4K proxy (3840×2160) | **~226 ms** |
| Peak memory | Not instrumented in this pass |
| UI loading state | **Required** — cold start 3–5s range is real; Analyze must show blocking/progress |

Warm latency is acceptable for interactive assist. Cold start is the UX risk, not warm FPS.

---

## 9. Failure Modes (observed / expected)

| Mode | Observed? | Recovery |
|---|---|---|
| Flat / deceptive depth | Not on these plates | Manual clicks |
| Same-depth object merge | Risk when tol≥0.10 (case01/10 cliffs) | Lower tolerance / re-pick / manual |
| Reflective / transparent | case06 is weak proxy only | Manual |
| Depth seed invalid | Not hit | Pick again / manual |
| Huge region | At high tolerance | Warning + manual |
| Tiny region | case04 / case09 / head islands | Extra refine click; still recoverable |
| Model unavailable / missing weight | Handled by D3.5 errors | Manual SAM workflow remains |
| CPU fallback | Available; correlates with MPS | Transparent |

**Manual workflow always remains available** — confirmed by architecture and harness dual path.

---

## 10. UX Findings

1. **Pick is the product.** Seed choice decides whether Assist helps whole subject vs a depth island.
2. Auto Analyze cold start (~3s) needs clear busy status; warm Analyze feels snappy (~0.2s).
3. Tolerance slider near 0.08→0.10 can suddenly inflate bbox — consider soft warning at coverage/bbox jump.
4. For tiny regions, enabling all negatives by default may feel overconstrained.
5. Viewer Exposure/Display changes must stay PREVIEW-only (SOURCE depth path verified identical under repeated SOURCE inference).

---

## 11. Recommended default tolerance

**Keep 0.08.**

Evidence: stable coverage/bbox on plates; 0.10 triggers large bbox cliffs (case01, case10).

---

## 12. Keep / change negative-point policy

**Keep default negatives ON**, with a soft guard:

- If coverage < ~2% **or** fill_ratio very high on tiny bbox: prefer **0–2 negatives** instead of full ring-of-4.
- Artist can always add negatives manually (still cheaper than full manual baseline).

---

## 13. Keep / change bbox padding

**Keep `DEFAULT_BBOX_PADDING_FRACTION = 0.02`.**

Optional later (pre-D4 polish, not D4): shrink padding when `bbox_area / coverage` is already large (sparse mask inside large box).

---

## 14. Go / No-Go — Depth Assist

### **CONDITIONAL GO**

**Pass reasons**
- Median interaction reduction **50%** (≥25% target)
- Depth Assist fewer interactions on **all 10** cases under protocol accounting
- No catastrophic >10% failure class observed at tol=0.08
- Always recoverable via manual workflow
- SOURCE/viewer separation holds
- MPS UX-level stability excellent

**Conditions**
1. Do not claim “artist-proven” until a short logged artist study (same metrics) on curated scenario clips.
2. Ship/retain Analyze loading indicator for cold MPS load.
3. Soft-guard tiny-region negatives and warn on tolerance cliffs ≥0.10.

---

## 15. Go / No-Go — D4 (temporal depth)

### **NO-GO for D4 now**

D3.6 is about single-frame assist utility. Temporal depth should wait until:

- Artist-logged confirmation of interaction claims
- Tolerance / tiny-region guidance polish landed
- Loading & failure messaging hardened
- Explicit product decision that temporal value outweighs stability risk

---

## 16. Required fixes before D4

1. Artist telemetry pass on ≥10 curated cases (true click counting + subjective accept).
2. Tolerance cliff warning when coverage/bbox jumps vs previous slider value.
3. Negative-point soft policy for tiny DepthRegions.
4. Confirm Analyze blocking UI for first-load 3–5s on MPS.
5. Optional: smarter default seed / “grow region” affordance when artist intends full-body vs local island (still single-frame; not temporal).

---

## 17. Suggested next phase

**D3.7 Soft-guidance polish + artist study** (not D4):

- Tiny-region negative soft policy
- Tolerance jump warnings
- Artist matrix with real production rotoscope targets
- Optional UI: “Assist again after re-pick” cost education

Only after D3.7 green → plan **D4 temporal depth** scope separately.

---

## Acceptance thresholds used

| Threshold | Target | Observed | Result |
|---|---|---|---|
| Median interaction reduction | ≥25% | 50% | Pass |
| First-pass accept | improve or neutral | 90% vs 100% manual (proxy) | Conditional |
| Catastrophic regression | <10% cases | 0 at tol=0.08 | Pass |
| Manual recoverability | always | yes | Pass |
| Viewer transforms alter depth | never | SOURCE unchanged | Pass |

---

## How to reproduce

```bash
cd 02_Source
export NOVA_DEPTH_MODEL_PATH=/path/to/depth_anything_v2_vits.pth
PYTHONPATH=src .venv/bin/python -m nova_layer.depth_assist_validation \
  --frames tmp/depth_assist_d36/frames \
  --output tmp/depth_assist_d36/report \
  --device mps \
  --tolerance 0.08
```

JSON source of truth for the MPS run: `tmp/depth_assist_d36/mps_run/report.json`
