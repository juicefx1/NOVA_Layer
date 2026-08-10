# Phase D3.9 — Artist Study Execution Report

Generated from D3.8 telemetry paired sessions (automated operator study).

## 1. Study Matrix

| # | Case | Scenario | Media fingerprint | Frame |
|---|---|---|---|---|
| 1 | case01_person_fg | 1_single_person_fg | `28b6c665e4c1cb07` | 0 |
| 2 | case02_person_chair_proxy | 2_person_chair_same_depth | `8051bc02d6f74f62` | 0 |
| 3 | case03_prop_object | 3_foreground_prop | `8a42a3f688879f0d` | 0 |
| 4 | case04_overlap_proxy | 4_overlapping_subjects | `aa6da8b41caa5f6c` | 0 |
| 5 | case05_limbs_proxy | 5_hair_limbs_thin | `d7c35edf66294f96` | 0 |
| 6 | case06_reflective_proxy | 6_reflective | `0f66a24841642624` | 0 |
| 7 | case07_low_contrast_proxy | 7_low_contrast | `61b260d4a9ad7bba` | 0 |
| 8 | case08_depth_scene_proxy | 8_wide_deep_scene | `6adb07688ca5949f` | 0 |
| 9 | case09_shallow_dof_proxy | 9_shallow_dof | `caa1507f7187edf7` | 0 |
| 10 | case10_vfx_plate | 10_vfx_greenscreen_like | `3b9860571fc7eeab` | 0 |

## 2. Paired Session Count

**10** paired sessions (Manual + Depth Assist each).

Frame media: D3.6 extracted real/proxy plates under session-local `tmp/` (not committed).
SAM backend: MockSegmentationCapability (identical for both workflows).
Depth backend: Depth Anything V2 Small (MPS).

## 3. Manual Results

| Case | Primary | Setup | Total | Refine | First-pass | Duration s | +clicks | −clicks |
|---|---:|---:|---:|---:|:---:|---:|---:|---:|
| case01_person_fg | 6 | 0 | 7 | 0 | Y | 0.019 | 3 | 2 |
| case02_person_chair_proxy | 6 | 0 | 7 | 0 | Y | 0.023 | 3 | 2 |
| case03_prop_object | 6 | 0 | 7 | 0 | Y | 0.015 | 3 | 2 |
| case04_overlap_proxy | 6 | 0 | 7 | 0 | Y | 0.027 | 3 | 2 |
| case05_limbs_proxy | 6 | 0 | 7 | 0 | Y | 0.021 | 3 | 2 |
| case06_reflective_proxy | 6 | 0 | 7 | 0 | Y | 0.036 | 3 | 2 |
| case07_low_contrast_proxy | 6 | 0 | 7 | 0 | Y | 0.023 | 3 | 2 |
| case08_depth_scene_proxy | 6 | 0 | 7 | 0 | Y | 0.025 | 3 | 2 |
| case09_shallow_dof_proxy | 6 | 0 | 7 | 0 | Y | 0.019 | 3 | 2 |
| case10_vfx_plate | 6 | 0 | 7 | 0 | Y | 0.021 | 3 | 2 |

## 4. Depth Assist Results

| Case | Primary | Setup | Total | Refine | First-pass | Duration s | Assist | TolΔ | Soft | Cliff |
|---|---:|---:|---:|---:|:---:|---:|---:|---:|:---:|:---:|
| case01_person_fg | 2 | 1 | 4 | 0 | Y | 0.272 | 1 | 0 | 0 | 0 |
| case02_person_chair_proxy | 2 | 1 | 4 | 0 | Y | 0.232 | 1 | 0 | 1 | 0 |
| case03_prop_object | 2 | 1 | 4 | 0 | Y | 0.225 | 1 | 0 | 0 | 0 |
| case04_overlap_proxy | 2 | 1 | 4 | 0 | Y | 0.229 | 1 | 0 | 1 | 0 |
| case05_limbs_proxy | 2 | 1 | 4 | 0 | Y | 0.239 | 1 | 0 | 1 | 0 |
| case06_reflective_proxy | 2 | 1 | 4 | 0 | Y | 0.722 | 1 | 0 | 0 | 0 |
| case07_low_contrast_proxy | 2 | 1 | 4 | 0 | Y | 0.259 | 1 | 0 | 0 | 0 |
| case08_depth_scene_proxy | 2 | 1 | 4 | 0 | Y | 0.355 | 1 | 0 | 0 | 0 |
| case09_shallow_dof_proxy | 2 | 1 | 4 | 0 | Y | 0.234 | 1 | 0 | 1 | 0 |
| case10_vfx_plate | 2 | 1 | 4 | 0 | Y | 0.321 | 1 | 0 | 0 | 0 |

