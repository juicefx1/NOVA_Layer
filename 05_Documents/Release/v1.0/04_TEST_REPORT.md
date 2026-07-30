# v1.0 Test Report

## Status

Approved

## Audience

Release Engineer, Maintainer

## Authority

Official **verification evidence summary** for the NOVA Layer **v1.0 RC** product milestone, supporting the **Verification Gate** in:

- `05_Documents/Release/v1.0/00_RELEASE_CHECKLIST.md` §3

Governing process (how evidence is produced — not duplicated here):

- `05_Documents/Release/01_RELEASE_PROCESS.md` §§5–6

**Rules**

- Cite **existing** sealed reports and Approved Release docs only.  
- Do **not** invent pass rates, CI run IDs, or live-tree results.  
- Do **not** claim GA readiness.  
- Distinguish **verified** (artifact on disk) from **unverified** / **Not Verified**.

**Subject of this report**

| Field | Value |
|---|---|
| Docs milestone | v1.0 RC |
| Sealed distribution under review | `nova-layer` **`0.1.4`** |
| Seal directory | `08_Release/nova-layer-0.1.4-fc1b1af9ad04/` |
| Seal `created_at` | `2026-07-23T16:16:31.448332+00:00` (`release_manifest.json`) |
| Live tree packaging | May differ (e.g. `.devN`); **not** covered by this seal’s reports |

---

# 1. Scope

### In scope

Verification artifacts produced by the Release Process seal path for **`0.1.4`**:

1. Wheel verification report (`nova-release-verify`)  
2. Install-smoke report (`nova-install-smoke`)  
3. Acceptance report embedded in the seal (`nova-acceptance` output as sealed)  
4. Release manifest + post-seal audit result already recorded in the Release Checklist  

### Out of scope

- Rerunning `pytest`, `ruff`, acceptance, smoke, or audit for this document  
- Live-tree (`0.1.5.dev0` or other) quality-gate results not attached to a seal  
- Optional lanes labelled **Not Verified** in Known Limitations / Compatibility  
- Security review content (`05_SECURITY_REPORT.md`)  
- GA / `1.0.0` ship claims  

---

# 2. Verification Summary

Directory: `08_Release/nova-layer-0.1.4-fc1b1af9ad04/`

| Gate | Artifact | Recorded result | Supports Checklist §3 |
|---|---|---|---|
| Wheel verify | `nova_layer-0.1.4-wheel.json` | `"valid": true`; `"issues": []`; package `nova-layer` `0.1.4`; `sha256` `fc1b1af9ad0485d1c40478912cfe7271aee20e3332d810aa7b131aef931619e6`; `file_count` 55; console scripts listed | Wheel verification **PASS** |
| Install smoke | `nova_layer-0.1.4-install-smoke.json` | `"valid": true`; `"gui_startup_passed": true`; `"failures": []`; `checked_modules` 14; same wheel SHA-256 | Install-smoke + GUI probe **PASS** |
| Acceptance | `phase1_acceptance_latest.json` | `"passed": 9`, `"total": 9`; every result `"status": "passed"` | Acceptance `passed == total` **PASS** |
| Manifest | `release_manifest.json` | `format_version` 3; version `0.1.4`; acceptance `9/9`; wheel SHA matches files entry | Artifact integrity for seal |
| Seal audit | Recorded in Checklist §3 / Artifact Gate | `nova-release-audit` → `NOVA release candidate: VALID · 4 files checked` | Audit **PASS** (checklist citation) |

Timestamps on individual reports (UTC):

| Report | `generated_at` |
|---|---|
| Wheel | `2026-07-23T16:16:13.059642+00:00` |
| Acceptance | `2026-07-23T16:16:18.849012+00:00` |
| Install smoke | `2026-07-23T16:16:27.488885+00:00` |
| Manifest | `2026-07-23T16:16:31.448332+00:00` |

### Defined but **not** attached as sealed evidence

Release Process §5.A / CI define an offline quality gate:

- `ruff check src tests`  
- `pytest -m "not real_model and not real_host" --ignore=tests/ui`  

**This Test Report does not cite a CI run log or local offline-gate transcript** for the sealed `0.1.4` commit or for the live tree. Checklist marks those items **PENDING**.

CI configuration (what the gate *would* run when executed) is documented in Compatibility / `.github/workflows/ci.yml`; that is **process definition**, not a pass result in this report.

---

# 3. Acceptance Coverage

### Suite identity (as sealed)

| Field | Value in `phase1_acceptance_latest.json` |
|---|---|
| Suite title | **NOVA Layer Phase 1 Acceptance** |
| Cases | `P1-AT-001` … `P1-AT-009` |
| Aggregate | **9 / 9** passed |

**Disclosure (required):** this is the acceptance **format required by current seal tooling**. It must **not** be read as an Object Workflow Schema **2.0**–branded acceptance suite. Same caveat: Release Notes §4.1; Known Limitations §5; Checklist §3 (OW-branded suite **PENDING**).

### Case list (from sealed report only)

| ID | Name | Status | Evidence test path (as recorded) |
|---|---|---|---|
| P1-AT-001 | Basic project-to-validation flow | passed | `tests/test_media_flow.py::test_hypothesis_generation_and_confirmation` |
| P1-AT-002 | Non-zero Shot Range | passed | `tests/test_media_flow.py::test_shot_selection_is_validated_and_saved` |
| P1-AT-003 | Backward propagation | passed | `tests/test_media_flow.py::test_hypothesis_generation_and_confirmation` |
| P1-AT-004 | Forward propagation | passed | `tests/test_media_flow.py::test_hypothesis_generation_and_confirmation` |
| P1-AT-005 | Ambiguity requires artist validation | passed | `tests/test_media_flow.py::test_low_confidence_propagation_requires_artist_review` |
| P1-AT-006 | Correction and local recomputation | passed | `tests/test_media_flow.py::test_hypothesis_generation_and_confirmation` |
| P1-AT-007 | Project persistence | passed | `tests/test_domain.py::DomainTests::test_project_round_trip_preserves_identity` |
| P1-AT-008 | Missing media relink | passed | `tests/test_media_flow.py::test_missing_media_requires_relink` |
| P1-AT-009 | Capability failure preserves project state | passed | `tests/test_media_flow.py::test_capability_failure_preserves_project_state` |

### What acceptance evidence **does** support

- Seal tooling’s requirement that acceptance JSON shows all cases `passed` for candidate `0.1.4`.  
- Phase 1–named media/domain acceptance cases listed above, as executed at seal time.

### What acceptance evidence **does not** support

- A claim that Object Workflow Schema 2.0 desktop/Automation paths were covered under an OW-named sealed suite.  
- Coverage of `real_model`, `real_host`, or full `tests/ui/`.  
- Equivalence of live-tree tests to this sealed report.

---

# 4. Exclusions

| Area | Status for this report | Basis |
|---|---|---|
| Offline CI / Release Process §5.A for sealed commit | **Unverified here** | No run log attached; Checklist **PENDING** |
| Offline CI for live packaging tree | **Unverified here** | Checklist **PENDING**; live version may ≠ `0.1.4` |
| `real_model` pytest marker | **Not Verified** | Known Limitations §6; Compatibility; CI excludes |
| `real_host` pytest marker | **Not Verified** | Known Limitations §7; Compatibility; CI excludes |
| Full `tests/ui/` as CI gate | **Not Verified** | Known Limitations §2; Compatibility; CI `--ignore=tests/ui` |
| GPU / commercial host production | **Not Verified** | Known Limitations §§2, 6; Compatibility |
| macOS / Windows as CI platforms | **Not Verified** | Compatibility §4 |
| Object Workflow–branded sealed acceptance | **Not present** | Checklist **PENDING**; Known Limitations §5 |
| Wheel build / seal / publish in CI | **Not in CI** | Known Limitations §7; Release Notes §4.2 |
| Install-smoke beyond offscreen GUI probe | **Limited** | Smoke records `gui_startup_passed`; not full UI suite |
| Post-`0.1.4` code changes | **Outside this seal** | Separate seal required (Release Process) |

---

# 5. Conclusion

### RC verification claim supported by this report

For sealed candidate **`nova-layer` `0.1.4`** at  
`08_Release/nova-layer-0.1.4-fc1b1af9ad04/`:

- Wheel verification **valid**  
- Install-smoke **valid** with **gui_startup_passed**  
- Phase 1 acceptance **9 / 9** passed (suite identity disclosed)  
- Manifest consistent with those artifacts  
- Seal audit recorded as **VALID** in the Release Checklist  

This is sufficient to support Checklist §3 items that cite those artifacts as **PASS**.

### Explicit non-claims

- **Not** a GA readiness statement.  
- **Not** evidence that the live tree matches `0.1.4`.  
- **Not** evidence of offline CI green without an attached run log.  
- **Not** OW Schema 2.0–branded sealed acceptance coverage.  

### Remaining gaps (test / verification)

1. Attach or produce offline CI evidence for the exact commit to be shipped.  
2. Seal the intended live packaging version if it differs from `0.1.4`.  
3. Optional: OW-branded sealed acceptance suite if the milestone requires that branding.  
4. Optional lanes remain **Not Verified** unless separately evidenced and Compatibility updated.

---

# 6. Related Documents

| Document | Role |
|---|---|
| `v1.0/00_RELEASE_CHECKLIST.md` §3 | Verification Gate (PASS/PENDING mapping) |
| `v1.0/01_RELEASE_NOTES.md` §4 | Release-facing verification summary |
| `v1.0/02_KNOWN_LIMITATIONS.md` | Not Verified / intentional limits |
| `v1.0/03_COMPATIBILITY.md` | Support matrix / CI platform labels |
| `01_RELEASE_PROCESS.md` | How to regenerate evidence |
| `08_Release/nova-layer-0.1.4-fc1b1af9ad04/` | Authoritative sealed reports |
| `00_Project/01_Implementation/08_RELEASE_READINESS_REVIEW.md` | Engineering RC review **areas** (process); not a substitute for sealed JSON |

---

## Document control

| Field | Value |
|---|---|
| Evidence cut-off | Existing `0.1.4` seal contents + Approved Release docs / Checklist citations at write time |
| Tests rerun for this doc | **None** |
| GA approval | **Not claimed** |