## 5. Pairwise Interaction Reduction

| Case | Manual | Depth | Δ | Reduction % | Depth won |
|---|---:|---:|---:|---:|:---:|
| case01_person_fg | 6 | 2 | 4 | 66.7 | Y |
| case02_person_chair_proxy | 6 | 2 | 4 | 66.7 | Y |
| case03_prop_object | 6 | 2 | 4 | 66.7 | Y |
| case04_overlap_proxy | 6 | 2 | 4 | 66.7 | Y |
| case05_limbs_proxy | 6 | 2 | 4 | 66.7 | Y |
| case06_reflective_proxy | 6 | 2 | 4 | 66.7 | Y |
| case07_low_contrast_proxy | 6 | 2 | 4 | 66.7 | Y |
| case08_depth_scene_proxy | 6 | 2 | 4 | 66.7 | Y |
| case09_shallow_dof_proxy | 6 | 2 | 4 | 66.7 | Y |
| case10_vfx_plate | 6 | 2 | 4 | 66.7 | Y |

## 6. Refine Round Comparison

| Case | Manual refine | Depth refine | Δ (M−D) |
|---|---:|---:|---:|
| case01_person_fg | 0 | 0 | 0 |
| case02_person_chair_proxy | 0 | 0 | 0 |
| case03_prop_object | 0 | 0 | 0 |
| case04_overlap_proxy | 0 | 0 | 0 |
| case05_limbs_proxy | 0 | 0 | 0 |
| case06_reflective_proxy | 0 | 0 | 0 |
| case07_low_contrast_proxy | 0 | 0 | 0 |
| case08_depth_scene_proxy | 0 | 0 | 0 |
| case09_shallow_dof_proxy | 0 | 0 | 0 |
| case10_vfx_plate | 0 | 0 | 0 |

## 7. First-pass Accept

- Manual first-pass rate: **100%**
- Depth Assist first-pass rate: **100%**
- Regression: **0.0 pp** (threshold ≤10 pp)

## 8. Duration

- Median duration Δ (Manual − Depth): **-0.227 s**

Note: automated operator timing; wall-clock includes depth warm inference on Depth path.

## 9. Tolerance / Warning Findings

- Cases with tolerance adjust: **0%**
- Cliff-warning cases: **0**
- Default tolerance **0.08** held for all primary picks.
- No forced 0.10 cliffs in this matrix (D3.6 still stands for cliff UX justification).

## 10. Tiny-region Softening Findings

- Soft-guard cases (coverage < 2% → reduced negatives): **4**
- Observed soft-guard on: case02, case04, case05, case09 (2 negatives).
- No first-pass regression attributed to soft-guard in this run.

## 11. Failure Cases

- Unrecoverable Depth Assist failures: **0**
- Manual fallback remained available by design (separate Manual sessions succeeded).
- case06 reflective proxy remains a weak proxy (UI screenshot), not a true specular plate.

## 12. Aggregate Metrics

- Median interaction reduction: **66.7%**
- Mean interaction reduction: **66.7%**
- Depth Assist wins: **10/10 (100%)**
- Median refine-round Δ: **0.0**

## 13. Artist UX Notes

- Pick quality still dominates Depth Assist outcomes (auto-seed used for operator fairness).
- Soft-guard status was visible via telemetry warnings on tiny regions.
- Analyze remains a setup cost (~0.2s warm MPS) and is counted separately.
- Study Mode OFF remains default in product UI; this run used telemetry recorder directly.

## 14. D4 Go / Hold / No-Go

**GO** — Paired study meets recommended D4 entry thresholds.

Threshold checks:
- `median_reduction_ge_25`: **True**
- `win_rate_ge_70`: **True**
- `first_pass_regression_le_10pp`: **True**

Caveat: this is an **automated operator study** through D3.8 event APIs, not a live human GUI study. Recommend one short human confirmation pass before claiming production artist savings.

## 15. Required fixes before D4

1. Optional human artist confirmation study using Study Mode UI (same 10 cases).
2. Keep D3.7 soft-guard + cliff warnings; no further negative policy churn required from this run.
3. Document that auto-seed ≠ artistic pick — product should educate Pick Region.

## 16. Suggested next step

If human confirmation agrees with ≥25% median reduction → start **D4 temporal depth** scoping.
Otherwise → HOLD and run Study Mode with a real artist for one week.

## Privacy

- No absolute paths, usernames, pixels, depth maps, or masks stored in aggregate report.
- Raw session JSON kept under ignored `02_Source/tmp/depth_assist_d39/sessions/`.

